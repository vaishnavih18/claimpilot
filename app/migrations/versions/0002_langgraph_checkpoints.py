"""langgraph checkpoint tables

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-07

This migration looks different from 0001 on purpose: it contains no
`op.create_table()` calls, because the tables it creates aren't ours to
define.

LangGraph's PostgresSaver (the checkpointer the agent will use to persist
its state/conversation history between turns) owns its own schema -
`checkpoints`, `checkpoint_blobs`, `checkpoint_writes`, and a
`checkpoint_migrations` tracking table - and ships a `.setup()` method
that creates and versions them itself. Hand-writing SQLAlchemy models for
those tables here would mean maintaining a second, parallel copy of a
schema LangGraph already owns and might change between versions.

Why this still goes through Alembic rather than just calling `.setup()`
once from a setup script: `alembic upgrade head` is the one command that
provisions the ENTIRE schema (claims/decisions AND the checkpointer) in
the right order, from a clean database. Without this file, a fresh RDS
instance (or a teammate running this for the first time) would need to
remember a second, separate step that no tool reminds them about.

When to change: if a future langgraph-checkpoint-postgres upgrade changes
what `.setup()` does, this migration's behavior changes with it
automatically - there's nothing here to update by hand for that.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    import psycopg
    from langgraph.checkpoint.postgres import PostgresSaver

    from app.core.config import get_database_url

    # Opens its OWN raw psycopg connection rather than reusing Alembic's -
    # tried that first, and it fails: Alembic's connection comes through
    # SQLAlchemy's connection pool as a _ConnectionFairy wrapper, but
    # PostgresSaver.setup() calls psycopg-specific methods directly and
    # raises `TypeError: Invalid connection type` on anything that isn't
    # an actual psycopg.Connection. psycopg.connect() wants a plain
    # "postgresql://" DSN, so strip SQLAlchemy's "+psycopg" driver tag
    # before passing the URL through.
    #
    # Trade-off this creates: .setup() commits in its own transaction,
    # separate from the one 0001's op.create_table() calls ran in. If
    # 0001 somehow succeeded but this migration failed outright (not the
    # case here, but worth naming), you'd need to confirm by hand that
    # 0001's tables exist before re-running `alembic upgrade head` -
    # `alembic current` after any failed upgrade tells you exactly which
    # revision the database is actually stamped at.
    # autocommit=True is required, not optional: .setup() runs
    # `CREATE INDEX CONCURRENTLY` as part of its own internal migrations,
    # and Postgres refuses that specific statement inside a transaction
    # block under any circumstances - this isn't a performance choice,
    # the migration simply fails without it (confirmed - the first version
    # of this file, without autocommit, raised
    # `psycopg.errors.ActiveSqlTransaction: CREATE INDEX CONCURRENTLY
    # cannot run inside a transaction block`).
    dsn = get_database_url().replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(dsn, autocommit=True) as connection:
        PostgresSaver(connection).setup()


def downgrade() -> None:
    # No official teardown API on PostgresSaver (only .setup(), which is
    # additive/idempotent) - dropping its tables by the exact names it's
    # documented to create is the only way back down. CASCADE because
    # checkpoint_writes/checkpoint_blobs reference checkpoints by FK.
    op.execute("DROP TABLE IF EXISTS checkpoint_writes CASCADE")
    op.execute("DROP TABLE IF EXISTS checkpoint_blobs CASCADE")
    op.execute("DROP TABLE IF EXISTS checkpoints CASCADE")
    op.execute("DROP TABLE IF EXISTS checkpoint_migrations CASCADE")
