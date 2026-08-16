"""
TeamMembership ORM Model

The source of truth for team-scoped authorization. Introduced to support
multi-team membership: a user can now belong to zero, one, or many teams,
with a distinct role on each.

This deliberately replaces the old model where User.team_id / User.role
conflated two unrelated concepts — "is this user a super_admin platform-
wide" and "what can this user do on this specific team" — in a single pair
of columns. That conflation was the root cause of a real bug: a team-scoped
action (adding an existing super_admin to a team) could silently overwrite
User.role and corrupt their platform privileges, because there was no
structural separation between the two meanings. See models/user.py's
platform_role docstring for the other half of that fix.

`role` is TEXT with a DB-level CHECK constraint, not a plain unchecked
column and not a native Postgres ENUM type. This is a deliberate deviation
from the plain-TEXT-with-app-level-validation pattern used elsewhere in
this schema (e.g. environments.env_type, environments.status):

  - This column gates authorization decisions, not just display state — a
    bad value here is a security-relevant bug, which earns a stronger
    guarantee than the rest of the schema gets.

Relationships:
  TeamMembership → User: many-to-one (many memberships belong to one user)
  TeamMembership → Team: many-to-one (many memberships belong to one team)
"""

import uuid
from sqlalchemy import Column, DateTime, ForeignKey, Text, UniqueConstraint, CheckConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base


class TeamMembership(Base):
    __tablename__ = "team_memberships"
    __table_args__ = (
        UniqueConstraint("user_id", "team_id", name="uq_team_memberships_user_team"),
        CheckConstraint("role IN ('member', 'team_admin')", name="ck_team_memberships_role"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
        comment="The member. Combined with team_id, unique — a user has at most one row per team.",
    )
    team_id = Column(
        UUID(as_uuid=True),
        ForeignKey("teams.id"),
        nullable=False,
        index=True,
        comment="The team this membership grants access to. Indexed for roster/last-admin queries.",
    )
    role = Column(
        Text,
        nullable=False,
        comment="Team-scoped role: member | team_admin. See module docstring for why this is "
        "TEXT+CHECK rather than a native enum, and why it's a separate column from "
        "User.platform_role rather than reusing it.",
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # --- Relationships ---
    user = relationship("User", back_populates="team_memberships")
    team = relationship("Team", back_populates="memberships")

    def __repr__(self) -> str:
        return f"<TeamMembership user_id={self.user_id} team_id={self.team_id} role={self.role}>"