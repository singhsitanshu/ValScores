"""Normalization rules shared by scraped records and persisted matches."""

import re


# game_id of the whole-series aggregate in VLR's map navigation and the API.
ALL_MAPS_GAME_ID = "all"


def canonical_match_id(match_url):
    path = match_url.replace("https://www.vlr.gg", "")
    match = re.match(r"^/(\d+)", path)
    return f"/{match.group(1)}" if match else path


def is_placeholder_team(name):
    return not name or name.strip().upper() == "TBD"


def should_replace_team_name(current_name, new_name):
    return not is_placeholder_team(new_name) and (
        is_placeholder_team(current_name) or current_name.strip() != new_name.strip()
    )


def richer_team_name(primary_name, fallback_name):
    if not is_placeholder_team(primary_name):
        return primary_name
    return fallback_name


def has_meaningful_score(team1_score, team2_score):
    return team1_score is not None and team2_score is not None and not (
        score_to_int(team1_score) == 0 and score_to_int(team2_score) == 0
    )


def score_to_int(score):
    try:
        return int(score)
    except (TypeError, ValueError):
        return 0


def optional_score_int(score):
    """Integer score for storage; None when the score is unknown."""
    try:
        return int(score)
    except (TypeError, ValueError):
        return None


def series_score_from_games(games):
    team1_maps = 0
    team2_maps = 0

    for game_data in games:
        if (game_data.get('game_id') or "") == "all":
            continue

        map_name = (game_data.get('map_name') or "").strip().upper()
        if map_name in {"", "TBD", "N/A", "OVERALL"}:
            continue

        team1_score = score_to_int(game_data.get('team1_round_score'))
        team2_score = score_to_int(game_data.get('team2_round_score'))
        if team1_score == team2_score:
            continue

        if team1_score > team2_score:
            team1_maps += 1
        else:
            team2_maps += 1

    if team1_maps == 0 and team2_maps == 0:
        return None

    return team1_maps, team2_maps


def latest_started_map_score(games):
    started_maps = []
    for game_data in games:
        if (game_data.get('game_id') or "") == "all":
            continue

        map_name = (game_data.get('map_name') or "").strip().upper()
        if map_name in {"", "TBD", "N/A"}:
            continue

        team1_score = score_to_int(game_data.get('team1_round_score'))
        team2_score = score_to_int(game_data.get('team2_round_score'))
        if team1_score == 0 and team2_score == 0:
            continue

        started_maps.append((
            game_data.get('map_number') or 0,
            str(team1_score),
            str(team2_score)
        ))

    if not started_maps:
        return None

    started_maps.sort(key=lambda item: item[0])
    return started_maps[-1][1], started_maps[-1][2]
