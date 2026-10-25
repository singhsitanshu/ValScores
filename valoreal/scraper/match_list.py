"""Parse VLR schedule and results list pages. Pure: no network or database access."""

import logging
import re
import warnings
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from ..domain.match_status import (
    MATCH_STATUS_LIVE,
    MATCH_STATUS_UPCOMING,
    normalize_match_status,
)
from ..domain.time_contract import parse_vlr_schedule_timestamp
from .client import VLR_BASE_URL
from .errors import MatchCardParseError, MatchListParseError, MatchListParseWarning
from .page_checks import raise_if_error_page


logger = logging.getLogger(__name__)


class MatchListParser:
    """Parses one list page into match records.

    After each ``parse``, ``last_failures`` lists cards that were skipped because
    required identity data was missing, and ``last_warnings`` lists cards that
    were kept although an optional field could not be read. Both entries carry
    the page ``url``, ``card_index`` and ``href`` for context.
    """

    def __init__(self, base_url=VLR_BASE_URL):
        self.base_url = base_url
        self.last_failures = ()
        self.last_warnings = ()

    def parse(self, html, status_override=None, source_url=None):
        """Parse a frozen or fetched VLR list page without performing I/O.

        Returns [] only for a recognized page that lists no matches. Error pages
        raise VlrErrorPageError; unrecognized layouts raise MatchListParseError.
        """
        self.last_failures = ()
        self.last_warnings = ()
        soup = BeautifulSoup(html, 'html.parser')
        raise_if_error_page(soup, "match list", source_url)

        main_column = soup.select_one("div.col.mod-1")
        if main_column is None:
            raise MatchListParseError(
                "Unrecognized VLR list page: the div.col.mod-1 match column is missing"
            )
        match_cards = self._match_cards_with_dates(main_column)
        if not match_cards:
            if any(self._canonical_id_from_href(link.get('href') or "")
                   for link in main_column.find_all('a')):
                raise MatchListParseError(
                    "Unrecognized VLR list page: match links are present but none "
                    "use the a.match-item card markup"
                )
            return []

        matches = []
        failures = []
        card_warnings = []
        for card_index, (card, schedule_date) in enumerate(match_cards, start=1):
            href = card.get('href') or "<missing href>"
            context = {'url': source_url, 'card_index': card_index, 'href': href}
            try:
                record, problems = self._parse_match_card(card, schedule_date, status_override)
            except MatchCardParseError as exc:
                failures.append({**context, 'error': str(exc)})
                message = f"Skipped malformed VLR match card {card_index} ({href}): {exc}"
                logger.warning(message)
                warnings.warn(message, MatchListParseWarning, stacklevel=2)
                continue
            matches.append(record)
            for field, message in problems:
                card_warnings.append({
                    **context,
                    'vlr_match_id': record['vlr_match_id'],
                    'field': field,
                    'message': message,
                })
                logger.info("VLR card %d (%s): %s", card_index, href, message)

        self.last_failures = tuple(failures)
        self.last_warnings = tuple(card_warnings)
        if not matches:
            raise MatchListParseError(
                f"All {len(match_cards)} VLR match cards were malformed"
            )
        return matches

    def _parse_match_card(self, card, schedule_date, status_override=None):
        """Return (record, [(field, message), ...]) or raise MatchCardParseError.

        Identity data (match link, both team names) is required. Status, time and
        scores are optional: when unreadable the record is kept with a warning.
        """
        problems = []
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
            status = MATCH_STATUS_UPCOMING
            problems.append((
                "status",
                f"missing or unsupported status {status_text!r}; recorded as upcoming",
            ))

        time_node = card.select_one('.match-item-time')
        match_time = time_node.get_text(" ", strip=True) if time_node else None
        match_time = match_time or None
        scheduled_time = self._combine_date_and_time(schedule_date, match_time)
        if match_time and match_time.upper() != "TBD" and scheduled_time is None:
            problems.append((
                "scheduled_time",
                f"could not parse schedule heading/time {schedule_date!r} / {match_time!r}",
            ))

        match_url = urljoin(f"{self.base_url}/", href)
        record = {
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
        return record, problems

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
        return int(score) if re.fullmatch(r"\d+", score) else None

    def _match_cards_with_dates(self, main_column):
        cards = []
        current_date = None
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
