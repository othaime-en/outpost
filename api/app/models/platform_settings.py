"""
Platform Settings ORM Model

Deliberately generic key/value store for platform-wide runtime toggles a
super_admin needs to flip without a redeploy or a new migration. The first
(and, as of this writing, only) consumer is TTL enforcement — see
routers/settings.py for the read/write API this backs, and
routers/environments.py's process_ttl() for the one place that currently
reads it.

`key` is the primary key (not a synthetic UUID id), and `value` is JSONB
rather than a typed column — this is intentionally NOT a general-purpose
audited entity like Environment or Team. One row per named setting, looked
up by name, is the whole shape. The next runtime toggle this project needs
should just be a new seeded row, not another migration.

updated_by_id has no ON DELETE CASCADE and is nullable — matching
audit_logs.actor_id's reasoning, not refresh_tokens.user_id's: knowing who
last flipped a platform setting is worth keeping even if that user's
account is ever removed. There's no user-deletion endpoint today anyway,
and this is attribution, not a live credential that needs to disappear
with its owner.
"""

from sqlalchemy import Column, DateTime, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.database import Base


class PlatformSettings(Base):
    __tablename__ = "platform_settings"

    key = Column(
        Text,
        primary_key=True,
        comment="Setting name, e.g. 'ttl_enforcement_enabled'. Looked up by name, not by a separate id.",
    )
    value = Column(
        JSONB,
        nullable=False,
        comment="Setting value — shape depends on `key`. A plain bool today, but JSONB so future "
        "settings aren't forced into that shape.",
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    updated_by_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
        comment="Who last changed this setting. Null if never changed since seeding.",
    )

    # No back_populates on User — this is a rarely-queried, one-directional
    # attribution field, not a relationship anything needs to traverse from
    # the User side (unlike team_memberships/environments/audit_logs).
    updated_by = relationship("User")

    def __repr__(self) -> str:
        return f"<PlatformSettings key={self.key} value={self.value}>"