"""scope_team_uniqueness_to_active_rows

Revision ID: c9c869c63ffd
Revises: baf70fge2a6s
Create Date: 2026-08-17 00:00:00.000000

Bug fix: teams.name and teams.slug are plain `UNIQUE` columns
(teams_name_key / teams_slug_key from the initial schema), and that
constraint was never revisited when ab2aeb5100c2 added soft deletes.
A soft-deleted team's name/slug therefore stay reserved forever —
create_team() would 409 on a brand-new team that happens to reuse the name
of a team someone deleted six months ago, which is not the intent of
soft-deleting (soft delete exists to preserve the audit trail and satisfy
environments.team_id's RESTRICT FK — see Team model + ab2aeb5100c2's
docstrings — not to reserve the name/slug namespace indefinitely).

Fix: replace the plain UNIQUE constraints with partial unique indexes
scoped to `WHERE deleted_at IS NULL`. Two (or more) soft-deleted teams can
now share a name/slug with each other and with a currently-active team's
former name — only ACTIVE teams must be unique against each other. This is
the standard Postgres pattern for "unique among non-deleted rows."

The corresponding query-side fix — create_team()'s duplicate check must
also filter to Team.deleted_at.is_(None), or the DB constraint change here
does nothing on its own — ships in the same commit as this migration.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "c9c869c63ffd"
down_revision: Union[str, None] = "baf70fge2a6s"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("teams_name_key", "teams", type_="unique")
    op.drop_constraint("teams_slug_key", "teams", type_="unique")

    op.create_index(
        "uq_teams_name_active",
        "teams",
        ["name"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "uq_teams_slug_active",
        "teams",
        ["slug"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    # NOTE: this will raise a UniqueViolation if any two soft-deleted teams
    # (or a soft-deleted and an active team) share a name or slug at the
    # time of downgrade — that state is only reachable after upgrade(), by
    # design. Resolve/rename the conflicting rows manually before
    # downgrading if that's occurred.
    op.drop_index("uq_teams_slug_active", table_name="teams")
    op.drop_index("uq_teams_name_active", table_name="teams")

    op.create_unique_constraint("teams_slug_key", "teams", ["slug"])
    op.create_unique_constraint("teams_name_key", "teams", ["name"])