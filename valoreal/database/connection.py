"""Database URL configuration, engine and session factory."""

import os

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from .models import Base


DATABASE_URL = os.environ.get("DATABASE_URL")


def configured_database_url() -> str:
    """Return the required runtime database URL with a useful startup error."""
    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL is required; configure a PostgreSQL URL such as "
            "postgresql+psycopg://user:password@localhost:5432/valscores"
        )
    return DATABASE_URL


def create_database_engine(database_url: str | None = None, **kwargs):
    """Build an engine for the configured database or an explicit test URL."""
    url = database_url or configured_database_url()
    kwargs.setdefault("pool_pre_ping", True)
    database_engine = create_engine(url, **kwargs)

    # SQLite is retained only for fast, isolated unit and legacy-migration tests.
    # PostgreSQL enforces foreign keys without a connection hook.
    if database_engine.dialect.name == "sqlite":
        @event.listens_for(database_engine, "connect")
        def enable_sqlite_foreign_keys(dbapi_connection, _connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return database_engine


def create_sqlite_engine(database_url: str, **kwargs):
    """Compatibility helper for explicitly isolated SQLite-only tests."""
    if not database_url.startswith("sqlite:"):
        raise ValueError("create_sqlite_engine accepts SQLite URLs only")
    return create_database_engine(database_url, **kwargs)


engine = create_database_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def initialize_database(database_engine=engine) -> None:
    """Create the canonical schema in a fresh PostgreSQL database."""
    Base.metadata.create_all(database_engine)
