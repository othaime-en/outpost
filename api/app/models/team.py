"""
Team ORM Model

A Team is a logical grouping of users. Every environment is owned by
exactly one team, and RBAC rules are scoped to team membership.

The `slug` field is particularly important — it's used as a tag value on all
AWS resources provisioned for that team's environments. This is how Cost Explorer
knows which team incurred which charges. It must be URL-safe (lowercase, hyphens only).

`deleted_at` — teams are SOFT-deleted, same pattern as Environment.destroyed_at.
This isn't optional: `environments.team_id` is NOT NULL with a default
(RESTRICT) foreign key, and environment rows are deliberately never removed
even after DESTROYED (audit trail, cost history). A hard `DELETE FROM teams`
would raise a ForeignKeyViolation for any team that ever had a single
environment — which is effectively every team that's actually been used.
See routers/teams.py's delete_team() for the enforcement.

Relationships:
  Team → TeamMembership: one-to-many (a team has many memberships — this
                          replaces the old direct Team → User relationship
                          now that a user can belong to more than one team;
                          reach members via membership.user)
  Team → Environment:    one-to-many (a team has many environments)
"""

import uuid
from sqlalchemy import Column, String, DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base


class Team(Base):
    __tablename__ = "teams"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        comment="UUID primary key — also used as a stable identifier in AWS tags",
    )
    name = Column(
        String,
        nullable=False,
        unique=True,
        comment="Human-readable team name, e.g. 'Platform Engineering'",
    )
    slug = Column(
        String,
        nullable=False,
        unique=True,
        comment="URL-safe identifier used in AWS resource tags, e.g. 'platform-eng'",
    )
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    deleted_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="Soft-delete marker. NULL means active. See module docstring for why this can't be a hard delete.",
    )

    # --- Relationships ---
    memberships = relationship("TeamMembership", back_populates="team")
    environments = relationship("Environment", back_populates="team")