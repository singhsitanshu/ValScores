"""Combine per-map player statistics into whole-series totals."""

from types import SimpleNamespace

from .rosters import is_placeholder_player
from .values import optional_int, optional_percent


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
