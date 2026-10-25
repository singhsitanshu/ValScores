"""HTTP access to vlr.gg; the only scraper module that performs network I/O."""

import requests

from .errors import VlrUpstreamError


DEFAULT_HTTP_TIMEOUT = (5, 20)
DEFAULT_USER_AGENT = "ValScores/1.0 (+https://www.vlr.gg)"
VLR_BASE_URL = "https://www.vlr.gg"


class VlrHttpClient:
    def __init__(self, session=None, timeout=DEFAULT_HTTP_TIMEOUT, base_url=VLR_BASE_URL):
        self.headers = {
            'User-Agent': DEFAULT_USER_AGENT,
            'Accept': 'text/html,application/xhtml+xml',
        }
        self.base_url = base_url
        self.session = session or requests.Session()
        self.timeout = timeout

    def url_for(self, path):
        return f"{self.base_url}{path}"

    def fetch_html(self, url):
        try:
            response = self.session.get(
                url,
                headers=self.headers,
                timeout=self.timeout,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise VlrUpstreamError(f"Unable to fetch VLR page {url}: {exc}") from exc
        return response.text
