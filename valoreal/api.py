from fastapi import FastAPI, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import sessionmaker
from types import SimpleNamespace
from datetime import datetime, timezone
from .vlreal import (
    MATCH_STATUS_FINISHED,
    MATCH_STATUS_LIVE,
    MATCH_STATUS_UPCOMING,
    VlrScraper,
    normalize_match_status,
    save_to_database,
)
import time
import json
import re

from .database_setup import Match, Game, PlayerStat, engine as database_engine
from .time_contract import normalize_explicit_utc_timestamp, parse_utc_datetime

app = FastAPI()

engine = database_engine
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
STALE_TBD_REFRESH_INTERVAL_SECONDS = 300
_last_stale_tbd_refresh_at = None

def score_to_string(score):
    return "" if score is None else str(score)

def canonical_match_id(vlr_match_id):
    match = re.match(r"^/(\d+)", vlr_match_id or "")
    return match.group(1) if match else (vlr_match_id or "")

def is_placeholder_team(name):
    return not name or name.strip().upper() == "TBD"

def parse_match_start_time(value):
    return parse_utc_datetime(value)

def has_meaningful_score(team1_score, team2_score):
    return team1_score is not None and team2_score is not None and not (
        int(team1_score or 0) == 0 and int(team2_score or 0) == 0
    )

def better_timeline_match(existing, candidate):
    existing_status = normalize_match_status(existing.status)
    candidate_status = normalize_match_status(candidate.status)
    if (candidate_status == MATCH_STATUS_LIVE) != (existing_status == MATCH_STATUS_LIVE):
        return candidate_status == MATCH_STATUS_LIVE

    existing_score = has_meaningful_score(existing.team1_series_score, existing.team2_series_score)
    candidate_score = has_meaningful_score(candidate.team1_series_score, candidate.team2_series_score)
    if candidate_score != existing_score:
        return candidate_score

    existing_teams = int(not is_placeholder_team(existing.team1_name)) + int(not is_placeholder_team(existing.team2_name))
    candidate_teams = int(not is_placeholder_team(candidate.team1_name)) + int(not is_placeholder_team(candidate.team2_name))
    if candidate_teams != existing_teams:
        return candidate_teams > existing_teams

    return candidate.id > existing.id

def player_to_dict(player):
    return {
        "name": player.player_name,
        "team": player.team_name,
        "role": player.role or "",
        "acs": player.acs,
        "kd": player.kd_ratio,
        "adr": player.adr,
        "kills": player.kills or 0,
        "deaths": player.deaths or 0,
        "assists": player.assists or 0,
        "plus_minus": player.plus_minus or "0",
        "kast": player.kast or "0%",
        "first_kills": player.first_kills or 0,
        "first_deaths": player.first_deaths or 0
    }

def split_rosters(players):
    grouped = []
    seen_teams = []

    for player in players:
        if player.team_name not in seen_teams:
            seen_teams.append(player.team_name)
            grouped.append([])

        grouped[seen_teams.index(player.team_name)].append(player)

    return (
        grouped[0] if len(grouped) > 0 else [],
        grouped[1] if len(grouped) > 1 else []
    )

def game_to_dict(game):
    is_all_maps = (game.vlr_game_id or "") == "all"
    return {
        "game_id": game.vlr_game_id or str(game.id),
        "map_number": game.map_number or 0,
        "map_name": "All Maps" if is_all_maps else game.map_name,
        "team1_round_score": "" if is_all_maps else score_to_string(game.team1_round_score),
        "team2_round_score": "" if is_all_maps else score_to_string(game.team2_round_score)
    }

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

def games_for_match(session, match):
    games = session.query(Game).filter(Game.match_id == match.id).order_by(Game.map_number, Game.id).all()
    if games and any(game.vlr_game_id == "all" for game in games):
        return games

    overall = session.query(Game).filter(Game.match_id == match.id, Game.map_name == "Overall").first()
    if overall and len(games) == 1:
        return [overall]

    return games

def games_for_response(games):
    if not games:
        return []

    all_maps = SimpleNamespace(
        id=None,
        vlr_game_id="all",
        map_number=0,
        map_name="All Maps",
        team1_round_score=None,
        team2_round_score=None
    )

    has_all = any(game.vlr_game_id == "all" for game in games)
    if has_all:
        return games

    if len(games) == 1 and (games[0].map_name or "").lower() == "overall":
        return [all_maps]

    return [all_maps] + games

def find_game(games, game_id):
    return next(
        (
            candidate for candidate in games
            if (candidate.vlr_game_id or str(candidate.id)) == game_id
        ),
        None
    )

def parse_percent(value):
    try:
        return float(str(value or "0").replace("%", "").strip())
    except ValueError:
        return 0.0

def aggregate_player_stats(session, games):
    map_games = [game for game in games if game.vlr_game_id != "all"]
    if not map_games:
        return []

    players = (
        session.query(PlayerStat)
        .filter(PlayerStat.game_id.in_([game.id for game in map_games]))
        .order_by(PlayerStat.game_id, PlayerStat.id)
        .all()
    )

    aggregates = {}
    order = []
    for player in players:
        key = (player.team_name, player.player_name)
        if key not in aggregates:
            aggregates[key] = {
                "player_name": player.player_name,
                "team_name": player.team_name,
                "role": player.role,
                "acs_values": [],
                "adr_values": [],
                "kast_values": [],
                "kills": 0,
                "deaths": 0,
                "assists": 0,
                "first_kills": 0,
                "first_deaths": 0
            }
            order.append(key)

        aggregate = aggregates[key]
        aggregate["acs_values"].append(player.acs or 0)
        aggregate["adr_values"].append(player.adr or 0)
        aggregate["kast_values"].append(parse_percent(player.kast))
        aggregate["kills"] += player.kills or 0
        aggregate["deaths"] += player.deaths or 0
        aggregate["assists"] += player.assists or 0
        aggregate["first_kills"] += player.first_kills or 0
        aggregate["first_deaths"] += player.first_deaths or 0

    aggregated_players = []
    for key in order:
        aggregate = aggregates[key]
        kills = aggregate["kills"]
        deaths = aggregate["deaths"]
        plus_minus = kills - deaths
        acs_values = aggregate["acs_values"]
        adr_values = aggregate["adr_values"]
        kast_values = aggregate["kast_values"]

        aggregated_players.append(SimpleNamespace(
            player_name=aggregate["player_name"],
            team_name=aggregate["team_name"],
            role=aggregate["role"],
            acs=round(sum(acs_values) / len(acs_values)) if acs_values else 0,
            kd_ratio=round(kills / deaths, 2) if deaths else float(kills),
            adr=round(sum(adr_values) / len(adr_values)) if adr_values else 0,
            kills=kills,
            deaths=deaths,
            assists=aggregate["assists"],
            plus_minus=f"+{plus_minus}" if plus_minus > 0 else str(plus_minus),
            kast=f"{round(sum(kast_values) / len(kast_values))}%" if kast_values else "0%",
            first_kills=aggregate["first_kills"],
            first_deaths=aggregate["first_deaths"]
        ))

    return aggregated_players

def refresh_match_details(match):
    scraper = VlrScraper()
    match_url = f"{scraper.base_url}{match.vlr_match_id}"
    details = scraper.get_match_details(match_url)

    match_dict = {
        "team1": details.get("team1") or match.team1_name,
        "team2": details.get("team2") or match.team2_name,
        "time": match.legacy_start_time or "",
        "scheduled_time": match.start_time,
        "status": normalize_match_status(
            details.get("status") or match.status,
            MATCH_STATUS_UPCOMING,
        ),
        "is_live": normalize_match_status(match.status) == MATCH_STATUS_LIVE,
        "team1_score": score_to_string(match.team1_series_score),
        "team2_score": score_to_string(match.team2_series_score),
        "team1_round_score": match.team1_round_score or "0",
        "team2_round_score": match.team2_round_score or "0",
        "url": match_url
    }

    save_to_database(match_dict, details)

def try_refresh_match_details(match):
    try:
        refresh_match_details(match)
        return True
    except Exception as exc:
        print(f"Could not refresh details for match {match.id}: {exc}")
        return False

def refresh_stale_tbd_matches(limit=12, force=False):
    global _last_stale_tbd_refresh_at

    now = datetime.now(timezone.utc)
    if (
        not force
        and _last_stale_tbd_refresh_at
        and (now - _last_stale_tbd_refresh_at).total_seconds() < STALE_TBD_REFRESH_INTERVAL_SECONDS
    ):
        return 0

    session = SessionLocal()
    try:
        placeholder_matches = (
            session.query(Match)
            .filter((func.upper(Match.team1_name) == "TBD") | (func.upper(Match.team2_name) == "TBD"))
            .order_by(Match.start_time.desc(), Match.id.desc())
            .all()
        )
        stale_matches = []
        for match in placeholder_matches:
            start_time = parse_match_start_time(match.start_time)
            if start_time and start_time <= now:
                stale_matches.append(SimpleNamespace(
                    id=match.id,
                    vlr_match_id=match.vlr_match_id,
                    team1_name=match.team1_name,
                    team2_name=match.team2_name,
                    start_time=match.start_time,
                    legacy_start_time=match.legacy_start_time,
                    status=match.status,
                    team1_series_score=match.team1_series_score,
                    team2_series_score=match.team2_series_score,
                    team1_round_score=match.team1_round_score,
                    team2_round_score=match.team2_round_score
                ))
                if len(stale_matches) >= limit:
                    break
    finally:
        session.close()

    refreshed_count = 0
    for match in stale_matches:
        if try_refresh_match_details(match):
            refreshed_count += 1
            time.sleep(0.5)

    _last_stale_tbd_refresh_at = now
    return refreshed_count

def should_refresh_players(match, players):
    if not players:
        return True

    status = normalize_match_status(match.status)
    has_final_stats = status in {MATCH_STATUS_LIVE, MATCH_STATUS_FINISHED}
    has_empty_stat_rows = any(
        (player.acs or 0) == 0
        and (player.adr or 0) == 0
        and (player.kills or 0) == 0
        for player in players
    )
    needs_expanded_match_stats = all(
        (player.kills or 0) == 0
        and (player.deaths or 0) == 0
        and (player.assists or 0) == 0
        for player in players
    )

    return has_final_stats and (has_empty_stat_rows or needs_expanded_match_stats)

@app.get("/api/matches/timeline")
def get_timeline():
    """Powers the main Games Timeline view."""
    refresh_stale_tbd_matches()

    session = SessionLocal()
    try:
        rows = session.query(Match).order_by(Match.start_time).all()
        matches_by_vlr_id = {}
        for row in rows:
            key = canonical_match_id(row.vlr_match_id)
            existing = matches_by_vlr_id.get(key)
            if not existing or better_timeline_match(existing, row):
                matches_by_vlr_id[key] = row

        matches = sorted(
            matches_by_vlr_id.values(),
            key=lambda match: (
                parse_match_start_time(match.start_time) is None,
                parse_match_start_time(match.start_time) or datetime.max.replace(tzinfo=timezone.utc),
                match.id,
            ),
        )
        
        result = []
        for match in matches:
            status = normalize_match_status(match.status, MATCH_STATUS_UPCOMING)
            is_live = status == MATCH_STATUS_LIVE
            is_finished = status == MATCH_STATUS_FINISHED
            match_games = session.query(Game).filter(Game.match_id == match.id).all()
            derived_series_score = map_wins_from_games(match_games)
            if derived_series_score and not is_live:
                is_finished = True

            show_series_score = is_live or is_finished
            if not is_live and not is_finished:
                status = MATCH_STATUS_UPCOMING
            elif is_finished and not is_live:
                status = MATCH_STATUS_FINISHED

            team1_series_score = match.team1_series_score
            team2_series_score = match.team2_series_score
            if derived_series_score and (
                team1_series_score is None
                or team2_series_score is None
                or (team1_series_score == 0 and team2_series_score == 0)
            ):
                team1_series_score, team2_series_score = derived_series_score

            result.append({
                "id": match.id,
                "team1": match.team1_name,
                "team2": match.team2_name,
                "team1_score": score_to_string(team1_series_score) if show_series_score else "",
                "team2_score": score_to_string(team2_series_score) if show_series_score else "",
                "team1_round_score": match.team1_round_score,
                "team2_round_score": match.team2_round_score,
                "status": status,
                "start_time": normalize_explicit_utc_timestamp(match.start_time),
                "is_live": is_live,
                "is_finished": is_finished
            })
        return result
    finally:
        session.close()

@app.get("/api/matches/{match_id}/stats")
def get_match_stats(match_id: int, game_id: str = Query(default="all")):
    """Powers the 'Game', 'SEN', and 'PRX' tabs."""
    session = SessionLocal()
    try:
        match = session.query(Match).filter(Match.id == match_id).first()
        if not match:
            raise HTTPException(status_code=404, detail="Match not found")
            
        games = games_for_match(session, match)
        all_game = find_game(games, "all")
        game = find_game(games, game_id)
        if game_id == "all":
            game = all_game
        game = game or all_game or (games[0] if games else None)
        
        if not game:
            try_refresh_match_details(match)
            session.expire_all()
            match = session.query(Match).filter(Match.id == match_id).first()
            games = games_for_match(session, match)
            all_game = find_game(games, "all")
            game = find_game(games, game_id)
            if game_id == "all":
                game = all_game
            game = game or all_game or (games[0] if games else None)

        if game_id == "all" and not all_game:
            players = aggregate_player_stats(session, games)
        else:
            players = session.query(PlayerStat).filter(PlayerStat.game_id == game.id).order_by(PlayerStat.id).all() if game else []

        if should_refresh_players(match, players):
            try_refresh_match_details(match)
            session.expire_all()
            match = session.query(Match).filter(Match.id == match_id).first()
            games = games_for_match(session, match)
            all_game = find_game(games, "all")
            game = find_game(games, game_id)
            if game_id == "all":
                game = all_game
            game = game or all_game or (games[0] if games else None)
            if game_id == "all" and not all_game:
                players = aggregate_player_stats(session, games)
            else:
                players = session.query(PlayerStat).filter(PlayerStat.game_id == game.id).order_by(PlayerStat.id).all() if game else []

        team1_stats, team2_stats = split_rosters(players)
        selected_game_id = "all" if game_id == "all" else ((game.vlr_game_id or str(game.id)) if game else "all")

        return {
            "match_info": {
                "team1": match.team1_name,
                "team2": match.team2_name,
                "map_vetoes": json.loads(match.map_vetoes_raw) if match.map_vetoes_raw else [],
                "selected_game_id": selected_game_id,
                "maps": [game_to_dict(candidate) for candidate in games_for_response(games)]
            },
            "team1_roster": [player_to_dict(p) for p in team1_stats],
            "team2_roster": [player_to_dict(p) for p in team2_stats]
        }
    finally:
        session.close()

@app.get("/api/matches/refresh")
def force_refresh_matches(limit: int = 50, details_limit: int = 12, results_limit: int = 100):
    print("Forcing a manual scrape...")
    scraper = VlrScraper()
    matches = scraper.get_matches()
    match_list_failures = list(scraper.last_list_parse_failures)
    results = scraper.get_results()
    result_list_failures = list(scraper.last_list_parse_failures)

    saved_count = 0
    detail_failures = []
    selected_matches = matches[:limit]
    selected_results = results[:results_limit]
    for index, match in enumerate(selected_matches + selected_results):
        details = {}
        is_result = index >= len(selected_matches)
        has_series_score = bool(match.get('team1_score') and match.get('team2_score'))
        should_fetch_details = match.get('is_live') or index < details_limit or (is_result and not has_series_score)

        if should_fetch_details:
            try:
                details = scraper.get_match_details(match['url'])
                time.sleep(0.5) # Be nice to VLR to avoid rate limits.
            except Exception as exc:
                print(f"Could not fetch details for {match['url']}: {exc}")
                detail_failures.append({
                    "vlr_match_id": match.get("vlr_match_id"),
                    "url": match["url"],
                    "error": str(exc),
                })

        save_to_database(match, details)
        saved_count += 1

    tbd_refreshed_count = refresh_stale_tbd_matches(force=True)

    return {
        "message": "Database successfully updated!",
        "saved": saved_count,
        "tbd_refreshed": tbd_refreshed_count,
        "parse_failures": {
            "matches": match_list_failures,
            "results": result_list_failures,
            "details": detail_failures,
        },
    }
