"""Convert persisted column values into contract values; None means unknown."""

import re


def optional_int(value):
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def optional_float(value):
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def optional_signed_int(value):
    """Parse a stored plus/minus such as '+7' or '-2'; None when unavailable."""
    match = re.fullmatch(r"\s*([+-]?\d+)\s*", str(value)) if value is not None else None
    return int(match.group(1)) if match else None


def optional_percent(value):
    """Parse a stored percentage such as '78%' into 78.0; None when unavailable."""
    match = (
        re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*%?\s*", str(value))
        if value is not None
        else None
    )
    return float(match.group(1)) if match else None


def public_vlr_match_id(stored_id: str) -> str:
    """Strip the leading slash from the stored canonical VLR path ID."""
    return (stored_id or "").lstrip("/") or stored_id
