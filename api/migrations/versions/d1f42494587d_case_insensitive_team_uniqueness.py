"""case_insensitive_team_uniqueness

Revision ID: d1f42494587d
Revises: c9c869c63ffd
Create Date: 2026-08-17 00:00:00.000000

Follow-up to e9c869c63ffd, which scoped team name/slug uniqueness to
active (non-deleted) rows but left it case-SENSITIVE — "Platform Eng" and
"platform eng" could still coexist as two different active teams, which
isn't the intent of a uniqueness constraint meant to prevent naming
collisions.

Fix: replace the two partial unique indexes with functional partial
unique indexes on `lower(name)` / `lower(slug)`, still scoped to
`WHERE deleted_at IS NULL`. Two teams may no longer differ only by case.

Deliberately NOT changed here: the `name` COLUMN itself is untouched and
stores whatever casing the creator typed ("IDP Lite", "K8s Platform",
etc.) — this migration only affects the uniqueness CHECK, not what's
persisted. There's no companion data migration to lowercase existing rows
in place, because the column values aren't changing, only how two of them
are compared for the purposes of the constraint.

`op.execute()` raw SQL is used instead of `op.create_index(..., unique=True)`
because Alembic's index-builder API doesn't have a clean cross-version way
to express a functional expression (`lower(name)`) as the index target
alongside a `postgresql_where` partial predicate — CREATE UNIQUE INDEX ...
ON teams (lower(name)) WHERE ... needs the raw DDL.

The companion query-side fix — create_team()'s duplicate check switching
to `func.lower(...)` comparisons, or this migration does nothing on its
own — ships in the same commit.
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d1f42494587d"
down_revision: Union[str, None] = "c9c869c63ffd"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index("uq_teams_name_active", table_name="teams")
    op.drop_index("uq_teams_slug_active", table_name="teams")

    op.execute(
        """
        CREATE UNIQUE INDEX uq_teams_name_active
        ON teams (lower(name))
        WHERE deleted_at IS NULL
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_teams_slug_active
        ON teams (lower(slug))
        WHERE deleted_at IS NULL
        """
    )


def downgrade() -> None:
    # NOTE: same caveat as c9c869c63ffd's downgrade — this will raise a
    # UniqueViolation if two active teams differing only by case exist at
    # downgrade time (only reachable pre-upgrade or via direct DB edits).
    op.execute("DROP INDEX IF EXISTS uq_teams_name_active")
    op.execute("DROP INDEX IF EXISTS uq_teams_slug_active")

    op.execute(
        """
        CREATE UNIQUE INDEX uq_teams_name_active
        ON teams (name)
        WHERE deleted_at IS NULL
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_teams_slug_active
        ON teams (slug)
        WHERE deleted_at IS NULL
        """
    )