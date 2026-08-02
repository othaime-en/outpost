"""
Audit Log Queries

Read-only. A member/team_admin sees audit rows tied to their own team's
environments, plus any action they personally performed even when it isn't
tied to an environment at all (e.g. API_KEY_GENERATED, TEAM_CREATED).
super_admin sees every row, unfiltered by team.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.middleware.rbac import require_member
from app.models.audit_log import AuditLog
from app.models.environment import Environment
from app.models.user import User
from app.schemas.audit import AuditLogResponse, PaginatedAuditResponse

router = APIRouter()


def _log_response(log: AuditLog) -> AuditLogResponse:
    return AuditLogResponse(
        id=str(log.id),
        environment_id=str(log.environment_id) if log.environment_id else None,
        actor_id=str(log.actor_id) if log.actor_id else None,
        action=log.action,
        actor_type=log.actor_type,
        metadata=log.event_metadata,
        created_at=log.created_at.isoformat(),
    )


@router.get("/", response_model=PaginatedAuditResponse)
def list_audit_logs(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_member),
    environment_id: Optional[str] = Query(default=None),
    action: Optional[str] = Query(default=None),
    actor_type: Optional[str] = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, le=200),
):
    query = db.query(AuditLog)

    if current_user.role != "super_admin":
        team_env_ids = db.query(Environment.id).filter(
            Environment.team_id == current_user.team_id
        )
        query = query.filter(
            or_(
                AuditLog.environment_id.in_(team_env_ids),
                AuditLog.actor_id == current_user.id,
            )
        )

    if environment_id:
        query = query.filter(AuditLog.environment_id == environment_id)
    if action:
        query = query.filter(AuditLog.action == action)
    if actor_type:
        query = query.filter(AuditLog.actor_type == actor_type)

    total = query.count()
    logs = (
        query.order_by(AuditLog.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return PaginatedAuditResponse(
        total=total,
        page=page,
        page_size=page_size,
        items=[_log_response(log) for log in logs],
    )