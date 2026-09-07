from datetime import timedelta, timezone
import unittest
from zoneinfo import ZoneInfo

from valoreal.time_contract import (
    choose_canonical_match_timestamp,
    normalize_explicit_utc_timestamp,
    normalize_vlr_utc_timestamp,
    parse_vlr_schedule_timestamp,
)


class TimeContractTests(unittest.TestCase):
    def test_all_full_month_names(self):
        for month in (
            "January", "February", "March", "April", "May", "June",
            "July", "August", "September", "October", "November", "December",
        ):
            with self.subTest(month=month):
                self.assertIsNotNone(
                    parse_vlr_schedule_timestamp(
                        f"Mon, {month} 1, 2027",
                        "1:00 PM",
                    )
                )

    def test_full_month_name(self):
        self.assertEqual(
            parse_vlr_schedule_timestamp("Sun, September 6, 2026 Today", "12:00 PM"),
            "2026-09-06T17:00:00Z",
        )

    def test_abbreviated_month_name(self):
        self.assertEqual(
            parse_vlr_schedule_timestamp("Thu, Jan 1, 2026", "12:30 AM"),
            "2026-01-01T06:30:00Z",
        )

    def test_vlr_exact_utc_timestamp(self):
        self.assertEqual(
            normalize_vlr_utc_timestamp("2026-09-06 13:00:00"),
            "2026-09-06T13:00:00Z",
        )

    def test_exact_utc_timestamp_wins_over_list_fallback(self):
        self.assertEqual(
            choose_canonical_match_timestamp(
                "2026-09-06 13:00:00",
                "2026-09-06T17:00:00Z",
            ),
            "2026-09-06T13:00:00Z",
        )

    def test_source_timezone_is_converted_to_utc(self):
        self.assertEqual(
            parse_vlr_schedule_timestamp(
                "Sun, September 6, 2026",
                "11:30 PM",
                source_timezone=timezone(timedelta(hours=-5)),
            ),
            "2026-09-07T04:30:00Z",
        )

    def test_date_crosses_midnight_in_utc(self):
        self.assertEqual(
            normalize_explicit_utc_timestamp("2026-09-06T23:30:00-05:00"),
            "2026-09-07T04:30:00Z",
        )

    def test_year_boundary(self):
        self.assertEqual(
            parse_vlr_schedule_timestamp(
                "Thu, December 31, 2026",
                "11:30 PM",
                source_timezone=ZoneInfo("America/Chicago"),
            ),
            "2027-01-01T05:30:00Z",
        )

    def test_naive_legacy_timestamp_is_not_reinterpreted(self):
        self.assertIsNone(normalize_explicit_utc_timestamp("2026-09-06 12:00:00"))
        self.assertIsNone(normalize_explicit_utc_timestamp("12:00 PM"))

    def test_invalid_timestamp(self):
        self.assertIsNone(normalize_vlr_utc_timestamp("not-a-timestamp"))
        self.assertIsNone(parse_vlr_schedule_timestamp("invalid", "25:90 PM"))


if __name__ == "__main__":
    unittest.main()
