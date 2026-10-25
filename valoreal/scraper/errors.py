"""Errors raised while fetching or parsing VLR pages."""


class VlrUpstreamError(RuntimeError):
    """Raised when VLR cannot be fetched or returns an unsuccessful response."""


class MatchListParseError(RuntimeError):
    """Raised when a VLR list page cannot produce any trustworthy records."""


class MatchCardParseError(ValueError):
    """Raised when one VLR match card is missing required identity data."""


class MatchListParseWarning(UserWarning):
    """Reports a malformed card that was skipped while its neighbors were retained."""


class MatchDetailParseError(RuntimeError):
    """Raised when a VLR detail page contains an incompatible stats structure."""
