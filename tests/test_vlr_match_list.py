import contextlib
from datetime import datetime, timezone
from pathlib import Path
import unittest
import warnings

import requests

from valoreal.domain.match_status import MATCH_STATUSES
from valoreal.scraper import (
    MatchListParseError,
    MatchListParseWarning,
    VlrErrorPageError,
    VlrScraper,
    VlrUpstreamError,
)
from valoreal.scraper.client import (
    DEFAULT_HTTP_TIMEOUT,
    DEFAULT_MIN_INTERVAL,
    VlrHttpClient,
    retry_after_seconds,
)


FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


class FakeResponse:
    def __init__(self, text="", status_code=200, headers=None):
        self.text = text
        self.status_code = status_code
        self.headers = headers or {}


class FakeSession:
    """Returns (or raises) scripted outcomes in order and records each call."""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class FakeClock:
    """Monotonic clock that only advances when the client sleeps."""

    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


def scraper_with(*outcomes):
    clock = FakeClock()
    session = FakeSession(*outcomes)
    client = VlrHttpClient(session=session, clock=clock, sleep=clock.sleep)
    return VlrScraper(client=client), session, clock


class VlrMatchListTests(unittest.TestCase):
    def setUp(self):
        self.scraper = VlrScraper()

    def parse(self, fixture_name, **kwargs):
        return self.scraper.parse_match_list(fixture(fixture_name), **kwargs)

    def test_upcoming_card_has_canonical_identity_time_status_and_url(self):
        match = self.parse("vlr_list_upcoming.html")[0]

        self.assertEqual(match["vlr_match_id"], "/724901")
        self.assertEqual(match["team1"], "FlyQuest RED")
        self.assertEqual(match["team2"], "Shopify Rebellion Gold")
        self.assertEqual(match["scheduled_time"], "2026-09-08T21:00:00Z")
        self.assertEqual(match["status"], "upcoming")
        self.assertFalse(match["is_live"])
        self.assertIsNone(match["team1_score"])
        self.assertIsNone(match["team2_score"])
        self.assertEqual(
            match["url"],
            "https://www.vlr.gg/724901/flyquest-red-vs-shopify-rebellion-gold-event",
        )

    def test_live_card_preserves_series_score(self):
        match = self.parse("vlr_list_live.html")[0]

        self.assertEqual(match["status"], "live")
        self.assertTrue(match["is_live"])
        self.assertEqual((match["team1_score"], match["team2_score"]), (1, 0))
        self.assertEqual(match["scheduled_time"], "2026-09-07T16:30:00Z")
        self.assertIsNone(match["team1_round_score"])
        self.assertIsNone(match["team2_round_score"])

    def test_completed_result_parses_finished_status_and_card_score(self):
        match = self.parse(
            "vlr_list_completed_result.html",
            status_override="finished",
        )[0]

        self.assertEqual(match["vlr_match_id"], "/734308")
        self.assertEqual(match["status"], "finished")
        self.assertEqual((match["team1_score"], match["team2_score"]), (3, 2))
        self.assertEqual(match["scheduled_time"], "2026-09-06T17:00:00Z")

    def test_tbd_team_is_valid_identity_data(self):
        match = self.parse("vlr_list_tbd_team.html")[0]

        self.assertEqual((match["team1"], match["team2"]), ("TBD", "MIBR GC"))
        self.assertEqual(match["status"], "upcoming")

    def test_full_month_heading_crosses_utc_year_boundary(self):
        match = self.parse("vlr_list_full_month_heading.html")[0]
        self.assertEqual(match["scheduled_time"], "2027-01-01T05:30:00Z")

    def test_missing_optional_fields_survive_and_malformed_neighbor_is_observable(self):
        with self.assertLogs("valoreal.scraper.match_list", level="WARNING") as logged:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                matches = self.parse("vlr_list_malformed_optional.html")

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["vlr_match_id"], "/700005")
        self.assertEqual(matches[0]["status"], "upcoming")
        self.assertIsNone(matches[0]["scheduled_time"])
        self.assertIsNone(matches[0]["team1_score"])
        self.assertEqual(len(self.scraper.last_list_parse_failures), 1)
        self.assertEqual(
            self.scraper.last_list_parse_failures[0]["href"],
            "/700006/malformed-card",
        )
        self.assertTrue(
            any(issubclass(item.category, MatchListParseWarning) for item in caught)
        )
        self.assertIn("expected two team containers", " ".join(logged.output))

    def test_empty_error_and_unrecognized_pages_are_distinguished(self):
        self.assertEqual(self.parse("vlr_list_empty.html"), [])
        cases = [
            ("vlr_error_challenge.html", VlrErrorPageError, "bot-check page"),
            ("vlr_list_redesigned.html", MatchListParseError, "none use the a.match-item card markup"),
        ]
        for name, error, message in cases:
            with self.subTest(name):
                with self.assertRaisesRegex(error, message):
                    self.parse(name)
        with self.assertRaisesRegex(MatchListParseError, "match column is missing"):
            self.scraper.parse_match_list("<html><body>maintenance</body></html>")

    def test_cards_with_unreadable_optional_fields_are_kept_with_warnings(self):
        url = "https://www.vlr.gg/matches"
        postponed, garbled, live = self.parse("vlr_list_incomplete_cards.html", source_url=url)

        self.assertEqual((postponed["status"], postponed["time"], postponed["team1_score"]),
                         ("postponed", None, None))
        self.assertEqual((garbled["status"], garbled["scheduled_time"], garbled["team1_score"]),
                         (None, None, None))
        # A genuine 0-0 live score is kept as integers, not treated as missing.
        self.assertEqual((live["status"], live["team1_score"], live["team2_score"]), ("live", 0, 0))
        self.assertEqual(self.scraper.last_list_parse_failures, ())
        self.assertEqual(
            [(w["url"], w["card_index"], w["vlr_match_id"], w["field"])
             for w in self.scraper.last_list_parse_warnings],
            [(url, 2, "/700031", "status"), (url, 2, "/700031", "scheduled_time")],
        )

    def test_all_malformed_cards_is_a_total_parse_failure(self):
        only_malformed = fixture("vlr_list_malformed_optional.html").replace(
            'class="wf-module-item match-item" href="/700005',
            'class="wf-module-item" href="/700005',
        )
        with self.assertLogs("valoreal.scraper.match_list", level="WARNING"):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", MatchListParseWarning)
                with self.assertRaisesRegex(
                    MatchListParseError,
                    "All 1 VLR match cards were malformed",
                ):
                    self.scraper.parse_match_list(only_malformed)

    def test_all_statuses_are_from_the_defined_contract(self):
        statuses = {
            self.parse("vlr_list_upcoming.html")[0]["status"],
            self.parse("vlr_list_live.html")[0]["status"],
            self.parse("vlr_list_completed_result.html")[0]["status"],
        }
        self.assertEqual(statuses, {"upcoming", "live", "finished"})
        self.assertLessEqual(statuses, MATCH_STATUSES)

    def test_postponed_and_cancelled_cards_are_retained(self):
        original = fixture("vlr_list_upcoming.html")
        for label, expected in (("Postponed", "postponed"), ("Cancelled", "cancelled")):
            with self.subTest(label=label):
                html = original.replace(">Upcoming<", f">{label}<", 1)
                self.assertNotEqual(html, original)
                self.assertEqual(self.scraper.parse_match_list(html)[0]["status"], expected)

    def test_canonical_id_is_stable_when_slug_changes(self):
        original = fixture("vlr_list_upcoming.html")
        changed_slug = original.replace(
            "/724901/flyquest-red-vs-shopify-rebellion-gold-event",
            "/724901/a-new-upstream-slug",
        )
        first = self.scraper.parse_match_list(original)[0]
        second = self.scraper.parse_match_list(changed_slug)[0]
        self.assertEqual(first["vlr_match_id"], second["vlr_match_id"])


class VlrHttpTests(unittest.TestCase):
    def test_requests_share_one_session_with_timeouts_user_agent_and_spacing(self):
        scraper, session, clock = scraper_with(
            FakeResponse(fixture("vlr_list_upcoming.html")),
            FakeResponse(fixture("vlr_list_completed_result.html")),
        )

        self.assertEqual(len(scraper.get_matches()), 1)
        self.assertEqual(scraper.get_results()[0]["status"], "finished")

        self.assertEqual([url for url, _ in session.calls],
                         ["https://www.vlr.gg/matches", "https://www.vlr.gg/matches/results"])
        for _, kwargs in session.calls:
            self.assertEqual(kwargs["timeout"], DEFAULT_HTTP_TIMEOUT)
            self.assertIn("ValScores", kwargs["headers"]["User-Agent"])
        # The second request waited out the minimum interval.
        self.assertEqual(clock.sleeps, [DEFAULT_MIN_INTERVAL])

    def test_transient_failures_retry_with_exponential_backoff(self):
        scraper, session, clock = scraper_with(
            requests.Timeout("read timed out"),
            FakeResponse("busy", status_code=503),
            FakeResponse(fixture("vlr_list_upcoming.html")),
        )
        with self.assertLogs("valoreal.scraper.client", level="WARNING"):
            matches = scraper.get_matches()

        self.assertEqual(len(matches), 1)
        self.assertEqual(len(session.calls), 3)
        self.assertEqual(clock.sleeps, [1.0, 2.0])

    def test_retries_stop_at_the_limit_and_never_repeat_permanent_failures(self):
        cases = [
            ("retryable status", [FakeResponse(status_code=503)] * 3, VlrUpstreamError, 3, 503),
            ("transport error", [requests.ConnectionError("refused")] * 3, VlrUpstreamError, 3, None),
            ("not found", [FakeResponse(status_code=404)], VlrUpstreamError, 1, 404),
            ("parse error", [FakeResponse("<html><body>maintenance</body></html>")],
             MatchListParseError, 1, None),
        ]
        for name, outcomes, error, calls, status_code in cases:
            with self.subTest(name):
                scraper, session, _clock = scraper_with(*outcomes)
                with self.assertLogs("valoreal.scraper.client", level="WARNING") if calls > 1 \
                        else contextlib.nullcontext():
                    with self.assertRaises(error) as raised:
                        scraper.get_matches()
                self.assertEqual(len(session.calls), calls)
                if error is VlrUpstreamError:
                    self.assertEqual(raised.exception.attempts, calls)
                    self.assertEqual(raised.exception.status_code, status_code)

    def test_retry_after_is_honored_within_a_limit(self):
        scraper, session, clock = scraper_with(
            FakeResponse(status_code=429, headers={"Retry-After": "5"}),
            FakeResponse(fixture("vlr_list_upcoming.html")),
        )
        with self.assertLogs("valoreal.scraper.client", level="WARNING"):
            scraper.get_matches()
        self.assertEqual(clock.sleeps, [5.0])

        scraper, session, clock = scraper_with(
            FakeResponse(status_code=429, headers={"Retry-After": "600"})
        )
        with self.assertRaisesRegex(VlrUpstreamError, "retry after 600s"):
            scraper.get_matches()
        self.assertEqual((len(session.calls), clock.sleeps), (1, []))

        http_date = FakeResponse(headers={"Retry-After": "Sun, 25 Oct 2026 12:00:30 GMT"})
        now = datetime(2026, 10, 25, 12, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(retry_after_seconds(http_date, now=now), 30.0)


if __name__ == "__main__":
    unittest.main()
