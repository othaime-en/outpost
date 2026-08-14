"""
Pydantic schemas for user-identity endpoints — and the shared user
representation other routers (e.g. teams.py) reuse when returning a user.

PLATFORM_ROLES and TEAM_ROLES replace the old single VALID_ROLES set. Under
the single-team model, one role value (member/team_admin/super_admin) meant
different things depending on context, but there was only ever one column
to validate it against. Now that platform-wide role (User.platform_role)
and team-scoped role (TeamMembership.role) are genuinely different concepts
with disjoint value sets, they need separate validation:

  PLATFORM_ROLES = {"user", "super_admin"}         — see ChangeRoleRequest
  TEAM_ROLES     = {"member", "team_admin"}         — see schemas/team.py's
                                                        AddMemberRequest /
                                                        UpdateMemberRoleRequest

schemas/team.py imports TEAM_ROLES from here rather than redefining its own
copy, same sharing pattern as before.
"""

from typing import List, Optional

from pydantic import BaseModel, field_validator

PLATFORM_ROLES = {"user", "super_admin"}
TEAM_ROLES = {"member", "team_admin"}


class TeamMembershipOut(BaseModel):
    """One row of `GET /users` or `/auth/me`'s membership list — this
    user's role on one specific team."""

    team_id: str
    team_name: str
    team_slug: str
    role: str  # 'member' | 'team_admin'


class UserResponse(BaseModel):
    """
    Platform-wide user representation — used by GET /users and
    PATCH /users/{id}/role. Not used for team-roster listings
    (GET /teams/{id}/members etc.) — those return TeamMemberResponse
    instead (see schemas/team.py), since "role" in a team-roster context
    means that team's membership role, not platform_role, and conflating
    the two in one response shape is exactly the ambiguity this migration
    exists to remove.
    """

    id: str
    username: str
    email: Optional[str]
    platform_role: str
    team_memberships: List[TeamMembershipOut] = []


class ChangeRoleRequest(BaseModel):
    """Body for PATCH /users/{id}/role — platform-wide, super_admin only.
    Validated against PLATFORM_ROLES, not TEAM_ROLES."""

    role: str

    @field_validator("role")
    @classmethod
    def role_must_be_valid(cls, v: str) -> str:
        if v not in PLATFORM_ROLES:
            raise ValueError(f"role must be one of {sorted(PLATFORM_ROLES)}")
        return v