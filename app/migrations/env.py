"""
Alembic environment script.

The one thing worth explaining: this imports `get_database_url()` from the
app's own config module rather than reading `sqlalchemy.url` from
alembic.ini. That means running a migration resolves the connection the
exact same way the running app does - set DATABASE_URL for local dev
against docker-compose, or RDS_SECRET_ARN to pull it from Secrets Manager
(see app/core/config.py). One resolver, used by both the app and its
migrations, instead of two things that could silently drift apart.
"""

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# Make `app.*` importable when Alembic is run from the app/ directory
# (where alembic.ini lives) - without this, `from app.core.config import
# ...` below would fail with ModuleNotFoundError.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import get_database_url  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db import models  # noqa: E402, F401  (import registers models on Base.metadata)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=get_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = get_database_url()
    connectable = engine_from_config(configuration, prefix="sqlalchemy.", poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
