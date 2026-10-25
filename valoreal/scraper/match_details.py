"""Parse VLR match-detail pages. Pure: no network or database access."""

import re

from bs4 import BeautifulSoup

from ..domain.match_status import (
    MATCH_STATUS_CANCELLED,
    MATCH_STATUS_FINISHED,
    MATCH_STATUS_LIVE,
    MATCH_STATUS_POSTPONED,
    MATCH_STATUS_UPCOMING,
)
from ..domain.time_contract import normalize_vlr_utc_timestamp
from .errors import MatchDetailParseError


class MatchDetailParser:
    def parse(self, html):
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

        if stats_root and not stats_containers and match_data['status'] in {MATCH_STATUS_LIVE, MATCH_STATUS_FINISHED}:
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
            elif row_state == 'pending' and match_data['status'] in {MATCH_STATUS_LIVE, MATCH_STATUS_FINISHED}:
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
        elif stats_containers and match_data['status'] in {MATCH_STATUS_LIVE, MATCH_STATUS_FINISHED}:
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
            return MATCH_STATUS_UPCOMING

        status_text = " ".join(note.get_text(" ", strip=True) for note in notes)
        status_upper = status_text.upper()

        if "POSTPONED" in status_upper:
            return MATCH_STATUS_POSTPONED
        if "CANCELLED" in status_upper or "CANCELED" in status_upper:
            return MATCH_STATUS_CANCELLED
        if "LIVE" in status_upper:
            return MATCH_STATUS_LIVE
        if "FINAL" in status_upper or "FINISHED" in status_upper or "COMPLETED" in status_upper:
            return MATCH_STATUS_FINISHED
        if "UPCOMING" in status_upper:
            return MATCH_STATUS_UPCOMING

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
            kd_ratio = self._kd_ratio_text(kills, deaths)

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

    # Missing or blank stat cells parse to None so an unavailable value is
    # never confused with a recorded zero.
    def _numeric_text(self, value):
        match = re.search(r'-?\d+', value or "")
        return match.group(0) if match else None

    def _signed_stat_text(self, value):
        match = re.search(r'[+-]?\d+', value or "")
        return match.group(0) if match else None

    def _percent_text(self, value):
        match = re.search(r'-?\d+(?:\.\d+)?%?', value or "")
        if not match:
            return None
        parsed = match.group(0)
        return parsed if parsed.endswith('%') else f"{parsed}%"

    def _kd_ratio_text(self, kills, deaths):
        if kills is None or deaths is None:
            return None
        if int(deaths) > 0:
            return str(round(int(kills) / int(deaths), 2))
        return kills

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

            kd_ratio = self._kd_ratio_text(kills, deaths)

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
        return self._numeric_text(self._stat_text(cols, index))

    def _stat_text(self, cols, index):
        if len(cols) <= index:
            return None

        stat = cols[index].find('span', class_='mod-both')
        text = stat.get_text(" ", strip=True) if stat else cols[index].get_text(" ", strip=True)
        return text or None
