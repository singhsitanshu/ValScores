"""Alembic environment for the ValScores PostgreSQL schema.

``python -m valoreal.database`` passes an open connection (already inside a
transaction) through ``config.attributes["connection"]``. The ``alembic`` CLI,
used only to author revisions, falls back to DATABASE_URL.
"""

import os

from alembic import context
from sqlalchemy import create_engine, pool

from valoreal.database.models import Base


config = context.config
target_metadata = Base.metadata


def run_with_connection(connection):
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    connection = config.attributes.get("connection")
    if connection is not None:
        run_with_connection(connection)
        return

    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is required to run Alembic directly")
    engine = create_engine(url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        run_with_connection(connection)


if context.is_offline_mode():
    raise RuntimeError("Offline SQL generation is not supported; run migrations against a database")
run_migrations_online()
