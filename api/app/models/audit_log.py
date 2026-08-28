"""
Audit Log ORM Model

The audit log is append-only. Rows are NEVER updated or deleted.
"""

import uuid
from sqlalchemy import Column, String, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship

from app.database import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    environment_id = Column(
        UUID(as_uuid=True),
        ForeignKey("environments.id"),
        nullable=True,
        comment="Null for non-environment actions like USER_ADDED, TEAM_CREATED",
    )
    actor_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
        comment="Null when actor_type is 'system' or 'cron' — no human involved",
    )
    action = Column(
        String,
        nullable=False,
        comment=(
            "Enum-like string. Valid values: "
            "ENV_CREATED | ENV_PROVISIONING | ENV_RUNNING | "
            "ENV_DESTROY_REQUESTED | ENV_DESTROYING | ENV_DESTROYED | ENV_CANCELLED | "
            "ENV_FAILED | ENV_CALLBACK_IGNORED | "
            "ENV_EXPIRING | ENV_EXTENDED_FROM_EXPIRING | "
            "ENV_PAUSE_REQUESTED | ENV_PAUSED | ENV_RESUME_REQUESTED | ENV_RESUMED | "
            "ENV_PAUSE_EXPIRED_DESTROYED | "
            "TTL_EXTENDED | USER_ADDED | USER_REMOVED | USER_ROLE_CHANGED | "
            "PLATFORM_ROLE_CHANGED | "
            "TEAM_CREATED | TEAM_DELETED | API_KEY_GENERATED. "
            "ENV_CANCELLED and ENV_CALLBACK_IGNORED added alongside PENDING-environment "
            "cancellation — see routers/environments.py's module docstring, "
            "'CANCELLING A PENDING ENVIRONMENT'. The ENV_EXPIRING through "
            "ENV_PAUSE_EXPIRED_DESTROYED actions were added alongside the grace-period/pause "
            "safety net — see that same file's docstring, 'GRACE PERIOD & PAUSE SAFETY NET'. "
            "USER_REMOVED and PLATFORM_ROLE_CHANGED existed already (routers/teams.py and "
            "routers/users.py respectively) but were missing from this comment; added for "
            "accuracy, not new behavior."
        ),
    )
    actor_type = Column(
        String,
        nullable=False,
        default="user",
        comment="user | system | cron — distinguishes human vs automated actions",
    )
    event_metadata = Column(
        "metadata",  # actual PostgreSQL column name
        JSONB,
        nullable=True,
        comment="Action-specific context: error messages, old/new values, IP addresses, etc.",
    )
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        comment="Indexed for efficient time-range queries — see migration for index definition",
    )

    # --- Relationships ---
    environment = relationship("Environment", back_populates="audit_logs")
    actor = relationship("User", back_populates="audit_logs")