from pathlib import Path
import unittest

from sqlalchemy.orm import sessionmaker

from database_support import close_test_engine, create_test_engine
from valoreal.database.match_persistence import persist_match
from valoreal.database.models import Base, Game, Match, PlayerStat
from valoreal.scraper import VlrScraper


FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


class DetailPersistenceTests(unittest.TestCase):
    """Parsed VLR detail pages persisted through the database layer."""

    def setUp(self):
        self.scraper = VlrScraper()
        self.engine = create_test_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.addCleanup(close_test_engine, self.engine)

    def session_factory(self):
        return sessionmaker(bind=self.engine)

    def test_current_details_are_persisted_per_map(self):
        session_factory = self.session_factory()

        details = self.scraper.parse_match_details(
            fixture("vlr_completed_multi_map.html")
        )
        persist_match(
            {
                "url": "https://www.vlr.gg/123456/example",
                "team1": "Alpha Five",
                "team2": "Bravo Crew",
                "time": "",
                "scheduled_time": "2026-08-14T18:00:00Z",
                "status": "Finished",
                "team1_score": "2",
                "team2_score": "0",
                "team1_round_score": "0",
                "team2_round_score": "0",
            },
            details,
            session_factory=session_factory,
        )

        session = session_factory()
        try:
            match = session.query(Match).one()
            games = session.query(Game).order_by(Game.map_number).all()
            players = session.query(PlayerStat).all()
            self.assertEqual(match.map_vetoes_raw is not None, True)
            self.assertEqual([game.map_name for game in games], ["Haven", "Pearl"])
            self.assertEqual(len(players), 4)
            self.assertEqual({player.team_name for player in players}, {"AF", "BC"})
        finally:
            session.close()

    def test_empty_detail_input_does_not_create_a_false_overall_game(self):
        session_factory = self.session_factory()

        persist_match(
            {
                "url": "https://www.vlr.gg/654321/example",
                "team1": "No Stats One",
                "team2": "No Stats Two",
                "time": "",
                "scheduled_time": "2026-08-14T18:00:00Z",
                "status": "Upcoming",
                "team1_score": None,
                "team2_score": None,
            },
            {},
            session_factory=session_factory,
        )

        session = session_factory()
        try:
            self.assertEqual(session.query(Match).count(), 1)
            self.assertEqual(session.query(Game).count(), 0)
            self.assertEqual(session.query(PlayerStat).count(), 0)
        finally:
            session.close()


if __name__ == "__main__":
    unittest.main()
