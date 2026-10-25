from pathlib import Path
import unittest

from valoreal.scraper import MatchDetailParseError, VlrErrorPageError, VlrScraper


FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


class VlrMatchDetailTests(unittest.TestCase):
    def setUp(self):
        self.scraper = VlrScraper()

    def test_current_multi_map_markup_parses_maps_scores_vetoes_and_players(self):
        details = self.scraper.parse_match_details(
            fixture("vlr_completed_multi_map.html")
        )

        self.assertEqual(details["status"], "finished")
        self.assertEqual(details["team1"], "Alpha Five")
        self.assertEqual(details["team2"], "Bravo Crew")
        self.assertEqual(details["live_score"], {"team1": 2, "team2": 0})
        self.assertEqual(details["stats_status"], "available")
        self.assertEqual(details["parse_warnings"], [])
        self.assertEqual(
            details["map_vetoes"],
            [
                "AF ban Split",
                "BC ban Bind",
                "AF pick Haven",
                "BC pick Pearl",
                "Sunset remains",
            ],
        )

        self.assertEqual(len(details["games"]), 2)
        haven, pearl = details["games"]
        self.assertEqual(
            (haven["game_id"], haven["map_number"], haven["map_name"]),
            ("map-1", 1, "Haven"),
        )
        self.assertEqual(
            (haven["team1_round_score"], haven["team2_round_score"]),
            (13, 9),
        )
        self.assertEqual(
            (pearl["map_number"], pearl["map_name"], pearl["team1_round_score"], pearl["team2_round_score"]),
            (2, "Pearl", 14, 12),
        )

        ace = haven["player_stats"][0]
        self.assertEqual(
            ace,
            {
                "player": "Ace",
                "team": "AF",
                "acs": 245,
                "k_d": 1.67,
                "adr": 164,
                "kills": 20,
                "deaths": 12,
                "assists": 7,
                "plus_minus": "+8",
                "kast": "78%",
                "first_kills": 4,
                "first_deaths": 1,
            },
        )
        self.assertEqual(
            {player["team"] for player in haven["player_stats"]},
            {"AF", "BC"},
        )

    def test_completed_single_map_is_identified(self):
        details = self.scraper.parse_match_details(
            fixture("vlr_completed_single_map.html")
        )

        self.assertEqual(details["stats_status"], "available")
        self.assertEqual(len(details["games"]), 1)
        game = details["games"][0]
        self.assertEqual((game["map_number"], game["map_name"]), (1, "Lotus"))
        self.assertEqual((game["team1_round_score"], game["team2_round_score"]), (13, 5))
        self.assertEqual(len(game["player_stats"]), 2)

    def test_live_partial_stats_are_retained_and_warned(self):
        details = self.scraper.parse_match_details(fixture("vlr_live_partial.html"))

        self.assertEqual(details["status"], "live")
        self.assertEqual(details["stats_status"], "partial")
        self.assertEqual(details["live_score"], {"team1": 1, "team2": 0})
        self.assertEqual(len(details["games"][0]["player_stats"]), 2)
        # A blank cell is unavailable (None), not a recorded zero.
        self.assertIsNone(details["games"][0]["player_stats"][1]["adr"])
        self.assertTrue(
            any("Echo is missing adr" in warning for warning in details["parse_warnings"])
        )

    def test_pending_stats_are_a_genuine_unavailable_result(self):
        details = self.scraper.parse_match_details(
            fixture("vlr_upcoming_stats_pending.html")
        )

        self.assertEqual(details["status"], "upcoming")
        self.assertEqual(details["stats_status"], "unavailable")
        self.assertEqual(details["games"][0]["player_stats"], [])
        # The page shows "0 - 0" for the unplayed map; that is unknown, not zero.
        game = details["games"][0]
        self.assertEqual((game["team1_round_score"], game["team2_round_score"]), (None, None))

    def test_error_and_unrecognized_pages_fail_explicitly(self):
        cases = [
            (fixture("vlr_error_challenge.html"), VlrErrorPageError, "bot-check page"),
            ("<html><body><div class='col mod-1'>Redesigned</div></body></html>",
             MatchDetailParseError, "match-header-vs header is missing"),
        ]
        for html, error, message in cases:
            with self.subTest(error=error.__name__):
                with self.assertRaisesRegex(error, message):
                    self.scraper.parse_match_details(html)

    def test_incompatible_current_markup_raises_instead_of_returning_empty(self):
        malformed = fixture("vlr_completed_multi_map.html").replace(
            'class="ovw-row"', 'class="unsupported-player-row"'
        )

        with self.assertRaisesRegex(
            MatchDetailParseError,
            "no supported player-stat rows matched",
        ):
            self.scraper.parse_match_details(malformed)


if __name__ == "__main__":
    unittest.main()
