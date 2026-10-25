"""Parse VLR schedule and results list pages. Pure: no network or database access."""

import logging
import re
import warnings
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from ..domain.match_status import MATCH_STATUS_LIVE, normalize_match_status
from ..domain.time_contract import parse_vlr_schedule_timestamp
from .client import VLR_BASE_URL
from .errors import MatchCardParseError, MatchListParseError, MatchListParseWarning


logger = logging.getLogger(__name__)


class MatchListParser:
    def __init__(self, base_url=VLR_BASE_URL):
        self.base_url = base_url
        self.last_failures = ()

    def parse(self, html, status_override=None):
        """Parse a frozen or fetched VLR list page without performing I/O."""
        soup = BeautifulSoup(html, 'html.parser')
        matches = []
        match_cards = self._match_cards_with_dates(soup)
        if not match_cards:
            self.last_failures = ()
            raise MatchListParseError("VLR list page contains no match cards")

        failures = []
        for card_index, (card, schedule_date) in enumerate(match_cards, start=1):
            try:
                matches.append(
                    self._parse_match_card(card, schedule_date, status_override)
                )
            except MatchCardParseError as exc:
                href = card.get('href') or "<missing href>"
                failure = {
                    'card_index': card_index,
                    'href': href,
                    'error': str(exc),
                }
                failures.append(failure)
                message = f"Skipped malformed VLR match card {card_index} ({href}): {exc}"
                logger.warning(message)
                warnings.warn(message, MatchListParseWarning, stacklevel=2)

        self.last_failures = tuple(failures)
        if not matches:
            raise MatchListParseError(
                f"All {len(match_cards)} VLR match cards were malformed"
            )
        return matches

    def _parse_match_card(self, card, schedule_date, status_override=None):
        href = (card.get('href') or "").strip()
        match_id = self._canonical_id_from_href(href)
        if match_id is None:
            raise MatchCardParseError("missing or invalid VLR match href")

        team_nodes = card.select('.match-item-vs-team')
        if len(team_nodes) < 2:
            raise MatchCardParseError("expected two team containers")

        team_names = []
        team_scores = []
        for team_node in team_nodes[:2]:
            name_node = team_node.select_one('.match-item-vs-team-name')
            name = name_node.get_text(" ", strip=True) if name_node else ""
            if not name:
                raise MatchCardParseError("team name is missing")
            team_names.append(name)
            team_scores.append(
                self._optional_score(team_node.select_one('.match-item-vs-team-score'))
            )

        status_node = card.select_one('.ml-status, .match-item-status')
        status_text = status_node.get_text(" ", strip=True) if status_node else None
        status = normalize_match_status(status_override or status_text)
        if status is None:
            raise MatchCardParseError(
                f"missing or unsupported match status: {status_text!r}"
            )

        time_node = card.select_one('.match-item-time')
        match_time = time_node.get_text(" ", strip=True) if time_node else None
        match_time = match_time or None
        scheduled_time = self._combine_date_and_time(schedule_date, match_time)
        if match_time and match_time.upper() != "TBD" and scheduled_time is None:
            raise MatchCardParseError(
                f"could not parse schedule heading/time: {schedule_date!r} / {match_time!r}"
            )

        match_url = urljoin(f"{self.base_url}/", href)
        return {
            'vlr_match_id': match_id,
            'team1': team_names[0],
            'team2': team_names[1],
            'time': match_time,
            'scheduled_time': scheduled_time,
            'status': status,
            'is_live': status == MATCH_STATUS_LIVE,
            'team1_score': team_scores[0],
            'team2_score': team_scores[1],
            # Round scores are not present in VLR list cards. Detail ingestion
            # may populate them later without inventing a list-level zero.
            'team1_round_score': None,
            'team2_round_score': None,
            'url': match_url,
        }

    def _canonical_id_from_href(self, href):
        parsed_url = urlparse(urljoin(f"{self.base_url}/", href))
        if parsed_url.netloc != urlparse(self.base_url).netloc:
            return None
        path = parsed_url.path
        match = re.match(r"^/(\d+)(?:/|$)", path)
        return f"/{match.group(1)}" if match else None

    def _optional_score(self, score_node):
        if score_node is None:
            return None
        score = score_node.get_text(" ", strip=True)
        return score if re.fullmatch(r"\d+", score) else None

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
