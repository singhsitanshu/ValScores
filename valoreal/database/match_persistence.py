"""Atomic upserts of scraped matches, maps and player statistics."""

from dataclasses import dataclass
import json
import logging

from ..domain.match_status import (
    MATCH_STATUS_FINISHED,
    MATCH_STATUS_LIVE,
    MATCH_STATUS_UPCOMING,
    normalize_match_status,
    resolve_status_transition,
    status_rank,
)
from ..domain.normalization import (
    canonical_match_id,
    has_meaningful_score,
    is_placeholder_team,
    latest_started_map_score,
    optional_score_int,
    richer_team_name,
    series_score_from_games,
    should_replace_team_name,
)
from ..domain.time_contract import choose_canonical_match_timestamp, parse_utc_datetime
from . import connection
from .models import Game, Match, PlayerStat


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PersistenceOutcome:
    action: str
    vlr_match_id: str
    database_id: int


def richer_match(existing, candidate):
    existing_score = has_meaningful_score(existing.team1_series_score, existing.team2_series_score)
    candidate_score = has_meaningful_score(candidate.team1_series_score, candidate.team2_series_score)
    if candidate_score != existing_score:
        return candidate_score

    existing_teams = int(not is_placeholder_team(existing.team1_name)) + int(not is_placeholder_team(existing.team2_name))
    candidate_teams = int(not is_placeholder_team(candidate.team1_name)) + int(not is_placeholder_team(candidate.team2_name))
    if candidate_teams != existing_teams:
        return candidate_teams > existing_teams

    return candidate.id < existing.id


def merge_duplicate_match(session, primary, duplicate):
    # richer_match(existing, candidate) answers whether the candidate is richer.
    # The old argument order inverted that decision and copied legacy data over
    # the canonical row.
    if richer_match(primary, duplicate):
        if not is_placeholder_team(duplicate.team1_name):
            primary.team1_name = duplicate.team1_name
        if not is_placeholder_team(duplicate.team2_name):
            primary.team2_name = duplicate.team2_name

    if status_rank(duplicate.status) > status_rank(primary.status):
        primary.status = normalize_match_status(duplicate.status, MATCH_STATUS_UPCOMING)

    if duplicate.start_time and not primary.start_time:
        primary.start_time = duplicate.start_time
    if duplicate.legacy_start_time and not primary.legacy_start_time:
        primary.legacy_start_time = duplicate.legacy_start_time
    if duplicate.map_vetoes_raw and not primary.map_vetoes_raw:
        primary.map_vetoes_raw = duplicate.map_vetoes_raw
    if has_meaningful_score(duplicate.team1_series_score, duplicate.team2_series_score) and not has_meaningful_score(primary.team1_series_score, primary.team2_series_score):
        primary.team1_series_score = duplicate.team1_series_score
        primary.team2_series_score = duplicate.team2_series_score

    for duplicate_game in list(duplicate.games):
        existing_game = session.query(Game).filter_by(
            match_id=primary.id,
            vlr_game_id=duplicate_game.vlr_game_id
        ).first()

        if not existing_game:
            duplicate_game.match = primary
            continue

        if existing_game.map_name in {"Overall", "Map", "TBD", "N/A"} and duplicate_game.map_name:
            existing_game.map_name = duplicate_game.map_name
        if existing_game.team1_round_score == 0 and existing_game.team2_round_score == 0:
            existing_game.team1_round_score = duplicate_game.team1_round_score
            existing_game.team2_round_score = duplicate_game.team2_round_score
        if len(existing_game.player_stats) < len(duplicate_game.player_stats):
            for stat in list(existing_game.player_stats):
                session.delete(stat)
            session.flush()
            for stat in list(duplicate_game.player_stats):
                stat.game = existing_game

        session.delete(duplicate_game)

    session.delete(duplicate)


def find_match_for_save(session, canonical_id):
    matches = (
        session.query(Match)
        .filter((Match.vlr_match_id == canonical_id) | (Match.vlr_match_id.like(f"{canonical_id}/%")))
        .order_by(Match.id)
        .all()
    )
    if not matches:
        return None

    exact = next((match for match in matches if match.vlr_match_id == canonical_id), None)
    primary = exact or matches[0]
    if not exact:
        for candidate in matches:
            if candidate.id != primary.id and richer_match(primary, candidate):
                primary = candidate

    for duplicate in matches:
        if duplicate.id != primary.id:
            merge_duplicate_match(session, primary, duplicate)

    primary.vlr_match_id = canonical_id
    primary.status = normalize_match_status(
        primary.status,
        MATCH_STATUS_UPCOMING,
    )
    session.flush()
    return primary


def _match_persistence_state(match):
    games = []
    for game in sorted(match.games, key=lambda item: (item.vlr_game_id or "", item.id or 0)):
        players = tuple(sorted(
            (
                player.team_name,
                player.player_name,
                player.role,
                player.acs,
                player.kd_ratio,
                player.adr,
                player.kills,
                player.deaths,
                player.assists,
                player.plus_minus,
                player.kast,
                player.first_kills,
                player.first_deaths,
            )
            for player in game.player_stats
        ))
        games.append((
            game.vlr_game_id,
            game.map_number,
            game.map_name,
            game.team1_round_score,
            game.team2_round_score,
            players,
        ))

    return (
        match.vlr_match_id,
        match.team1_name,
        match.team2_name,
        match.team1_round_score,
        match.team2_round_score,
        match.start_time,
        match.legacy_start_time,
        normalize_match_status(match.status, MATCH_STATUS_UPCOMING),
        match.team1_series_score,
        match.team2_series_score,
        match.map_vetoes_raw,
        tuple(games),
    )


def persist_match(match_dict, details_dict, session_factory=None):
    """Atomically upsert one logical match and report its actual write outcome."""
    session = (session_factory or connection.SessionLocal)()
    try:
        match_id_string = canonical_match_id(
            match_dict.get('vlr_match_id') or match_dict['url']
        )
        if not match_id_string:
            raise ValueError("A VLR match ID is required")
        db_match = find_match_for_save(session, match_id_string)
        was_inserted = db_match is None
        if was_inserted:
            prior_state = None
        else:
            database_id = db_match.id
            session.expire_all()
            db_match = session.get(Match, database_id)
            prior_state = _match_persistence_state(db_match)

        best_time = parse_utc_datetime(
            choose_canonical_match_timestamp(
                details_dict.get('exact_time'),
                match_dict.get('scheduled_time'),
            )
        )
        legacy_time = None if best_time else match_dict.get('time')
        team1_name = richer_team_name(
            details_dict.get('team1'),
            match_dict.get('team1'),
        )
        team2_name = richer_team_name(
            details_dict.get('team2'),
            match_dict.get('team2'),
        )
        list_status = normalize_match_status(
            match_dict.get('status'), MATCH_STATUS_UPCOMING
        )
        status = resolve_status_transition(list_status, details_dict.get('status'))

        if not db_match:
            db_match = Match(
                vlr_match_id=match_id_string,
                team1_name=team1_name,
                team2_name=team2_name,
                start_time=best_time,
                legacy_start_time=legacy_time,
                status=status
            )
            session.add(db_match)
        else:
            db_match.status = resolve_status_transition(db_match.status, status)
            if best_time:
                db_match.start_time = best_time
            elif not db_match.start_time and legacy_time and not db_match.legacy_start_time:
                db_match.legacy_start_time = legacy_time
            if should_replace_team_name(db_match.team1_name, team1_name):
                db_match.team1_name = team1_name
            if should_replace_team_name(db_match.team2_name, team2_name):
                db_match.team2_name = team2_name

        incoming_round_scores = (
            optional_score_int(match_dict.get('team1_round_score')),
            optional_score_int(match_dict.get('team2_round_score')),
        )
        if has_meaningful_score(*incoming_round_scores) or not has_meaningful_score(
            db_match.team1_round_score, db_match.team2_round_score
        ):
            db_match.team1_round_score = incoming_round_scores[0]
            db_match.team2_round_score = incoming_round_scores[1]

        current_status = normalize_match_status(
            db_match.status or status,
            MATCH_STATUS_UPCOMING,
        )
        db_match.status = current_status
        # 🔥 PRIORITY: Use card score (best for LIVE)
        if match_dict.get('team1_score') is not None and match_dict.get('team2_score') is not None:
            try:
                db_match.team1_series_score = int(match_dict['team1_score'])
                db_match.team2_series_score = int(match_dict['team2_score'])
            except (TypeError, ValueError) as exc:
                logger.warning("Ignoring invalid list-card series score: %s", exc)

        # 🔁 Fallback: use match page score
        elif details_dict.get('live_score'):
            try:
                db_match.team1_series_score = int(details_dict['live_score'].get('team1', 0))
                db_match.team2_series_score = int(details_dict['live_score'].get('team2', 0))
            except (TypeError, ValueError) as exc:
                logger.warning("Ignoring invalid detail-page series score: %s", exc)

        elif current_status == MATCH_STATUS_UPCOMING:
            db_match.team1_series_score = None
            db_match.team2_series_score = None

        if details_dict.get('map_vetoes'):
            db_match.map_vetoes_raw = json.dumps(details_dict['map_vetoes'])

        session.flush()

        games = details_dict.get('games') or []
        if not games and details_dict.get('player_stats'):
            games = [{
                'game_id': 'all',
                'map_number': 0,
                'map_name': 'Overall',
                'team1_round_score': None,
                'team2_round_score': None,
                'player_stats': details_dict['player_stats']
            }]

        if current_status == MATCH_STATUS_LIVE:
            live_map_score = latest_started_map_score(games)
            if live_map_score:
                db_match.team1_round_score = live_map_score[0]
                db_match.team2_round_score = live_map_score[1]

        authoritative_details = details_dict.get('stats_status') == 'available'
        seen_game_identifiers = set()
        for game_data in games:
            game_identifier = game_data.get('game_id') or "all"
            seen_game_identifiers.add(game_identifier)

            db_game = session.query(Game).filter_by(match_id=db_match.id, vlr_game_id=game_identifier).first()
            if not db_game and game_identifier == "all":
                db_game = session.query(Game).filter_by(match_id=db_match.id, map_name="Overall").first()

            map_name = "Overall" if game_identifier == "all" else game_data.get('map_name', "Map")
            if not db_game:
                db_game = Game(
                    match=db_match,
                    vlr_game_id=game_identifier,
                    map_name=map_name
                )
                session.add(db_game)

            db_game.vlr_game_id = game_identifier
            db_game.map_number = game_data.get('map_number')
            if (
                db_game.map_name in {"Overall", "Map", "TBD", "N/A"}
                or map_name not in {"Map", "TBD", "N/A"}
            ):
                db_game.map_name = map_name
            incoming_game_scores = (
                optional_score_int(game_data.get('team1_round_score')),
                optional_score_int(game_data.get('team2_round_score')),
            )
            if has_meaningful_score(*incoming_game_scores) or not has_meaningful_score(
                db_game.team1_round_score, db_game.team2_round_score
            ):
                db_game.team1_round_score = incoming_game_scores[0]
                db_game.team2_round_score = incoming_game_scores[1]
            session.flush()

            save_player_stats(
                session,
                db_game,
                game_data.get('player_stats', []),
                authoritative=authoritative_details,
            )

        if authoritative_details and seen_game_identifiers:
            stale_games = session.query(Game).filter(
                Game.match_id == db_match.id,
                Game.vlr_game_id.notin_(seen_game_identifiers),
            ).all()
            for stale_game in stale_games:
                session.delete(stale_game)

        derived_series_score = series_score_from_games(games)
        if (
            derived_series_score
            and current_status != MATCH_STATUS_LIVE
            and not has_meaningful_score(
                db_match.team1_series_score,
                db_match.team2_series_score,
            )
        ):
            db_match.team1_series_score = derived_series_score[0]
            db_match.team2_series_score = derived_series_score[1]

            if current_status == MATCH_STATUS_UPCOMING:
                db_match.status = MATCH_STATUS_FINISHED

        session.flush()
        database_id = db_match.id
        session.expire_all()
        db_match = session.get(Match, database_id)
        current_state = _match_persistence_state(db_match)
        action = (
            "inserted"
            if was_inserted
            else "updated"
            if current_state != prior_state
            else "unchanged"
        )
        session.commit()
        logger.info(
            "Saved %s vs %s (%s-%s)",
            db_match.team1_name,
            db_match.team2_name,
            db_match.team1_series_score,
            db_match.team2_series_score,
        )
        return PersistenceOutcome(action, match_id_string, database_id)

    except Exception as e:
        session.rollback()
        logger.error("Could not persist VLR match: %s", e)
        raise
    finally:
        session.close()


def save_player_stats(session, db_game, player_stats, authoritative=False):
    # 👤 Save players
    seen_player_identities = set()
    for p_data in player_stats:
        identity = (p_data['team'], p_data['player'])
        seen_player_identities.add(identity)
        db_player = session.query(PlayerStat).filter_by(
            game_id=db_game.id,
            player_name=p_data['player'],
            team_name=p_data['team']
        ).first()

        if not db_player:
            db_player = PlayerStat(
                game_id=db_game.id,
                player_name=p_data['player'],
                team_name=p_data['team']
            )
            session.add(db_player)

        db_player.team_name = p_data['team']
        incoming_role = p_data.get('role')
        if authoritative or incoming_role:
            db_player.role = incoming_role

        # None means VLR did not report the value. A partial page never erases
        # a known value; an authoritative page replaces it, including with None.
        def incoming_int(field):
            value = p_data.get(field)
            text = str(value).strip() if value is not None else ""
            return int(text) if text.lstrip('-').isdigit() else None

        def merge_value(incoming, current):
            return incoming if authoritative or incoming is not None else current

        def merge_numeric(field, current):
            return merge_value(incoming_int(field), current)

        db_player.acs = merge_numeric('acs', db_player.acs)

        try:
            incoming_kd = float(p_data['k_d']) if p_data.get('k_d') is not None else None
        except (TypeError, ValueError):
            incoming_kd = None
        db_player.kd_ratio = merge_value(incoming_kd, db_player.kd_ratio)

        db_player.adr = merge_numeric('adr', db_player.adr)
        db_player.kills = merge_numeric('kills', db_player.kills)
        db_player.deaths = merge_numeric('deaths', db_player.deaths)
        db_player.assists = merge_numeric('assists', db_player.assists)
        db_player.first_kills = merge_numeric('first_kills', db_player.first_kills)
        db_player.first_deaths = merge_numeric('first_deaths', db_player.first_deaths)

        incoming_plus_minus = p_data.get('plus_minus')
        if incoming_plus_minus is not None:
            incoming_plus_minus = str(incoming_plus_minus).strip() or None
        db_player.plus_minus = merge_value(incoming_plus_minus, db_player.plus_minus)
        db_player.kast = merge_value(p_data.get('kast') or None, db_player.kast)

    if authoritative and seen_player_identities:
        existing_stats = session.query(PlayerStat).filter(
            PlayerStat.game_id == db_game.id
        ).all()
        for existing_stat in existing_stats:
            if (existing_stat.team_name, existing_stat.player_name) not in seen_player_identities:
                session.delete(existing_stat)
