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
"""

from __future__ import annotations

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
from app.schemas.team import AddMemberRequest, CreateTeamRequest, TeamDetailResponse, TeamResponse
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
    query = db.query(Team)
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
    team = db.query(Team).filter(Team.id == team_id).first()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
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
    team = db.query(Team).filter(Team.id == team_id).first()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
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

    team = db.query(Team).filter(Team.id == team_id).first()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

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