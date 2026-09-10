from pathlib import Path
import unittest
import warnings

import requests

from valoreal.vlreal import (
    DEFAULT_HTTP_TIMEOUT,
    MATCH_STATUSES,
    MatchListParseError,
    MatchListParseWarning,
    VlrScraper,
    VlrUpstreamError,
)


FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


class FakeResponse:
    def __init__(self, text, error=None):
        self.text = text
        self.error = error

    def raise_for_status(self):
        if self.error:
            raise self.error


class FakeSession:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.error:
            raise self.error
        return self.response


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
        self.assertEqual((match["team1_score"], match["team2_score"]), ("1", "0"))
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
        self.assertEqual((match["team1_score"], match["team2_score"]), ("3", "2"))
        self.assertEqual(match["scheduled_time"], "2026-09-06T17:00:00Z")

    def test_tbd_team_is_valid_identity_data(self):
        match = self.parse("vlr_list_tbd_team.html")[0]

        self.assertEqual((match["team1"], match["team2"]), ("TBD", "MIBR GC"))
        self.assertEqual(match["status"], "upcoming")

    def test_full_month_heading_crosses_utc_year_boundary(self):
        match = self.parse("vlr_list_full_month_heading.html")[0]
        self.assertEqual(match["scheduled_time"], "2027-01-01T05:30:00Z")

    def test_missing_optional_fields_survive_and_malformed_neighbor_is_observable(self):
        with self.assertLogs("valoreal.vlreal", level="WARNING") as logged:
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

    def test_no_match_cards_is_a_total_parse_failure(self):
        with self.assertRaisesRegex(MatchListParseError, "no match cards"):
            self.scraper.parse_match_list("<html><body>maintenance</body></html>")

    def test_all_malformed_cards_is_a_total_parse_failure(self):
        only_malformed = fixture("vlr_list_malformed_optional.html").replace(
            'class="wf-module-item match-item" href="/700005',
            'class="wf-module-item" href="/700005',
        )
        with self.assertLogs("valoreal.vlreal", level="WARNING"):
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
        self.assertEqual(statuses, MATCH_STATUSES)

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
    def test_list_fetch_uses_central_timeout_headers_and_status_validation(self):
        response = FakeResponse(fixture("vlr_list_upcoming.html"))
        session = FakeSession(response=response)
        scraper = VlrScraper(session=session)

        matches = scraper.get_matches()

        self.assertEqual(len(matches), 1)
        self.assertEqual(len(session.calls), 1)
        url, kwargs = session.calls[0]
        self.assertEqual(url, "https://www.vlr.gg/matches")
        self.assertEqual(kwargs["timeout"], DEFAULT_HTTP_TIMEOUT)
        self.assertIn("ValScores", kwargs["headers"]["User-Agent"])

    def test_results_fetch_applies_finished_override(self):
        session = FakeSession(
            response=FakeResponse(fixture("vlr_list_completed_result.html"))
        )
        matches = VlrScraper(session=session).get_results()
        self.assertEqual(matches[0]["status"], "finished")

    def test_404_429_and_500_failures_are_wrapped_and_propagated(self):
        for status_code, reason in (
            (404, "Not Found"),
            (429, "Too Many Requests"),
            (500, "Server Error"),
        ):
            with self.subTest(status_code=status_code):
                error = requests.HTTPError(f"{status_code} {reason}")
                session = FakeSession(
                    response=FakeResponse("upstream failure", error=error)
                )

                with self.assertRaisesRegex(VlrUpstreamError, str(status_code)):
                    VlrScraper(session=session).get_matches()

    def test_transport_failure_is_wrapped_and_propagated(self):
        session = FakeSession(error=requests.Timeout("read timed out"))

        with self.assertRaisesRegex(VlrUpstreamError, "read timed out"):
            VlrScraper(session=session).get_matches()

    def test_malformed_fetched_html_is_rejected_without_network_access(self):
        session = FakeSession(
            response=FakeResponse("<html><body>maintenance</body></html>")
        )

        with self.assertRaisesRegex(MatchListParseError, "no match cards"):
            VlrScraper(session=session).get_matches()

        self.assertEqual(len(session.calls), 1)


if __name__ == "__main__":
    unittest.main()
