"""add_grace_period_and_pause_fields

Revision ID: e91f4a7c3b56
Revises: d82c9a24b7ce
Create Date: 2026-08-24 00:00:00.000000

Adds the columns needed for the TTL grace-period + pause safety net — see
routers/environments.py's module docstring, "GRACE PERIOD & PAUSE SAFETY
NET", for the full design rationale. Purely additive: no existing column
is touched and no backfill is needed (every existing environment simply
has NULL in all four new columns until it next passes through the
relevant part of the state machine), so this is a single migration rather
than an expand/contract pair.

The new environment statuses (EXPIRING, PAUSING, PAUSED, RESUMING) need no
schema change of their own — `environments.status` has always been a
plain TEXT column validated at the application layer (see Section 6 of
the implementation plan), not a DB CHECK constraint, unlike
team_memberships.role. Nothing here touches that column.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "e91f4a7c3b56"
down_revision: Union[str, None] = "d82c9a24b7ce"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "environments",
        sa.Column(
            "expiring_since",
            sa.DateTime(timezone=True),
            nullable=True,
            comment=(
                "Set when RUNNING -> EXPIRING. Cleared on extend (back to RUNNING) or on "
                "leaving EXPIRING for any other reason."
            ),
        ),
    )
    op.add_column(
        "environments",
        sa.Column(
            "paused_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Set when PAUSING -> PAUSED (confirmed by pause.yml's callback).",
        ),
    )
    op.add_column(
        "environments",
        sa.Column(
            "pause_expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment=(
                "paused_at + settings.paused_max_days. Past this, the TTL cron destroys the "
                "environment for real."
            ),
        ),
    )
    op.add_column(
        "environments",
        sa.Column(
            "pause_expiry_warning_sent_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment=(
                "Set the first time the 'will be destroyed soon' warning fires for a paused "
                "environment, so the 15-min cron sends it once, not on every pass."
            ),
        ),
    )


def downgrade() -> None:
    op.drop_column("environments", "pause_expiry_warning_sent_at")
    op.drop_column("environments", "pause_expires_at")
    op.drop_column("environments", "paused_at")
    op.drop_column("environments", "expiring_since")