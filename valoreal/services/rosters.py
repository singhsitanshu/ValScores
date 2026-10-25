"""Assign persisted player rows to the two match teams."""

import re
import unicodedata

from .errors import AmbiguousRosterError


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
        raise AmbiguousRosterError(
            "Persisted player rows contain more than two team identities"
        )

    if len(team_labels) == 1:
        player_team = team_labels[0]
        team1_score = team_identity_score(player_team, match.team1_name)
        team2_score = team_identity_score(player_team, match.team2_name)
        if team1_score == team2_score:
            raise AmbiguousRosterError(
                f"Player team {player_team!r} cannot be associated with exactly one match team"
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
        raise AmbiguousRosterError(
            "Persisted player team identities cannot be associated with the match teams"
        )
    if direct_score > swapped_score:
        return players_by_team[first_team], players_by_team[second_team]
    return players_by_team[second_team], players_by_team[first_team]
