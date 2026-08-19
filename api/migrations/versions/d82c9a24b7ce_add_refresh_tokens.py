"""add_refresh_tokens

Revision ID: d82c9a24b7ce
Revises: d1f42494587d
Create Date: 2026-08-19 00:00:00.000000

New table backing the httpOnly-cookie refresh-token flow (see
app/services/refresh_tokens.py's module docstring for the full design
rationale — opaque token + SHA-256 hash, rotation-on-use, reuse
detection).

One row per issued token. A row is never deleted on logout/rotation/reuse
— it's marked `revoked_at` instead, so a stolen-and-reused token is
detectable (a second presentation of an already-revoked hash is a strong
signal, not just "expired"). Nothing here purges old rows on a schedule;
at real scale this table would want a periodic sweep of long-expired,
already-revoked rows — acceptable to skip at portfolio-project scale, same
reasoning as the O(n) bcrypt loop in _user_from_api_key.

`user_id` uses `ON DELETE CASCADE` — a deliberate CONTRAST with
audit_logs.actor_id, which has no cascade specifically so audit history
survives a user's removal. A refresh token has zero value once its owner
is gone; there's nothing here worth preserving.

`replaced_by_id` self-references the row a token was rotated into, `ON
DELETE SET NULL` so cascading user-deletion doesn't hit FK ordering
issues when a whole rotation chain is removed together.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "d82c9a24b7ce"
down_revision = "d1f42494587d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "refresh_tokens",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "token_hash",
            sa.Text(),
            nullable=False,
            unique=True,
            comment=(
                "SHA-256 hex digest of the raw opaque token. The raw value "
                "itself is never persisted anywhere."
            ),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "revoked_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Set on logout, on successful rotation (old token revoked the instant it's used), or on reuse detection.",
        ),
        sa.Column(
            "replaced_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("refresh_tokens.id", ondelete="SET NULL"),
            nullable=True,
            comment="The token that superseded this one via rotation, if any.",
        ),
    )

    # Every refresh + logout call looks up a token by user_id (revoke-all
    # on reuse detection) — this index is what keeps that from becoming a
    # sequential scan as the table grows.
    op.create_index("ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_refresh_tokens_user_id", table_name="refresh_tokens")
    op.drop_table("refresh_tokens")