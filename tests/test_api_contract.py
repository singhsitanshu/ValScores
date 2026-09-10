import unittest

from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from valoreal import api
from valoreal.database_setup import Base, Game, Match, PlayerStat, create_sqlite_engine
from valoreal.refresh_service import RefreshInProgressError


class APIContractTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_sqlite_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(
            bind=self.engine,
            autocommit=False,
            autoflush=False,
        )
        self.original_session_factory = api.SessionLocal
        self.original_refresh_service = api.match_refresh_service
        api.SessionLocal = self.session_factory
        self.client = TestClient(api.app)
        self._seed_database()

    def tearDown(self):
        api.SessionLocal = self.original_session_factory
        api.match_refresh_service = self.original_refresh_service
        self.engine.dispose()

    def _seed_database(self):
        session = self.session_factory()
        try:
            in_range = Match(
                vlr_match_id="/101",
                team1_name="Alpha Five",
                team2_name="Bravo Crew",
                team1_round_score="13",
                team2_round_score="9",
                start_time="2026-09-07T01:30:00Z",
                status="finished",
                team1_series_score=1,
                team2_series_score=0,
                map_vetoes_raw='["Alpha ban Lotus"]',
            )
            game = Game(
                vlr_game_id="map-1",
                map_number=1,
                map_name="Haven",
                team1_round_score=13,
                team2_round_score=9,
            )
            # Deliberately persist team2 first: roster ownership must not depend on row order.
            game.player_stats.extend(
                [
                    PlayerStat(
                        player_name="Bolt",
                        team_name="UNRELATED",
                        role=None,
                        acs=None,
                        kd_ratio=None,
                        adr=None,
                        kills=None,
                        deaths=None,
                        assists=None,
                        plus_minus=None,
                        kast=None,
                        first_kills=None,
                        first_deaths=None,
                    ),
                    PlayerStat(
                        player_name="Ace",
                        team_name="AF",
                        role="duelist",
                        acs=245,
                        kd_ratio=1.5,
                        adr=160,
                        kills=21,
                        deaths=14,
                        assists=7,
                        plus_minus="+7",
                        kast="78%",
                        first_kills=4,
                        first_deaths=1,
                    ),
                    PlayerStat(
                        player_name="TBD",
                        team_name="TBD",
                    ),
                ]
            )
            in_range.games.append(game)
            session.add_all(
                [
                    in_range,
                    Match(
                        vlr_match_id="/102",
                        team1_name="At",
                        team2_name="Exclusive End",
                        start_time="2026-09-08T05:00:00Z",
                        status="upcoming",
                    ),
                    Match(
                        vlr_match_id="/103",
                        team1_name="Outside",
                        team2_name="Window",
                        start_time="2026-10-10T12:00:00Z",
                        status="upcoming",
                    ),
                    Match(
                        vlr_match_id="/104",
                        team1_name="Legacy",
                        team2_name="Timestamp",
                        start_time=None,
                        legacy_start_time="7:00 PM",
                        status="upcoming",
                    ),
                ]
            )
            session.commit()
        finally:
            session.close()

    def timeline_params(self):
        return {
            "start": "2026-09-06T00:00:00-05:00",
            "end": "2026-09-08T00:00:00-05:00",
        }

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

    def test_timeline_is_bounded_typed_and_uses_two_selects(self):
        select_count = 0

        def count_selects(_connection, _cursor, statement, _parameters, _context, _many):
            nonlocal select_count
            if statement.lstrip().upper().startswith("SELECT"):
                select_count += 1

        event.listen(self.engine, "before_cursor_execute", count_selects)
        try:
            response = self.client.get(
                "/api/matches/timeline",
                params=self.timeline_params(),
            )
        finally:
            event.remove(self.engine, "before_cursor_execute", count_selects)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(select_count, 2)
        self.assertEqual(len(response.json()), 1)
        match = response.json()[0]
        self.assertEqual(match["start_time"], "2026-09-07T01:30:00Z")
        self.assertIsInstance(match["team1_score"], int)
        self.assertIsInstance(match["team1_round_score"], int)

    def test_timeline_and_stats_gets_do_not_mutate_database_or_refresh(self):
        class ForbiddenRefreshService:
            def refresh(self, **_kwargs):
                raise AssertionError("read endpoint invoked refresh")

        api.match_refresh_service = ForbiddenRefreshService()
        before = self.database_counts()
        timeline = self.client.get("/api/matches/timeline", params=self.timeline_params())
        stats = self.client.get("/api/matches/1/stats", params={"game_id": "map-1"})

        self.assertEqual(timeline.status_code, 200)
        self.assertEqual(stats.status_code, 200)
        self.assertEqual(self.database_counts(), before)

    def test_rosters_follow_match_teams_not_player_row_order(self):
        response = self.client.get("/api/matches/1/stats", params={"game_id": "map-1"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual([player["name"] for player in payload["team1_roster"]], ["Ace"])
        self.assertEqual([player["name"] for player in payload["team2_roster"]], ["Bolt"])
        self.assertEqual(payload["team1_roster"][0]["team"], "Alpha Five")
        self.assertEqual(payload["team2_roster"][0]["team"], "Bravo Crew")
        self.assertEqual(payload["team1_roster"][0]["team_abbreviation"], "AF")
        self.assertEqual(payload["team2_roster"][0]["team_abbreviation"], "UNRELATED")
        self.assertEqual(payload["team1_roster"][0]["role"], "duelist")
        for key in ("acs", "kd", "adr", "kills", "deaths", "assists"):
            self.assertIsNotNone(payload["team2_roster"][0][key])

    def test_nullable_scores_and_empty_stats_follow_the_typed_contract(self):
        session = self.session_factory()
        try:
            upcoming_match = Match(
                vlr_match_id="/105",
                team1_name="Future Alpha",
                team2_name="Future Bravo",
                start_time="2026-09-07T18:00:00Z",
                status="upcoming",
            )
            empty_game = Game(
                match_id=1,
                vlr_game_id="map-2",
                map_number=2,
                map_name="Pearl",
                team1_round_score=None,
                team2_round_score=None,
            )
            session.add_all([upcoming_match, empty_game])
            # Column defaults preserve compatibility for normal writes. Explicitly
            # store SQL NULL after insertion to exercise legacy/null API handling.
            session.flush()
            upcoming_match.team1_round_score = None
            upcoming_match.team2_round_score = None
            empty_game.team1_round_score = None
            empty_game.team2_round_score = None
            session.commit()
        finally:
            session.close()

        timeline = self.client.get(
            "/api/matches/timeline",
            params=self.timeline_params(),
        )
        self.assertEqual(timeline.status_code, 200)
        upcoming = next(
            match for match in timeline.json() if match["team1"] == "Future Alpha"
        )
        for key in (
            "team1_score",
            "team2_score",
            "team1_round_score",
            "team2_round_score",
        ):
            self.assertIsNone(upcoming[key])

        stats = self.client.get("/api/matches/1/stats", params={"game_id": "map-2"})
        self.assertEqual(stats.status_code, 200)
        payload = stats.json()
        selected_map = next(
            item
            for item in payload["match_info"]["maps"]
            if item["game_id"] == "map-2"
        )
        self.assertIsNone(selected_map["team1_round_score"])
        self.assertIsNone(selected_map["team2_round_score"])
        self.assertEqual(payload["team1_roster"], [])
        self.assertEqual(payload["team2_roster"], [])

    def test_specific_missing_map_does_not_fall_back(self):
        response = self.client.get("/api/matches/1/stats", params={"game_id": "map-2"})

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "game_not_found")

    def test_invalid_resources_and_ranges_return_structured_4xx(self):
        cases = [
            ("/api/matches/0/stats", {"game_id": "all"}, 422),
            ("/api/matches/999/stats", {"game_id": "all"}, 404),
            ("/api/matches/1/stats", {"game_id": "bad map"}, 422),
            (
                "/api/matches/timeline",
                {"start": "2026-09-07T00:00:00", "end": "2026-09-08T00:00:00Z"},
                422,
            ),
            (
                "/api/matches/timeline",
                {"start": "2026-09-08T00:00:00Z", "end": "2026-09-07T00:00:00Z"},
                422,
            ),
            (
                "/api/matches/timeline",
                {"start": "2026-01-01T00:00:00Z", "end": "2026-03-01T00:00:00Z"},
                422,
            ),
        ]
        for path, params, expected_status in cases:
            with self.subTest(path=path, params=params):
                response = self.client.get(path, params=params)
                self.assertEqual(response.status_code, expected_status)
                self.assertEqual(set(response.json()), {"error"})
                self.assertEqual(set(response.json()["error"]), {"code", "message"})

    def test_openapi_exposes_application_response_models(self):
        schema = self.client.get("/openapi.json").json()
        timeline_schema = schema["paths"]["/api/matches/timeline"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
        stats_schema = schema["paths"]["/api/matches/{match_id}/stats"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
        refresh_path = schema["paths"]["/api/matches/refresh"]

        self.assertEqual(timeline_schema["items"]["$ref"], "#/components/schemas/TimelineMatchResponse")
        self.assertEqual(stats_schema["$ref"], "#/components/schemas/MatchStatsResponse")
        player_properties = schema["components"]["schemas"]["PlayerStatResponse"]["properties"]
        self.assertIn("team_abbreviation", player_properties)
        self.assertIn("role", player_properties)
        self.assertIn("post", refresh_path)
        self.assertNotIn("get", refresh_path)

    def test_refresh_is_post_only_and_parameters_are_bounded(self):
        class SuccessfulRefreshService:
            def refresh(self, **kwargs):
                self.kwargs = kwargs
                return {
                    "status": "success",
                    "matches_examined": 0,
                    "inserted": 0,
                    "updated": 0,
                    "unchanged": 0,
                    "details_refreshed": 0,
                    "failure_count": 0,
                    "failures": [],
                }

        service = SuccessfulRefreshService()
        api.match_refresh_service = service

        self.assertEqual(self.client.get("/api/matches/refresh").status_code, 405)
        too_large = self.client.post("/api/matches/refresh", params={"limit": 101})
        self.assertEqual(too_large.status_code, 422)
        self.assertEqual(too_large.json()["error"]["code"], "validation_error")

        response = self.client.post(
            "/api/matches/refresh",
            params={"limit": 10, "details_limit": 3, "results_limit": 20},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            service.kwargs,
            {"limit": 10, "details_limit": 3, "results_limit": 20},
        )

    def test_busy_refresh_returns_structured_conflict(self):
        class BusyRefreshService:
            def refresh(self, **_kwargs):
                raise RefreshInProgressError("A match refresh is already in progress")

        api.match_refresh_service = BusyRefreshService()
        response = self.client.post("/api/matches/refresh")

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "refresh_in_progress")

    def test_partial_refresh_failures_are_serialized_by_the_response_model(self):
        class PartialRefreshService:
            def refresh(self, **_kwargs):
                return {
                    "status": "partial",
                    "matches_examined": 2,
                    "inserted": 1,
                    "updated": 0,
                    "unchanged": 0,
                    "details_refreshed": 0,
                    "failure_count": 1,
                    "failures": [
                        {
                            "stage": "results_fetch",
                            "source": "results",
                            "error": "429 Too Many Requests",
                        }
                    ],
                }

        api.match_refresh_service = PartialRefreshService()
        response = self.client.post("/api/matches/refresh")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "partial")
        self.assertEqual(response.json()["failure_count"], 1)
        self.assertEqual(
            response.json()["failures"][0],
            {
                "stage": "results_fetch",
                "error": "429 Too Many Requests",
                "source": "results",
                "vlr_match_id": None,
                "url": None,
                "card_index": None,
                "href": None,
            },
        )


if __name__ == "__main__":
    unittest.main()
