"""Alembic migrations against real PostgreSQL databases.

Each test creates and drops its own database on the TEST_DATABASE_URL server, so
migrations run exactly as in production. Without TEST_DATABASE_URL these tests
are skipped (SQLite cannot run the PostgreSQL migrations); CI always runs them.
"""

from contextlib import contextmanager
from pathlib import Path
import unittest
from uuid import uuid4

from alembic import command
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from database_support import TEST_DATABASE_URL
from valoreal.database import migrator
from valoreal.database.migration_errors import (
    MigrationConflictError,
    MigrationError,
    SchemaVersionError,
)
from valoreal.database.models import Base
from valoreal.database.schema_inspection import schema_snapshot


PRE_ALEMBIC_SCHEMA = (
    Path(__file__).parent / "fixtures" / "database" / "pre_alembic_schema.sql"
).read_text()

REPRESENTATIVE_DATA = """
INSERT INTO matches (id, vlr_match_id, team1_name, team2_name, team1_round_score,
    team2_round_score, start_time, legacy_start_time, status, team1_series_score,
    team2_series_score, map_vetoes_raw) VALUES
 (1, '/1001', 'Alpha', 'Bravo', '7', '5', '2026-09-07T10:00:00Z', NULL, 'LIVE', 1, 0, '["A ban Bind"]'),
 (2, '/1002', 'Charlie', 'Delta', '0', '0', '2026-09-06T08:00:00Z', NULL, 'Finished', 2, 1, NULL),
 (3, '/1003', 'Echo', 'Foxtrot', NULL, NULL, NULL, '7:00 PM', NULL, NULL, NULL, NULL),
 (4, '/1004', 'Golf', 'Hotel', '', ' ', '2026-09-08T12:00:00Z', NULL, 'upcoming', NULL, NULL, NULL),
 (5, '/1005', 'India', 'Juliet', ' 3 ', '11', '2026-09-08T15:00:00Z', NULL, 'Postponed', NULL, NULL, NULL);
SELECT setval('matches_id_seq', 5);
INSERT INTO games (id, match_id, vlr_game_id, map_number, map_name, team1_round_score, team2_round_score) VALUES
 (1, 1, '601', 1, 'Ascent', 13, 9),
 (2, 1, '602', 2, 'Lotus', 7, 5),
 (3, 2, 'all', 0, 'Overall', NULL, NULL);
SELECT setval('games_id_seq', 3);
INSERT INTO player_stats (id, game_id, player_name, team_name, role, acs, kd_ratio, adr,
    kills, deaths, assists, plus_minus, kast, first_kills, first_deaths) VALUES
 (1, 1, 'Boo', 'TH', 'initiator', 231, 1.36, 152, 19, 14, 6, '+5', '76%', 3, 2),
 (2, 2, 'Chronicle', 'FNC', NULL, 176, 0.67, NULL, 4, 6, 0, '-2', NULL, NULL, NULL);
SELECT setval('player_stats_id_seq', 2);
"""


def requires_postgresql(test_case):
    return unittest.skipUnless(
        TEST_DATABASE_URL,
        "Alembic migrations target PostgreSQL; set TEST_DATABASE_URL to run them",
    )(test_case)


@contextmanager
def temporary_database():
    """A brand-new database on the test server, dropped afterwards."""
    server_url = make_url(TEST_DATABASE_URL)
    name = f"{server_url.database}_migration_{uuid4().hex[:12]}"
    admin = create_engine(server_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    engine = create_engine(server_url.set(database=name))
    try:
        yield engine
    finally:
        engine.dispose()
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


def execute_script(engine, sql):
    # Straight to psycopg: without parameters it does not treat "%" as a placeholder.
    with engine.begin() as connection:
        connection.connection.dbapi_connection.execute(sql)


def snapshot(engine):
    with engine.connect() as connection:
        return schema_snapshot(connection)


def rows(engine, query):
    with engine.connect() as connection:
        return [tuple(row) for row in connection.execute(text(query))]


def table_contents(engine):
    return {
        table: rows(engine, f"SELECT * FROM {table} ORDER BY id")
        for table in ("matches", "games", "player_stats")
    }


@requires_postgresql
class MigrationTests(unittest.TestCase):
    def test_empty_database_upgrades_to_the_models_schema(self):
        with temporary_database() as migrated, temporary_database() as created:
            before, after = migrator.upgrade(migrated)
            Base.metadata.create_all(created)

            self.assertEqual((before, after), (None, migrator.head_revision()))
            self.assertEqual(snapshot(migrated), snapshot(created))
            migrator.ensure_schema_current(migrated)

    def test_rerunning_upgrade_changes_nothing(self):
        with temporary_database() as engine:
            execute_script(engine, PRE_ALEMBIC_SCHEMA + REPRESENTATIVE_DATA)
            migrator.baseline(engine)
            migrator.upgrade(engine)
            schema_before, data_before = snapshot(engine), table_contents(engine)

            before, after = migrator.upgrade(engine)

            self.assertEqual(before, after)
            self.assertEqual(snapshot(engine), schema_before)
            self.assertEqual(table_contents(engine), data_before)

    def test_baseline_revision_reproduces_the_pre_alembic_schema(self):
        with temporary_database() as historical, temporary_database() as baseline:
            execute_script(historical, PRE_ALEMBIC_SCHEMA)
            with baseline.begin() as connection:
                command.upgrade(migrator.alembic_config(connection), migrator.BASELINE_REVISION)

            self.assertEqual(snapshot(historical), snapshot(baseline))
            with historical.connect() as connection:
                self.assertEqual(migrator.baseline_problems(connection), [])

    def test_existing_installation_is_baselined_and_upgraded_without_data_loss(self):
        with temporary_database() as engine, temporary_database() as created:
            execute_script(engine, PRE_ALEMBIC_SCHEMA + REPRESENTATIVE_DATA)
            original = table_contents(engine)

            with self.assertRaisesRegex(MigrationError, "baseline"):
                migrator.upgrade(engine)
            with self.assertRaisesRegex(SchemaVersionError, "no migration history"):
                migrator.ensure_schema_current(engine)

            migrator.baseline(engine)
            migrator.upgrade(engine)
            migrator.ensure_schema_current(engine)
            Base.metadata.create_all(created)
            self.assertEqual(snapshot(engine), snapshot(created))

            upgraded = table_contents(engine)
            self.assertEqual(upgraded["games"], original["games"])
            self.assertEqual(upgraded["player_stats"], original["player_stats"])
            self.assertEqual(
                rows(engine, "SELECT id, status, team1_round_score, team2_round_score FROM matches ORDER BY id"),
                [
                    (1, "live", 7, 5),
                    (2, "finished", 0, 0),
                    (3, "upcoming", None, None),
                    (4, "upcoming", None, None),
                    (5, "postponed", 3, 11),
                ],
            )
            # Every other match column is untouched.
            untouched = "id, vlr_match_id, team1_name, team2_name, start_time, legacy_start_time, " \
                        "team1_series_score, team2_series_score, map_vetoes_raw"
            self.assertEqual(
                rows(engine, f"SELECT {untouched} FROM matches ORDER BY id"),
                [(r[0], r[1], r[2], r[3], r[6], r[7], r[9], r[10], r[11]) for r in original["matches"]],
            )

    def test_conflicting_rows_stop_the_upgrade_with_actionable_errors(self):
        with temporary_database() as engine:
            execute_script(engine, PRE_ALEMBIC_SCHEMA + """
                INSERT INTO matches (id, vlr_match_id, team1_name, team2_name, status,
                    team1_round_score, team1_series_score) VALUES
                 (1, '/2001', 'A', 'B', 'forfeited', NULL, NULL),
                 (2, '/2002', 'C', 'D', 'upcoming', 'abc', NULL),
                 (3, '/2003', 'E', 'F', 'finished', '4', -1);
                INSERT INTO games (id, match_id, vlr_game_id, map_number, map_name)
                VALUES (1, 3, '701', -2, 'Bind');
            """)
            migrator.baseline(engine)
            schema_before, data_before = snapshot(engine), table_contents(engine)

            with self.assertRaises(MigrationConflictError) as raised:
                migrator.upgrade(engine)

            message = str(raised.exception)
            self.assertEqual(len(raised.exception.conflicts), 4)
            for expected in (
                "matches.status 'forfeited' is not a recognized status (match ids 1)",
                "UPDATE matches SET status = 'upcoming' WHERE id IN (1);",
                "matches.team1_round_score contains text that is not a non-negative integer (match ids 2)",
                "matches.team1_series_score is negative (matches ids 3)",
                "games.map_number is negative (games ids 1)",
                "Nothing was changed",
            ):
                self.assertIn(expected, message)

            # The failed upgrade rolled back completely.
            self.assertEqual(migrator.schema_state(engine).current, migrator.BASELINE_REVISION)
            self.assertEqual(snapshot(engine), schema_before)
            self.assertEqual(table_contents(engine), data_before)

    def test_baseline_refuses_a_schema_that_does_not_match(self):
        with temporary_database() as engine:
            execute_script(engine, PRE_ALEMBIC_SCHEMA + "ALTER TABLE matches DROP COLUMN map_vetoes_raw;")

            with self.assertRaisesRegex(MigrationError, "matches.map_vetoes_raw is missing"):
                migrator.baseline(engine)
            self.assertIsNone(migrator.schema_state(engine).current)

    def test_baseline_of_an_empty_database_points_to_upgrade(self):
        with temporary_database() as engine:
            with self.assertRaisesRegex(MigrationError, "upgrade"):
                migrator.baseline(engine)

    def test_head_revision_downgrades_to_the_baseline_and_upgrades_again(self):
        with temporary_database() as engine, temporary_database() as historical:
            execute_script(historical, PRE_ALEMBIC_SCHEMA)
            execute_script(engine, PRE_ALEMBIC_SCHEMA + REPRESENTATIVE_DATA)
            migrator.baseline(engine)
            migrator.upgrade(engine)

            with engine.begin() as connection:
                command.downgrade(migrator.alembic_config(connection), migrator.BASELINE_REVISION)
            self.assertEqual(snapshot(engine), snapshot(historical))
            self.assertEqual(
                rows(engine, "SELECT id, status, team1_round_score FROM matches WHERE id IN (1, 3) ORDER BY id"),
                [(1, "live", "7"), (3, "upcoming", None)],
            )

            migrator.upgrade(engine)
            migrator.ensure_schema_current(engine)

    def test_startup_check_explains_each_incompatible_state(self):
        with temporary_database() as engine:
            with self.assertRaisesRegex(SchemaVersionError, "has no ValScores schema.*upgrade"):
                migrator.ensure_schema_current(engine)

            with engine.begin() as connection:
                command.upgrade(migrator.alembic_config(connection), migrator.BASELINE_REVISION)
            with self.assertRaisesRegex(SchemaVersionError, "at revision 0001, but .* requires 0002"):
                migrator.ensure_schema_current(engine)

            migrator.upgrade(engine)
            migrator.ensure_schema_current(engine)

            with engine.begin() as connection:
                connection.execute(text("UPDATE alembic_version SET version_num = '9999'"))
            with self.assertRaisesRegex(SchemaVersionError, "9999.*newer release"):
                migrator.ensure_schema_current(engine)
            with self.assertRaisesRegex(SchemaVersionError, "9999"):
                migrator.upgrade(engine)


class MigrationCommandTests(unittest.TestCase):
    def test_migrations_refuse_sqlite(self):
        engine = create_engine("sqlite://")
        self.addCleanup(engine.dispose)
        with self.assertRaisesRegex(MigrationError, "only on PostgreSQL"):
            migrator.upgrade(engine)
        with self.assertRaisesRegex(MigrationError, "only on PostgreSQL"):
            migrator.baseline(engine)

    def test_revision_history_is_linear(self):
        revisions = list(migrator.script_directory().walk_revisions())
        self.assertEqual([revision.revision for revision in reversed(revisions)], ["0001", "0002"])
        self.assertEqual(migrator.head_revision(), "0002")


if __name__ == "__main__":
    unittest.main()
