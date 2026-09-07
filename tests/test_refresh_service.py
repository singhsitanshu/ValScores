import tempfile
import threading
import unittest
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy.orm import sessionmaker

from valoreal import api
from valoreal.database_setup import Base, Game, Match, PlayerStat, create_sqlite_engine
from valoreal.refresh_service import RefreshInProgressError, RefreshService
from valoreal.vlreal import PersistenceOutcome, persist_match


def match_record(match_id="/900001", status="upcoming", **overrides):
    slug = match_id.removeprefix("/")
    record = {
        "vlr_match_id": match_id,
        "team1": "Alpha",
        "team2": "Bravo",
        "time": "1:00 PM",
        "scheduled_time": "2026-09-07T18:00:00Z",
        "status": status,
        "is_live": status == "live",
        "team1_score": None,
        "team2_score": None,
        "team1_round_score": None,
        "team2_round_score": None,
        "url": f"https://www.vlr.gg/{slug}/alpha-vs-bravo",
    }
    record.update(overrides)
    return record


def player(name="Ace", team="ALP", kills="21"):
    return {
        "player": name,
        "team": team,
        "role": "duelist",
        "acs": "245",
        "k_d": "1.5",
        "adr": "160",
        "kills": kills,
        "deaths": "14",
        "assists": "7",
        "plus_minus": "+7",
        "kast": "78%",
        "first_kills": "4",
        "first_deaths": "1",
    }


def final_details(**overrides):
    details = {
        "team1": "Alpha",
        "team2": "Bravo",
        "status": "finished",
        "stats_status": "available",
        "parse_warnings": [],
        "live_score": {"team1": "2", "team2": "0"},
        "games": [
            {
                "game_id": "map-1",
                "map_number": 1,
                "map_name": "Haven",
                "team1_round_score": "13",
                "team2_round_score": "9",
                "player_stats": [player()],
            }
        ],
    }
    details.update(overrides)
    return details


class FakeScraper:
    def __init__(self, schedule=None, results=None, details=None):
        self.schedule = [] if schedule is None else schedule
        self.results = [] if results is None else results
        self.details = {} if details is None else details
        self.last_list_parse_failures = ()
        self.detail_calls = []

    def get_matches(self):
        if isinstance(self.schedule, Exception):
            raise self.schedule
        return [dict(record) for record in self.schedule]

    def get_results(self):
        if isinstance(self.results, Exception):
            raise self.results
        return [dict(record) for record in self.results]

    def get_match_details(self, url):
        self.detail_calls.append(url)
        match_id = "/" + url.split("/", 4)[3]
        result = self.details.get(match_id, {})
        if isinstance(result, Exception):
            raise result
        return result


class RefreshServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        database_path = Path(self.temporary_directory.name) / "refresh.db"
        self.engine = create_sqlite_engine(f"sqlite:///{database_path}")
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.scraper = FakeScraper()
        self.service = RefreshService(
            scraper_factory=lambda: self.scraper,
            session_factory=self.session_factory,
            lock=threading.Lock(),
        )

    def tearDown(self):
        self.engine.dispose()
        self.temporary_directory.cleanup()

    def database_counts(self):
        session = self.session_factory()
        try:
            return (
                session.query(Match).count(),
                session.query(Game).count(),
                session.query(PlayerStat).count(),
            )
        finally:
            session.close()

    def stored_match(self):
        session = self.session_factory()
        try:
            match = session.query(Match).one()
            session.expunge(match)
            return match
        finally:
            session.close()

    def test_repeated_refresh_is_idempotent_and_reports_unchanged(self):
        self.scraper.schedule = [match_record()]

        first = self.service.refresh()
        second = self.service.refresh()

        self.assertEqual(first["inserted"], 1)
        self.assertEqual(first["updated"], 0)
        self.assertEqual(second["inserted"], 0)
        self.assertEqual(second["updated"], 0)
        self.assertEqual(second["unchanged"], 1)
        self.assertEqual(self.database_counts(), (1, 0, 0))

    def test_upcoming_to_live_to_finished_uses_one_logical_match(self):
        self.scraper.schedule = [match_record(status="upcoming")]
        upcoming = self.service.refresh()

        self.scraper.schedule = [
            match_record(
                status="live",
                team1_score="1",
                team2_score="0",
            )
        ]
        self.scraper.details = {
            "/900001": {
                "team1": "Alpha",
                "team2": "Bravo",
                "status": "live",
                "stats_status": "unavailable",
                "parse_warnings": [],
                "games": [],
            }
        }
        live = self.service.refresh()

        self.scraper.schedule = []
        self.scraper.results = [
            match_record(
                status="finished",
                team1_score="2",
                team2_score="0",
            )
        ]
        self.scraper.details = {"/900001": final_details()}
        finished = self.service.refresh()

        stored = self.stored_match()
        self.assertEqual(upcoming["inserted"], 1)
        self.assertEqual(live["updated"], 1)
        self.assertEqual(live["details_refreshed"], 1)
        self.assertEqual(finished["updated"], 1)
        self.assertEqual(finished["details_refreshed"], 1)
        self.assertEqual(self.database_counts(), (1, 1, 1))
        self.assertEqual(stored.status, "finished")
        self.assertEqual(
            (stored.team1_series_score, stored.team2_series_score),
            (2, 0),
        )

    def test_schedule_and_results_versions_merge_before_one_upsert(self):
        self.scraper.schedule = [
            match_record(status="live", team1_score="1", team2_score="0")
        ]
        self.scraper.results = [
            match_record(status="finished", team1_score="2", team2_score="0")
        ]
        self.scraper.details = {"/900001": final_details()}

        result = self.service.refresh()

        self.assertEqual(result["matches_examined"], 2)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["inserted"], 1)
        self.assertEqual(result["details_refreshed"], 1)
        self.assertEqual(self.database_counts(), (1, 1, 1))
        self.assertEqual(self.stored_match().status, "finished")

    def test_tbd_team_is_enriched_without_creating_a_duplicate(self):
        self.scraper.schedule = [match_record(team1="TBD")]
        self.scraper.details = {"/900001": {}}
        self.service.refresh()

        self.scraper.schedule = [match_record(team1="Resolved Alpha")]
        second = self.service.refresh()

        self.assertEqual(second["updated"], 1)
        self.assertEqual(self.database_counts()[0], 1)
        self.assertEqual(self.stored_match().team1_name, "Resolved Alpha")

    def test_shallow_result_becomes_detailed_after_a_transient_failure(self):
        self.scraper.results = [
            match_record(
                status="finished",
                team1_score="2",
                team2_score="0",
            )
        ]
        self.scraper.details = {"/900001": RuntimeError("detail unavailable")}

        first = self.service.refresh()
        self.assertEqual(first["status"], "partial")
        self.assertEqual(first["inserted"], 1)
        self.assertEqual(first["details_refreshed"], 0)
        self.assertEqual(first["failure_count"], 1)
        self.assertEqual(self.database_counts(), (1, 0, 0))

        self.scraper.details = {"/900001": final_details()}
        second = self.service.refresh()

        self.assertEqual(second["status"], "success")
        self.assertEqual(second["updated"], 1)
        self.assertEqual(second["details_refreshed"], 1)
        self.assertEqual(self.database_counts(), (1, 1, 1))

    def test_persistence_failure_is_not_counted_as_success(self):
        self.scraper.schedule = [
            match_record("/900001"),
            match_record("/900002"),
        ]

        def partially_failing_persistence(record, details, session_factory=None):
            if record["vlr_match_id"] == "/900002":
                raise RuntimeError("database write failed")
            return PersistenceOutcome("inserted", record["vlr_match_id"], 1)

        service = RefreshService(
            scraper_factory=lambda: self.scraper,
            session_factory=self.session_factory,
            persistence=partially_failing_persistence,
            lock=threading.Lock(),
        )
        result = service.refresh()

        self.assertEqual(result["matches_examined"], 2)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["inserted"], 1)
        self.assertEqual(result["updated"], 0)
        self.assertEqual(result["unchanged"], 0)
        self.assertEqual(result["failure_count"], 1)
        self.assertEqual(result["failures"][0]["stage"], "persistence")

    def test_total_persistence_failure_reports_failed_with_zero_successes(self):
        self.scraper.schedule = [match_record()]

        def failing_persistence(_record, _details, session_factory=None):
            raise RuntimeError("database unavailable")

        service = RefreshService(
            scraper_factory=lambda: self.scraper,
            persistence=failing_persistence,
            lock=threading.Lock(),
        )
        result = service.refresh()

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["inserted"], 0)
        self.assertEqual(result["updated"], 0)
        self.assertEqual(result["unchanged"], 0)
        self.assertEqual(result["failure_count"], 1)

    def test_partial_upstream_failure_preserves_richer_stored_data(self):
        persist_match(
            match_record(
                status="finished",
                team1_score="2",
                team2_score="0",
            ),
            final_details(),
            session_factory=self.session_factory,
        )
        self.scraper.schedule = [
            match_record(status="upcoming", team1="TBD", team2="TBD")
        ]
        self.scraper.results = RuntimeError("results unavailable")

        result = self.service.refresh()

        stored = self.stored_match()
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["unchanged"], 1)
        self.assertEqual(result["failure_count"], 1)
        self.assertEqual(stored.status, "finished")
        self.assertEqual((stored.team1_name, stored.team2_name), ("Alpha", "Bravo"))
        self.assertEqual(self.database_counts(), (1, 1, 1))

    def test_partial_detail_does_not_delete_or_zero_richer_player_data(self):
        rich_details = final_details()
        rich_details["games"][0]["player_stats"] = [
            player("Ace", "ALP", "21"),
            player("Bolt", "BRV", "18"),
        ]
        persist_match(
            match_record(status="finished", team1_score="2", team2_score="0"),
            rich_details,
            session_factory=self.session_factory,
        )

        partial = final_details(stats_status="partial")
        partial["games"][0]["player_stats"] = [
            {
                **player("Ace", "ALP", "22"),
                "acs": "0",
                "adr": "0",
            }
        ]
        persist_match(
            match_record(status="finished", team1_score="2", team2_score="0"),
            partial,
            session_factory=self.session_factory,
        )

        session = self.session_factory()
        try:
            players = {
                item.player_name: item
                for item in session.query(PlayerStat).order_by(PlayerStat.id).all()
            }
            self.assertEqual(set(players), {"Ace", "Bolt"})
            self.assertEqual(players["Ace"].kills, 22)
            self.assertEqual(players["Ace"].acs, 245)
            self.assertEqual(players["Ace"].adr, 160)
        finally:
            session.close()

    def test_concurrent_refresh_is_rejected_while_first_owns_lock(self):
        entered = threading.Event()
        release = threading.Event()

        class BlockingScraper(FakeScraper):
            def get_matches(self):
                entered.set()
                release.wait(timeout=2)
                return [match_record()]

        scraper = BlockingScraper()
        service = RefreshService(
            scraper_factory=lambda: scraper,
            session_factory=self.session_factory,
            lock=threading.Lock(),
        )
        completed = []
        worker = threading.Thread(target=lambda: completed.append(service.refresh()))
        worker.start()
        self.assertTrue(entered.wait(timeout=1))

        with self.assertRaises(RefreshInProgressError):
            service.refresh()

        release.set()
        worker.join(timeout=3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(completed[0]["inserted"], 1)


class RefreshEndpointTests(unittest.TestCase):
    def test_endpoint_maps_busy_refresh_to_http_409(self):
        class BusyService:
            def refresh(self, **_kwargs):
                raise RefreshInProgressError("A match refresh is already in progress")

        original = api.match_refresh_service
        api.match_refresh_service = BusyService()
        self.addCleanup(setattr, api, "match_refresh_service", original)

        with self.assertRaises(HTTPException) as raised:
            api.force_refresh_matches()

        self.assertEqual(raised.exception.status_code, 409)


if __name__ == "__main__":
    unittest.main()
