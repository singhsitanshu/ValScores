"""Shared database selection for backend tests.

Set TEST_DATABASE_URL to run persistence and API coverage against PostgreSQL.
Without it, tests use isolated SQLite databases for fast local feedback.
"""

import os
from uuid import uuid4


TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
os.environ.setdefault("DATABASE_URL", TEST_DATABASE_URL or "sqlite://")


def create_test_engine(sqlite_url: str, **sqlite_kwargs):
    from sqlalchemy.schema import CreateSchema

    from valoreal.database_setup import Base, create_database_engine

    if not TEST_DATABASE_URL:
        return create_database_engine(sqlite_url, **sqlite_kwargs)

    # Every test receives a new schema, so the configured database is never
    # truncated or dropped. The disposable container removes these schemas.
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
    test_engine.dispose()
