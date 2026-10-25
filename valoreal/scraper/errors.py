"""Errors raised while fetching or parsing VLR pages."""


class VlrUpstreamError(RuntimeError):
    """Raised when VLR cannot be fetched or returns an unsuccessful response."""

    def __init__(self, message, url=None, status_code=None, attempts=None):
        super().__init__(message)
        self.url = url
        self.status_code = status_code
        self.attempts = attempts


class VlrErrorPageError(VlrUpstreamError):
    """VLR answered successfully but served an error or bot-check page."""


class MatchListParseError(RuntimeError):
    """Raised when a VLR list page cannot produce any trustworthy records."""


class MatchCardParseError(ValueError):
    """Raised when one VLR match card is missing required identity data."""


class MatchListParseWarning(UserWarning):
    """Reports a malformed card that was skipped while its neighbors were retained."""


class MatchDetailParseError(RuntimeError):
    """Raised when a VLR detail page contains an incompatible stats structure."""
