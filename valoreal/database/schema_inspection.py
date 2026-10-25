"""Catalog snapshots of the PostgreSQL schema, independent of SQLAlchemy models."""

from sqlalchemy import text


APP_TABLES = ("games", "matches", "player_stats")


def schema_snapshot(connection, tables=APP_TABLES):
    """Columns, constraints and indexes of ``tables`` in the current schema.

    Definitions come from PostgreSQL's own catalog (pg_get_constraintdef,
    pg_get_indexdef), so two databases with the same snapshot have the same DDL.
    """
    table_list = list(tables)
    columns = connection.execute(
        text(
            """
            SELECT table_name, column_name, data_type, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_schema = current_schema() AND table_name = ANY(:tables)
            """
        ),
        {"tables": table_list},
    ).all()
    constraints = connection.execute(
        text(
            """
            SELECT rel.relname, con.conname, pg_get_constraintdef(con.oid)
            FROM pg_constraint con
            JOIN pg_class rel ON rel.oid = con.conrelid
            JOIN pg_namespace ns ON ns.oid = rel.relnamespace
            WHERE ns.nspname = current_schema() AND rel.relname = ANY(:tables)
            """
        ),
        {"tables": table_list},
    ).all()
    indexes = connection.execute(
        text(
            """
            SELECT tablename, indexname, indexdef
            FROM pg_indexes
            WHERE schemaname = current_schema() AND tablename = ANY(:tables)
            """
        ),
        {"tables": table_list},
    ).all()
    schema_prefix = connection.execute(text("SELECT current_schema()")).scalar() + "."

    snapshot = {table: {"columns": {}, "constraints": {}, "indexes": {}} for table in table_list}
    for table, column, data_type, nullable, default in columns:
        snapshot[table]["columns"][column] = (data_type, nullable == "YES", default)
    for table, name, definition in constraints:
        snapshot[table]["constraints"][name] = definition
    for table, name, definition in indexes:
        snapshot[table]["indexes"][name] = definition.replace(schema_prefix, "")
    return snapshot


def existing_tables(connection):
    return set(
        connection.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = current_schema()"
            )
        ).scalars()
    )
