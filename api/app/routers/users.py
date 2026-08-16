"""
User Identity & Platform Role Management

Operations here act on a user directly by id and change PLATFORM-wide
state only — they never require (or assume) any specific team. This is
deliberately a separate router from teams.py: a user can hold zero, one,
or many team memberships, so a super_admin can promote someone's platform
role before they've ever joined any team, or while they belong to several.
If this endpoint lived under /teams/{team_id}/..., there'd be no single
correct team_id to put in the URL for those cases — which is exactly why
it doesn't.

Rule of thumb used to decide what belongs here vs. in teams.py: if the
permission check or the data being changed needs a team_id from the URL,
it's a /teams/... route. If it doesn't reference any team at all — as is
true for platform role changes — it belongs here instead.

MULTI-TEAM CHANGE: the audit action for this endpoint is now
PLATFORM_ROLE_CHANGED, not USER_ROLE_CHANGED. Under the old single-role
model there was only one kind of role change, so one action name covered
it. Now that routers/teams.py's update_member_role() ALSO writes
USER_ROLE_CHANGED for a conceptually different event (a team-scoped role
change), reusing the same action name here would make the audit log
genuinely ambiguous about which kind of change happened. Renaming this one
disambiguates without touching the team-scoped action's existing name.
"""

from __future__ import annotations

from sqlalchemy.orm import Session, joinedload

from fastapi import APIRouter, Depends, HTTPException
from app.database import get_db
from app.middleware.rbac import require_super_admin
from app.models.audit_log import AuditLog
from app.models.team_membership import TeamMembership
from app.models.user import User
from app.schemas.user import ChangeRoleRequest, TeamMembershipOut, UserResponse

router = APIRouter()


def _user_response(user: User, db: Session) -> UserResponse:
    memberships = (
        db.query(TeamMembership)
        .options(joinedload(TeamMembership.team))
        .filter(TeamMembership.user_id == user.id)
        .all()
    )
    return UserResponse(
        id=str(user.id),
        username=user.username,
        email=user.email,
        platform_role=user.platform_role,
        team_memberships=[
            TeamMembershipOut(
                team_id=str(m.team_id),
                team_name=m.team.name,
                team_slug=m.team.slug,
                role=m.role,
            )
            for m in memberships
        ],
    )


@router.get("/", response_model=list[UserResponse])
def list_users(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_super_admin),
):
    """
    Every user on the platform, with their full team membership list. This
    is what makes it possible to find and promote a user's platform role
    regardless of how many teams (including zero) they currently belong to.
    """
    users = db.query(User).order_by(User.username).all()
    return [_user_response(u, db) for u in users]


@router.patch("/{user_id}/role", response_model=UserResponse)
def change_role(
    user_id: str,
    body: ChangeRoleRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_super_admin),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    old_role = user.platform_role
    user.platform_role = body.role

    db.add(
        AuditLog(
            actor_id=current_user.id,
            action="PLATFORM_ROLE_CHANGED",
            actor_type="user",
            event_metadata={
                "user_id": str(user.id),
                "old_platform_role": old_role,
                "new_platform_role": body.role,
            },
        )
    )
    db.commit()
    db.refresh(user)
    return _user_response(user, db)