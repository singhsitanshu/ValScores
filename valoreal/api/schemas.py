"""Typed client-facing schemas for the ValScores API.

docs/API-CONTRACT.md describes these models. Every nullable field uses null to
mean "unknown or not applicable"; a number is always a value VLR reported.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field



MatchStatus = Literal["upcoming", "live", "postponed", "finished", "cancelled"]

ErrorCode = Literal[
    "validation_error",
    "invalid_range",
    "not_found",
    "match_not_found",
    "game_not_found",
    "method_not_allowed",
    "refresh_in_progress",
    "ambiguous_roster",
    "http_error",
    "internal_error",
]


class APIModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ErrorDetail(APIModel):
    code: ErrorCode = Field(description="Stable machine-readable error code.")
    message: str = Field(description="Human-readable explanation; not for parsing.")


class ErrorResponse(APIModel):
    error: ErrorDetail


class TimelineMatchResponse(APIModel):
    id: int = Field(
        ge=1,
        description="ValScores match ID. The only match identifier accepted by API paths.",
    )
    vlr_match_id: str = Field(
        min_length=1,
        description="Upstream VLR match ID (the number in vlr.gg/<id>/...). Informational.",
    )
    team1: str
    team2: str
    team1_score: int | None = Field(
        ge=0,
        description="Maps won by team 1. Null unless live or finished with a known score.",
    )
    team2_score: int | None = Field(ge=0, description="Maps won by team 2. See team1_score.")
    team1_round_score: int | None = Field(
        ge=0,
        description="Team 1 rounds on the current map. Null unless live with a known score.",
    )
    team2_round_score: int | None = Field(
        ge=0,
        description="Team 2 rounds on the current map. See team1_round_score.",
    )
    status: MatchStatus
    start_time: datetime = Field(description="Scheduled start as an ISO-8601 UTC instant.")
    is_live: bool = Field(description="Derived: status == 'live'.")
    is_finished: bool = Field(description="Derived: status == 'finished'.")


class MapStatResponse(APIModel):
    game_id: str = Field(
        description="Upstream VLR game ID, or 'all' for the whole-series aggregate.",
    )
    map_number: int | None = Field(
        ge=1,
        description="Position in the series. Null for the 'all' aggregate or when unknown.",
    )
    map_name: str
    team1_round_score: int | None = Field(
        ge=0,
        description="Rounds won on this map. Null for 'all' and for unplayed maps.",
    )
    team2_round_score: int | None = Field(ge=0)


class PlayerStatResponse(APIModel):
    name: str
    team: str = Field(description="Match team name (team1 or team2) this player belongs to.")
    team_abbreviation: str = Field(description="Team label VLR shows beside the player.")
    role: str | None
    acs: int | None = Field(description="Average combat score. Null when unavailable.")
    kd: float | None = Field(description="Kills / deaths. Null when either is unavailable.")
    adr: int | None = Field(description="Average damage per round.")
    kills: int | None
    deaths: int | None
    assists: int | None
    plus_minus: int | None = Field(description="Kills minus deaths, signed.")
    kast: float | None = Field(description="KAST as a percentage, e.g. 78.0 for 78%.")
    first_kills: int | None
    first_deaths: int | None


class MatchStatsInfoResponse(APIModel):
    match_id: int = Field(ge=1, description="ValScores match ID.")
    vlr_match_id: str = Field(min_length=1, description="Upstream VLR match ID.")
    team1: str
    team2: str
    status: MatchStatus
    map_vetoes: list[str]
    selected_game_id: str = Field(description="The game_id these rosters describe.")
    maps: list[MapStatResponse]


class MatchStatsResponse(APIModel):
    match_info: MatchStatsInfoResponse
    team1_roster: list[PlayerStatResponse]
    team2_roster: list[PlayerStatResponse]


class RefreshFailureResponse(APIModel):
    stage: str
    error: str
    source: str | None = None
    vlr_match_id: str | None = None
    url: str | None = None
    card_index: int | None = Field(default=None, ge=1)
    href: str | None = None


class RefreshWarningResponse(APIModel):
    stage: Literal["list_warning", "detail_warning"] = Field(
        description="list_warning: a list card was stored with unreadable optional fields. "
                    "detail_warning: a match page was stored but VLR omitted some statistics.",
    )
    message: str
    source: str | None = None
    vlr_match_id: str | None = None
    url: str | None = None
    card_index: int | None = Field(default=None, ge=1)
    href: str | None = None
    field: str | None = None


class RefreshResponse(APIModel):
    status: Literal["success", "partial", "failed"] = Field(
        description="success: no failures (warnings allowed). partial: some failures and "
                    "some matches stored. failed: failures and nothing stored.",
    )
    matches_examined: int = Field(ge=0)
    inserted: int = Field(ge=0)
    updated: int = Field(ge=0)
    unchanged: int = Field(ge=0)
    details_refreshed: int = Field(ge=0)
    failure_count: int = Field(ge=0, description="Fetch, parse and persistence failures.")
    failures: list[RefreshFailureResponse]
    warning_count: int = Field(ge=0, description="Data stored with incomplete upstream fields.")
    warnings: list[RefreshWarningResponse]
