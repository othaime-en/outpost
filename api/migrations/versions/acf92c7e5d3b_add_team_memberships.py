"""Add team_memberships table and users.platform_role (Migration A: expand)

This is the expand half of an expand/contract migration for multi-team
membership. It adds the new team_memberships table and users.platform_role,
and backfills both from existing users.team_id / users.role data.

users.role and users.team_id are deliberately left in place and untouched.
They are dropped only in Migration B, after application code reading from
team_memberships / platform_role has been deployed and verified. Do not
drop them in this migration.

Revision ID: acf92c7e5d3b
Revises: ab2aeb5100c2
Create Date: 2026-08-13
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "acf92c7e5d3b"
down_revision = "ab2aeb5100c2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. New table: team_memberships
    op.create_table(
        "team_memberships",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "team_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("teams.id"),
            nullable=False,
        ),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.UniqueConstraint(
            "user_id", "team_id", name="uq_team_memberships_user_team"
        ),
    )
    # Unique constraint above covers lookups by user_id (leftmost column),
    # but team-scoped queries (roster listing, last-admin checks) filter by
    # team_id alone, so it needs its own index.
    op.create_index(
        "ix_team_memberships_team_id", "team_memberships", ["team_id"]
    )

    # 2. Add platform_role as nullable first — tighten to NOT NULL only
    #    after every row is backfilled, never before.
    op.add_column(
        "users", sa.Column("platform_role", sa.Text(), nullable=True)
    )

    # 3. Backfill platform_role from the existing users.role column.
    #    Only 'super_admin' carries platform-wide meaning going forward;
    #    'member' / 'team_admin' collapse to the ordinary 'user' platform
    #    role — their team-scoped meaning now lives in team_memberships.role.
    op.execute(
        """
        UPDATE users
        SET platform_role = CASE
            WHEN role = 'super_admin' THEN 'super_admin'
            ELSE 'user'
        END
        """
    )

    op.alter_column("users", "platform_role", nullable=False)

    # 4. Backfill team_memberships from existing (users.team_id, users.role).
    #
    #    - role = 'team_admin' -> membership role 'team_admin'
    #    - role = 'member'     -> membership role 'member'
    #    - role = 'super_admin' with a non-null team_id (structurally
    #      possible under the old single-column model even if unused in
    #      practice) -> membership role 'member'.
    #
    #    This last case is a deliberate default, not an oversight: platform_role
    #    already grants this user full access everywhere via has_team_role()'s
    #      super_admin short-circuit, so the team-scoped role value here is
    #      cosmetic (a display label) rather than a source of authorization.
    #    If you'd rather this show as 'team_admin' for any such rows, it's a
    #    one-line UPDATE against team_memberships after this migration runs —
    #    nothing here is hard to reverse or re-run.
    op.execute(
        """
        INSERT INTO team_memberships (id, user_id, team_id, role, created_at)
        SELECT
            gen_random_uuid(),
            id,
            team_id,
            CASE
                WHEN role IN ('team_admin', 'super_admin') THEN 'team_admin'
                ELSE 'member'
            END,
            NOW()
        FROM users
        WHERE team_id IS NOT NULL
        """
    )


def downgrade() -> None:
    # Safe to fully reverse: users.role / users.team_id were never touched
    # by this migration, so downgrading just removes what it added.
    op.drop_index("ix_team_memberships_team_id", table_name="team_memberships")
    op.drop_table("team_memberships")
    op.drop_column("users", "platform_role")