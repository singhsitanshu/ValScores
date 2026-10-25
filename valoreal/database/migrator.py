"""Run and check Alembic migrations for the PostgreSQL schema.

Never imported by legacy SQLite code; never run implicitly by the API.
"""

from dataclasses import dataclass
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from alembic.util.exc import CommandError

from .migration_errors import MigrationError, SchemaVersionError
from .schema_inspection import APP_TABLES, existing_tables, schema_snapshot


MIGRATIONS_DIRECTORY = Path(__file__).with_name("migrations")
BASELINE_REVISION = "0001"
UPGRADE_COMMAND = "python -m valoreal.database upgrade"
BASELINE_COMMAND = "python -m valoreal.database baseline"

VARCHAR, INTEGER = "character varying", "integer"
# Columns (type, nullable) of a pre-Alembic installation; see 0001_baseline.py.
BASELINE_COLUMNS = {
    "matches": {
        "id": (INTEGER, False),
        "vlr_match_id": (VARCHAR, False),
        "team1_name": (VARCHAR, False),
        "team2_name": (VARCHAR, False),
        "team1_round_score": (VARCHAR, True),
        "team2_round_score": (VARCHAR, True),
        "start_time": ("timestamp with time zone", True),
        "legacy_start_time": (VARCHAR, True),
        "status": (VARCHAR, True),
        "team1_series_score": (INTEGER, True),
        "team2_series_score": (INTEGER, True),
        "map_vetoes_raw": (VARCHAR, True),
    },
    "games": {
        "id": (INTEGER, False),
        "match_id": (INTEGER, False),
        "vlr_game_id": (VARCHAR, False),
        "map_number": (INTEGER, True),
        "map_name": (VARCHAR, False),
        "team1_round_score": (INTEGER, True),
        "team2_round_score": (INTEGER, True),
    },
    "player_stats": {
        "id": (INTEGER, False),
        "game_id": (INTEGER, False),
        "player_name": (VARCHAR, False),
        "team_name": (VARCHAR, False),
        "role": (VARCHAR, True),
        "acs": (INTEGER, True),
        "kd_ratio": ("double precision", True),
        "adr": (INTEGER, True),
        "kills": (INTEGER, True),
        "deaths": (INTEGER, True),
        "assists": (INTEGER, True),
        "plus_minus": (VARCHAR, True),
        "kast": (VARCHAR, True),
        "first_kills": (INTEGER, True),
        "first_deaths": (INTEGER, True),
    },
}
BASELINE_INDEXES = {
    "matches": {"ix_matches_vlr_match_id": "UNIQUE INDEX ix_matches_vlr_match_id ON matches USING btree (vlr_match_id)"},
    "games": {
        "uq_games_match_id_vlr_game_id": "UNIQUE INDEX uq_games_match_id_vlr_game_id ON games USING btree (match_id, vlr_game_id)",
        "ix_games_vlr_game_id": "INDEX ix_games_vlr_game_id ON games USING btree (vlr_game_id)",
    },
    "player_stats": {
        "uq_player_stats_game_player_identity": "UNIQUE INDEX uq_player_stats_game_player_identity ON player_stats USING btree (game_id, team_name, player_name)",
    },
}
BASELINE_FOREIGN_KEYS = {
    "games": "FOREIGN KEY (match_id) REFERENCES matches(id) ON DELETE CASCADE",
    "player_stats": "FOREIGN KEY (game_id) REFERENCES games(id) ON DELETE CASCADE",
}


@dataclass(frozen=True)
class SchemaState:
    current: str | None
    head: str
    has_version_table: bool
    has_app_tables: bool

    @property
    def is_current(self):
        return self.current == self.head


def alembic_config(connection=None):
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIRECTORY))
    config.attributes["connection"] = connection
    return config


def script_directory():
    return ScriptDirectory.from_config(alembic_config())


def head_revision():
    return script_directory().get_current_head()


def schema_state(engine):
    with engine.connect() as connection:
        tables = existing_tables(connection) if engine.dialect.name == "postgresql" else set(
            engine.dialect.get_table_names(connection)
        )
        current = MigrationContext.configure(connection).get_current_revision()
    return SchemaState(
        current=current,
        head=head_revision(),
        has_version_table="alembic_version" in tables,
        has_app_tables=bool(tables & set(APP_TABLES)),
    )


def require_postgresql(engine):
    if engine.dialect.name != "postgresql":
        raise MigrationError(
            f"Migrations run only on PostgreSQL, not {engine.dialect.name}. "
            "Set DATABASE_URL to a postgresql+psycopg:// URL."
        )


def unversioned_installation_message():
    return (
        "The database has ValScores tables but no migration history (it was created "
        "before Alembic). Back up the database, then run "
        f"`{BASELINE_COMMAND}` followed by `{UPGRADE_COMMAND}`."
    )


def upgrade(engine):
    """Apply all pending revisions atomically. Returns (before, after) revisions."""
    require_postgresql(engine)
    state = schema_state(engine)
    if state.current is None and state.has_app_tables:
        raise MigrationError(unversioned_installation_message())
    if state.current is not None:
        ensure_known_revision(state.current, state.head)
    with engine.begin() as connection:
        command.upgrade(alembic_config(connection), "head")
    return state.current, schema_state(engine).current


def baseline_problems(connection):
    """Differences between an existing database and the 0001 baseline schema."""
    snapshot = schema_snapshot(connection)
    problems = []
    for table, expected_columns in BASELINE_COLUMNS.items():
        actual = {name: (data_type, nullable) for name, (data_type, nullable, _default)
                  in snapshot[table]["columns"].items()}
        if not actual:
            problems.append(f"table {table} is missing")
            continue
        for column, expected in expected_columns.items():
            if column not in actual:
                problems.append(f"{table}.{column} is missing")
            elif actual[column] != expected:
                problems.append(f"{table}.{column} is {actual[column]}, expected {expected}")
        for column in sorted(set(actual) - set(expected_columns)):
            problems.append(f"{table}.{column} is not part of the baseline schema")
        for name, definition in BASELINE_INDEXES[table].items():
            actual_definition = snapshot[table]["indexes"].get(name, "")
            if not actual_definition.endswith(definition):
                problems.append(f"index {name} is missing or differs")
        foreign_key = BASELINE_FOREIGN_KEYS.get(table)
        if foreign_key and foreign_key not in snapshot[table]["constraints"].values():
            problems.append(f"{table} is missing `{foreign_key}`")
    return problems


def baseline(engine):
    """Mark a verified pre-Alembic installation as revision 0001. Returns a message."""
    require_postgresql(engine)
    state = schema_state(engine)
    if state.current is not None:
        return f"Already under migration control at revision {state.current}; nothing to do."
    if not state.has_app_tables:
        raise MigrationError(
            f"The database has no ValScores tables. Run `{UPGRADE_COMMAND}` to create the schema."
        )
    with engine.begin() as connection:
        problems = baseline_problems(connection)
        if problems:
            raise MigrationError(
                "The existing schema does not match baseline revision "
                f"{BASELINE_REVISION}, so it was not stamped:\n"
                + "\n".join(f"  - {problem}" for problem in problems)
            )
        command.stamp(alembic_config(connection), BASELINE_REVISION)
    return (
        f"Stamped revision {BASELINE_REVISION}. Back up the database, then run "
        f"`{UPGRADE_COMMAND}` to apply the remaining revisions."
    )


def ensure_known_revision(current, head):
    try:
        script_directory().get_revision(current)
    except CommandError as exc:
        raise SchemaVersionError(
            f"The database is at schema revision {current}, which this version of "
            f"ValScores does not know (its latest revision is {head}). It was probably "
            "migrated by a newer release; deploy that release or restore a compatible backup."
        ) from exc


def ensure_schema_current(engine):
    """Raise SchemaVersionError unless the database is exactly at the head revision."""
    state = schema_state(engine)
    if state.is_current:
        return
    if state.current is None and not state.has_app_tables:
        raise SchemaVersionError(
            f"The database has no ValScores schema. Run `{UPGRADE_COMMAND}` before "
            "starting the API."
        )
    if state.current is None:
        raise SchemaVersionError(unversioned_installation_message())
    ensure_known_revision(state.current, state.head)
    raise SchemaVersionError(
        f"The database schema is at revision {state.current}, but this version of "
        f"ValScores requires {state.head}. Back up the database, then run `{UPGRADE_COMMAND}`."
    )
