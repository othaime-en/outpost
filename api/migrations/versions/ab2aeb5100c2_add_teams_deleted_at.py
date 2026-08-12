"""add_teams_deleted_at

Revision ID: ab2aeb5100c2
Revises: 054a3bd6eeb6
Create Date: 2026-08-11 00:00:00.000000

Adds teams.deleted_at for soft-deleting teams.

Teams cannot be hard-deleted: environments.team_id is NOT NULL with a
default (RESTRICT) foreign key, and environment rows are deliberately kept
forever even after DESTROYED (audit trail, cost history — see the
Environment model and Phase 8's Design Decisions Q&A on soft deletes). Any
team that has ever had a single environment would raise a
ForeignKeyViolation on a hard `DELETE FROM teams`. Soft-deleting instead
keeps the row (and every environment's team_id reference) intact forever,
consistent with the same pattern already used for environments.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "ab2aeb5100c2"
down_revision: Union[str, None] = "054a3bd6eeb6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "teams",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("teams", "deleted_at")