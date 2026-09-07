import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import textwrap
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def run_isolated_backend(database_path: Path, source: str) -> subprocess.CompletedProcess:
    environment = os.environ.copy()
    environment["VALSCORES_DATABASE_PATH"] = str(database_path)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(source)],
        cwd=REPOSITORY_ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )


class DatabaseTimeContractTests(unittest.TestCase):
    def test_migration_normalizes_zoned_values_and_quarantines_ambiguous_values(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "legacy.db"
            connection = sqlite3.connect(database_path)
            connection.execute(
                "CREATE TABLE matches (id INTEGER PRIMARY KEY, start_time VARCHAR)"
            )
            connection.executemany(
                "INSERT INTO matches (id, start_time) VALUES (?, ?)",
                [
                    (1, "2026-09-06T08:00:00-05:00"),
                    (2, "2026-09-06 12:00:00"),
                    (3, "12:00 PM"),
                    (4, "not-a-timestamp"),
                ],
            )
            connection.commit()
            connection.close()

            run_isolated_backend(
                database_path,
                """
                from valoreal.database_setup import migrate_match_time_contract

                # A second pass verifies that startup migration is idempotent.
                migrate_match_time_contract()
                """,
            )

            connection = sqlite3.connect(database_path)
            rows = connection.execute(
                "SELECT id, start_time, legacy_start_time FROM matches ORDER BY id"
            ).fetchall()
            connection.close()

            self.assertEqual(rows[0], (1, "2026-09-06T13:00:00Z", None))
            self.assertEqual(rows[1], (2, None, "2026-09-06 12:00:00"))
            self.assertEqual(rows[2], (3, None, "12:00 PM"))
            self.assertEqual(rows[3], (4, None, "not-a-timestamp"))

    def test_timeline_exposes_only_machine_readable_canonical_timestamp(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "api.db"
            completed = run_isolated_backend(
                database_path,
                """
                import json

                from valoreal import api
                from valoreal.database_setup import Match

                session = api.SessionLocal()
                session.add_all([
                    Match(
                        vlr_match_id="/1",
                        team1_name="Alpha",
                        team2_name="Bravo",
                        start_time="2026-09-06T13:00:00Z",
                        status="Upcoming",
                    ),
                    Match(
                        vlr_match_id="/2",
                        team1_name="Charlie",
                        team2_name="Delta",
                        start_time="12:00 PM",
                        legacy_start_time="12:00 PM",
                        status="Upcoming",
                    ),
                ])
                session.commit()
                session.close()

                api.refresh_stale_tbd_matches = lambda: 0
                print(json.dumps(api.get_timeline()))
                """,
            )
            timeline = json.loads(completed.stdout)

            self.assertEqual(timeline[0]["start_time"], "2026-09-06T13:00:00Z")
            self.assertIsNone(timeline[1]["start_time"])
            for match in timeline:
                self.assertNotIn("time", match)
                self.assertNotIn("date_label", match)


if __name__ == "__main__":
    unittest.main()
