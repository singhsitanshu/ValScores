"""Client-facing FastAPI routes for timeline, statistics, and explicit refreshes."""

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import json
import logging
import re
from types import SimpleNamespace
from typing import Annotated
import unicodedata

from fastapi import FastAPI, HTTPException, Path, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.orm import selectinload, sessionmaker
from starlette.exceptions import HTTPException as StarletteHTTPException

from .api_models import (
    ALL_MAPS_GAME_ID,
    ErrorDetail,
    ErrorResponse,
    MatchStatsResponse,
    RefreshResponse,
    TimelineMatchResponse,
)
from .database_setup import Game, Match, engine as database_engine, initialize_database
from .match_status import (
    MATCH_STATUS_FINISHED,
    MATCH_STATUS_LIVE,
    MATCH_STATUS_UPCOMING,
    normalize_match_status,
)
from .refresh_service import RefreshInProgressError, RefreshService
from .time_contract import parse_utc_datetime


MAX_TIMELINE_RANGE = timedelta(days=31)
GAME_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"
ERROR_RESPONSES = {
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
    500: {"model": ErrorResponse},
}
# Framework-raised HTTP errors without an application code.
GENERIC_ERROR_CODES = {404: "not_found", 405: "method_not_allowed"}

logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(_app: FastAPI):
    initialize_database(database_engine)
    yield


app = FastAPI(title="ValScores API", version="1.0.0", lifespan=lifespan)

engine = database_engine
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
match_refresh_service = RefreshService(session_factory=SessionLocal)


def api_error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message},
    )


@app.exception_handler(StarletteHTTPException)
async def http_error_response(_request: Request, exc: StarletteHTTPException):
    detail = exc.detail
    if isinstance(detail, dict) and {"code", "message"}.issubset(detail):
        error = ErrorDetail(code=str(detail["code"]), message=str(detail["message"]))
    else:
        error = ErrorDetail(
            code=GENERIC_ERROR_CODES.get(exc.status_code, "http_error"),
            message=str(detail),
        )
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(error=error).model_dump(),
        headers=exc.headers,
    )


@app.exception_handler(RequestValidationError)
async def validation_error_response(_request: Request, exc: RequestValidationError):
    first_error = exc.errors()[0] if exc.errors() else None
    message = first_error.get("msg", "Invalid request") if first_error else "Invalid request"
    return JSONResponse(
        status_code=422,
        content=ErrorResponse(
            error=ErrorDetail(code="validation_error", message=message)
        ).model_dump(),
    )


@app.exception_handler(Exception)
async def internal_error_response(_request: Request, exc: Exception):
    logger.exception("Unhandled API error", exc_info=exc)
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            error=ErrorDetail(code="internal_error", message="An unexpected error occurred")
        ).model_dump(),
    )


def optional_int(value):
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def optional_float(value):
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def optional_signed_int(value):
    """Parse a stored plus/minus such as '+7' or '-2'; None when unavailable."""
    match = re.fullmatch(r"\s*([+-]?\d+)\s*", str(value)) if value is not None else None
    return int(match.group(1)) if match else None


def optional_percent(value):
    """Parse a stored percentage such as '78%' into 78.0; None when unavailable."""
    match = (
        re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*%?\s*", str(value))
        if value is not None
        else None
    )
    return float(match.group(1)) if match else None


def public_vlr_match_id(stored_id: str) -> str:
    """Strip the leading slash from the stored canonical VLR path ID."""
    return (stored_id or "").lstrip("/") or stored_id


def map_wins_from_games(games):
    team1_maps = 0
    team2_maps = 0

    for game in games:
        if (game.vlr_game_id or "") == "all":
            continue

        map_name = (game.map_name or "").strip().upper()
        if map_name in {"", "TBD", "N/A", "OVERALL"}:
            continue

        team1_score = game.team1_round_score or 0
        team2_score = game.team2_round_score or 0
        if team1_score == team2_score:
            continue

        if team1_score > team2_score:
            team1_maps += 1
        else:
            team2_maps += 1

    if team1_maps == 0 and team2_maps == 0:
        return None
    return team1_maps, team2_maps


def ordered_games(match):
    return sorted(
        match.games,
        key=lambda game: (
            game.map_number is None,
            game.map_number if game.map_number is not None else 0,
            game.id,
        ),
    )


def games_for_response(games):
    if not games:
        return []
    if any(game.vlr_game_id == "all" for game in games):
        return games
    if len(games) == 1 and (games[0].map_name or "").lower() == "overall":
        return [
            SimpleNamespace(
                id=None,
                vlr_game_id=ALL_MAPS_GAME_ID,
                map_number=None,
                map_name="All Maps",
                team1_round_score=None,
                team2_round_score=None,
            )
        ]

    return [
        SimpleNamespace(
            id=None,
            vlr_game_id=ALL_MAPS_GAME_ID,
            map_number=None,
            map_name="All Maps",
            team1_round_score=None,
            team2_round_score=None,
        ),
        *games,
    ]


def game_to_dict(game):
    is_all_maps = game.vlr_game_id == ALL_MAPS_GAME_ID
    return {
        "game_id": game.vlr_game_id,
        "map_number": None if is_all_maps or not game.map_number else game.map_number,
        "map_name": "All Maps" if is_all_maps else game.map_name,
        "team1_round_score": None if is_all_maps else optional_int(game.team1_round_score),
        "team2_round_score": None if is_all_maps else optional_int(game.team2_round_score),
    }


def sum_if_known(values):
    """Sum per-map values; None if any map did not report the value."""
    if not values or any(value is None for value in values):
        return None
    return sum(values)


def mean_if_known(values, digits=None):
    if not values or any(value is None for value in values):
        return None
    return round(sum(values) / len(values), digits)


def aggregate_player_stats(games):
    map_games = [game for game in games if game.vlr_game_id != "all"]
    aggregates = {}
    order = []

    for game in map_games:
        for player in sorted(game.player_stats, key=lambda row: row.id):
            if is_placeholder_player(player):
                continue
            key = (player.team_name, player.player_name)
            if key not in aggregates:
                aggregates[key] = {
                    "player_name": player.player_name,
                    "team_name": player.team_name,
                    "role": player.role,
                    "acs_values": [],
                    "adr_values": [],
                    "kast_values": [],
                    "kills": [],
                    "deaths": [],
                    "assists": [],
                    "first_kills": [],
                    "first_deaths": [],
                }
                order.append(key)

            aggregate = aggregates[key]
            aggregate["acs_values"].append(optional_int(player.acs))
            aggregate["adr_values"].append(optional_int(player.adr))
            aggregate["kast_values"].append(optional_percent(player.kast))
            for field in ("kills", "deaths", "assists", "first_kills", "first_deaths"):
                aggregate[field].append(optional_int(getattr(player, field)))

    result = []
    for key in order:
        aggregate = aggregates[key]
        kills = sum_if_known(aggregate["kills"])
        deaths = sum_if_known(aggregate["deaths"])
        known_kd = kills is not None and deaths is not None
        result.append(
            SimpleNamespace(
                player_name=aggregate["player_name"],
                team_name=aggregate["team_name"],
                role=aggregate["role"],
                acs=mean_if_known(aggregate["acs_values"]),
                kd_ratio=(round(kills / deaths, 2) if deaths else float(kills)) if known_kd else None,
                adr=mean_if_known(aggregate["adr_values"]),
                kills=kills,
                deaths=deaths,
                assists=sum_if_known(aggregate["assists"]),
                plus_minus=kills - deaths if known_kd else None,
                kast=mean_if_known(aggregate["kast_values"], digits=1),
                first_kills=sum_if_known(aggregate["first_kills"]),
                first_deaths=sum_if_known(aggregate["first_deaths"]),
            )
        )
    return result


def normalized_identity(value: str | None) -> str:
    decomposed = unicodedata.normalize("NFKD", (value or "").casefold())
    return "".join(
        character
        for character in decomposed
        if character.isalnum() and not unicodedata.combining(character)
    )


def team_aliases(team_name: str) -> set[str]:
    decomposed = unicodedata.normalize("NFKD", team_name.casefold())
    tokens = re.findall(r"[^\W_]+", decomposed)
    compact = normalized_identity(team_name)
    aliases = {compact}
    if tokens:
        aliases.add("".join(token if token.isdigit() else token[0] for token in tokens))
        first_token = normalized_identity(tokens[0])
        if len(first_token) >= 3 and first_token not in {"team", "esports", "gaming"}:
            aliases.add(first_token)
    return {alias for alias in aliases if alias}


def is_placeholder_player(player) -> bool:
    return normalized_identity(player.player_name) in {"", "tbd"} or normalized_identity(
        player.team_name
    ) in {"", "tbd"}


def team_identity_score(player_team: str, match_team: str) -> int:
    player_identity = normalized_identity(player_team)
    match_identity = normalized_identity(match_team)
    if not player_identity:
        return 0
    if player_identity == match_identity:
        return 100
    if player_identity in team_aliases(match_team):
        return 80
    if len(player_identity) >= 3 and (
        match_identity.startswith(player_identity) or player_identity.startswith(match_identity)
    ):
        return 50
    if 2 <= len(player_identity) <= 5:
        match_characters = iter(match_identity)
        if all(character in match_characters for character in player_identity):
            return 40
    return 0


def split_rosters(players, match):
    players_by_team = {}
    for player in players:
        players_by_team.setdefault(player.team_name, []).append(player)

    team_labels = sorted(players_by_team, key=normalized_identity)
    if not team_labels:
        return [], []
    if len(team_labels) > 2:
        raise api_error(
            409,
            "ambiguous_roster",
            "Persisted player rows contain more than two team identities",
        )

    if len(team_labels) == 1:
        player_team = team_labels[0]
        team1_score = team_identity_score(player_team, match.team1_name)
        team2_score = team_identity_score(player_team, match.team2_name)
        if team1_score == team2_score:
            raise api_error(
                409,
                "ambiguous_roster",
                f"Player team {player_team!r} cannot be associated with exactly one match team",
            )
        if team1_score > team2_score:
            return players_by_team[player_team], []
        return [], players_by_team[player_team]

    first_team, second_team = team_labels
    direct_score = (
        team_identity_score(first_team, match.team1_name)
        + team_identity_score(second_team, match.team2_name)
    )
    swapped_score = (
        team_identity_score(first_team, match.team2_name)
        + team_identity_score(second_team, match.team1_name)
    )
    if direct_score == swapped_score:
        raise api_error(
            409,
            "ambiguous_roster",
            "Persisted player team identities cannot be associated with the match teams",
        )
    if direct_score > swapped_score:
        return players_by_team[first_team], players_by_team[second_team]
    return players_by_team[second_team], players_by_team[first_team]


def player_to_dict(player, canonical_team_name):
    return {
        "name": player.player_name,
        "team": canonical_team_name,
        "team_abbreviation": player.team_name or "",
        "role": player.role or None,
        "acs": optional_int(player.acs),
        "kd": optional_float(player.kd_ratio),
        "adr": optional_int(player.adr),
        "kills": optional_int(player.kills),
        "deaths": optional_int(player.deaths),
        "assists": optional_int(player.assists),
        "plus_minus": optional_signed_int(player.plus_minus),
        "kast": optional_percent(player.kast),
        "first_kills": optional_int(player.first_kills),
        "first_deaths": optional_int(player.first_deaths),
    }


def parse_map_vetoes(raw_value):
    if not raw_value:
        return []
    try:
        decoded = json.loads(raw_value)
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(decoded, list):
        return []
    return [str(value) for value in decoded]


def public_match_status(match):
    """Canonical status for API responses.

    Legacy rows whose stored label is unrecognized are reported as upcoming. An
    upcoming row that already has decided maps is reported as finished, matching
    how persistence promotes such matches.
    """
    status = normalize_match_status(match.status, MATCH_STATUS_UPCOMING)
    if status == MATCH_STATUS_UPCOMING and map_wins_from_games(match.games):
        return MATCH_STATUS_FINISHED
    return status


def validated_timeline_range(start: datetime, end: datetime):
    if start.tzinfo is None or start.utcoffset() is None:
        raise api_error(422, "invalid_range", "start must include a timezone offset")
    if end.tzinfo is None or end.utcoffset() is None:
        raise api_error(422, "invalid_range", "end must include a timezone offset")

    start_utc = start.astimezone(timezone.utc)
    end_utc = end.astimezone(timezone.utc)
    if end_utc <= start_utc:
        raise api_error(422, "invalid_range", "end must be later than start")
    if end_utc - start_utc > MAX_TIMELINE_RANGE:
        raise api_error(422, "invalid_range", "timeline range cannot exceed 31 days")
    return start_utc, end_utc


@app.get(
    "/api/matches/timeline",
    response_model=list[TimelineMatchResponse],
    responses=ERROR_RESPONSES,
)
def get_timeline(
    start: Annotated[
        datetime,
        Query(description="Inclusive range start; ISO-8601 with a UTC offset, e.g. 2026-09-07T00:00:00Z"),
    ],
    end: Annotated[
        datetime,
        Query(description="Exclusive range end; later than start and at most 31 days after it"),
    ],
):
    """Return persisted matches in a bounded half-open UTC range."""
    start_utc, end_utc = validated_timeline_range(start, end)
    session = SessionLocal()
    try:
        matches = (
            session.query(Match)
            .options(selectinload(Match.games))
            .filter(
                Match.start_time.is_not(None),
                Match.start_time >= start_utc,
                Match.start_time < end_utc,
            )
            .order_by(Match.start_time, Match.id)
            .all()
        )

        result = []
        for match in matches:
            start_time = parse_utc_datetime(match.start_time)
            if start_time is None:
                continue

            status = public_match_status(match)
            is_live = status == MATCH_STATUS_LIVE
            is_finished = status == MATCH_STATUS_FINISHED
            derived_series_score = map_wins_from_games(match.games)

            team1_series_score = match.team1_series_score
            team2_series_score = match.team2_series_score
            if derived_series_score and (
                team1_series_score is None
                or team2_series_score is None
                or (team1_series_score == 0 and team2_series_score == 0)
            ):
                team1_series_score, team2_series_score = derived_series_score

            show_series_score = is_live or is_finished
            result.append(
                {
                    "id": match.id,
                    "vlr_match_id": public_vlr_match_id(match.vlr_match_id),
                    "team1": match.team1_name,
                    "team2": match.team2_name,
                    "team1_score": optional_int(team1_series_score) if show_series_score else None,
                    "team2_score": optional_int(team2_series_score) if show_series_score else None,
                    # Round scores describe the map in progress, so only live
                    # matches report them.
                    "team1_round_score": optional_int(match.team1_round_score) if is_live else None,
                    "team2_round_score": optional_int(match.team2_round_score) if is_live else None,
                    "status": status,
                    "start_time": start_time,
                    "is_live": is_live,
                    "is_finished": is_finished,
                }
            )
        return result
    finally:
        session.close()


@app.get(
    "/api/matches/{match_id}/stats",
    response_model=MatchStatsResponse,
    responses=ERROR_RESPONSES,
)
def get_match_stats(
    match_id: Annotated[int, Path(ge=1)],
    game_id: Annotated[
        str,
        Query(min_length=1, max_length=64, pattern=GAME_ID_PATTERN),
    ] = ALL_MAPS_GAME_ID,
):
    """Return only statistics already persisted for one match and map selection."""
    session = SessionLocal()
    try:
        match = (
            session.query(Match)
            .options(selectinload(Match.games).selectinload(Game.player_stats))
            .filter(Match.id == match_id)
            .first()
        )
        if match is None:
            raise api_error(404, "match_not_found", f"Match {match_id} was not found")

        games = ordered_games(match)
        selected_game = next(
            (game for game in games if game.vlr_game_id == game_id),
            None,
        )
        if game_id != ALL_MAPS_GAME_ID and selected_game is None:
            raise api_error(
                404,
                "game_not_found",
                f"Game {game_id!r} was not found for match {match_id}",
            )

        if game_id == ALL_MAPS_GAME_ID:
            if selected_game is not None:
                players = [
                    player
                    for player in sorted(selected_game.player_stats, key=lambda player: player.id)
                    if not is_placeholder_player(player)
                ]
            else:
                players = aggregate_player_stats(games)
        else:
            players = [
                player
                for player in sorted(selected_game.player_stats, key=lambda player: player.id)
                if not is_placeholder_player(player)
            ]

        team1_stats, team2_stats = split_rosters(players, match)
        return {
            "match_info": {
                "match_id": match.id,
                "vlr_match_id": public_vlr_match_id(match.vlr_match_id),
                "team1": match.team1_name,
                "team2": match.team2_name,
                "status": public_match_status(match),
                "map_vetoes": parse_map_vetoes(match.map_vetoes_raw),
                "selected_game_id": game_id,
                "maps": [game_to_dict(game) for game in games_for_response(games)],
            },
            "team1_roster": [
                player_to_dict(player, match.team1_name) for player in team1_stats
            ],
            "team2_roster": [
                player_to_dict(player, match.team2_name) for player in team2_stats
            ],
        }
    finally:
        session.close()


@app.post(
    "/api/matches/refresh",
    response_model=RefreshResponse,
    responses={code: ERROR_RESPONSES[code] for code in (409, 422, 500)},
)
def force_refresh_matches(
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    details_limit: Annotated[int, Query(ge=0, le=50)] = 12,
    results_limit: Annotated[int, Query(ge=0, le=200)] = 100,
):
    """Explicitly refresh persisted data from VLR with bounded work limits."""
    try:
        result = match_refresh_service.refresh(
            limit=limit,
            details_limit=details_limit,
            results_limit=results_limit,
        )
    except RefreshInProgressError as exc:
        raise api_error(409, "refresh_in_progress", str(exc)) from exc
    failures = [
        {**failure, "vlr_match_id": public_vlr_match_id(failure["vlr_match_id"])}
        if failure.get("vlr_match_id")
        else failure
        for failure in result.get("failures", [])
    ]
    return {**result, "failures": failures}
