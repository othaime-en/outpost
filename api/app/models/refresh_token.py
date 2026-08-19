"""
RefreshToken ORM Model

One row per issued (or since-rotated-away/revoked) refresh token. See
services/refresh_tokens.py's module docstring for the full design
rationale: opaque high-entropy token (not a JWT — this credential must be
revocable, which a self-verifying stateless JWT can't be), SHA-256 hash
at rest (not bcrypt — see that docstring for why bcrypt's deliberate
slowness is the wrong tool for a 384-bit random token), rotation-on-use,
and reuse detection.

Unlike audit_logs, which is deliberately append-only and never deleted
(it IS the record, kept even after the actor is long gone — see
audit_log.py), a refresh_tokens row has zero value once its owning user
is gone: there's nothing here worth preserving for audit purposes, only
ephemeral session material. Hence `ON DELETE CASCADE` on user_id, in
deliberate contrast to audit_logs.actor_id's lack of any cascade.
"""

import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Indexed — revoke_all_for_user() (reuse-detection containment) filters by this.",
    )

    token_hash = Column(
        Text,
        nullable=False,
        unique=True,
        comment=(
            "SHA-256 hex digest of the raw opaque token. The raw value itself "
            "is never persisted anywhere — see services/refresh_tokens.py."
        ),
    )

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)

    revoked_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment=(
            "Set on logout, on successful rotation (the OLD token is revoked "
            "the instant it's used), or defensively on reuse detection."
        ),
    )

    replaced_by_id = Column(
        UUID(as_uuid=True),
        ForeignKey("refresh_tokens.id", ondelete="SET NULL"),
        nullable=True,
        comment=(
            "Points at the token that superseded this one via rotation. Null "
            "if this token was never rotated (still active, or revoked some "
            "other way — logout, reuse detection, expiry)."
        ),
    )

    user = relationship("User")

    def __repr__(self) -> str:
        return f"<RefreshToken user_id={self.user_id} revoked={self.revoked_at is not None}>"