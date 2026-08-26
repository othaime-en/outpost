"""
Pydantic schemas for environment endpoints.

CreateEnvironmentRequest.team_id is new: under the old single-team model,
which team an environment belonged to was implicit (current_user.team_id).
Now that a user can belong to more than one team, the caller must say which
one. The router validates this against the caller's actual memberships via
has_team_role() — passing an arbitrary team_id is rejected with 403, not
silently accepted.

CallbackRequest.status covers every value GitHub Actions can ever POST
back: RUNNING (provision.yml completing, OR resume.yml completing — the
router tells the two apart by the environment's prior status, not by this
field), PAUSED (pause.yml completing), DESTROYED, and FAILED. PENDING,
PROVISIONING, EXPIRING, PAUSING, DESTROYING, and RESUMING are states the
API itself sets before or while dispatching a workflow, never values a
callback should be allowed to set directly.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator

NAME_PATTERN = re.compile(r"^[a-z0-9-]+$")
VALID_ENV_TYPES = {"dev", "staging"}
VALID_CALLBACK_STATUSES = {"RUNNING", "PAUSED", "DESTROYED", "FAILED"}


class CreateEnvironmentRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    team_id: str = Field(..., description="Team this environment belongs to. Must be one of "
                          "the caller's own team memberships (or any team, for a super_admin).")
    env_type: str
    ttl_hours: int = Field(default=24, ge=1, le=168)
    aws_region: str = Field(default="us-east-1")

    @field_validator("name")
    @classmethod
    def name_must_be_url_safe(cls, v: str) -> str:
        if not NAME_PATTERN.match(v):
            raise ValueError("name must be lowercase alphanumeric with hyphens only")
        return v

    @field_validator("env_type")
    @classmethod
    def env_type_must_be_valid(cls, v: str) -> str:
        if v not in VALID_ENV_TYPES:
            raise ValueError(f"env_type must be one of {sorted(VALID_ENV_TYPES)}")
        return v


class CreateEnvironmentResponse(BaseModel):
    env_id: str
    status: str


class ExtendTTLRequest(BaseModel):
    extend_hours: int = Field(..., ge=1, le=168)


class ExtendTTLResponse(BaseModel):
    expires_at: str


class CallbackRequest(BaseModel):
    status: str
    outputs: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    actor: Optional[str] = "system"

    @field_validator("status")
    @classmethod
    def status_must_be_valid(cls, v: str) -> str:
        if v not in VALID_CALLBACK_STATUSES:
            raise ValueError(f"status must be one of {sorted(VALID_CALLBACK_STATUSES)}")
        return v


class EnvironmentResponse(BaseModel):
    id: str
    name: str
    team_id: str
    team_slug: str
    created_by: str
    created_by_username: str
    env_type: str
    status: str
    ttl_hours: int
    expires_at: str
    aws_region: str
    outputs: Optional[Dict[str, Any]] = None
    health_status: str
    health_checked_at: Optional[str] = None
    cost_estimate_usd: Optional[float] = None
    created_at: str
    destroyed_at: Optional[str] = None
    # --- Grace period & pause — see routers/environments.py's module
    # docstring, "GRACE PERIOD & PAUSE SAFETY NET" ---
    expiring_since: Optional[str] = None
    paused_at: Optional[str] = None
    pause_expires_at: Optional[str] = None


class ExpiredEnvironmentResponse(BaseModel):
    env_id: str
    name: str
    team: str


class ProcessTTLTarget(BaseModel):
    env_id: str
    region: str


class ProcessTTLResponse(BaseModel):
    """
    Returned by POST /environments/process-ttl. The endpoint has already
    updated each environment's DB status by the time it returns —
    `to_pause`/`to_destroy` are just the env_ids (+region) the caller
    (ttl-cron.yml) still needs to dispatch a workflow for. See that
    endpoint's docstring for the three sweeps this summarizes.
    """
    transitioned_to_expiring: List[str]
    to_pause: List[ProcessTTLTarget]
    to_destroy: List[ProcessTTLTarget]


class RunbookResponse(BaseModel):
    content_md: str
    generated_at: str


class CostBreakdownResponse(BaseModel):
    ecs_fargate: float
    rds_postgres: float
    cloudwatch_logs: float
    secrets_manager: float
    total_monthly: float
    env_type: str
    note: str


class CostSnapshotResponse(BaseModel):
    period_start: str
    period_end: str
    actual_cost_usd: float


EnvironmentListResponse = List[EnvironmentResponse]
CostSnapshotListResponse = List[CostSnapshotResponse]