"""
Environment ORM Model

This is the central entity of the entire application. Every other model
either belongs to an environment (audit_logs, runbook, cost_snapshots) or
owns environments (team, user).

GRACE PERIOD & PAUSE FIELDS — see routers/environments.py's module
docstring, "GRACE PERIOD & PAUSE SAFETY NET", for the full design. In
short: a RUNNING environment whose TTL expires no longer goes straight to
DESTROYING. It passes through EXPIRING (a 24h grace period) and, if nobody
extends it, PAUSING/PAUSED (ECS scaled to 0, RDS stopped — reversible) for
up to 7 days before a final, distinctly-audited destroy. `expiring_since`,
`paused_at`, `pause_expires_at`, and `pause_expiry_warning_sent_at` back
that flow; all four are nullable and unrelated to the older `expires_at`/
`ttl_hours` pair, which continue to mean exactly what they always did.
"""

import uuid
from sqlalchemy import Column, String, Integer, ForeignKey, DateTime, Numeric, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship

from app.database import Base


class Environment(Base):
    __tablename__ = "environments"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        comment="Also used as the Terraform workspace name and S3 state key",
    )
    name = Column(
        String,
        nullable=False,
        comment="Human label, e.g. 'my-feature-branch'. Validated: lowercase alphanum + hyphens",
    )
    team_id = Column(
        UUID(as_uuid=True),
        ForeignKey("teams.id"),
        nullable=False,
    )
    created_by = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
    )
    env_type = Column(
        String,
        nullable=False,
        comment="dev | staging — affects resource sizing and cost multiplier",
    )
    status = Column(
        String,
        nullable=False,
        default="PENDING",
        comment=(
            "PENDING | PROVISIONING | RUNNING | EXPIRING | PAUSING | PAUSED | RESUMING | "
            "DESTROYING | DESTROYED | FAILED — see routers/environments.py's module "
            "docstring for the full state machine, including the grace-period/pause branch "
            "added alongside expiring_since/paused_at/pause_expires_at below."
        ),
    )
    ttl_hours = Column(
        Integer,
        nullable=False,
        default=24,
        comment="Requested lifetime. expires_at = created_at + ttl_hours",
    )
    expires_at = Column(
        DateTime(timezone=True),
        nullable=False,
        comment="When the TTL cron moves this environment from RUNNING into EXPIRING",
    )
    expiring_since = Column(
        DateTime(timezone=True),
        nullable=True,
        comment=(
            "Set when RUNNING -> EXPIRING. Cleared on extend (back to RUNNING) or on leaving "
            "EXPIRING for any other reason. The TTL cron auto-pauses once "
            "settings.expiring_grace_period_hours has elapsed since this timestamp."
        ),
    )
    aws_region = Column(
        String,
        nullable=False,
        default="us-east-1",
    )
    outputs = Column(
        JSONB,
        nullable=True,
        comment="Terraform outputs written by the /callback endpoint: ARNs, endpoints, etc.",
    )
    health_status = Column(
        String,
        nullable=False,
        default="UNKNOWN",
        comment="HEALTHY | DEGRADED | UNKNOWN — polled from CloudWatch every 5 minutes",
    )
    health_checked_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="Timestamp of the last CloudWatch health poll",
    )
    cost_estimate_usd = Column(
        Numeric(10, 4),
        nullable=True,
        comment="Static monthly cost estimate computed at creation time",
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    destroyed_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="Set when status transitions to DESTROYED. Never hard-deleted.",
    )
    paused_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="Set when PAUSING -> PAUSED (confirmed by pause.yml's callback).",
    )
    pause_expires_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment=(
            "paused_at + settings.paused_max_days. Past this, the TTL cron destroys the "
            "environment for real — audited as ENV_PAUSE_EXPIRED_DESTROYED, not ENV_DESTROYED."
        ),
    )
    pause_expiry_warning_sent_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment=(
            "Set the first time the 'will be destroyed soon' notification fires for a paused "
            "environment, so the 15-min cron sends it once rather than on every pass."
        ),
    )

    # --- Relationships ---
    team = relationship("Team", back_populates="environments")
    creator = relationship("User", back_populates="environments")
    audit_logs = relationship("AuditLog", back_populates="environment")
    runbook = relationship("Runbook", back_populates="environment", uselist=False)
    cost_snapshots = relationship("CostSnapshot", back_populates="environment")