"""Match-level facts derived from persisted maps, shared by API services."""

from ..domain.match_status import (
    MATCH_STATUS_FINISHED,
    MATCH_STATUS_UPCOMING,
    normalize_match_status,
)


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
