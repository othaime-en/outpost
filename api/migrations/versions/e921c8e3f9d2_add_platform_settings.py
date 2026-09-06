"""add_platform_settings

Revision ID: e921c8e3f9d2
Revises: e91f4a7c3b56
Create Date: 2026-09-05 00:00:00.000000

Adds a small, deliberately generic key/value settings table so a
super_admin can toggle platform-wide runtime behavior — starting with TTL
enforcement — without a redeploy. See routers/settings.py's module
docstring for the read/write API this backs, and
routers/environments.py's process_ttl() for the one place that reads it
today.

Key/value (rather than, say, a dedicated `ttl_enforcement_enabled` boolean
column bolted onto some other table) is a deliberate choice: the next
runtime toggle this project needs won't require its own migration, just a
new seeded row. `value` is JSONB for the same reason — different settings
will have different shapes.

Seeds exactly one row (ttl_enforcement_enabled=true) so the table is never
empty in practice. app/services/platform_settings.py's
is_ttl_enforcement_enabled() still defaults to True defensively if the row
is ever missing (e.g. a hand-edited DB) — failing this check closed would
silently and permanently disable cost-governance TTL enforcement with no
operator visibility, a worse failure mode than "enforcement stays on."

Purely additive: no existing table or column is touched, so this is a
single migration rather than an expand/contract pair.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

# revision identifiers, used by Alembic.
revision: str = "e921c8e3f9d2"
down_revision: Union[str, None] = "e91f4a7c3b56"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "platform_settings",
        sa.Column(
            "key",
            sa.Text(),
            primary_key=True,
            comment="Setting name, e.g. 'ttl_enforcement_enabled'.",
        ),
        sa.Column("value", JSONB(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_by_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
    )
    op.execute(
        "INSERT INTO platform_settings (key, value, updated_at) "
        "VALUES ('ttl_enforcement_enabled', 'true'::jsonb, now())"
    )


def downgrade() -> None:
    op.drop_table("platform_settings")