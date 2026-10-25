"""Match statistics: persisted maps and rosters as contract dictionaries."""

import json
from types import SimpleNamespace

from sqlalchemy.orm import selectinload

from ..database.models import Game, Match
from ..domain.normalization import ALL_MAPS_GAME_ID
from .errors import GameNotFoundError, MatchNotFoundError
from .match_summary import public_match_status
from .rosters import is_placeholder_player, split_rosters
from .stats_aggregation import aggregate_player_stats
from .values import (
    optional_float,
    optional_int,
    optional_percent,
    optional_signed_int,
    public_vlr_match_id,
)


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


def get_match_stats(session_factory, match_id, game_id=ALL_MAPS_GAME_ID):
    """Return persisted statistics for one match and map selection."""
    session = session_factory()
    try:
        match = (
            session.query(Match)
            .options(selectinload(Match.games).selectinload(Game.player_stats))
            .filter(Match.id == match_id)
            .first()
        )
        if match is None:
            raise MatchNotFoundError(f"Match {match_id} was not found")

        games = ordered_games(match)
        selected_game = next(
            (game for game in games if game.vlr_game_id == game_id),
            None,
        )
        if game_id != ALL_MAPS_GAME_ID and selected_game is None:
            raise GameNotFoundError(f"Game {game_id!r} was not found for match {match_id}")

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
