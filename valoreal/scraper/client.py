"""HTTP access to vlr.gg; the only scraper module that performs network I/O.

Every request goes through ``VlrHttpClient.fetch_html``, which applies explicit
timeouts, reuses one ``requests.Session``, spaces requests apart, and retries
only failures that are likely to be temporary.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import logging
import time

import requests

from .errors import VlrUpstreamError


DEFAULT_HTTP_TIMEOUT = (5, 20)  # (connect, read) seconds
DEFAULT_USER_AGENT = "ValScores/1.0 (+https://github.com/singhsitanshu/ValScores)"
DEFAULT_MIN_INTERVAL = 1.0  # seconds between requests to vlr.gg
VLR_BASE_URL = "https://www.vlr.gg"

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RetryPolicy:
    """Bounded retries with exponential backoff.

    Attempt n (1-based) that fails transiently waits
    ``min(backoff_base * backoff_factor ** (n - 1), max_backoff)`` seconds, or the
    server's ``Retry-After`` when given. A ``Retry-After`` longer than
    ``max_retry_after`` fails immediately instead of blocking the refresh.
    """

    max_attempts: int = 3
    backoff_base: float = 1.0
    backoff_factor: float = 2.0
    max_backoff: float = 10.0
    max_retry_after: float = 60.0
    retry_statuses: frozenset = frozenset({429, 500, 502, 503, 504})

    def backoff(self, attempt):
        return min(self.backoff_base * self.backoff_factor ** (attempt - 1), self.max_backoff)


class RateLimiter:
    """Keeps at least ``min_interval`` seconds between consecutive requests."""

    def __init__(self, min_interval, clock=time.monotonic, sleep=time.sleep):
        self.min_interval = min_interval
        self.clock = clock
        self.sleep = sleep
        self._last_request = None

    def wait(self):
        if self._last_request is not None:
            remaining = self.min_interval - (self.clock() - self._last_request)
            if remaining > 0:
                self.sleep(remaining)
        self._last_request = self.clock()


def retry_after_seconds(response, now=None):
    """Seconds requested by a Retry-After header (delta or HTTP date), if any."""
    value = (getattr(response, "headers", None) or {}).get("Retry-After")
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        retry_at = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    return max(0.0, (retry_at - now).total_seconds())


class VlrHttpClient:
    def __init__(
        self,
        session=None,
        timeout=DEFAULT_HTTP_TIMEOUT,
        base_url=VLR_BASE_URL,
        retry_policy=RetryPolicy(),
        min_interval=DEFAULT_MIN_INTERVAL,
        clock=time.monotonic,
        sleep=time.sleep,
    ):
        self.headers = {
            'User-Agent': DEFAULT_USER_AGENT,
            'Accept': 'text/html,application/xhtml+xml',
        }
        self.base_url = base_url
        # One session per client keeps TCP/TLS connections alive across requests.
        self.session = session or requests.Session()
        self.timeout = timeout
        self.retry_policy = retry_policy
        self.rate_limiter = RateLimiter(min_interval, clock=clock, sleep=sleep)
        self.sleep = sleep

    def url_for(self, path):
        return f"{self.base_url}{path}"

    def fetch_html(self, url):
        """Return the body of a successful response or raise VlrUpstreamError."""
        policy = self.retry_policy
        for attempt in range(1, policy.max_attempts + 1):
            self.rate_limiter.wait()
            try:
                response = self.session.get(url, headers=self.headers, timeout=self.timeout)
            except (requests.Timeout, requests.ConnectionError) as exc:
                if attempt == policy.max_attempts:
                    raise VlrUpstreamError(
                        f"Unable to fetch VLR page {url} after {attempt} attempts: {exc}",
                        url=url,
                        attempts=attempt,
                    ) from exc
                self._wait_before_retry(url, attempt, policy.backoff(attempt), str(exc))
                continue
            except requests.RequestException as exc:
                raise VlrUpstreamError(
                    f"Unable to fetch VLR page {url}: {exc}", url=url, attempts=attempt
                ) from exc

            status = response.status_code
            if 200 <= status < 300:
                return response.text
            if status not in policy.retry_statuses or attempt == policy.max_attempts:
                raise VlrUpstreamError(
                    f"VLR returned HTTP {status} for {url} after {attempt} attempt(s)",
                    url=url,
                    status_code=status,
                    attempts=attempt,
                )

            delay = retry_after_seconds(response)
            if delay is not None and delay > policy.max_retry_after:
                raise VlrUpstreamError(
                    f"VLR returned HTTP {status} for {url} and asked to retry after "
                    f"{delay:.0f}s, longer than the {policy.max_retry_after:.0f}s limit",
                    url=url,
                    status_code=status,
                    attempts=attempt,
                )
            self._wait_before_retry(
                url, attempt, policy.backoff(attempt) if delay is None else delay, f"HTTP {status}"
            )
        raise AssertionError("unreachable")  # pragma: no cover

    def _wait_before_retry(self, url, attempt, delay, reason):
        logger.warning(
            "Retrying VLR request %s after %s (attempt %d); waiting %.1fs",
            url, reason, attempt, delay,
        )
        self.sleep(delay)
