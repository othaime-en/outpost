import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

# Import Base and all models so Alembic can see the full target schema.
# If you add a new model file, you MUST import it here or autogenerate won't detect it.
from app.database import Base
import app.models.team          # noqa: F401
import app.models.user          # noqa: F401
import app.models.environment   # noqa: F401
import app.models.audit_log     # noqa: F401
import app.models.cost_snapshot # noqa: F401
import app.models.runbook       # noqa: F401
import app.models.platform_settings  # noqa: F401

# Alembic Config object — provides access to values in alembic.ini
config = context.config

# Set up Python logging from alembic.ini [loggers] section
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Override the database URL from the environment variable.
# This means the same `alembic upgrade head` command works in local dev, CI, and prod —
# you just set DATABASE_URL appropriately for each context.
database_url = os.environ.get("DATABASE_URL")
if database_url:
    config.set_main_option("sqlalchemy.url", database_url)

# Point Alembic at our SQLAlchemy metadata so --autogenerate works.
# Without this, Alembic can't compare the DB against our models.
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations without a live DB — generates SQL scripts."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live DB — the normal case."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,  # NullPool: no connection pooling in migration scripts
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()