"""Canonical UTC timestamp parsing for the ValScores backend."""

from datetime import datetime, timezone
import re
from zoneinfo import ZoneInfo


UTC = timezone.utc
VLR_LIST_TIMEZONE = ZoneInfo("America/Chicago")

_MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}

_DATE_HEADING = re.compile(
    r"^[A-Za-z]+,\s+(?P<month>[A-Za-z]+)\s+(?P<day>\d{1,2}),\s+"
    r"(?P<year>\d{4})(?:\s+(?:Today|Yesterday))?$",
    re.IGNORECASE,
)
_CLOCK_TIME = re.compile(
    r"^(?P<hour>\d{1,2}):(?P<minute>\d{2})\s*(?P<period>AM|PM)$",
    re.IGNORECASE,
)


def format_utc_timestamp(value: datetime) -> str:
    """Return a timezone-aware datetime as second-precision ISO-8601 UTC."""
    if value.tzinfo is None:
        raise ValueError("UTC timestamps must be timezone-aware")
    return value.astimezone(UTC).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso_timestamp(value: str) -> datetime | None:
    normalized = value.strip()
    if not normalized:
        return None
    if normalized.endswith(("Z", "z")):
        normalized = f"{normalized[:-1]}+00:00"
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def normalize_explicit_utc_timestamp(value: str | datetime | None) -> str | None:
    """Normalize only timestamps that explicitly include a timezone."""
    if value is None:
        return None
    parsed = value if isinstance(value, datetime) else _parse_iso_timestamp(str(value))
    if parsed is None or parsed.tzinfo is None:
        return None
    return format_utc_timestamp(parsed)


def normalize_vlr_utc_timestamp(value: str | int | float | None) -> str | None:
    """Normalize VLR's UTC-labelled timestamp, including its naive text form."""
    if value is None:
        return None
    if isinstance(value, (int, float)) or str(value).strip().isdigit():
        try:
            return format_utc_timestamp(datetime.fromtimestamp(int(value), UTC))
        except (OverflowError, ValueError):
            return None

    parsed = _parse_iso_timestamp(str(value))
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return format_utc_timestamp(parsed)


def parse_vlr_schedule_timestamp(
    schedule_date: str | None,
    match_time: str | None,
    source_timezone=VLR_LIST_TIMEZONE,
) -> str | None:
    """Combine VLR's rendered heading and clock into a canonical UTC timestamp."""
    if not schedule_date or not match_time:
        return None

    date_match = _DATE_HEADING.fullmatch(schedule_date.strip())
    time_match = _CLOCK_TIME.fullmatch(match_time.strip())
    if not date_match or not time_match:
        return None

    month = _MONTHS.get(date_match.group("month").lower())
    if month is None:
        return None

    hour = int(time_match.group("hour"))
    minute = int(time_match.group("minute"))
    if hour not in range(1, 13) or minute not in range(60):
        return None

    if time_match.group("period").upper() == "AM":
        hour = 0 if hour == 12 else hour
    elif hour != 12:
        hour += 12

    try:
        local_value = datetime(
            int(date_match.group("year")),
            month,
            int(date_match.group("day")),
            hour,
            minute,
            tzinfo=source_timezone,
        )
    except ValueError:
        return None
    return format_utc_timestamp(local_value)


def choose_canonical_match_timestamp(
    exact_vlr_utc: str | int | float | None,
    scheduled_timestamp: str | None,
) -> str | None:
    """Prefer VLR's exact UTC timestamp over the normalized list fallback."""
    return (
        normalize_vlr_utc_timestamp(exact_vlr_utc)
        or normalize_explicit_utc_timestamp(scheduled_timestamp)
    )


def parse_utc_datetime(value: str | datetime | None) -> datetime | None:
    """Parse a canonical or explicitly zoned value as an aware UTC datetime."""
    normalized = normalize_explicit_utc_timestamp(value)
    if normalized is None:
        return None
    return datetime.fromisoformat(normalized.replace("Z", "+00:00"))
