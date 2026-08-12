"""
Pydantic schemas for team endpoints.

Role validation (VALID_ROLES) is imported from schemas/user.py rather than
redefined here — a team's AddMemberRequest sets a role too, so both files
share one source of truth for what a valid role string is.

TeamDetailResponse reuses EnvironmentResponse and UserResponse from the
sibling schema modules rather than redefining slimmer copies — the team
detail page shows the exact same environment cards/member rows the rest of
the UI already knows how to render, so the shapes need to match exactly.
"""

import re
from typing import List

from pydantic import BaseModel, Field, field_validator

from app.schemas.environment import EnvironmentResponse
from app.schemas.user import VALID_ROLES, UserResponse

SLUG_PATTERN = re.compile(r"^[a-z0-9-]+$")


class CreateTeamRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    slug: str = Field(..., min_length=1, max_length=50)

    @field_validator("slug")
    @classmethod
    def slug_must_be_url_safe(cls, v: str) -> str:
        if not SLUG_PATTERN.match(v):
            raise ValueError("slug must be lowercase alphanumeric with hyphens only")
        return v


class TeamResponse(BaseModel):
    id: str
    name: str
    slug: str


class TeamDetailResponse(BaseModel):
    """
    Response for GET /teams/{id}. Everything a "what team am I looking at"
    page needs in one call: who's on it, what it's running, and what that's
    costing — rather than making the frontend stitch together three separate
    requests (team, members, environments) itself.
    """

    id: str
    name: str
    slug: str
    created_at: str
    members: List[UserResponse]
    environments: List[EnvironmentResponse]
    # DESTROYED environments are excluded from this count — "active" means
    # currently occupying (or about to occupy) real AWS resources.
    active_environment_count: int
    # Sum of cost_estimate_usd across environments that are currently
    # incurring — or about to incur — AWS cost (i.e. not DESTROYED/FAILED).
    # This is the *estimate* total, same static pricing table as everywhere
    # else in the app; it is not a live Cost Explorer figure.
    estimated_monthly_cost_usd: float


class AddMemberRequest(BaseModel):
    github_username: str = Field(..., min_length=1)
    role: str = Field(default="member")

    @field_validator("role")
    @classmethod
    def role_must_be_valid(cls, v: str) -> str:
        if v not in VALID_ROLES:
            raise ValueError(f"role must be one of {sorted(VALID_ROLES)}")
        return v


class UpdateMemberRoleRequest(BaseModel):
    """Body for PATCH /teams/{id}/members/{user_id}/role — promotes or
    demotes an existing member within that team. Distinct from
    PATCH /users/{id}/role (see routers/users.py), which is platform-wide
    and super_admin-only; this one is team-scoped."""

    role: str = Field(...)

    @field_validator("role")
    @classmethod
    def role_must_be_valid(cls, v: str) -> str:
        if v not in VALID_ROLES:
            raise ValueError(f"role must be one of {sorted(VALID_ROLES)}")
        return v


class TeamDeleteResponse(BaseModel):
    ok: bool
    detached_members: List[str]  # usernames, for the confirmation UI