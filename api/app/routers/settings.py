"""
Platform Settings — Read & Toggle

Backs the small, deliberately generic key/value table in
models/platform_settings.py so a super_admin can flip platform-wide
runtime behavior without a redeploy. The only setting today is TTL
enforcement — see routers/environments.py's process_ttl(), the one place
that reads it via app/services/platform_settings.py.

GET /settings is readable by any authenticated user — not team-scoped,
since this isn't team data — matching the "roster readable by any member"
visibility pattern used elsewhere for read-only platform state (see
teams.py's GET /teams/{id}/members). Only PATCH /settings/ttl-enforcement
is super_admin-gated, via require_super_admin — the same dependency
users.py uses for platform-wide role changes, since this is exactly that
kind of change: platform-wide, not scoped to any one team.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.middleware.auth import get_current_user
from app.middleware.rbac import require_super_admin
from app.models.audit_log import AuditLog
from app.models.platform_settings import PlatformSettings
from app.models.user import User
from app.schemas.settings import PlatformSettingsResponse, ToggleTTLEnforcementRequest
from app.services.platform_settings import TTL_ENFORCEMENT_KEY, is_ttl_enforcement_enabled

router = APIRouter()


def _settings_response(db: Session) -> PlatformSettingsResponse:
    row = (
        db.query(PlatformSettings)
        .options(joinedload(PlatformSettings.updated_by))
        .filter(PlatformSettings.key == TTL_ENFORCEMENT_KEY)
        .first()
    )
    return PlatformSettingsResponse(
        ttl_enforcement_enabled=is_ttl_enforcement_enabled(db),
        updated_at=row.updated_at.isoformat() if row else None,
        updated_by_username=row.updated_by.username if row and row.updated_by else None,
    )


@router.get("/", response_model=PlatformSettingsResponse)
def get_settings(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return _settings_response(db)


@router.patch("/ttl-enforcement", response_model=PlatformSettingsResponse)
def toggle_ttl_enforcement(
    body: ToggleTTLEnforcementRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_super_admin),
):
    row = db.query(PlatformSettings).filter(PlatformSettings.key == TTL_ENFORCEMENT_KEY).first()
    previous = is_ttl_enforcement_enabled(db)

    if row is None:
        # Defensive only — the migration seeds this row, so this branch
        # shouldn't fire outside a hand-edited or partially-migrated DB.
        # Create it rather than 500ing on a missing singleton.
        row = PlatformSettings(key=TTL_ENFORCEMENT_KEY, value=body.enabled, updated_by_id=current_user.id)
        db.add(row)
    else:
        row.value = body.enabled
        row.updated_by_id = current_user.id

    db.add(
        AuditLog(
            actor_id=current_user.id,
            action="TTL_ENFORCEMENT_TOGGLED",
            actor_type="user",
            event_metadata={"enabled": body.enabled, "previous": previous},
        )
    )
    db.commit()
    return _settings_response(db)