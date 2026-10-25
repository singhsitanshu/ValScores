"""HTTP routes: validate requests, call services, and translate their errors."""

from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query

from ..domain.normalization import ALL_MAPS_GAME_ID
from ..services.errors import ServiceError
from ..services.match_stats import get_match_stats as build_match_stats
from ..services.refresh import RefreshInProgressError, public_refresh_result
from ..services.timeline import list_timeline
from .dependencies import get_refresh_service, get_session_factory
from .errors import ERROR_RESPONSES, api_error, service_api_error
from .schemas import MatchStatsResponse, RefreshResponse, TimelineMatchResponse


MAX_TIMELINE_RANGE = timedelta(days=31)
GAME_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"

router = APIRouter()


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


@router.get(
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
    session_factory=Depends(get_session_factory),
):
    """Return persisted matches in a bounded half-open UTC range."""
    start_utc, end_utc = validated_timeline_range(start, end)
    return list_timeline(session_factory, start_utc, end_utc)


@router.get(
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
    session_factory=Depends(get_session_factory),
):
    """Return only statistics already persisted for one match and map selection."""
    try:
        return build_match_stats(session_factory, match_id, game_id)
    except ServiceError as exc:
        raise service_api_error(exc) from exc


@router.post(
    "/api/matches/refresh",
    response_model=RefreshResponse,
    responses={code: ERROR_RESPONSES[code] for code in (409, 422, 500)},
)
def force_refresh_matches(
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    details_limit: Annotated[int, Query(ge=0, le=50)] = 12,
    results_limit: Annotated[int, Query(ge=0, le=200)] = 100,
    refresh_service=Depends(get_refresh_service),
):
    """Explicitly refresh persisted data from VLR with bounded work limits."""
    try:
        result = refresh_service.refresh(
            limit=limit,
            details_limit=details_limit,
            results_limit=results_limit,
        )
    except RefreshInProgressError as exc:
        raise api_error(409, "refresh_in_progress", str(exc)) from exc
    return public_refresh_result(result)
