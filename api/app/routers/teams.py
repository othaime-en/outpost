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
                 non-super_admin sees only teams they belong to;
                 super_admin sees all teams.
  - GET /teams/{id} is new. Same scoping: caller's own teams only, unless
                 super_admin. Returns team info + members + environments +
                 aggregate stats, so the frontend's team detail page is one call.
  - POST /teams  is self-serve: any authenticated user can create a team
                 and becomes its team_admin automatically.
  - GET /teams/{id}/members is open to any authenticated user who can see
                 the team at all — plain members can see their teammates
                 (read-only; no admin controls gated behind this response).

FOLLOW-UP — member removal and team deletion (unchanged by multi-team):

  - PATCH /teams/{id}/members/{user_id}/role — promotes/demotes an
    *existing* member within a team.
  - DELETE /teams/{id}/members/{user_id} — removes a member from a team.
    Self-serve (anyone can remove themselves) or forced (team_admin on own
    team / super_admin on any). Blocked if the target is the team's last
    remaining team_admin.
  - DELETE /teams/{id} — team_admin (own team) / super_admin (any team).
    Blocked unless every environment on the team is DESTROYED. This is a
    SOFT delete (teams.deleted_at) — see the Team model's docstring for why.

MULTI-TEAM MEMBERSHIP MIGRATION — what changed in this file and why.

Team membership moved from a single `users.team_id`/`users.role` pair to a
`team_memberships` table (one row per user-per-team, each with its own
role). This router is the one most affected:

  - POST / no longer blocks a user who already belongs to a team. Under
    the old model "you already belong to a team" was a hard 400, because
    User.team_id could only ever hold one value. That restriction is gone
    by construction now — creating a second (third, fourth...) team just
    adds another TeamMembership row. The creator becomes team_admin of the
    new team regardless of how many other teams they're already on, or
    what their platform_role is.

  - Every "team_admin (own team) / super_admin (any)" gate that used to be
    `Depends(require_team_admin)` plus a manual
    `current_user.role == "team_admin" and current_user.team_id != team_id`
    check is now `Depends(require_team_role("team_admin"))`. That manual
    check only worked because a user had exactly one team, so "is
    team_admin" and "is team_admin OF THIS TEAM" were the same question —
    under multi-team they're not, and require_team_role checks the role
    scoped to the team_id in the URL, not a global property of the user.

  - add_member() and update_member_role() both used to explicitly block
    acting on a user whose (single, shared) `role` was "super_admin" —
    because writing a team role through that column would have silently
    overwritten their platform privileges. That guard is now REMOVED. It's
    not just unneeded, it's structurally impossible for it to matter:
    TeamMembership.role is a separate column from User.platform_role, and
    the DB CHECK constraint on TeamMembership.role only permits
    'member'/'team_admin' — 'super_admin' can never even be written there.
    A team_admin can now freely add a super_admin to their team or set
    their team-scoped role, and the super_admin's platform_role is
    untouched either way. This is the actual bug fix this migration was
    for, not a side effect of it.

  - The "team_admin can't grant super_admin" guards in add_member/
    update_member_role are also removed — AddMemberRequest.role and
    UpdateMemberRoleRequest.role are now validated against TEAM_ROLES
    ({"member", "team_admin"}) at the schema layer, so submitting
    "super_admin" through either endpoint is rejected by Pydantic before
    the handler body ever runs. The guard is redundant, not just
    unreachable in practice — removing it removes dead code, not a check.

  - add_member() now explicitly 409s if the target user already has a
    TeamMembership row for this team, rather than silently overwriting one
    (the old model's `user.team_id = team.id; user.role = body.role` had
    no such conflict to guard, since a user could only ever be on one team).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.middleware.auth import get_current_user
from app.middleware.rbac import has_team_role, require_team_role
from app.models.audit_log import AuditLog
from app.models.environment import Environment
from app.models.team import Team
from app.models.team_membership import TeamMembership
from app.models.user import User
from app.schemas.environment import EnvironmentResponse
from app.schemas.team import (
    AddMemberRequest,
    CreateTeamRequest,
    TeamDeleteResponse,
    TeamDetailResponse,
    TeamMemberResponse,
    TeamResponse,
    UpdateMemberRoleRequest,
)

router = APIRouter()

# Environments in these statuses are still occupying (or about to occupy)
# real AWS resources, so they count toward a team's "active" total and its
# estimated running cost. DESTROYED and FAILED are excluded — FAILED never
# successfully finished provisioning, and DESTROYED no longer holds anything.
COST_RELEVANT_STATUSES = ("PENDING", "PROVISIONING", "RUNNING", "DESTROYING")


def _team_response(team: Team) -> TeamResponse:
    return TeamResponse(id=str(team.id), name=team.name, slug=team.slug)


def _team_member_response(user: User, role: str) -> TeamMemberResponse:
    """Builds a team-roster entry from a User plus that user's role on the
    ONE team being queried. `role` is passed explicitly rather than read
    off the user, since a user's role varies per team under multi-team
    membership — there's no single "the" role to read off User anymore."""
    return TeamMemberResponse(id=str(user.id), username=user.username, email=user.email, team_role=role)


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


def _get_active_team_or_404(db: Session, team_id: str) -> Team:
    """Fetches a team, treating a soft-deleted one as not found — a deleted
    team should behave as absent to every caller except the audit log."""
    team = db.query(Team).filter(Team.id == team_id, Team.deleted_at.is_(None)).first()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    return team


def _is_last_team_admin(db: Session, team_id: str, membership: TeamMembership) -> bool:
    """True if `membership` is a team_admin row on `team_id` and no other
    team_admin membership exists for that team. Used to block both
    demotion and removal of the last admin standing — a team must always
    have at least one.

    Unlike has_team_role()/team_role(), this genuinely needs a DB query —
    it's asking about every OTHER membership on the team, not just the
    current user's own eager-loaded rows."""
    if membership.role != "team_admin":
        return False
    other_admins = (
        db.query(TeamMembership)
        .filter(
            TeamMembership.team_id == team_id,
            TeamMembership.role == "team_admin",
            TeamMembership.id != membership.id,
        )
        .count()
    )
    return other_admins == 0


@router.post("/", response_model=TeamResponse, status_code=status.HTTP_201_CREATED)
def create_team(
    body: CreateTeamRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Self-serve team creation. Any authenticated user can create a team and
    becomes its team_admin — including a user who already belongs to one
    or more other teams, and including a super_admin (whose platform_role
    is unaffected either way; the team_admin membership is purely
    team-scoped, per this module's docstring).
    """
    existing = db.query(Team).filter(
        (Team.name == body.name) | (Team.slug == body.slug)
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="A team with that name or slug already exists")

    team = Team(name=body.name, slug=body.slug)
    db.add(team)
    db.flush()  # populate team.id before we reference it below

    db.add(TeamMembership(user_id=current_user.id, team_id=team.id, role="team_admin"))

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
    current_user: User = Depends(get_current_user),
):
    """super_admin sees every team. Everyone else sees only teams they
    currently hold a membership on (zero, one, or many)."""
    query = db.query(Team).filter(Team.deleted_at.is_(None))
    if current_user.platform_role != "super_admin":
        team_ids = [m.team_id for m in current_user.team_memberships]
        if not team_ids:
            return []
        query = query.filter(Team.id.in_(team_ids))
    teams = query.order_by(Team.name).all()
    return [_team_response(t) for t in teams]


@router.get("/{team_id}", response_model=TeamDetailResponse)
def get_team(
    team_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Team info + members + environments + aggregate stats in one call, so the
    frontend's team detail page doesn't need three separate round trips.
    """
    team = _get_active_team_or_404(db, team_id)
    if not has_team_role(current_user, team_id):
        raise HTTPException(status_code=403, detail="Not your team")

    memberships = (
        db.query(TeamMembership)
        .options(joinedload(TeamMembership.user))
        .filter(TeamMembership.team_id == team.id)
        .all()
    )
    memberships.sort(key=lambda m: m.user.username)

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
        members=[_team_member_response(m.user, m.role) for m in memberships],
        environments=[_environment_response(e) for e in environments],
        active_environment_count=active_count,
        estimated_monthly_cost_usd=round(estimated_cost, 2),
    )


@router.get("/{team_id}/members", response_model=List[TeamMemberResponse])
def list_members(
    team_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Read-only for everyone who can see the team at all — including plain
    members. No admin action is gated behind this response, just a roster.
    """
    _get_active_team_or_404(db, team_id)  # 404s if missing/soft-deleted; team itself unused below
    if not has_team_role(current_user, team_id):
        raise HTTPException(status_code=403, detail="Not your team")

    memberships = (
        db.query(TeamMembership)
        .options(joinedload(TeamMembership.user))
        .filter(TeamMembership.team_id == team_id)
        .all()
    )
    memberships.sort(key=lambda m: m.user.username)
    return [_team_member_response(m.user, m.role) for m in memberships]


@router.post("/{team_id}/members", response_model=TeamMemberResponse)
def add_member(
    team_id: str,
    body: AddMemberRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_team_role("team_admin")),
):
    """team_admin (own team) / super_admin (any team) — enforced by the
    require_team_role dependency, scoped to this specific team_id."""
    team = _get_active_team_or_404(db, team_id)

    user = db.query(User).filter(User.username == body.github_username).first()
    if not user:
        raise HTTPException(
            status_code=404,
            detail="User not found — they must log in with GitHub at least once first",
        )

    existing_membership = (
        db.query(TeamMembership)
        .filter(TeamMembership.user_id == user.id, TeamMembership.team_id == team.id)
        .first()
    )
    if existing_membership:
        raise HTTPException(status_code=409, detail="User is already a member of this team")

    membership = TeamMembership(user_id=user.id, team_id=team.id, role=body.role)
    db.add(membership)

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
    return _team_member_response(user, membership.role)


@router.patch("/{team_id}/members/{user_id}/role", response_model=TeamMemberResponse)
def update_member_role(
    team_id: str,
    user_id: str,
    body: UpdateMemberRoleRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_team_role("team_admin")),
):
    """
    Promotes or demotes an existing member of `team_id`. Distinct from the
    onboarding flow (POST .../members, which looks a user up by GitHub
    username) and from the platform-wide PATCH /users/{id}/role (super_admin
    only — see routers/users.py).
    """
    _get_active_team_or_404(db, team_id)  # 404s if missing/soft-deleted; team itself unused below

    target_membership = (
        db.query(TeamMembership)
        .options(joinedload(TeamMembership.user))
        .filter(TeamMembership.user_id == user_id, TeamMembership.team_id == team_id)
        .first()
    )
    if not target_membership:
        raise HTTPException(status_code=404, detail="User is not a member of this team")

    if body.role != "team_admin" and _is_last_team_admin(db, team_id, target_membership):
        raise HTTPException(
            status_code=400,
            detail="Cannot demote the team's last team_admin. Promote another member first.",
        )

    old_role = target_membership.role
    target_membership.role = body.role

    db.add(
        AuditLog(
            actor_id=current_user.id,
            action="USER_ROLE_CHANGED",
            actor_type="user",
            event_metadata={
                "user_id": str(target_membership.user_id),
                "username": target_membership.user.username,
                "team_id": team_id,
                "old_role": old_role,
                "new_role": body.role,
            },
        )
    )
    db.commit()
    return _team_member_response(target_membership.user, target_membership.role)


@router.delete("/{team_id}/members/{user_id}", response_model=TeamMemberResponse)
def remove_member(
    team_id: str,
    user_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Removes a member from a team (deletes their TeamMembership row for it —
    any OTHER team memberships they hold are untouched). Self-serve —
    anyone can call this on their own user_id to leave. Also usable by that
    team's team_admin (own team) or a super_admin (any team) to forcibly
    remove someone else. Blocked if the target is the team's last
    team_admin — see update_member_role() above for how to hand off first.
    """
    _get_active_team_or_404(db, team_id)  # 404s if missing/soft-deleted; team itself unused below

    is_self = str(current_user.id) == user_id
    is_forced_by_admin = has_team_role(current_user, team_id, "team_admin")
    if not is_self and not is_forced_by_admin:
        raise HTTPException(
            status_code=403,
            detail="You can only remove yourself, unless you're this team's team_admin or a super_admin",
        )

    target_membership = (
        db.query(TeamMembership)
        .options(joinedload(TeamMembership.user))
        .filter(TeamMembership.user_id == user_id, TeamMembership.team_id == team_id)
        .first()
    )
    if not target_membership:
        raise HTTPException(status_code=404, detail="User is not a member of this team")

    if _is_last_team_admin(db, team_id, target_membership):
        raise HTTPException(
            status_code=400,
            detail="Cannot remove the team's last team_admin. Promote another member first.",
        )

    # Capture everything the response/audit log needs before delete+commit —
    # the ORM object may be expired once the transaction commits.
    removed_user = target_membership.user
    old_role = target_membership.role

    db.delete(target_membership)
    db.add(
        AuditLog(
            actor_id=current_user.id,
            action="USER_REMOVED",
            actor_type="user",
            event_metadata={
                "user_id": str(removed_user.id),
                "username": removed_user.username,
                "team_id": team_id,
                "old_role": old_role,
                "self_serve": is_self,
            },
        )
    )
    db.commit()
    return _team_member_response(removed_user, old_role)


@router.delete("/{team_id}", response_model=TeamDeleteResponse)
def delete_team(
    team_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_team_role("team_admin")),
):
    """
    Deletes (soft-deletes) a team. team_admin (own team) / super_admin (any team).

    Blocked unless every environment on the team is DESTROYED — this is a
    hard, non-cascading precondition; the caller must destroy (or, for a
    FAILED environment, manually resolve) each one individually first. See
    this module's docstring for why environments and members are treated
    differently here, and the Team model's docstring for why this can't be
    a hard row delete.

    Remaining members are auto-detached as part of this same transaction —
    their TeamMembership rows for THIS team are deleted; any memberships
    they hold on other teams are untouched.
    """
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

    memberships = (
        db.query(TeamMembership)
        .options(joinedload(TeamMembership.user))
        .filter(TeamMembership.team_id == team_id)
        .all()
    )
    detached_usernames = [m.user.username for m in memberships]
    for m in memberships:
        db.delete(m)

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