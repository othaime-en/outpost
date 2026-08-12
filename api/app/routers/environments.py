"""
Environment Lifecycle Management

This is the core of the application: the state machine driving
PENDING → PROVISIONING → RUNNING → DESTROYING → DESTROYED (with FAILED as a
terminal off-ramp from either transition). Every status change here writes
an audit log row in the same DB transaction — see the `_audit()` helper.

Two endpoints — /callback and /expired — are called by GitHub Actions, not
a logged-in user, and are guarded by `require_callback_secret` (a shared
header secret) instead of JWT/API-key auth. /cost-preview takes no auth at
all: it's a read-only pricing calculator, not a query over anything private.

DEVIATION FROM THE ORIGINAL PLAN — documented per project convention.
GET / originally took no query params and always returned every environment
visible to the caller, DESTROYED included. Dashboard usage showed that grows
unbounded and unusable over time, so list_environments() now accepts filter
and sort query params (see the docstring on that function), and DESTROYED
environments are excluded by default unless explicitly asked for.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.middleware.rbac import require_callback_secret, require_member
from app.models.audit_log import AuditLog
from app.models.cost_snapshot import CostSnapshot
from app.models.environment import Environment
from app.models.runbook import Runbook
from app.models.user import User
from app.schemas.environment import (
    VALID_ENV_TYPES,
    CallbackRequest,
    CostBreakdownResponse,
    CostSnapshotListResponse,
    CostSnapshotResponse,
    CreateEnvironmentRequest,
    CreateEnvironmentResponse,
    EnvironmentListResponse,
    EnvironmentResponse,
    ExpiredEnvironmentResponse,
    ExtendTTLRequest,
    ExtendTTLResponse,
    RunbookResponse,
)
from app.services import cost, terraform
from app.services import runbook as runbook_service

router = APIRouter()

# Terminal-ish statuses a destroy can be triggered from.
DESTROYABLE_STATUSES = ("RUNNING", "FAILED")

# All valid values for the environment state machine. Used to validate the
# `status` filter query param — anything outside this set is a client error,
# not a query that should just silently return nothing.
VALID_ENV_STATUSES = {"PENDING", "PROVISIONING", "RUNNING", "DESTROYING", "DESTROYED", "FAILED"}
VALID_HEALTH_STATUSES = {"HEALTHY", "DEGRADED", "UNKNOWN"}

# Whitelisted sort columns — deliberately not a free-form column name, to
# avoid building dynamic SQL from user input.
_SORT_COLUMNS = {
    "created_at": Environment.created_at,
    "expires_at": Environment.expires_at,
    "cost_estimate_usd": Environment.cost_estimate_usd,
}


def _audit(
    db: Session,
    *,
    action: str,
    environment_id: Optional[uuid.UUID] = None,
    actor_id: Optional[uuid.UUID] = None,
    actor_type: str = "user",
    metadata: Optional[dict] = None,
) -> None:
    """
    Adds an AuditLog row to the current session without committing.
    Callers are responsible for committing alongside the status change that
    prompted it, so the two are always atomic — never a status update that
    "won" without a corresponding audit row, or vice versa.
    """
    db.add(
        AuditLog(
            environment_id=environment_id,
            actor_id=actor_id,
            action=action,
            actor_type=actor_type,
            event_metadata=metadata or {},
        )
    )


def _environment_response(env: Environment) -> EnvironmentResponse:
    return EnvironmentResponse(
        id=str(env.id),
        name=env.name,
        team_id=str(env.team_id),
        team_slug=env.team.slug,
        created_by=str(env.created_by),
        created_by_username=env.creator.username,
        env_type=env.env_type,
        status=env.status,
        ttl_hours=env.ttl_hours,
        expires_at=env.expires_at.isoformat(),
        aws_region=env.aws_region,
        outputs=env.outputs,
        health_status=env.health_status,
        health_checked_at=env.health_checked_at.isoformat() if env.health_checked_at else None,
        cost_estimate_usd=float(env.cost_estimate_usd) if env.cost_estimate_usd is not None else None,
        created_at=env.created_at.isoformat(),
        destroyed_at=env.destroyed_at.isoformat() if env.destroyed_at else None,
    )


def _get_env_or_404(db: Session, env_id: str) -> Environment:
    try:
        env_uuid = uuid.UUID(env_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Environment not found")
    env = (
        db.query(Environment)
        .options(joinedload(Environment.team), joinedload(Environment.creator))
        .filter(Environment.id == env_uuid)
        .first()
    )
    if not env:
        raise HTTPException(status_code=404, detail="Environment not found")
    return env


def _assert_team_visibility(env: Environment, current_user: User) -> None:
    """super_admin sees everything; everyone else is scoped to their team."""
    if current_user.role != "super_admin" and str(env.team_id) != str(current_user.team_id):
        raise HTTPException(status_code=403, detail="Not your team's environment")


# --- Cost preview (no auth — pure calculator) ---------------------------


@router.get("/cost-preview", response_model=CostBreakdownResponse)
def cost_preview(env_type: str = "dev"):
    if env_type not in ("dev", "staging"):
        raise HTTPException(status_code=422, detail="env_type must be 'dev' or 'staging'")
    return CostBreakdownResponse(**cost.get_cost_breakdown(env_type))


# --- TTL cron support (callback-secret auth) -----------------------------


@router.get("/expired", response_model=list[ExpiredEnvironmentResponse])
def get_expired(db: Session = Depends(get_db), _=Depends(require_callback_secret)):
    now = datetime.now(timezone.utc)
    expired = (
        db.query(Environment)
        .filter(Environment.status == "RUNNING", Environment.expires_at < now)
        .all()
    )
    return [
        ExpiredEnvironmentResponse(env_id=str(e.id), name=e.name, team=e.team.slug)
        for e in expired
    ]


# --- Core CRUD ------------------------------------------------------------


@router.get("/", response_model=EnvironmentListResponse)
def list_environments(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_member),
    statuses: Optional[List[str]] = Query(
        default=None,
        alias="status",
        description="Repeat to pass multiple, e.g. ?status=RUNNING&status=FAILED. "
        "If omitted, DESTROYED is excluded by default (see include_destroyed).",
    ),
    team_id: Optional[str] = Query(
        default=None,
        description="super_admin only — filters to one team. Ignored for everyone else, "
        "since they're already scoped to their own team.",
    ),
    env_type: Optional[str] = Query(default=None, description="'dev' or 'staging'"),
    health_status: Optional[str] = Query(default=None, description="HEALTHY | DEGRADED | UNKNOWN"),
    expiring_within_hours: Optional[int] = Query(
        default=None,
        ge=1,
        description="Only RUNNING environments whose expires_at falls within this many hours.",
    ),
    include_destroyed: bool = Query(
        default=False,
        description="Include DESTROYED environments. Ignored if `status` is explicitly passed.",
    ),
    created_by_me: bool = Query(default=False, description="Only environments the caller created."),
    sort_by: str = Query(default="created_at", pattern="^(created_at|expires_at|cost_estimate_usd)$"),
    sort_dir: str = Query(default="desc", pattern="^(asc|desc)$"),
):
    """
    List environments visible to the caller, with optional server-side
    filtering and sorting.

    Team scoping (unchanged): non-super_admin users only ever see their own
    team's environments, regardless of the `team_id` param — that param only
    does anything for a super_admin looking across teams.

    DESTROYED environments are excluded unless the caller either passes
    `include_destroyed=true` or explicitly filters `status=DESTROYED` — a
    dashboard that always showed every environment ever created would grow
    unusable within weeks of real use.
    """
    query = db.query(Environment).options(
        joinedload(Environment.team), joinedload(Environment.creator)
    )

    if current_user.role != "super_admin":
        query = query.filter(Environment.team_id == current_user.team_id)
    elif team_id:
        query = query.filter(Environment.team_id == team_id)

    if statuses:
        invalid = set(statuses) - VALID_ENV_STATUSES
        if invalid:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid status value(s): {sorted(invalid)}. Must be one of {sorted(VALID_ENV_STATUSES)}",
            )
        query = query.filter(Environment.status.in_(statuses))
    elif not include_destroyed:
        query = query.filter(Environment.status != "DESTROYED")

    if env_type:
        if env_type not in VALID_ENV_TYPES:
            raise HTTPException(
                status_code=422, detail=f"env_type must be one of {sorted(VALID_ENV_TYPES)}"
            )
        query = query.filter(Environment.env_type == env_type)

    if health_status:
        if health_status not in VALID_HEALTH_STATUSES:
            raise HTTPException(
                status_code=422,
                detail=f"health_status must be one of {sorted(VALID_HEALTH_STATUSES)}",
            )
        query = query.filter(Environment.health_status == health_status)

    if expiring_within_hours is not None:
        cutoff = datetime.now(timezone.utc) + timedelta(hours=expiring_within_hours)
        query = query.filter(
            Environment.status == "RUNNING",
            Environment.expires_at <= cutoff,
        )

    if created_by_me:
        query = query.filter(Environment.created_by == current_user.id)

    sort_column = _SORT_COLUMNS[sort_by]
    sort_column = sort_column.asc() if sort_dir == "asc" else sort_column.desc()
    envs = query.order_by(sort_column).all()

    return [_environment_response(e) for e in envs]


@router.post("/", response_model=CreateEnvironmentResponse, status_code=status.HTTP_202_ACCEPTED)
def create_environment(
    body: CreateEnvironmentRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_member),
):
    if not current_user.team_id:
        raise HTTPException(
            status_code=400,
            detail="You must belong to a team to provision environments",
        )

    env_id = uuid.uuid4()
    env = Environment(
        id=env_id,
        name=body.name,
        team_id=current_user.team_id,
        created_by=current_user.id,
        env_type=body.env_type,
        status="PENDING",
        ttl_hours=body.ttl_hours,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=body.ttl_hours),
        aws_region=body.aws_region,
        cost_estimate_usd=cost.estimate_monthly_cost(body.env_type),
    )
    db.add(env)
    _audit(
        db,
        action="ENV_CREATED",
        environment_id=env_id,
        actor_id=current_user.id,
        metadata={
            "env_name": body.name,
            "env_type": body.env_type,
            "ttl_hours": body.ttl_hours,
        },
    )
    # Commit before dispatching the workflow — the row (and its audit log)
    # must exist before GitHub Actions can possibly call back about it.
    db.commit()

    terraform.trigger_provision(
        env_id=str(env_id),
        env_name=body.name,
        team=current_user.team.slug,
        env_type=body.env_type,
        ttl_hours=body.ttl_hours,
        region=body.aws_region,
    )

    return CreateEnvironmentResponse(env_id=str(env_id), status="PENDING")


@router.get("/{env_id}", response_model=EnvironmentResponse)
def get_environment(
    env_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_member),
):
    env = _get_env_or_404(db, env_id)
    _assert_team_visibility(env, current_user)
    return _environment_response(env)


@router.delete("/{env_id}", response_model=CreateEnvironmentResponse, status_code=status.HTTP_202_ACCEPTED)
def destroy_environment(
    env_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_member),
):
    env = _get_env_or_404(db, env_id)

    if env.status not in DESTROYABLE_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot destroy environment with status: {env.status}",
        )

    # RBAC: member → own envs only, team_admin → own team, super_admin → any.
    if current_user.role == "member" and str(env.created_by) != str(current_user.id):
        raise HTTPException(status_code=403, detail="You can only destroy your own environments")
    if current_user.role == "team_admin" and str(env.team_id) != str(current_user.team_id):
        raise HTTPException(status_code=403, detail="You can only destroy your team's environments")

    env.status = "DESTROYING"
    _audit(
        db,
        action="ENV_DESTROY_REQUESTED",
        environment_id=env.id,
        actor_id=current_user.id,
        metadata={"triggered_by": current_user.username},
    )
    db.commit()

    terraform.trigger_destroy(str(env.id), env.aws_region, actor=current_user.username)

    return CreateEnvironmentResponse(env_id=str(env.id), status="DESTROYING")


@router.patch("/{env_id}/ttl", response_model=ExtendTTLResponse)
def extend_ttl(
    env_id: str,
    body: ExtendTTLRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_member),
):
    env = _get_env_or_404(db, env_id)
    _assert_team_visibility(env, current_user)

    if env.status != "RUNNING":
        raise HTTPException(status_code=400, detail="Can only extend TTL of RUNNING environments")

    old_expires_at = env.expires_at
    env.expires_at = env.expires_at + timedelta(hours=body.extend_hours)
    env.ttl_hours += body.extend_hours

    _audit(
        db,
        action="TTL_EXTENDED",
        environment_id=env.id,
        actor_id=current_user.id,
        metadata={
            "old_expires_at": old_expires_at.isoformat(),
            "new_expires_at": env.expires_at.isoformat(),
            "extended_by_hours": body.extend_hours,
        },
    )
    db.commit()

    return ExtendTTLResponse(expires_at=env.expires_at.isoformat())


# --- Callback (callback-secret auth, called by GitHub Actions) -----------


@router.post("/{env_id}/callback")
def environment_callback(
    env_id: str,
    body: CallbackRequest,
    db: Session = Depends(get_db),
    _=Depends(require_callback_secret),
):
    env = _get_env_or_404(db, env_id)
    env.status = body.status

    if body.status == "RUNNING":
        env.outputs = body.outputs or {}
        _audit(db, action="ENV_RUNNING", environment_id=env.id, actor_type="system")

        content = runbook_service.generate(env, env.outputs)
        existing = db.query(Runbook).filter(Runbook.environment_id == env.id).first()
        if existing:
            existing.content_md = content
            existing.generated_at = datetime.now(timezone.utc)
        else:
            db.add(Runbook(environment_id=env.id, content_md=content))

    elif body.status == "DESTROYED":
        env.destroyed_at = datetime.now(timezone.utc)
        actor_type = "cron" if body.actor == "cron" else "user"
        _audit(
            db,
            action="ENV_DESTROYED",
            environment_id=env.id,
            actor_type=actor_type,
            metadata={"actor": body.actor},
        )

    elif body.status == "FAILED":
        _audit(
            db,
            action="ENV_FAILED",
            environment_id=env.id,
            actor_type="system",
            metadata={"error": body.error},
        )

    # Status update + audit log (+ runbook, when applicable) committed
    # together — a callback either fully lands or fully doesn't.
    db.commit()
    return {"ok": True}


# --- Runbook ---------------------------------------------------------------


@router.get("/{env_id}/runbook", response_model=RunbookResponse)
def get_runbook(
    env_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_member),
):
    env = _get_env_or_404(db, env_id)
    _assert_team_visibility(env, current_user)

    rb = db.query(Runbook).filter(Runbook.environment_id == env.id).first()
    if not rb:
        raise HTTPException(
            status_code=404,
            detail="Runbook not yet generated — environment may still be provisioning",
        )
    return RunbookResponse(content_md=rb.content_md, generated_at=rb.generated_at.isoformat())


# --- Cost snapshots ---------------------------------------------------------


@router.get("/{env_id}/cost-snapshots", response_model=CostSnapshotListResponse)
def get_cost_snapshots(
    env_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_member),
):
    """
    Reads whatever actual-cost rows exist for this environment.

    This is deliberately just the read side. Writing rows here requires a
    background job that calls AWS Cost Explorer (tagged by env_id) and is
    blocked on the AWS bootstrap being complete — see cost_snapshot.py's
    docstring. Until that job exists, this will always return `[]`, and the
    UI's Cost tab already has a documented fallback message for that case.
    """
    env = _get_env_or_404(db, env_id)
    _assert_team_visibility(env, current_user)

    snapshots = (
        db.query(CostSnapshot)
        .filter(CostSnapshot.environment_id == env.id)
        .order_by(CostSnapshot.period_start.desc())
        .all()
    )
    return [
        CostSnapshotResponse(
            period_start=s.period_start.isoformat(),
            period_end=s.period_end.isoformat(),
            actual_cost_usd=float(s.actual_cost_usd),
        )
        for s in snapshots
    ]