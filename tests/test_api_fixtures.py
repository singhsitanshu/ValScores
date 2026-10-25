"""Golden contract fixtures shared by the backend and the Swift client.

Each file in tests/fixtures/api is the exact response the API produces for a
deterministic database, and it must validate against FastAPI's generated
OpenAPI schema. The Swift XCTest target decodes the same files.

After an intentional contract change, regenerate the files with:

    UPDATE_API_FIXTURES=1 python -m unittest discover -s tests -p 'test_api_fixtures.py'
"""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import unittest

from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database_support import close_test_engine, create_test_engine
from valoreal.api import app
from valoreal.api.dependencies import get_refresh_service, get_session_factory
from valoreal.database.models import Base, Game, Match, PlayerStat
from valoreal.services.refresh import RefreshInProgressError


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIRECTORY = REPOSITORY_ROOT / "tests" / "fixtures" / "api"
CONTRACT_DOCUMENT = REPOSITORY_ROOT / "docs" / "API-CONTRACT.md"
UPDATE_FIXTURES = os.environ.get("UPDATE_API_FIXTURES") == "1"

# fixture file -> (method, OpenAPI path, request path, query, expected status)
FIXTURE_REQUESTS = {
    "timeline.json": (
        "get", "/api/matches/timeline", "/api/matches/timeline",
        {"start": "2026-09-07T00:00:00Z", "end": "2026-09-08T00:00:00Z"}, 200,
    ),
    "match_stats_upcoming.json": (
        "get", "/api/matches/{match_id}/stats", "/api/matches/1/stats", {"game_id": "all"}, 200,
    ),
    "match_stats_live_all.json": (
        "get", "/api/matches/{match_id}/stats", "/api/matches/2/stats", {"game_id": "all"}, 200,
    ),
    "match_stats_live_map_incomplete.json": (
        "get", "/api/matches/{match_id}/stats", "/api/matches/2/stats", {"game_id": "602"}, 200,
    ),
    "match_stats_finished_all.json": (
        "get", "/api/matches/{match_id}/stats", "/api/matches/3/stats", {"game_id": "all"}, 200,
    ),
    "refresh_partial.json": (
        "post", "/api/matches/refresh", "/api/matches/refresh", {}, 200,
    ),
    "error_validation_error.json": (
        "post", "/api/matches/refresh", "/api/matches/refresh", {"limit": "101"}, 422,
    ),
    "error_invalid_range.json": (
        "get", "/api/matches/timeline", "/api/matches/timeline",
        {"start": "2026-09-07T00:00:00Z", "end": "2026-10-09T00:00:00Z"}, 422,
    ),
    "error_match_not_found.json": (
        "get", "/api/matches/{match_id}/stats", "/api/matches/999/stats", {}, 404,
    ),
    "error_game_not_found.json": (
        "get", "/api/matches/{match_id}/stats", "/api/matches/3/stats", {"game_id": "999"}, 404,
    ),
    "error_refresh_in_progress.json": (
        "post", "/api/matches/refresh", "/api/matches/refresh", {}, 409,
    ),
}


def player(name, team, acs, kd, adr, kills, deaths, assists, plus_minus, kast, fk, fd, role=None):
    return PlayerStat(
        player_name=name, team_name=team, role=role, acs=acs, kd_ratio=kd, adr=adr,
        kills=kills, deaths=deaths, assists=assists, plus_minus=plus_minus, kast=kast,
        first_kills=fk, first_deaths=fd,
    )


def seed_contract_database(session):
    """Insert one match per representative state, with IDs 1-5 in order."""
    upcoming = Match(
        vlr_match_id="/730001", team1_name="Paper Rex", team2_name="DRX",
        start_time=datetime(2026, 9, 7, 9, 0, tzinfo=timezone.utc), status="upcoming",
    )

    live = Match(
        vlr_match_id="/730002", team1_name="Team Heretics", team2_name="FNATIC",
        start_time=datetime(2026, 9, 7, 10, 0, tzinfo=timezone.utc), status="live",
        team1_series_score=1, team2_series_score=0,
        team1_round_score="7", team2_round_score="5",
        map_vetoes_raw='["TH ban Bind", "FNC ban Pearl", "TH pick Ascent", "FNC pick Lotus"]',
    )
    live.games.extend([
        Game(vlr_game_id="601", map_number=1, map_name="Ascent", team1_round_score=13, team2_round_score=9),
        Game(vlr_game_id="602", map_number=2, map_name="Lotus", team1_round_score=7, team2_round_score=5),
        Game(vlr_game_id="603", map_number=3, map_name="Split", team1_round_score=None, team2_round_score=None),
    ])
    live.games[0].player_stats.extend([
        player("Boo", "TH", 231, 1.36, 152, 19, 14, 6, "+5", "76%", 3, 2, role="initiator"),
        player("Chronicle", "FNC", 198, 0.88, 131, 15, 17, 4, "-2", "70%", 1, 3),
    ])
    # Map 2 is in progress: VLR has not published ADR, KAST or first kills yet,
    # and Boo has genuinely zero assists.
    live.games[1].player_stats.extend([
        player("Boo", "TH", 244, 1.75, None, 7, 4, 0, "+3", None, None, None, role="initiator"),
        player("Chronicle", "FNC", 176, 0.67, None, 4, 6, 2, "-2", None, None, None),
    ])

    finished = Match(
        vlr_match_id="/730003", team1_name="Sentinels", team2_name="G2 Esports",
        start_time=datetime(2026, 9, 7, 7, 0, tzinfo=timezone.utc), status="finished",
        team1_series_score=2, team2_series_score=0,
        team1_round_score="0", team2_round_score="0",
        map_vetoes_raw="[]",
    )
    finished.games.extend([
        Game(vlr_game_id="all", map_number=0, map_name="Overall", team1_round_score=None, team2_round_score=None),
        Game(vlr_game_id="611", map_number=1, map_name="Haven", team1_round_score=13, team2_round_score=0),
        Game(vlr_game_id="612", map_number=2, map_name="Icebox", team1_round_score=13, team2_round_score=11),
    ])
    finished.games[0].player_stats.extend([
        player("zekken", "SEN", 262, 1.5, 171, 33, 22, 9, "+11", "81%", 6, 2, role="duelist"),
        player("leaf", "G2", 204, 0.91, 138, 21, 23, 7, "-2", "68%", 2, 4),
    ])

    postponed = Match(
        vlr_match_id="/730004", team1_name="Team Liquid", team2_name="Natus Vincere",
        start_time=datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc), status="postponed",
    )
    cancelled = Match(
        vlr_match_id="/730005", team1_name="KRÜ Esports", team2_name="LEVIATÁN",
        start_time=datetime(2026, 9, 7, 13, 0, tzinfo=timezone.utc), status="cancelled",
    )

    for match in (upcoming, live, finished, postponed, cancelled):
        session.add(match)
        session.flush()
    session.commit()


class FixtureRefreshService:
    def refresh(self, **_kwargs):
        return {
            "status": "partial",
            "matches_examined": 12,
            "inserted": 2,
            "updated": 3,
            "unchanged": 6,
            "details_refreshed": 4,
            "failure_count": 1,
            "failures": [
                {
                    "stage": "detail_fetch",
                    "vlr_match_id": "/730002",
                    "url": "https://www.vlr.gg/730002",
                    "error": "429 Too Many Requests",
                }
            ],
        }


class BusyRefreshService:
    def refresh(self, **_kwargs):
        raise RefreshInProgressError("A match refresh is already in progress")


def openapi_response_validator(openapi, method, path, status):
    response = openapi["paths"][path][method]["responses"][str(status)]
    schema = response["content"]["application/json"]["schema"]
    return Draft202012Validator({**schema, "components": openapi["components"]})


def documented_examples():
    """Yield (method, path, status, payload) for each tagged JSON block in the contract doc."""
    pattern = re.compile(
        r"<!-- example: (GET|POST) (\S+) (\d{3}) -->\s*```json\n(.*?)\n```",
        re.DOTALL,
    )
    for method, path, status, body in pattern.findall(CONTRACT_DOCUMENT.read_text()):
        yield method.lower(), path, int(status), json.loads(body)


class APIFixtureContractTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_test_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine, autoflush=False)
        app.dependency_overrides[get_session_factory] = lambda: self.session_factory
        self.client = TestClient(app)
        session = self.session_factory()
        try:
            seed_contract_database(session)
        finally:
            session.close()
        self.openapi = self.client.get("/openapi.json").json()

    def tearDown(self):
        app.dependency_overrides.clear()
        close_test_engine(self.engine)

    def request_fixture(self, name):
        method, _path, request_path, params, _status = FIXTURE_REQUESTS[name]
        service = (
            BusyRefreshService() if name == "error_refresh_in_progress.json" else FixtureRefreshService()
        )
        app.dependency_overrides[get_refresh_service] = lambda: service
        return self.client.request(method.upper(), request_path, params=params)

    def test_fixtures_are_the_exact_api_responses(self):
        if UPDATE_FIXTURES:
            FIXTURE_DIRECTORY.mkdir(parents=True, exist_ok=True)
        for name, (_method, _path, _request_path, _params, status) in FIXTURE_REQUESTS.items():
            with self.subTest(fixture=name):
                response = self.request_fixture(name)
                self.assertEqual(response.status_code, status, response.text)
                fixture_path = FIXTURE_DIRECTORY / name
                if UPDATE_FIXTURES:
                    fixture_path.write_text(
                        json.dumps(response.json(), indent=2, ensure_ascii=False) + "\n"
                    )
                self.assertEqual(response.json(), json.loads(fixture_path.read_text()))

    def test_every_fixture_file_is_covered(self):
        on_disk = {path.name for path in FIXTURE_DIRECTORY.glob("*.json")}
        self.assertEqual(on_disk, set(FIXTURE_REQUESTS))

    def test_fixtures_validate_against_generated_openapi_schema(self):
        for name, (method, path, _request_path, _params, status) in FIXTURE_REQUESTS.items():
            with self.subTest(fixture=name):
                validator = openapi_response_validator(self.openapi, method, path, status)
                payload = json.loads((FIXTURE_DIRECTORY / name).read_text())
                errors = [error.message for error in validator.iter_errors(payload)]
                self.assertEqual(errors, [])

    def test_documented_examples_validate_against_generated_openapi_schema(self):
        examples = list(documented_examples())
        self.assertGreaterEqual(len(examples), 4)
        for method, path, status, payload in examples:
            with self.subTest(example=f"{method.upper()} {path} {status}"):
                validator = openapi_response_validator(self.openapi, method, path, status)
                errors = [error.message for error in validator.iter_errors(payload)]
                self.assertEqual(errors, [])

    def test_fixtures_cover_every_status_and_missing_value(self):
        timeline = json.loads((FIXTURE_DIRECTORY / "timeline.json").read_text())
        self.assertEqual(
            {match["status"] for match in timeline},
            {"upcoming", "live", "postponed", "finished", "cancelled"},
        )

        incomplete = json.loads(
            (FIXTURE_DIRECTORY / "match_stats_live_map_incomplete.json").read_text()
        )
        boo = incomplete["team1_roster"][0]
        self.assertEqual(boo["assists"], 0)
        self.assertIsNone(boo["adr"])
        unplayed = incomplete["match_info"]["maps"][-1]
        self.assertIsNone(unplayed["team1_round_score"])

    def test_every_error_code_is_documented(self):
        codes = self.openapi["components"]["schemas"]["ErrorDetail"]["properties"]["code"]["enum"]
        document = CONTRACT_DOCUMENT.read_text()
        for code in codes:
            with self.subTest(code=code):
                self.assertIn(f"`{code}`", document)


if __name__ == "__main__":
    unittest.main()
