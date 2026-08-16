"""drop_legacy_users_role_and_team_id

Revision ID: baf70fge2a6s
Revises: acf92c7e5d3b
Create Date: 2026-08-16 10:23:17.985107

Contract half of the expand/contract migration for multi-team membership
(see the add_team_memberships migration's docstring for the expand half).
 
Drops users.role and users.team_id, which have been dead weight since that
migration ran -- every application code path has read exclusively from
users.platform_role and team_memberships since then. This migration should
only be run once that's been true in production for a while, not
immediately after deploying the code that stopped reading them.

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'baf70fge2a6s'
down_revision: Union[str, Sequence[str], None] = 'acf92c7e5d3b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Snapshot before dropping -- see module docstring. Safe to re-run:
    # DROP + recreate rather than CREATE IF NOT EXISTS, so a second
    # accidental run of this upgrade doesn't silently keep a stale
    # snapshot from a first partial attempt.
    op.execute("DROP TABLE IF EXISTS legacy_users_role_team_id_backup")
    op.execute(
        """
        CREATE TABLE legacy_users_role_team_id_backup AS
        SELECT id AS user_id, role, team_id, NOW() AS backed_up_at
        FROM users
        """
    )
 
    # Dropping team_id also drops its FK constraint to teams(id)
    # automatically -- Postgres removes constraints that depend on a
    # column as part of DROP COLUMN, no separate DROP CONSTRAINT needed.
    op.execute("ALTER TABLE users DROP COLUMN role")
    op.execute("ALTER TABLE users DROP COLUMN team_id")


def downgrade() -> None:
    # Recreate the columns matching the original initial_schema definition
    # exactly (team_id UUID REFERENCES teams(id); role TEXT NOT NULL
    # DEFAULT 'member') so anything relying on that shape still works.
    op.execute("ALTER TABLE users ADD COLUMN team_id UUID REFERENCES teams(id)")
    op.execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'member'")
 
    # Best-effort restore from the snapshot -- see module docstring for why
    # this is lossy for any user who has gained a second team membership
    # since Migration B ran. If the backup table is gone (e.g. manually
    # cleaned up long after upgrade), every user just keeps role='member',
    # team_id=NULL -- the column-default fallback, not a crash.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_name = 'legacy_users_role_team_id_backup'
            ) THEN
                UPDATE users
                SET role = backup.role,
                    team_id = backup.team_id
                FROM legacy_users_role_team_id_backup AS backup
                WHERE users.id = backup.user_id;
            END IF;
        END $$;
        """
    )
 