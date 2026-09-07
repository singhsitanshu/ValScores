"""Typed client-facing schemas for the ValScores API."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class APIModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ErrorDetail(APIModel):
    code: str
    message: str


class ErrorResponse(APIModel):
    error: ErrorDetail


class TimelineMatchResponse(APIModel):
    id: int = Field(ge=1)
    team1: str
    team2: str
    team1_score: int | None
    team2_score: int | None
    team1_round_score: int | None
    team2_round_score: int | None
    status: Literal["upcoming", "live", "finished"]
    start_time: datetime | None
    is_live: bool
    is_finished: bool


class MapStatResponse(APIModel):
    game_id: str
    map_number: int = Field(ge=0)
    map_name: str
    team1_round_score: int | None
    team2_round_score: int | None


class PlayerStatResponse(APIModel):
    name: str
    team: str
    role: str
    acs: int
    kd: float
    adr: int
    kills: int
    deaths: int
    assists: int
    plus_minus: str
    kast: str
    first_kills: int
    first_deaths: int


class MatchStatsInfoResponse(APIModel):
    team1: str
    team2: str
    map_vetoes: list[str]
    selected_game_id: str
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


class RefreshResponse(APIModel):
    status: Literal["success", "partial", "failed"]
    matches_examined: int = Field(ge=0)
    inserted: int = Field(ge=0)
    updated: int = Field(ge=0)
    unchanged: int = Field(ge=0)
    details_refreshed: int = Field(ge=0)
    failure_count: int = Field(ge=0)
    failures: list[RefreshFailureResponse]
