"""initial_schema

Revision ID: 054a3bd6eeb6
Revises: 
Create Date: 2026-02-26 23:46:58.575100

This is the initial database schema for Outpost.
It creates all 6 tables in dependency order (referenced tables before referencing tables).

Table creation order matters because of foreign key constraints:
  1. teams        (no foreign keys)
  2. users        (references teams)
  3. environments (references teams and users)
  4. audit_logs   (references environments and users)
  5. cost_snapshots (references environments)
  6. runbooks     (references environments)
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '054a3bd6eeb6'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- 1. teams ---
    # No foreign keys, so this goes first.
    # The slug must be URL-safe (enforced in the API layer via Pydantic pattern validation).
    op.execute("""
        CREATE TABLE teams (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name        TEXT NOT NULL UNIQUE,
            slug        TEXT NOT NULL UNIQUE,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    # --- 2. users ---
    # References teams. Note github_id is BIGINT (not INT) — GitHub IDs exceed 2^31.
    # api_key_hash is nullable: it's only set after the user explicitly generates a CLI key.
    op.execute("""
        CREATE TABLE users (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            github_id       BIGINT NOT NULL UNIQUE,
            username        TEXT NOT NULL,
            email           TEXT,
            team_id         UUID REFERENCES teams(id),
            role            TEXT NOT NULL DEFAULT 'member',
            api_key_hash    TEXT,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    # --- 3. environments ---
    # The `id` UUID is also used as the Terraform workspace name and S3 state key.
    # `outputs` is JSONB: stores raw Terraform output, including ARNs and endpoints.
    # `expires_at` is computed at creation time: created_at + ttl_hours.
    op.execute("""
        CREATE TABLE environments (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name                TEXT NOT NULL,
            team_id             UUID NOT NULL REFERENCES teams(id),
            created_by          UUID NOT NULL REFERENCES users(id),
            env_type            TEXT NOT NULL CHECK (env_type IN ('dev', 'staging')),
            status              TEXT NOT NULL DEFAULT 'PENDING',
            ttl_hours           INTEGER NOT NULL DEFAULT 24,
            expires_at          TIMESTAMPTZ NOT NULL,
            aws_region          TEXT NOT NULL DEFAULT 'us-east-1',
            outputs             JSONB,
            health_status       TEXT NOT NULL DEFAULT 'UNKNOWN',
            health_checked_at   TIMESTAMPTZ,
            cost_estimate_usd   NUMERIC(10, 4),
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            destroyed_at        TIMESTAMPTZ
        )
    """)

    # --- 4. audit_logs ---
    # Append-only. The application layer enforces no updates/deletes — there is no
    # ORM update() call for this table anywhere in the codebase.
    # Both indexes are critical for query performance:
    #   - environment_id: used by "show me all events for environment X"
    #   - created_at DESC: used by "show me the 50 most recent events"
    op.execute("""
        CREATE TABLE audit_logs (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            environment_id  UUID REFERENCES environments(id),
            actor_id        UUID REFERENCES users(id),
            action          TEXT NOT NULL,
            actor_type      TEXT NOT NULL DEFAULT 'user',
            metadata        JSONB,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE INDEX idx_audit_logs_environment_id ON audit_logs(environment_id)
    """)
    op.execute("""
        CREATE INDEX idx_audit_logs_created_at ON audit_logs(created_at DESC)
    """)

    # --- 5. cost_snapshots ---
    # Daily actual-cost records from AWS Cost Explorer.
    # Keyed by environment_id + date range to allow multiple records per environment.
    op.execute("""
        CREATE TABLE cost_snapshots (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            environment_id  UUID NOT NULL REFERENCES environments(id),
            period_start    DATE NOT NULL,
            period_end      DATE NOT NULL,
            actual_cost_usd NUMERIC(10, 4) NOT NULL,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    # --- 6. runbooks ---
    # UNIQUE on environment_id enforces the one-runbook-per-environment invariant at the DB level.
    # The application layer UPSERTs (INSERT ... ON CONFLICT) on regeneration.
    op.execute("""
        CREATE TABLE runbooks (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            environment_id  UUID NOT NULL UNIQUE REFERENCES environments(id),
            content_md      TEXT NOT NULL,
            generated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)


def downgrade() -> None:
    # Drop in reverse order to respect foreign key constraints.
    op.execute("DROP TABLE IF EXISTS runbooks")
    op.execute("DROP TABLE IF EXISTS cost_snapshots")
    op.execute("DROP INDEX IF EXISTS idx_audit_logs_created_at")
    op.execute("DROP INDEX IF EXISTS idx_audit_logs_environment_id")
    op.execute("DROP TABLE IF EXISTS audit_logs")
    op.execute("DROP TABLE IF EXISTS environments")
    op.execute("DROP TABLE IF EXISTS users")
    op.execute("DROP TABLE IF EXISTS teams")