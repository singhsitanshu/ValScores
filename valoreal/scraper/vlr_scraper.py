"""Facade combining the VLR HTTP client with the list and detail parsers."""

from ..domain.match_status import MATCH_STATUS_FINISHED
from .client import DEFAULT_HTTP_TIMEOUT, VlrHttpClient
from .match_details import MatchDetailParser
from .match_list import MatchListParser


class VlrScraper:
    def __init__(self, session=None, timeout=DEFAULT_HTTP_TIMEOUT):
        self.client = VlrHttpClient(session=session, timeout=timeout)
        self.list_parser = MatchListParser(base_url=self.client.base_url)
        self.detail_parser = MatchDetailParser()

    @property
    def last_list_parse_failures(self):
        """Malformed cards skipped by the most recent list parse."""
        return self.list_parser.last_failures

    def get_matches(self):
        return self._get_match_list("/matches")

    def get_results(self):
        return self._get_match_list(
            "/matches/results",
            status_override=MATCH_STATUS_FINISHED,
        )

    def get_match_details(self, match_url):
        return self.parse_match_details(self.client.fetch_html(match_url))

    def parse_match_list(self, html, status_override=None):
        """Parse a frozen or fetched VLR list page without performing I/O."""
        return self.list_parser.parse(html, status_override=status_override)

    def parse_match_details(self, html):
        """Parse a frozen or fetched VLR match-detail page without doing I/O."""
        return self.detail_parser.parse(html)

    def _get_match_list(self, path, status_override=None):
        html = self.client.fetch_html(self.client.url_for(path))
        return self.parse_match_list(html, status_override=status_override)
