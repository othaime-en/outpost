"""
User ORM Model

Users authenticate via GitHub OAuth.

platform_role is now the ONLY role concept that lives directly on User —
and it means something narrower than the old `role` column did:

  platform_role:
    'user'         → No platform-wide privileges beyond whatever their
                      individual team memberships grant.
    'super_admin'  → Full platform access, everywhere, unconditionally —
                      independent of any team membership.

Everything about what a user can do on a *specific* team — 'member' vs.
'team_admin' — now lives exclusively in TeamMembership.role, one row per
(user, team) pair, via the team_memberships relationship below. A user can
have zero, one, or many such rows.

This is a deliberate split from the old single `role` column, which
conflated "platform-wide privilege" and "this team's role" and could not
represent more than one team per user. The old model also had a real bug
as a consequence: a team-scoped action (adding an existing super_admin to
a team) could silently overwrite `role` and corrupt platform privileges,
since there was no structural separation between the two meanings. That
class of bug is now impossible by construction — a team_admin editing
TeamMembership.role has no column through which to reach platform_role.

Relationships:
  User → TeamMembership: one-to-many (a user holds 0..N team memberships)
  User → Environment:    one-to-many (a user creates many environments)
  User → AuditLog:       one-to-many (a user performs many audited actions)
"""

import uuid
from sqlalchemy import Column, String, BigInteger, DateTime, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    github_id = Column(
        BigInteger,
        nullable=False,
        unique=True,
        comment="GitHub's internal numeric user ID — stable even if username changes",
    )
    username = Column(
        String,
        nullable=False,
        comment="GitHub login handle — display only, do NOT use as a key",
    )
    email = Column(
        String,
        nullable=True,
        comment="May be null if the user's GitHub email is private",
    )
    platform_role = Column(
        Text,
        nullable=False,
        default="user",
        comment="Platform-wide role ONLY: 'user' | 'super_admin'. Carries no information about "
        "any specific team — that's TeamMembership.role's job. See module docstring.",
    )
    api_key_hash = Column(
        String,
        nullable=True,
        comment="bcrypt hash of the CLI API key. Never store the plaintext key.",
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # --- Relationships ---
    team_memberships = relationship("TeamMembership", back_populates="user")
    environments = relationship("Environment", back_populates="creator")
    audit_logs = relationship("AuditLog", back_populates="actor")

    def __repr__(self) -> str:
        return f"<User username={self.username} platform_role={self.platform_role}>"