"""
User Identity & Role Management

Operations here act on a user directly by id — they never require (or
assume) that user belongs to a team. This is deliberately a separate router
from teams.py: `team_id` is nullable on the User model, so a super_admin can
promote someone before they've ever been assigned to any team. If this
endpoint lived under /teams/{team_id}/..., there'd be no sensible team_id to
put in the URL for that case — which is exactly why it doesn't.

Rule of thumb used to decide what belongs here vs. in teams.py: if the
permission check or the data being changed needs a team_id from the URL,
it's a /teams/... route. If it doesn't reference any team at all — as is
true for role changes — it belongs here instead.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.middleware.rbac import require_super_admin
from app.models.audit_log import AuditLog
from app.models.user import User
from app.schemas.user import ChangeRoleRequest, UserResponse

router = APIRouter()


def _user_response(user: User) -> UserResponse:
    return UserResponse(
        id=str(user.id),
        username=user.username,
        email=user.email,
        role=user.role,
        team_id=str(user.team_id) if user.team_id else None,
    )


@router.get("/", response_model=list[UserResponse])
def list_users(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_super_admin),
):
    """
    Every user on the platform, team or no team. This is what makes it
    possible to find and promote a user who's logged in via GitHub OAuth but
    hasn't been assigned to a team yet — GET /teams/{id}/members can't show
    them, since by definition they're not a member of anything.
    """
    users = db.query(User).order_by(User.username).all()
    return [_user_response(u) for u in users]


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

    old_role = user.role
    user.role = body.role

    db.add(
        AuditLog(
            actor_id=current_user.id,
            action="USER_ROLE_CHANGED",
            actor_type="user",
            event_metadata={
                "user_id": str(user.id),
                "old_role": old_role,
                "new_role": body.role,
            },
        )
    )
    db.commit()
    db.refresh(user)
    return _user_response(user)