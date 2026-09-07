import requests
from bs4 import BeautifulSoup
import time
import json
import re
from sqlalchemy.orm import sessionmaker
from .database_setup import Match, Game, PlayerStat, engine as database_engine
from .time_contract import (
    choose_canonical_match_timestamp,
    normalize_vlr_utc_timestamp,
    parse_vlr_schedule_timestamp,
)


class MatchDetailParseError(RuntimeError):
    """Raised when a VLR detail page contains an incompatible stats structure."""


class VlrScraper:
    def __init__(self):
        self.headers = {
            'User-Agent': 'Mozilla/5.0'
        }
        self.base_url = "https://www.vlr.gg"

    def get_matches(self):
        return self._get_match_list("/matches")

    def get_results(self):
        return self._get_match_list("/matches/results", status_override="Finished")

    def _get_match_list(self, path, status_override=None):
        url = f"{self.base_url}{path}"
        response = requests.get(url, headers=self.headers, timeout=20)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')

        matches = []
        match_cards = self._match_cards_with_dates(soup)

        for card, schedule_date in match_cards:
            match_url = self.base_url + card['href']

            teams = card.find_all('div', class_='match-item-vs-team-name')
            if len(teams) < 2:
                continue

            # 🔥 LIVE detection using ml-status
            ml_status = card.find('div', class_='ml-status')
            is_live = ml_status and "LIVE" in ml_status.text.upper()
            
            team1_round = "0"
            team2_round = "0"

            if is_live:
                try:
                    match_page = requests.get(match_url, headers=self.headers, timeout=20)
                    match_soup = BeautifulSoup(match_page.text, 'html.parser')

                    score_container = match_soup.find('div', class_='match-header-vs-score')
                    if score_container:
                        score_text = score_container.get_text(" ", strip=True)
                        score_parts = [part for part in score_text.replace(":", " ").split() if part.isdigit()]
                        if len(score_parts) >= 2:
                            team1_round = score_parts[0]
                            team2_round = score_parts[1]
                except Exception as e:
                    print(f"Failed to fetch live round score for {match_url}: {e}")

            status_div = card.find('div', class_='match-item-status')
            status_text = status_div.text.strip() if status_div else "Upcoming"
            status = status_override or ("LIVE" if is_live else self._normalize_status(status_text))

            # 🕒 Raw time string
            match_time_str = card.find('div', class_='match-item-time').text.strip()

            # 🔥 SCORE extraction from card (correct location)
            score_divs = card.find_all('div', class_='match-item-vs-team-score')

            team1_score = None
            team2_score = None

            if len(score_divs) >= 2:
                try:
                    if len(score_divs) > 2 and not score_divs[1].text.strip().isdigit():
                        team1_score = score_divs[0].text.strip()
                        team2_score = score_divs[2].text.strip()
                    else:
                        team1_score = score_divs[0].text.strip()
                        team2_score = score_divs[1].text.strip()
                except:
                    pass

            scheduled_time = self._combine_date_and_time(schedule_date, match_time_str)

            matches.append({
                'team1': teams[0].text.strip(),
                'team2': teams[1].text.strip(),
                'time': match_time_str,
                'scheduled_time': scheduled_time,
                'status': status,
                'is_live': is_live,
                'team1_score': team1_score,
                'team2_score': team2_score,
                'team1_round_score': team1_round,  # Pass the round scores to dictionary
                'team2_round_score': team2_round,
                'url': match_url
            })

        return matches

    def _normalize_status(self, status):
        status_upper = status.upper() if status else ""

        if "LIVE" in status_upper:
            return "LIVE"

        if "COMPLETED" in status_upper or "FINISHED" in status_upper:
            return "Finished"

        return "Upcoming"

    def _match_cards_with_dates(self, soup):
        cards = []
        current_date = None
        main_column = soup.select_one("div.col.mod-1")

        if not main_column:
            return [(card, None) for card in soup.find_all('a', class_='match-item')]

        for child in main_column.children:
            if getattr(child, "name", None) != "div":
                continue

            classes = child.get("class", [])
            if "wf-label" in classes:
                current_date = child.get_text(" ", strip=True)
                continue

            if "wf-card" in classes:
                for card in child.find_all('a', class_='match-item', recursive=False):
                    cards.append((card, current_date))

        return cards

    def _combine_date_and_time(self, schedule_date, match_time):
        return parse_vlr_schedule_timestamp(schedule_date, match_time)

    def get_match_details(self, match_url):
        response = requests.get(match_url, headers=self.headers, timeout=20)
        response.raise_for_status()
        return self.parse_match_details(response.text)

    def parse_match_details(self, html):
        """Parse a frozen or fetched VLR match-detail page without doing I/O."""
        soup = BeautifulSoup(html, 'html.parser')

        match_data = {
            'map_vetoes': [],
            'live_score': {},
            'player_stats': [],
            'games': [],
            'exact_time': None,
            'team1': None,
            'team2': None,
            'status': None,
            'stats_status': 'unavailable',
            'parse_warnings': []
        }

        teams = self._extract_match_header_teams(soup)
        if len(teams) >= 2:
            match_data['team1'] = teams[0]
            match_data['team2'] = teams[1]

        status = self._extract_match_status(soup)
        if status:
            match_data['status'] = status

        # 🕒 Exact timestamp
        time_div = soup.find('div', class_='moment-tz-convert')
        if time_div and time_div.has_attr('data-utc-ts'):
            match_data['exact_time'] = normalize_vlr_utc_timestamp(time_div['data-utc-ts'])

        # 🗺️ Map vetoes
        veto_block = soup.find('div', class_='match-header-note')
        if veto_block:
            match_data['map_vetoes'] = self._extract_vetoes(veto_block)

        match_data['live_score'] = self._extract_series_score(soup)

        game_nav = self._extract_game_nav(soup)
        stats_root = soup.select_one('.vm-stats')
        stats_containers = soup.select('div.vm-stats-game[data-game-id]')
        parsed_player_count = 0
        saw_current_rows = False
        has_partial_stats = False

        if stats_root and not stats_containers and match_data['status'] in {'LIVE', 'Finished'}:
            raise MatchDetailParseError(
                "VLR stats root was found, but no vm-stats-game containers matched"
            )
        if stats_root and not stats_containers:
            match_data['parse_warnings'].append(
                "VLR stats root was found, but no vm-stats-game containers matched"
            )

        if not stats_root:
            match_data['parse_warnings'].append(
                "No VLR stats section is present; statistics may not be available for this match"
            )

        for stats_container in stats_containers:
            game_id = stats_container.get('data-game-id')
            nav_info = game_nav.get(game_id, {})
            header_info = self._extract_game_header(stats_container)
            map_name = nav_info.get('map_name') or header_info.get('map_name') or ("Overall" if game_id == "all" else "Map")
            player_stats, player_warnings, row_state = self._extract_player_stats(stats_container)
            if row_state == 'absent':
                player_warnings.append("no supported player-stat rows matched")
            elif row_state == 'pending' and match_data['status'] in {'LIVE', 'Finished'}:
                player_warnings.append("player-stat rows contain no populated statistics")
            parsed_player_count += len(player_stats)
            saw_current_rows = saw_current_rows or row_state != 'absent'
            has_partial_stats = has_partial_stats or bool(player_warnings)
            match_data['parse_warnings'].extend(
                f"{map_name}: {warning}" for warning in player_warnings
            )

            game_data = {
                'game_id': game_id,
                'map_number': nav_info.get('map_number'),
                'map_name': map_name,
                'team1_round_score': header_info.get('team1_round_score'),
                'team2_round_score': header_info.get('team2_round_score'),
                'player_stats': player_stats
            }
            match_data['games'].append(game_data)

            if game_id == "all":
                match_data['player_stats'] = game_data['player_stats']

        if parsed_player_count:
            match_data['stats_status'] = 'partial' if has_partial_stats else 'available'
        elif stats_containers and match_data['status'] in {'LIVE', 'Finished'}:
            if not saw_current_rows:
                raise MatchDetailParseError(
                    "VLR map containers were found, but no supported player-stat rows matched"
                )
            raise MatchDetailParseError(
                "VLR player-stat rows matched, but no populated statistics could be parsed"
            )

        return match_data

    def _extract_vetoes(self, veto_block):
        text = veto_block.get_text(" ", strip=True)
        return [part.strip() for part in re.split(r';|\n', text) if part.strip()]

    def _extract_series_score(self, soup):
        score_header = soup.select_one('.match-header-vs > .match-header-vs-score')
        if not score_header:
            return {}

        current_scores = score_header.select(
            '.match-header-vs-score-winner, .match-header-vs-score-loser'
        )
        if len(current_scores) >= 2:
            return {
                'team1': current_scores[0].get_text(" ", strip=True),
                'team2': current_scores[1].get_text(" ", strip=True)
            }

        legacy_scores = score_header.select('.js-spoiler')
        if len(legacy_scores) >= 2:
            return {
                'team1': legacy_scores[0].get_text(" ", strip=True),
                'team2': legacy_scores[1].get_text(" ", strip=True)
            }

        return {}

    def _extract_match_header_teams(self, soup):
        selectors = [
            '.match-header-link-name .wf-title-med',
            '.match-header-link-name',
            'a.match-header-link .wf-title-med'
        ]

        for selector in selectors:
            names = [
                node.get_text(" ", strip=True)
                for node in soup.select(selector)
                if node.get_text(" ", strip=True)
            ]
            if len(names) >= 2:
                return names[:2]

        return []

    def _extract_match_status(self, soup):
        notes = soup.select('.match-header-vs-note')
        if any('mod-upcoming' in note.get('class', []) for note in notes):
            return "Upcoming"

        status_text = " ".join(note.get_text(" ", strip=True) for note in notes)
        status_upper = status_text.upper()

        if "LIVE" in status_upper:
            return "LIVE"
        if "FINAL" in status_upper or "FINISHED" in status_upper or "COMPLETED" in status_upper:
            return "Finished"
        if "UPCOMING" in status_upper:
            return "Upcoming"

        return None

    def _extract_game_nav(self, soup):
        games = {}
        for item in soup.select('.vm-stats-gamesnav-item[data-game-id]'):
            game_id = item.get('data-game-id')
            if item.get('data-disabled') == "1":
                continue

            text = item.get_text(" ", strip=True)
            if game_id == "all":
                games[game_id] = {
                    'map_number': 0,
                    'map_name': "All Maps"
                }
                continue

            number_match = re.match(r'(\d+)\s+(.*)', text)
            games[game_id] = {
                'map_number': int(number_match.group(1)) if number_match else None,
                'map_name': number_match.group(2).strip() if number_match else text
            }
        return games

    def _extract_game_header(self, stats_container):
        header = stats_container.find('div', class_='vm-stats-game-header')
        if not header:
            return {}

        scores = [score.get_text(" ", strip=True) for score in header.find_all('div', class_='score')]
        map_div = header.find('div', class_='map')
        map_name = None
        if map_div:
            map_span = map_div.find('span')
            direct_text = map_span.find(string=True, recursive=False) if map_span else None
            map_name = direct_text.strip() if direct_text else map_div.get_text(" ", strip=True)

        return {
            'map_name': map_name,
            'team1_round_score': scores[0] if len(scores) > 0 else None,
            'team2_round_score': scores[1] if len(scores) > 1 else None
        }

    def _extract_player_stats(self, stats_container):
        current_rows = stats_container.select('.ovw-row:not(.mod-head)')
        if current_rows:
            return self._extract_current_player_stats(current_rows)

        legacy_stats = self._extract_legacy_player_stats(stats_container)
        if legacy_stats:
            return legacy_stats, [], 'parsed'

        return [], [], 'absent'

    def _extract_current_player_stats(self, rows):
        player_stats = []
        warnings = []
        pending_rows = 0
        required_stats = {
            'acs': 'acs',
            'kills': 'kills',
            'deaths': 'deaths',
            'assists': 'assists',
            'plus_minus': 'kd-diff',
            'kast': 'kast',
            'adr': 'adr',
            'first_kills': 'fb',
            'first_deaths': 'fd'
        }

        for row_number, row in enumerate(rows, start=1):
            player_tag = row.select_one('.ovw-player-name')
            team_tag = row.select_one('.ovw-player-tag')
            player_name = player_tag.get_text(" ", strip=True) if player_tag else ""
            team_name = team_tag.get_text(" ", strip=True) if team_tag else ""

            if not player_name:
                warnings.append(f"player row {row_number} has no player name")
                continue
            if not team_name:
                warnings.append(f"player {player_name} has no team abbreviation")
                continue

            raw_stats = {
                name: self._current_stat_text(row, data_col)
                for name, data_col in required_stats.items()
            }
            if not any(self._has_stat_value(value) for value in raw_stats.values()):
                pending_rows += 1
                continue

            missing = [
                name for name, value in raw_stats.items()
                if not self._has_stat_value(value)
            ]
            if missing:
                warnings.append(
                    f"player {player_name} is missing {', '.join(missing)}"
                )

            kills = self._numeric_text(raw_stats['kills'])
            deaths = self._numeric_text(raw_stats['deaths'])
            kd_ratio = "0.0"
            try:
                kd_ratio = str(round(int(kills) / int(deaths), 2)) if int(deaths) > 0 else kills
            except (TypeError, ValueError):
                warnings.append(f"player {player_name} has invalid kills/deaths values")

            player_stats.append({
                'player': player_name,
                'team': team_name,
                'acs': self._numeric_text(raw_stats['acs']),
                'k_d': kd_ratio,
                'adr': self._numeric_text(raw_stats['adr']),
                'kills': kills,
                'deaths': deaths,
                'assists': self._numeric_text(raw_stats['assists']),
                'plus_minus': self._signed_stat_text(raw_stats['plus_minus']),
                'kast': self._percent_text(raw_stats['kast']),
                'first_kills': self._numeric_text(raw_stats['first_kills']),
                'first_deaths': self._numeric_text(raw_stats['first_deaths'])
            })

        teams = {player['team'] for player in player_stats}
        if player_stats and len(teams) < 2:
            warnings.append("parsed player rows contain fewer than two teams")
        if pending_rows and player_stats:
            warnings.append(f"{pending_rows} player row(s) have no statistics yet")

        if player_stats:
            state = 'partial' if warnings else 'parsed'
        else:
            state = 'pending'
        return player_stats, warnings, state

    def _current_stat_text(self, row, data_col):
        node = row.select_one(f'[data-col="{data_col}"]')
        if not node:
            return None

        both = node.select_one('.side.mod-both')
        value = (both or node).get_text(" ", strip=True)
        return value or None

    def _has_stat_value(self, value):
        return bool(value and re.search(r'[-+]?\d', value))

    def _numeric_text(self, value):
        match = re.search(r'-?\d+', value or "")
        return match.group(0) if match else "0"

    def _signed_stat_text(self, value):
        match = re.search(r'[+-]?\d+', value or "")
        return match.group(0) if match else "0"

    def _percent_text(self, value):
        match = re.search(r'-?\d+(?:\.\d+)?%?', value or "")
        if not match:
            return "0%"
        parsed = match.group(0)
        return parsed if parsed.endswith('%') else f"{parsed}%"

    def _extract_legacy_player_stats(self, stats_container):
        player_stats = []
        rows = stats_container.find_all('tr')
        for row in rows[1:]:
            cols = row.find_all('td')
            if len(cols) <= 5:
                continue

            player_name_tag = cols[0].find('div', class_='text-of')
            if not player_name_tag:
                continue

            team_tag = cols[0].find('div', class_='ge-text-light')
            acs = self._stat_value(cols, 3)
            kills = self._stat_value(cols, 4)
            deaths = self._stat_value(cols, 5)
            assists = self._stat_value(cols, 6)
            plus_minus = self._stat_text(cols, 7)
            kast = self._stat_text(cols, 8)
            adr = self._stat_value(cols, 9)
            first_kills = self._stat_value(cols, 11)
            first_deaths = self._stat_value(cols, 12)

            kd_ratio = "0.0"
            try:
                kd_ratio = str(round(int(kills) / int(deaths), 2)) if int(deaths) > 0 else kills
            except (TypeError, ValueError):
                pass

            player_stats.append({
                'player': player_name_tag.text.strip(),
                'team': team_tag.text.strip() if team_tag else "",
                'acs': acs,
                'k_d': kd_ratio,
                'adr': adr,
                'kills': kills,
                'deaths': deaths,
                'assists': assists,
                'plus_minus': plus_minus,
                'kast': kast,
                'first_kills': first_kills,
                'first_deaths': first_deaths
            })

        return player_stats

    def _stat_value(self, cols, index):
        text = self._stat_text(cols, index)
        match = re.search(r'-?\d+', text)
        return match.group(0) if match else "0"

    def _stat_text(self, cols, index):
        if len(cols) <= index:
            return "0"

        stat = cols[index].find('span', class_='mod-both')
        return stat.get_text(" ", strip=True) if stat else cols[index].get_text(" ", strip=True)


# 🔌 DB setup
engine = database_engine
Session = sessionmaker(bind=engine)


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


def has_meaningful_score(team1_score, team2_score):
    return team1_score is not None and team2_score is not None and not (
        score_to_int(team1_score) == 0 and score_to_int(team2_score) == 0
    )


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


def status_rank(status):
    status_upper = (status or "").upper()
    if "FINISHED" in status_upper or "COMPLETED" in status_upper or "FINAL" in status_upper:
        return 2
    if "LIVE" in status_upper:
        return 1
    return 0


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
        primary.status = duplicate.status

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
    session.flush()
    return primary


def save_to_database(match_dict, details_dict):
    session = Session()
    try:
        match_id_string = canonical_match_id(match_dict['url'])
        if not match_id_string:
            raise ValueError("A VLR match ID is required")
        db_match = find_match_for_save(session, match_id_string)

        best_time = choose_canonical_match_timestamp(
            details_dict.get('exact_time'),
            match_dict.get('scheduled_time'),
        )
        legacy_time = None if best_time else match_dict.get('time')
        team1_name = details_dict.get('team1') or match_dict.get('team1')
        team2_name = details_dict.get('team2') or match_dict.get('team2')
        status = details_dict.get('status') or match_dict['status']

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
            if status_rank(status) >= status_rank(db_match.status):
                db_match.status = status
            if best_time:
                db_match.start_time = best_time
            elif not db_match.start_time and legacy_time and not db_match.legacy_start_time:
                db_match.legacy_start_time = legacy_time
            if should_replace_team_name(db_match.team1_name, team1_name):
                db_match.team1_name = team1_name
            if should_replace_team_name(db_match.team2_name, team2_name):
                db_match.team2_name = team2_name

        incoming_round_scores = (
            match_dict.get('team1_round_score'),
            match_dict.get('team2_round_score'),
        )
        if has_meaningful_score(*incoming_round_scores) or not has_meaningful_score(
            db_match.team1_round_score, db_match.team2_round_score
        ):
            db_match.team1_round_score = incoming_round_scores[0] or "0"
            db_match.team2_round_score = incoming_round_scores[1] or "0"

        status_upper = (db_match.status or status or '').upper()
        # 🔥 PRIORITY: Use card score (best for LIVE)
        if match_dict.get('team1_score') and match_dict.get('team2_score'):
            try:
                db_match.team1_series_score = int(match_dict['team1_score'])
                db_match.team2_series_score = int(match_dict['team2_score'])
            except:
                pass

        # 🔁 Fallback: use match page score
        elif details_dict.get('live_score'):
            try:
                db_match.team1_series_score = int(details_dict['live_score'].get('team1', 0))
                db_match.team2_series_score = int(details_dict['live_score'].get('team2', 0))
            except:
                pass

        elif "UPCOMING" in status_upper:
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

        if "LIVE" in status_upper:
            live_map_score = latest_started_map_score(games)
            if live_map_score:
                db_match.team1_round_score = live_map_score[0]
                db_match.team2_round_score = live_map_score[1]

        for game_data in games:
            game_identifier = game_data.get('game_id') or "all"

            db_game = session.query(Game).filter_by(match_id=db_match.id, vlr_game_id=game_identifier).first()
            if not db_game and game_identifier == "all":
                db_game = session.query(Game).filter_by(match_id=db_match.id, map_name="Overall").first()

            map_name = "Overall" if game_identifier == "all" else game_data.get('map_name', "Map")
            if not db_game:
                db_game = Game(
                    match_id=db_match.id,
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
                score_to_int(game_data.get('team1_round_score')),
                score_to_int(game_data.get('team2_round_score')),
            )
            if has_meaningful_score(*incoming_game_scores) or not has_meaningful_score(
                db_game.team1_round_score, db_game.team2_round_score
            ):
                db_game.team1_round_score = incoming_game_scores[0]
                db_game.team2_round_score = incoming_game_scores[1]
            session.flush()

            save_player_stats(session, db_game, game_data.get('player_stats', []))

        derived_series_score = series_score_from_games(games)
        if derived_series_score and "LIVE" not in status_upper:
            db_match.team1_series_score = derived_series_score[0]
            db_match.team2_series_score = derived_series_score[1]

            if "UPCOMING" in status_upper:
                db_match.status = "Finished"

        session.commit()
        print(f"✅ Saved: {db_match.team1_name} vs {db_match.team2_name} | {db_match.team1_series_score}-{db_match.team2_series_score}")
        return True

    except Exception as e:
        session.rollback()
        print(f"❌ Error: {e}")
        raise
    finally:
        session.close()


def score_to_int(score):
    try:
        return int(score)
    except (TypeError, ValueError):
        return 0


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


def save_player_stats(session, db_game, player_stats):
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
        db_player.role = p_data.get('role')
        db_player.acs = int(p_data['acs']) if p_data['acs'].isdigit() else 0

        try:
            db_player.kd_ratio = float(p_data.get('k_d', '0'))
        except:
            db_player.kd_ratio = 0.0

        db_player.adr = int(p_data.get('adr', '0')) if p_data.get('adr', '0').isdigit() else 0
        db_player.kills = int(p_data.get('kills', '0')) if p_data.get('kills', '0').lstrip('-').isdigit() else 0
        db_player.deaths = int(p_data.get('deaths', '0')) if p_data.get('deaths', '0').lstrip('-').isdigit() else 0
        db_player.assists = int(p_data.get('assists', '0')) if p_data.get('assists', '0').lstrip('-').isdigit() else 0
        db_player.plus_minus = p_data.get('plus_minus', "0")
        db_player.kast = p_data.get('kast', "0%")
        db_player.first_kills = int(p_data.get('first_kills', '0')) if p_data.get('first_kills', '0').lstrip('-').isdigit() else 0
        db_player.first_deaths = int(p_data.get('first_deaths', '0')) if p_data.get('first_deaths', '0').lstrip('-').isdigit() else 0

    if seen_player_identities:
        existing_stats = session.query(PlayerStat).filter(
            PlayerStat.game_id == db_game.id
        ).all()
        for existing_stat in existing_stats:
            if (existing_stat.team_name, existing_stat.player_name) not in seen_player_identities:
                session.delete(existing_stat)


if __name__ == "__main__":
    scraper = VlrScraper()
    matches = scraper.get_matches()

    for match in matches[:10]:  # grab more matches
        details = scraper.get_match_details(match['url'])
        save_to_database(match, details)
        time.sleep(1.5)
