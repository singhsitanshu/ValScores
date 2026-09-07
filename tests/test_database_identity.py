import sqlite3
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from valoreal import vlreal
from valoreal.database_setup import Game, Match, PlayerStat, create_sqlite_engine
from valoreal.migrations import LATEST_SCHEMA_VERSION, run_migrations


def match_payload(status="Upcoming", **overrides):
    payload = {
        "team1": "Alpha",
        "team2": "Bravo",
        "time": "",
        "scheduled_time": "2026-09-06T13:00:00Z",
        "status": status,
        "team1_score": None,
        "team2_score": None,
        "team1_round_score": "0",
        "team2_round_score": "0",
        "url": "https://www.vlr.gg/12345/alpha-vs-bravo",
    }
    payload.update(overrides)
    return payload


def details_payload(**overrides):
    payload = {
        "games": [
            {
                "game_id": "game-1",
                "map_number": 1,
                "map_name": "Haven",
                "team1_round_score": "13",
                "team2_round_score": "9",
                "player_stats": [
                    {
                        "player": "Ace",
                        "team": "ALP",
                        "acs": "245",
                        "k_d": "1.5",
                        "adr": "160",
                        "kills": "21",
                        "deaths": "14",
                        "assists": "7",
                        "plus_minus": "+7",
                        "kast": "78%",
                        "first_kills": "4",
                        "first_deaths": "1",
                    }
                ],
            }
        ]
    }
    payload.update(overrides)
    return payload


class DatabaseIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        database_path = Path(self.temporary_directory.name) / "test.db"
        self.engine = create_sqlite_engine(f"sqlite:///{database_path}")
        run_migrations(self.engine)
        self.session_factory = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.original_session_factory = vlreal.Session
        vlreal.Session = self.session_factory

    def tearDown(self):
        vlreal.Session = self.original_session_factory
        self.engine.dispose()
        self.temporary_directory.cleanup()

    def counts(self):
        session = self.session_factory()
        try:
            return (
                session.query(Match).count(),
                session.query(Game).count(),
                session.query(PlayerStat).count(),
            )
        finally:
            session.close()

    def test_repeated_same_match_save_is_idempotent(self):
        vlreal.save_to_database(match_payload(), {})
        vlreal.save_to_database(match_payload(), {})
        self.assertEqual(self.counts(), (1, 0, 0))

    def test_repeated_same_game_save_is_idempotent(self):
        vlreal.save_to_database(match_payload(), details_payload())
        vlreal.save_to_database(match_payload(), details_payload())
        self.assertEqual(self.counts(), (1, 1, 1))

    def test_repeated_same_player_save_updates_in_place(self):
        vlreal.save_to_database(match_payload(), details_payload())
        updated = details_payload()
        updated["games"][0]["player_stats"][0]["kills"] = "24"
        vlreal.save_to_database(match_payload(status="LIVE"), updated)

        session = self.session_factory()
        try:
            self.assertEqual(session.query(PlayerStat).count(), 1)
            self.assertEqual(session.query(PlayerStat).one().kills, 24)
        finally:
            session.close()

    def test_upcoming_match_updates_to_live_without_duplication(self):
        vlreal.save_to_database(match_payload(), {})
        vlreal.save_to_database(
            match_payload(
                status="LIVE",
                team1_score="1",
                team2_score="0",
                team1_round_score="7",
                team2_round_score="5",
            ),
            {},
        )

        session = self.session_factory()
        try:
            match = session.query(Match).one()
            self.assertEqual(match.status, "LIVE")
            self.assertEqual((match.team1_series_score, match.team2_series_score), (1, 0))
            self.assertEqual((match.team1_round_score, match.team2_round_score), ("7", "5"))
        finally:
            session.close()

    def test_legacy_alias_cannot_overwrite_richer_canonical_match(self):
        session = self.session_factory()
        session.add_all(
            [
                Match(
                    vlr_match_id="/12345",
                    team1_name="Alpha",
                    team2_name="Bravo",
                    status="Finished",
                    team1_series_score=2,
                    team2_series_score=1,
                ),
                Match(
                    vlr_match_id="/12345/old-slug",
                    team1_name="TBD",
                    team2_name="TBD",
                    status="Upcoming",
                ),
            ]
        )
        session.commit()

        canonical = vlreal.find_match_for_save(session, "/12345")
        session.commit()

        self.assertEqual(session.query(Match).count(), 1)
        self.assertEqual(canonical.vlr_match_id, "/12345")
        self.assertEqual((canonical.team1_name, canonical.team2_name), ("Alpha", "Bravo"))
        self.assertEqual(canonical.status, "Finished")
        self.assertEqual((canonical.team1_series_score, canonical.team2_series_score), (2, 1))
        session.close()

    def test_save_rolls_back_all_rows_on_error(self):
        with self.assertRaises(IntegrityError):
            vlreal.save_to_database(match_payload(team2=None), details_payload())
        self.assertEqual(self.counts(), (0, 0, 0))

    def test_foreign_keys_are_enforced_and_delete_cascades(self):
        with self.engine.connect() as connection:
            self.assertEqual(connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one(), 1)

        session = self.session_factory()
        session.add(Game(match_id=999, vlr_game_id="orphan", map_name="Haven"))
        with self.assertRaises(IntegrityError):
            session.commit()
        session.rollback()
        session.close()

        vlreal.save_to_database(match_payload(), details_payload())
        session = self.session_factory()
        match = session.query(Match).one()
        session.delete(match)
        session.commit()
        session.close()
        self.assertEqual(self.counts(), (0, 0, 0))

    def test_logical_identity_constraints_reject_duplicate_rows(self):
        vlreal.save_to_database(match_payload(), details_payload())

        session = self.session_factory()
        match = session.query(Match).one()
        game = session.query(Game).one()
        session.add(
            Match(vlr_match_id="/12345", team1_name="Other", team2_name="Teams")
        )
        with self.assertRaises(IntegrityError):
            session.commit()
        session.rollback()

        session.add(
            Game(match_id=match.id, vlr_game_id="game-1", map_name="Duplicate")
        )
        with self.assertRaises(IntegrityError):
            session.commit()
        session.rollback()

        session.add(
            PlayerStat(
                game_id=game.id,
                team_name="ALP",
                player_name="Ace",
            )
        )
        with self.assertRaises(IntegrityError):
            session.commit()
        session.rollback()
        session.close()


class LegacyMigrationTests(unittest.TestCase):
    def test_representative_legacy_schema_migrates_repeatably(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "legacy.db"
            connection = sqlite3.connect(database_path)
            connection.executescript(
                """
                CREATE TABLE matches (
                    id INTEGER PRIMARY KEY,
                    vlr_match_id VARCHAR,
                    team1_name VARCHAR NOT NULL,
                    team2_name VARCHAR NOT NULL,
                    start_time VARCHAR,
                    status VARCHAR,
                    team1_series_score INTEGER,
                    team2_series_score INTEGER
                );
                CREATE TABLE games (
                    id INTEGER PRIMARY KEY,
                    match_id INTEGER,
                    map_name VARCHAR NOT NULL,
                    team1_round_score INTEGER,
                    team2_round_score INTEGER
                );
                CREATE TABLE player_stats (
                    id INTEGER PRIMARY KEY,
                    game_id INTEGER,
                    player_name VARCHAR NOT NULL,
                    team_name VARCHAR NOT NULL,
                    role VARCHAR,
                    acs INTEGER,
                    kd_ratio FLOAT,
                    adr INTEGER
                );

                INSERT INTO matches VALUES
                    (1, '/77', 'Alpha', 'Bravo', '2026-09-06T08:00:00-05:00', 'Finished', 2, 0),
                    (2, '/77/legacy-slug', 'TBD', 'TBD', '12:00 PM', 'Upcoming', NULL, NULL);
                INSERT INTO games VALUES (10, 2, 'Overall', 0, 0);
                INSERT INTO player_stats VALUES (20, 10, 'Ace', 'ALP', NULL, 200, 1.2, 150);
                """
            )
            connection.commit()
            connection.close()

            engine = create_sqlite_engine(f"sqlite:///{database_path}")
            run_migrations(engine)
            run_migrations(engine)

            with engine.connect() as migrated:
                self.assertEqual(
                    migrated.exec_driver_sql("PRAGMA user_version").scalar_one(),
                    LATEST_SCHEMA_VERSION,
                )
                match = migrated.exec_driver_sql(
                    "SELECT vlr_match_id, team1_name, team2_name, start_time, status "
                    "FROM matches"
                ).one()
                self.assertEqual(
                    match,
                    ("/77", "Alpha", "Bravo", "2026-09-06T13:00:00Z", "Finished"),
                )
                self.assertEqual(
                    migrated.exec_driver_sql(
                        "SELECT match_id, vlr_game_id FROM games"
                    ).one(),
                    (1, "all"),
                )
                self.assertEqual(
                    migrated.exec_driver_sql("SELECT COUNT(*) FROM player_stats").scalar_one(),
                    1,
                )
                self.assertEqual(migrated.exec_driver_sql("PRAGMA foreign_key_check").all(), [])

                inspector = inspect(migrated)
                self.assertEqual(
                    {index["name"] for index in inspector.get_indexes("matches")},
                    {"ix_matches_vlr_match_id"},
                )
                self.assertEqual(
                    {index["name"] for index in inspector.get_indexes("games")},
                    {"ix_games_vlr_game_id", "uq_games_match_id_vlr_game_id"},
                )
                self.assertEqual(
                    {index["name"] for index in inspector.get_indexes("player_stats")},
                    {"uq_player_stats_game_player_identity"},
                )
                self.assertTrue(
                    next(
                        column for column in inspector.get_columns("games")
                        if column["name"] == "match_id"
                    )["nullable"]
                    is False
                )
                self.assertEqual(
                    inspector.get_foreign_keys("games")[0]["options"].get("ondelete"),
                    "CASCADE",
                )
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
