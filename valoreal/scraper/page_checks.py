"""Recognize error and bot-check pages that VLR or its CDN serve with HTTP 200."""

from .errors import VlrErrorPageError


ERROR_TITLE_MARKERS = (
    "just a moment",
    "attention required",
    "access denied",
    "too many requests",
    "bad gateway",
    "service unavailable",
    "gateway timeout",
    "maintenance",
)
ERROR_ELEMENT_SELECTORS = (
    "#cf-error-details",
    "#challenge-form",
    "#challenge-running",
    ".cf-browser-verification",
)


def raise_if_error_page(soup, page_kind, source_url=None):
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    lowered = title.lower()
    if any(marker in lowered for marker in ERROR_TITLE_MARKERS) or any(
        soup.select_one(selector) for selector in ERROR_ELEMENT_SELECTORS
    ):
        raise VlrErrorPageError(
            f"VLR served an error or bot-check page instead of the {page_kind}"
            f" (title: {title or 'none'!r})",
            url=source_url,
        )
