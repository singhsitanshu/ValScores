"""Timeline listing: persisted matches in a UTC range as contract dictionaries."""

from sqlalchemy.orm import selectinload

from ..database.models import Match
from ..domain.match_status import MATCH_STATUS_FINISHED, MATCH_STATUS_LIVE
from ..domain.time_contract import parse_utc_datetime
from .match_summary import map_wins_from_games, public_match_status
from .values import optional_int, public_vlr_match_id


def list_timeline(session_factory, start_utc, end_utc):
    """Return persisted matches with start_utc <= start_time < end_utc."""
    session = session_factory()
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
