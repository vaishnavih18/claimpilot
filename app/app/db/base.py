"""
Shared SQLAlchemy base + engine/session setup.

One Base, imported by every model file, so Alembic's autogenerate (and
`Base.metadata.create_all()` if that's ever used for a quick local reset)
sees every table in one place. Split into its own file instead of living in
models.py so migrations/env.py can import Base without also importing
model classes directly - keeps the import graph simple as more model
modules get added (e.g. a separate module when the LangGraph agent itself
needs its own tables beyond the checkpointer's).
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import get_database_url


class Base(DeclarativeBase):
    pass


# echo=False even in dev - SQLAlchemy's query-echo logging is noisy and
# duplicates what a proper APM/logging setup should do later; flip to True
# locally for one-off debugging, don't commit it on.
engine = create_engine(get_database_url(), pool_pre_ping=True, echo=False)

# pool_pre_ping=True: issues a cheap "is this connection still alive" check
# before handing a pooled connection to a request. Without it, a connection
# RDS silently closed (idle timeout, a failover, Secrets Manager rotating
# the password under us later) surfaces as a confusing mid-request
# OperationalError instead of SQLAlchemy quietly reconnecting.

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
