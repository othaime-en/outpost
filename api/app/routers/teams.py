"""
Team Management

DEVIATION FROM THE ORIGINAL PLAN — documented per project convention (see
IDP_LITE_IMPLEMENTATION_PLAN.md, "Key learnings & principles: deviations
from plan should be documented explicitly").

The plan originally specced:
  - GET /teams and POST /teams as super_admin-only
  - No GET /teams/{id} endpoint at all

In practice that made it impossible for a team_admin or member to ever see
their own team, and team creation required a super_admin as a bottleneck for
every new team. Both were revisited after real UI usage surfaced the gap:

  - GET /teams   is now open to any authenticated user, scoped by role:
                 member/team_admin see only their own team (list of 0 or 1);
                 super_admin sees all teams.
  - GET /teams/{id} is new. Same scoping: own team only, unless super_admin.
                 Returns team info + members + environments + aggregate
                 stats, so the frontend's team detail page is one call.
  - POST /teams  is now self-serve: any authenticated user with no team yet
                 can create one and becomes its team_admin automatically
                 (never downgrades an existing super_admin). A user who
                 already belongs to a team is blocked with 400 — multi-team
                 membership is out of scope for now (single team_id FK on
                 User), so "create a second team" isn't a supported move.
                 See the module docstring in models/user.py for the schema
                 constraint this rests on.
  - GET /teams/{id}/members is now open to any authenticated user, scoped
                 the same way as GET /teams/{id} — plain members can see
                 their teammates (read-only; no admin controls gated behind
                 this on the frontend). Previously team_admin+ only.

Adding members, and role changes generally, are unchanged: still
team_admin (own team) / super_admin (any team) for POST .../members, and
still entirely out of this file for role changes generally — see
routers/users.py's module docstring for why PATCH /users/{id}/role isn't
here.

FOLLOW-UP ADDITION — member removal and team deletion.

  - PATCH /teams/{id}/members/{user_id}/role — promotes/demotes an
    *existing* member within a team. Needed because POST .../members only
    covers onboarding someone new by GitHub username; there was previously
    no way to change an existing member's role without going through them
    as if they were new.

  - DELETE /teams/{id}/members/{user_id} — removes a member from a team
    (nulls team_id, resets role to "member" unless they're a super_admin).
    Self-serve (anyone can remove themselves) or forced (team_admin on own
    team / super_admin on any). Blocked if the target is the team's last
    remaining team_admin — a team can never be left without one. Promote a
    peer via the endpoint above first.

  - DELETE /teams/{id} — team_admin (own team) / super_admin (any team).
    Blocked unless every environment on the team is DESTROYED (FAILED
    included — per the architecture doc, a FAILED environment can still
    have partially-provisioned AWS resources and needs manual resolution
    first; this is a hard, non-cascading block, deliberately not something
    team deletion auto-resolves). Members, by contrast, ARE auto-detached
    as part of deletion — team_id/role bookkeeping in our own DB is fully
    reversible and has no external side effect, unlike environments, so
    there's no reason to force a manual "remove everyone first" step for
    that half of the precondition.

    This is a SOFT delete (teams.deleted_at), not a hard row delete — see
    the Team model's own docstring: environments.team_id is NOT NULL with
    a default (RESTRICT) foreign key, and environment rows are kept
    forever even after DESTROYED for audit/cost history. Any team that's
    ever had a single environment would fail a hard delete with a
    ForeignKeyViolation. Soft-deleted teams are filtered out of every list
    / get / membership endpoint via _get_active_team_or_404() below, so
    they behave as gone to normal callers while every historical
    environment's team_id reference stays valid.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.middleware.rbac import require_member, require_team_admin
from app.models.audit_log import AuditLog
from app.models.environment import Environment
from app.models.team import Team
from app.models.user import User
from app.schemas.environment import EnvironmentResponse
from app.schemas.team import (
    AddMemberRequest,
    CreateTeamRequest,
    TeamDeleteResponse,
    TeamDetailResponse,
    TeamResponse,
    UpdateMemberRoleRequest,
)
from app.schemas.user import UserResponse

router = APIRouter()

# Environments in these statuses are still occupying (or about to occupy)
# real AWS resources, so they count toward a team's "active" total and its
# estimated running cost. DESTROYED and FAILED are excluded — FAILED never
# successfully finished provisioning, and DESTROYED no longer holds anything.
COST_RELEVANT_STATUSES = ("PENDING", "PROVISIONING", "RUNNING", "DESTROYING")


def _team_response(team: Team) -> TeamResponse:
    return TeamResponse(id=str(team.id), name=team.name, slug=team.slug)


def _member_response(user: User) -> UserResponse:
    return UserResponse(
        id=str(user.id),
        username=user.username,
        email=user.email,
        role=user.role,
        team_id=str(user.team_id) if user.team_id else None,
    )


def _environment_response(env: Environment) -> EnvironmentResponse:
    # Mirrors routers/environments.py's own _environment_response exactly.
    # Kept as a separate copy (rather than importing the underscore-prefixed
    # helper across router modules) since the two routers otherwise have no
    # dependency on each other and this keeps it that way.
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


def _assert_team_visibility(team_id: str, current_user: User) -> None:
    """super_admin sees every team; everyone else is scoped to their own."""
    if current_user.role != "super_admin" and str(current_user.team_id) != team_id:
        raise HTTPException(status_code=403, detail="Not your team")


def _get_active_team_or_404(db: Session, team_id: str) -> Team:
    """Fetches a team, treating a soft-deleted one as not found — a deleted
    team should behave as absent to every caller except the audit log."""
    team = db.query(Team).filter(Team.id == team_id, Team.deleted_at.is_(None)).first()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    return team


@router.post("/", response_model=TeamResponse, status_code=status.HTTP_201_CREATED)
def create_team(
    body: CreateTeamRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_member),
):
    """
    Self-serve team creation. Any authenticated user with no team yet can
    create one; the creator becomes its team_admin. A user already on a
    team is blocked — see this module's docstring for why multi-team
    membership isn't supported.
    """
    if current_user.team_id:
        raise HTTPException(
            status_code=400,
            detail="You already belong to a team. Leave your current team before creating a new one.",
        )

    existing = db.query(Team).filter(
        (Team.name == body.name) | (Team.slug == body.slug)
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="A team with that name or slug already exists")

    team = Team(name=body.name, slug=body.slug)
    db.add(team)
    db.flush()  # populate team.id before we reference it below

    current_user.team_id = team.id
    # Never downgrade an existing super_admin to team_admin — super_admin
    # is a strict superset of what team_admin can do.
    if current_user.role != "super_admin":
        current_user.role = "team_admin"

    db.add(
        AuditLog(
            actor_id=current_user.id,
            action="TEAM_CREATED",
            actor_type="user",
            event_metadata={
                "team_id": str(team.id),
                "team_name": team.name,
                "self_serve": True,
                "creator": current_user.username,
            },
        )
    )
    db.commit()
    db.refresh(team)
    return _team_response(team)


@router.get("/", response_model=List[TeamResponse])
def list_teams(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_member),
):
    """super_admin sees every team. Everyone else sees only their own (0 or 1)."""
    query = db.query(Team).filter(Team.deleted_at.is_(None))
    if current_user.role != "super_admin":
        if not current_user.team_id:
            return []
        query = query.filter(Team.id == current_user.team_id)
    teams = query.order_by(Team.name).all()
    return [_team_response(t) for t in teams]


@router.get("/{team_id}", response_model=TeamDetailResponse)
def get_team(
    team_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_member),
):
    """
    Team info + members + environments + aggregate stats in one call, so the
    frontend's team detail page doesn't need three separate round trips.
    """
    team = _get_active_team_or_404(db, team_id)
    _assert_team_visibility(team_id, current_user)

    members = db.query(User).filter(User.team_id == team.id).order_by(User.username).all()
    environments = (
        db.query(Environment)
        .options(joinedload(Environment.team), joinedload(Environment.creator))
        .filter(Environment.team_id == team.id)
        .order_by(Environment.created_at.desc())
        .all()
    )

    active_count = sum(1 for e in environments if e.status != "DESTROYED")
    estimated_cost = sum(
        float(e.cost_estimate_usd)
        for e in environments
        if e.status in COST_RELEVANT_STATUSES and e.cost_estimate_usd is not None
    )

    return TeamDetailResponse(
        id=str(team.id),
        name=team.name,
        slug=team.slug,
        created_at=team.created_at.isoformat(),
        members=[_member_response(m) for m in members],
        environments=[_environment_response(e) for e in environments],
        active_environment_count=active_count,
        estimated_monthly_cost_usd=round(estimated_cost, 2),
    )


@router.get("/{team_id}/members", response_model=List[UserResponse])
def list_members(
    team_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_member),
):
    """
    Read-only for everyone who can see the team at all — including plain
    members. Previously team_admin+ only; opened up because there's no
    admin action gated behind this response, just a member roster.
    """
    _get_active_team_or_404(db, team_id)  # 404s if missing/soft-deleted; team itself unused below
    _assert_team_visibility(team_id, current_user)

    members = db.query(User).filter(User.team_id == team_id).order_by(User.username).all()
    return [_member_response(m) for m in members]


@router.post("/{team_id}/members", response_model=UserResponse)
def add_member(
    team_id: str,
    body: AddMemberRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_team_admin),
):
    """Unchanged: adding members is still team_admin (own team) / super_admin (any)."""
    if current_user.role == "team_admin" and str(current_user.team_id) != team_id:
        raise HTTPException(status_code=403, detail="You can only add members to your own team")

    team = _get_active_team_or_404(db, team_id)

    # A team_admin can promote a peer to team_admin, but never to super_admin.
    if current_user.role == "team_admin" and body.role == "super_admin":
        raise HTTPException(status_code=403, detail="Only a super_admin can grant the super_admin role")

    user = db.query(User).filter(User.username == body.github_username).first()
    if not user:
        raise HTTPException(
            status_code=404,
            detail="User not found — they must log in with GitHub at least once first",
        )

    user.team_id = team.id
    user.role = body.role

    db.add(
        AuditLog(
            actor_id=current_user.id,
            action="USER_ADDED",
            actor_type="user",
            event_metadata={
                "added_user": body.github_username,
                "team_id": str(team.id),
                "role": body.role,
            },
        )
    )
    db.commit()
    db.refresh(user)
    return _member_response(user)


def _is_last_team_admin(db: Session, team_id, user: User) -> bool:
    """True if `user` is a team_admin on `team_id` and no other team_admin
    exists on that team. Used to block both demotion and removal of the
    last admin standing — a team must always have at least one."""
    if user.role != "team_admin":
        return False
    other_admins = (
        db.query(User)
        .filter(User.team_id == team_id, User.role == "team_admin", User.id != user.id)
        .count()
    )
    return other_admins == 0


@router.patch("/{team_id}/members/{user_id}/role", response_model=UserResponse)
def update_member_role(
    team_id: str,
    user_id: str,
    body: UpdateMemberRoleRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_team_admin),
):
    """
    Promotes or demotes an existing member of `team_id`. Distinct from the
    onboarding flow (POST .../members, which looks a user up by GitHub
    username) and from the platform-wide PATCH /users/{id}/role (super_admin
    only, works even for team-less users — see routers/users.py).
    """
    if current_user.role == "team_admin" and str(current_user.team_id) != team_id:
        raise HTTPException(status_code=403, detail="You can only manage your own team's members")
    if current_user.role == "team_admin" and body.role == "super_admin":
        raise HTTPException(status_code=403, detail="Only a super_admin can grant the super_admin role")

    _get_active_team_or_404(db, team_id)  # 404s if missing/soft-deleted; team itself unused below

    target = db.query(User).filter(User.id == user_id, User.team_id == team_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User is not a member of this team")

    if body.role != "team_admin" and _is_last_team_admin(db, team_id, target):
        raise HTTPException(
            status_code=400,
            detail="Cannot demote the team's last team_admin. Promote another member first.",
        )

    old_role = target.role
    target.role = body.role

    db.add(
        AuditLog(
            actor_id=current_user.id,
            action="USER_ROLE_CHANGED",
            actor_type="user",
            event_metadata={
                "user_id": str(target.id),
                "username": target.username,
                "team_id": team_id,
                "old_role": old_role,
                "new_role": body.role,
            },
        )
    )
    db.commit()
    db.refresh(target)
    return _member_response(target)


@router.delete("/{team_id}/members/{user_id}", response_model=UserResponse)
def remove_member(
    team_id: str,
    user_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_member),
):
    """
    Removes a member from a team. Self-serve — anyone can call this on
    their own user_id to leave. Also usable by that team's team_admin (own
    team) or a super_admin (any team) to forcibly remove someone else.
    Blocked if the target is the team's last team_admin — see
    update_member_role() above for how to hand off admin first.
    """
    _get_active_team_or_404(db, team_id)  # 404s if missing/soft-deleted; team itself unused below

    is_self = str(current_user.id) == user_id
    is_forced_by_admin = current_user.role == "super_admin" or (
        current_user.role == "team_admin" and str(current_user.team_id) == team_id
    )
    if not is_self and not is_forced_by_admin:
        raise HTTPException(
            status_code=403,
            detail="You can only remove yourself, unless you're this team's team_admin or a super_admin",
        )

    target = db.query(User).filter(User.id == user_id, User.team_id == team_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User is not a member of this team")

    if _is_last_team_admin(db, team_id, target):
        raise HTTPException(
            status_code=400,
            detail="Cannot remove the team's last team_admin. Promote another member first.",
        )

    old_role = target.role
    target.team_id = None
    if target.role != "super_admin":
        target.role = "member"

    db.add(
        AuditLog(
            actor_id=current_user.id,
            action="USER_REMOVED",
            actor_type="user",
            event_metadata={
                "user_id": str(target.id),
                "username": target.username,
                "team_id": team_id,
                "old_role": old_role,
                "self_serve": is_self,
            },
        )
    )
    db.commit()
    db.refresh(target)
    return _member_response(target)


@router.delete("/{team_id}", response_model=TeamDeleteResponse)
def delete_team(
    team_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_team_admin),
):
    """
    Deletes (soft-deletes) a team. team_admin (own team) / super_admin (any team).

    Blocked unless every environment on the team is DESTROYED — this is a
    hard, non-cascading precondition; the caller must destroy (or, for a
    FAILED environment, manually resolve) each one individually first. See
    this module's docstring for why environments and members are treated
    differently here, and the Team model's docstring for why this can't be
    a hard row delete.

    Remaining members are auto-detached (team_id/role bookkeeping only, no
    external side effect) as part of this same transaction — no separate
    "remove everyone first" step required.
    """
    if current_user.role == "team_admin" and str(current_user.team_id) != team_id:
        raise HTTPException(status_code=403, detail="You can only delete your own team")

    team = _get_active_team_or_404(db, team_id)

    non_destroyed = (
        db.query(Environment)
        .filter(Environment.team_id == team_id, Environment.status != "DESTROYED")
        .count()
    )
    if non_destroyed:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Cannot delete team: {non_destroyed} environment(s) are not DESTROYED. "
                "Destroy (or resolve FAILED) environments first."
            ),
        )

    members = db.query(User).filter(User.team_id == team_id).all()
    detached_usernames = [m.username for m in members]
    for m in members:
        m.team_id = None
        if m.role != "super_admin":
            m.role = "member"

    team_name, team_slug = team.name, team.slug
    team.deleted_at = datetime.now(timezone.utc)

    db.add(
        AuditLog(
            actor_id=current_user.id,
            action="TEAM_DELETED",
            actor_type="user",
            event_metadata={
                "team_id": team_id,
                "team_name": team_name,
                "team_slug": team_slug,
                "detached_members": detached_usernames,
            },
        )
    )
    db.commit()
    return TeamDeleteResponse(ok=True, detached_members=detached_usernames)