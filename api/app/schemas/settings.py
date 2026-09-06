"""
Pydantic schemas for the platform settings endpoints (routers/settings.py).
"""

from typing import Optional

from pydantic import BaseModel


class PlatformSettingsResponse(BaseModel):
    """
    Returned by both GET /settings and PATCH /settings/ttl-enforcement.
    `updated_at`/`updated_by_username` describe the ttl_enforcement_enabled
    setting specifically — if more settings are added to the underlying
    key/value table later, this response shape (and the query behind it)
    will need to grow accordingly rather than being assumed to generalize
    automatically.
    """

    ttl_enforcement_enabled: bool
    updated_at: Optional[str] = None
    updated_by_username: Optional[str] = None


class ToggleTTLEnforcementRequest(BaseModel):
    enabled: bool