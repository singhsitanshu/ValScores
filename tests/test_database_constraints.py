"""Schema constraints that keep match, map and player rows consistent.

Runs against the models' schema in both SQLite and PostgreSQL test modes;
tests/test_migrations.py proves the migrated PostgreSQL schema is identical.
"""

from datetime import datetime, timezone
import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database_support import close_test_engine, create_test_engine
from valoreal.api import app
from valoreal.database.migration_errors import SchemaVersionError
from valoreal.database.models import Base, Game, Match, PlayerStat


def match(vlr_match_id="/3001", **overrides):
    values = {
        "vlr_match_id": vlr_match_id,
        "team1_name": "Alpha",
        "team2_name": "Bravo",
        "start_time": datetime(2026, 9, 7, 10, 0, tzinfo=timezone.utc),
    }
    values.update(overrides)
    return Match(**values)


class DatabaseConstraintTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_test_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        Base.metadata.create_all(self.engine)
        self.addCleanup(close_test_engine, self.engine)
        self.session = sessionmaker(bind=self.engine)()
        self.addCleanup(self.session.close)

    def assertRejected(self, *objects):
        self.session.add_all(objects)
        with self.assertRaises(IntegrityError):
            self.session.commit()
        self.session.rollback()

    def saved_match(self, **overrides):
        record = match(**overrides)
        self.session.add(record)
        self.session.commit()
        return record

    def test_upstream_match_id_is_unique(self):
        self.saved_match()
        self.assertRejected(match())

    def test_map_identity_is_unique_per_match(self):
        record = self.saved_match()
        self.session.add(Game(match_id=record.id, vlr_game_id="601", map_name="Ascent"))
        self.session.commit()
        self.assertRejected(Game(match_id=record.id, vlr_game_id="601", map_name="Ascent"))

    def test_player_identity_is_unique_per_map(self):
        record = self.saved_match()
        game = Game(match_id=record.id, vlr_game_id="601", map_name="Ascent")
        self.session.add(game)
        self.session.commit()
        self.session.add(PlayerStat(game_id=game.id, player_name="Boo", team_name="TH"))
        self.session.commit()
        self.assertRejected(PlayerStat(game_id=game.id, player_name="Boo", team_name="TH"))

    def test_maps_and_player_rows_cannot_be_orphaned(self):
        self.assertRejected(Game(match_id=999, vlr_game_id="601", map_name="Ascent"))
        self.assertRejected(PlayerStat(game_id=999, player_name="Boo", team_name="TH"))

    def test_deleting_a_match_cascades_to_maps_and_players(self):
        record = self.saved_match()
        game = Game(match_id=record.id, vlr_game_id="601", map_name="Ascent")
        game.player_stats.append(PlayerStat(player_name="Boo", team_name="TH"))
        self.session.add(game)
        self.session.commit()

        self.session.delete(record)
        self.session.commit()

        self.assertEqual(self.session.query(Game).count(), 0)
        self.assertEqual(self.session.query(PlayerStat).count(), 0)

    def test_status_defaults_to_upcoming_and_rejects_unknown_labels(self):
        self.assertEqual(self.saved_match().status, "upcoming")
        self.assertRejected(match("/3002", status="Finished"))
        # The ORM substitutes the default for None; a Core insert sends NULL.
        with self.assertRaises(IntegrityError):
            with self.engine.begin() as connection:
                connection.execute(Match.__table__.insert().values(
                    vlr_match_id="/3003", team1_name="A", team2_name="B", status=None
                ))

    def test_scores_and_map_numbers_cannot_be_negative(self):
        self.assertRejected(match("/3004", team1_series_score=-1, team2_series_score=0))
        self.assertRejected(match("/3005", team1_round_score=-3, team2_round_score=0))
        record = self.saved_match(vlr_match_id="/3006", team1_round_score=0, team2_round_score=0)
        self.assertRejected(Game(match_id=record.id, vlr_game_id="601", map_name="A", map_number=-1))
        self.assertRejected(Game(match_id=record.id, vlr_game_id="602", map_name="B", team2_round_score=-1))


def shared_memory_engine():
    # The lifespan runs in another thread; StaticPool shares one in-memory database.
    return create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)


class StartupSchemaCheckTests(unittest.TestCase):
    """The API refuses to start on an incompatible schema instead of changing it."""

    def start_with(self, engine):
        app.state.database_engine = engine
        self.addCleanup(delattr, app.state, "database_engine")
        with TestClient(app):
            pass

    def test_empty_database_names_the_upgrade_command(self):
        engine = shared_memory_engine()
        self.addCleanup(engine.dispose)
        with self.assertRaisesRegex(SchemaVersionError, "python -m valoreal.database upgrade"):
            self.start_with(engine)
        with engine.connect() as connection:
            self.assertEqual(engine.dialect.get_table_names(connection), [])

    def test_unversioned_tables_name_the_baseline_command(self):
        engine = shared_memory_engine()
        self.addCleanup(engine.dispose)
        Base.metadata.create_all(engine)
        with self.assertRaisesRegex(SchemaVersionError, "python -m valoreal.database baseline"):
            self.start_with(engine)


if __name__ == "__main__":
    unittest.main()
