"""
Pydantic schemas for auth endpoints.
"""

from typing import List, Optional

from pydantic import BaseModel

from app.schemas.user import TeamMembershipOut


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserProfile(BaseModel):
    """
    Response for GET /auth/me. Replaces the old flat role/team_id fields:
    platform_role answers "is this user a super_admin platform-wide" —
    nothing team-specific. team_memberships lists every team this user
    belongs to and their role on each; zero entries means not yet on any
    team, more than one is the "embedded engineer across two teams" case
    multi-team membership exists to support.
    """

    id: str
    username: str
    email: Optional[str] = None
    platform_role: str
    team_memberships: List[TeamMembershipOut] = []


class ApiKeyResponse(BaseModel):
    api_key: str
    note: str = "Store this now — it will not be shown again."