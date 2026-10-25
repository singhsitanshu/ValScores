import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from database_support import close_test_engine, create_test_engine
from valoreal.api import app
from valoreal.api.dependencies import get_session_factory
from valoreal.database.match_persistence import persist_match
from valoreal.database.models import Base, Match
from valoreal.domain.match_status import (
    ALLOWED_STATUS_TRANSITIONS,
    MATCH_STATUSES,
    normalize_match_status,
    resolve_status_transition,
)


def list_record(status, **overrides):
    record = {
        "vlr_match_id": "/840001",
        "team1": "Alpha",
        "team2": "Bravo",
        "time": "1:00 PM",
        "scheduled_time": "2026-09-06T18:00:00Z",
        "status": status,
        "team1_score": None,
        "team2_score": None,
        "team1_round_score": None,
        "team2_round_score": None,
        "url": "https://www.vlr.gg/840001/alpha-vs-bravo",
    }
    record.update(overrides)
    return record


class MatchStatusRulesTests(unittest.TestCase):
    def test_normalization_recognizes_postponed_and_cancelled_labels(self):
        cases = {
            "Postponed": "postponed",
            "POSTPONED": "postponed",
            "Cancelled": "cancelled",
            "Canceled": "cancelled",
            "LIVE": "live",
            "Completed": "finished",
            "TBD": "upcoming",
            "Forfeit?": None,
        }
        for label, expected in cases.items():
            with self.subTest(label=label):
                self.assertEqual(normalize_match_status(label), expected)

    def test_transition_table_covers_every_status_and_terminal_states(self):
        self.assertEqual(set(ALLOWED_STATUS_TRANSITIONS), set(MATCH_STATUSES))
        self.assertEqual(ALLOWED_STATUS_TRANSITIONS["finished"], frozenset())
        self.assertEqual(ALLOWED_STATUS_TRANSITIONS["cancelled"], frozenset())

    def test_disallowed_transitions_keep_the_current_status(self):
        cases = [
            ("finished", "live", "finished"),
            ("finished", "upcoming", "finished"),
            ("live", "upcoming", "live"),
            ("live", "postponed", "live"),
            ("cancelled", "upcoming", "cancelled"),
            ("upcoming", "postponed", "postponed"),
            ("postponed", "upcoming", "upcoming"),
            ("live", "cancelled", "cancelled"),
            ("upcoming", "garbage", "upcoming"),
        ]
        for current, incoming, expected in cases:
            with self.subTest(current=current, incoming=incoming):
                self.assertEqual(resolve_status_transition(current, incoming), expected)


class MatchStatusPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        database_path = Path(self.temporary_directory.name) / "status.db"
        self.engine = create_test_engine(f"sqlite:///{database_path}")
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine, expire_on_commit=False)

    def tearDown(self):
        close_test_engine(self.engine)
        self.temporary_directory.cleanup()

    def persist(self, status, details=None, **overrides):
        persist_match(list_record(status, **overrides), details or {}, session_factory=self.session_factory)
        session = self.session_factory()
        try:
            return session.query(Match).one()
        finally:
            session.close()

    def test_postponed_match_can_be_rescheduled_but_finished_never_regresses(self):
        self.assertEqual(self.persist("Upcoming").status, "upcoming")
        self.assertEqual(self.persist("Postponed").status, "postponed")
        # An unreadable status (None) is not an observation and changes nothing.
        self.assertEqual(self.persist(None).status, "postponed")
        self.assertEqual(self.persist("Upcoming").status, "upcoming")
        self.assertEqual(self.persist("LIVE").status, "live")
        self.assertEqual(self.persist("Upcoming").status, "live")
        self.assertEqual(self.persist("Completed", team1_score="2", team2_score="1").status, "finished")
        self.assertEqual(self.persist("LIVE").status, "finished")

    def test_cancelled_is_terminal(self):
        self.persist("Upcoming")
        self.assertEqual(self.persist("Cancelled").status, "cancelled")
        self.assertEqual(self.persist("Upcoming").status, "cancelled")

    def test_detail_page_status_wins_only_through_an_allowed_transition(self):
        self.assertEqual(self.persist("Upcoming", details={"status": "postponed"}).status, "postponed")

    def test_unknown_round_scores_are_stored_as_null(self):
        match = self.persist("Upcoming")
        self.assertIsNone(match.team1_round_score)
        self.assertIsNone(match.team2_round_score)


class ErrorEnvelopeTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app, raise_server_exceptions=False)

    def test_framework_errors_use_contract_codes(self):
        cases = [
            ("GET", "/api/does-not-exist", 404, "not_found"),
            ("GET", "/api/matches/refresh", 405, "method_not_allowed"),
            ("GET", "/api/matches/timeline", 422, "validation_error"),
        ]
        for method, path, status, code in cases:
            with self.subTest(path=path):
                response = self.client.request(method, path)
                self.assertEqual(response.status_code, status)
                self.assertEqual(response.json()["error"]["code"], code)

    def test_unhandled_errors_return_the_error_envelope(self):
        def broken_session():
            raise RuntimeError("database exploded")

        app.dependency_overrides[get_session_factory] = lambda: broken_session
        try:
            with self.assertLogs("valoreal.api", level="ERROR"):
                response = self.client.get("/api/matches/1/stats")
        finally:
            app.dependency_overrides.clear()
        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            response.json(),
            {"error": {"code": "internal_error", "message": "An unexpected error occurred"}},
        )


if __name__ == "__main__":
    unittest.main()
