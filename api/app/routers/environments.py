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

MULTI-TEAM MEMBERSHIP MIGRATION — what changed in this file and why.

  - CreateEnvironmentRequest now requires an explicit `team_id`. Under the
    old single-team model, which team a new environment belonged to was
    implicit (current_user.team_id) — there was only ever one right
    answer. Now that a user can belong to several teams, the caller has to
    say which one; create_environment() validates the requested team_id
    against the caller's actual memberships via has_team_role() rather
    than trusting it blindly.

  - _assert_team_visibility() (get_environment, extend_ttl, get_runbook,
    get_cost_snapshots) now checks has_team_role(current_user, env.team_id)
    instead of comparing env.team_id to a single current_user.team_id.
    Same question ("can this user see this environment's team"), answered
    against however many memberships the caller actually has.

  - list_environments()'s `team_id` filter query param is no longer
    super_admin-exclusive. Under the old model a non-super_admin was
    always scoped to exactly one team, so a filter param would have been
    redundant for them. Under multi-team, a caller on several teams needs
    a way to narrow the dashboard down to one — so the param now works for
    anyone, validated to be one of the caller's own teams (super_admin can
    still pass any team_id, unrestricted, as before).

  - destroy_environment()'s RBAC now resolves the caller's role SCOPED TO
    THIS ENVIRONMENT'S TEAM via team_role(), rather than reading a single
    global current_user.role. A user who is team_admin on Team A and has
    no membership at all on Team B should not be able to lean on their
    Team A admin status to destroy a Team B environment — under the old
    model this couldn't happen (one team per user), so there was no
    explicit "not a member of this team at all" branch. There is now.

  - require_member is gone from every handler in this file — it never
    actually checked anything beyond "is this a logged-in user" (see
    middleware/rbac.py's docstring), so those Depends() now call
    get_current_user directly. Real authorization is, as before, the
    explicit team_role()/has_team_role() checks in each handler body.

CANCELLING A PENDING ENVIRONMENT — deviation from the original plan,
documented per project convention.

The plan's state machine only ever allowed DELETE /{env_id} to fire from
RUNNING or FAILED (DESTROYABLE_STATUSES). PENDING had no exit at all: a
row that never received a callback (GitHub Actions secrets unset, a
workflow that silently no-ops, a dispatch that never started) was stuck
forever — which, in turn, permanently blocked deleting whatever team it
belonged to (delete_team() in routers/teams.py requires every environment
to reach DESTROYED first).

PENDING is now also acceptable to DELETE /{env_id} (CANCELLABLE_STATUSES),
but it is NOT treated like RUNNING/FAILED destruction — a PENDING row has
no confirmation either way that any AWS resource actually exists, so the
two paths differ in an important way:

  - RUNNING/FAILED -> DESTROYING, wait for GitHub Actions to confirm via
    /callback before reaching DESTROYED. There's real infrastructure to
    tear down and the DB shouldn't claim it's gone until that's confirmed.

  - PENDING -> DESTROYED immediately, no waiting on a callback. Making
    this wait on DESTROYING the same way would just trade "stuck at
    PENDING forever" for "stuck at DESTROYING forever" in exactly the
    same unconfigured-GitHub-Actions environments where this problem is
    most likely to bite — defeating the entire point of the fix.

    A best-effort terraform.trigger_destroy() is still fired regardless
    (fire-and-forget, after the commit, not blocking the response) as
    insurance against the narrow race where a provision workflow was
    silently mid-flight when cancellation happened — `terraform destroy`
    against a never-applied workspace is a well-defined no-op, so this
    costs nothing in the overwhelmingly common case where nothing was
    ever created.

    The DB status ends up "DESTROYED" either way (so team deletion,
    dashboard filters, and status badges need zero special-casing to
    handle this) — but the audit action is "ENV_CANCELLED", not
    "ENV_DESTROYED", with `confirmed_teardown: False` in its metadata.
    "ENV_DESTROYED" means GitHub Actions confirmed teardown; reusing it
    here for a state that was never confirmed would be dishonest in the
    audit trail.

  - environment_callback() now no-ops (logs ENV_CALLBACK_IGNORED, doesn't
    mutate state) for any callback landing on an already-DESTROYED
    environment — needed because of the above: a destroy/provision
    workflow dispatched before or during cancellation can still report
    back long after the row is already closed, and silently overwriting
    DESTROYED back to RUNNING or FAILED would resurrect something the
    caller explicitly closed out from under them.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.middleware.auth import get_current_user
from app.middleware.rbac import has_team_role, require_callback_secret, team_role
from app.models.audit_log import AuditLog
from app.models.cost_snapshot import CostSnapshot
from app.models.environment import Environment
from app.models.runbook import Runbook
from app.models.team import Team
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

# Terminal-ish statuses a real destroy (RUNNING/FAILED -> DESTROYING ->
# callback -> DESTROYED) can be triggered from.
DESTROYABLE_STATUSES = ("RUNNING", "FAILED")

# PENDING can also be closed via DELETE /{env_id}, but goes straight to
# DESTROYED with no DESTROYING wait — see this module's docstring, section
# "CANCELLING A PENDING ENVIRONMENT", for why this is a deliberately
# different path from DESTROYABLE_STATUSES rather than just being added to
# that tuple.
CANCELLABLE_STATUSES = ("PENDING",)

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
    """super_admin sees everything; everyone else needs a membership
    (any role) on this environment's team."""
    if not has_team_role(current_user, env.team_id):
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
    current_user: User = Depends(get_current_user),
    statuses: Optional[List[str]] = Query(
        default=None,
        alias="status",
        description="Repeat to pass multiple, e.g. ?status=RUNNING&status=FAILED. "
        "If omitted, DESTROYED is excluded by default (see include_destroyed).",
    ),
    team_id: Optional[str] = Query(
        default=None,
        description="Filter to one team. For a super_admin, any team_id. For everyone else, "
        "must be one of the caller's own team memberships — otherwise 403.",
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

    Team scoping: super_admin sees every team's environments. Everyone else
    sees environments across ALL of their own team memberships by default —
    a user on two teams sees both teams' environments in one call. Passing
    `team_id` narrows to one specific team; for a non-super_admin that team
    must be one of their own memberships (403 otherwise), since this param
    is a narrowing filter, not a way to see outside your own teams.

    DESTROYED environments are excluded unless the caller either passes
    `include_destroyed=true` or explicitly filters `status=DESTROYED` — a
    dashboard that always showed every environment ever created would grow
    unusable within weeks of real use.
    """
    query = db.query(Environment).options(
        joinedload(Environment.team), joinedload(Environment.creator)
    )

    is_super = current_user.platform_role == "super_admin"
    if team_id:
        if not is_super and not has_team_role(current_user, team_id):
            raise HTTPException(status_code=403, detail="Not your team")
        query = query.filter(Environment.team_id == team_id)
    elif not is_super:
        own_team_ids = [m.team_id for m in current_user.team_memberships]
        if not own_team_ids:
            return []
        query = query.filter(Environment.team_id.in_(own_team_ids))

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
    current_user: User = Depends(get_current_user),
):
    if not has_team_role(current_user, body.team_id):
        raise HTTPException(
            status_code=403,
            detail="You are not a member of the requested team",
        )

    team = db.query(Team).filter(Team.id == body.team_id, Team.deleted_at.is_(None)).first()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    env_id = uuid.uuid4()
    env = Environment(
        id=env_id,
        name=body.name,
        team_id=team.id,
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
            "team_id": str(team.id),
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
        team=team.slug,
        env_type=body.env_type,
        ttl_hours=body.ttl_hours,
        region=body.aws_region,
    )

    return CreateEnvironmentResponse(env_id=str(env_id), status="PENDING")


@router.get("/{env_id}", response_model=EnvironmentResponse)
def get_environment(
    env_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    env = _get_env_or_404(db, env_id)
    _assert_team_visibility(env, current_user)
    return _environment_response(env)


@router.delete("/{env_id}", response_model=CreateEnvironmentResponse, status_code=status.HTTP_202_ACCEPTED)
def destroy_environment(
    env_id: str,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    env = _get_env_or_404(db, env_id)

    if env.status not in DESTROYABLE_STATUSES and env.status not in CANCELLABLE_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot destroy environment with status: {env.status}",
        )

    # RBAC, scoped to THIS environment's team specifically — identical for
    # both the real-destroy and cancel-a-PENDING paths below:
    #   no membership on this team (and not super_admin) -> can't act at all
    #   member on this team                               -> own envs only
    #   team_admin on this team / super_admin              -> any env on the team
    is_super = current_user.platform_role == "super_admin"
    role = team_role(current_user, env.team_id)

    if role is None and not is_super:
        raise HTTPException(status_code=403, detail="You are not a member of this environment's team")
    if role == "member" and str(env.created_by) != str(current_user.id) and not is_super:
        raise HTTPException(status_code=403, detail="You can only destroy your own environments")

    if env.status in CANCELLABLE_STATUSES:
        # See this module's docstring, "CANCELLING A PENDING ENVIRONMENT" —
        # goes straight to DESTROYED, no DESTROYING wait, distinct audit
        # action from a confirmed destroy.
        env.status = "DESTROYED"
        env.destroyed_at = datetime.now(timezone.utc)
        _audit(
            db,
            action="ENV_CANCELLED",
            environment_id=env.id,
            actor_id=current_user.id,
            metadata={
                "triggered_by": current_user.username,
                "cancelled_from_status": "PENDING",
                "confirmed_teardown": False,
            },
        )
        db.commit()

        # Best-effort insurance only — fired after the commit (same
        # ordering as create_environment()'s dispatch) and deliberately
        # not awaited or allowed to affect the response: this environment
        # is already DESTROYED locally no matter what this call does. See
        # the module docstring for why waiting on it here would just trade
        # one stuck status for another in exactly the environments where
        # this problem is most likely to occur.
        terraform.trigger_destroy(str(env.id), env.aws_region, actor=current_user.username)

        # 200, not the decorator's default 202 — there's no pending async
        # work left; the environment is already in its terminal state by
        # the time this response goes out.
        response.status_code = status.HTTP_200_OK
        return CreateEnvironmentResponse(env_id=str(env.id), status="DESTROYED")

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
    current_user: User = Depends(get_current_user),
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

    if env.status == "DESTROYED":
        # A callback landing after the environment is already DESTROYED —
        # most likely a provision or destroy workflow that was dispatched
        # before or during a PENDING cancellation (see this module's
        # docstring, "CANCELLING A PENDING ENVIRONMENT") finally reporting
        # back, possibly minutes or hours later. DESTROYED is terminal:
        # silently overwriting it back to RUNNING or FAILED would
        # resurrect an environment the caller explicitly closed out from
        # under them. Log it and no-op rather than mutate state.
        _audit(
            db,
            action="ENV_CALLBACK_IGNORED",
            environment_id=env.id,
            actor_type="system",
            metadata={"attempted_status": body.status, "reason": "environment already DESTROYED"},
        )
        db.commit()
        return {"ok": True, "ignored": True}

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
    current_user: User = Depends(get_current_user),
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
    current_user: User = Depends(get_current_user),
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