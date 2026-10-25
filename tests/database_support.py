"""Shared database selection for backend tests.

Set TEST_DATABASE_URL to run persistence and API coverage against PostgreSQL.
Without it, tests use isolated SQLite databases for fast local feedback.

Import this module before any ``valoreal`` module: the backend binds its
module-level engine to DATABASE_URL at import time, so it is replaced here to
keep tests away from a developer's configured database.
"""

import os
from uuid import uuid4

from sqlalchemy.engine import make_url


TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL") or None


def _validate_test_database_url(test_url: str) -> None:
    database_name = make_url(test_url).database or ""
    if "test" not in database_name.lower():
        raise RuntimeError(
            "TEST_DATABASE_URL must name a disposable database whose name contains "
            f"'test' (got {database_name!r}); start one with "
            "`docker compose --profile test up -d test-db`"
        )
    development_url = os.environ.get("DATABASE_URL")
    if development_url and make_url(development_url) == make_url(test_url):
        raise RuntimeError("TEST_DATABASE_URL must not be the same database as DATABASE_URL")


if TEST_DATABASE_URL:
    _validate_test_database_url(TEST_DATABASE_URL)
os.environ["DATABASE_URL"] = TEST_DATABASE_URL or "sqlite://"


def create_test_engine(sqlite_url: str, **sqlite_kwargs):
    from sqlalchemy.schema import CreateSchema

    from valoreal.database.connection import create_database_engine
    from valoreal.database.models import Base

    if not TEST_DATABASE_URL:
        return create_database_engine(sqlite_url, **sqlite_kwargs)

    # Every test receives a new schema, so existing data is never truncated.
    # close_test_engine drops the schema again.
    schema_name = f"valscores_test_{uuid4().hex}"
    bootstrap_engine = create_database_engine(TEST_DATABASE_URL)
    with bootstrap_engine.begin() as connection:
        connection.execute(CreateSchema(schema_name))
    bootstrap_engine.dispose()

    test_engine = create_database_engine(TEST_DATABASE_URL).execution_options(
        schema_translate_map={None: schema_name}
    )
    Base.metadata.create_all(test_engine)
    return test_engine


def close_test_engine(test_engine) -> None:
    schema_map = test_engine.get_execution_options().get("schema_translate_map") or {}
    schema_name = schema_map.get(None)
    test_engine.dispose()
    if not schema_name:
        return

    from sqlalchemy.schema import DropSchema

    from valoreal.database.connection import create_database_engine

    bootstrap_engine = create_database_engine(TEST_DATABASE_URL)
    with bootstrap_engine.begin() as connection:
        connection.execute(DropSchema(schema_name, cascade=True))
    bootstrap_engine.dispose()
