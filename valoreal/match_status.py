"""Canonical match statuses and the transitions persistence may apply.

See docs/API-CONTRACT.md for the client-facing description of each status.
"""

MATCH_STATUS_UPCOMING = "upcoming"
MATCH_STATUS_LIVE = "live"
MATCH_STATUS_POSTPONED = "postponed"
MATCH_STATUS_FINISHED = "finished"
MATCH_STATUS_CANCELLED = "cancelled"
MATCH_STATUSES = frozenset({
    MATCH_STATUS_UPCOMING,
    MATCH_STATUS_LIVE,
    MATCH_STATUS_POSTPONED,
    MATCH_STATUS_FINISHED,
    MATCH_STATUS_CANCELLED,
})

# Finished and cancelled are terminal. A postponed match returns to upcoming
# when it is rescheduled, or may go straight to live/finished if a refresh
# missed the reschedule.
ALLOWED_STATUS_TRANSITIONS = {
    MATCH_STATUS_UPCOMING: frozenset({
        MATCH_STATUS_LIVE,
        MATCH_STATUS_POSTPONED,
        MATCH_STATUS_FINISHED,
        MATCH_STATUS_CANCELLED,
    }),
    MATCH_STATUS_POSTPONED: frozenset({
        MATCH_STATUS_UPCOMING,
        MATCH_STATUS_LIVE,
        MATCH_STATUS_FINISHED,
        MATCH_STATUS_CANCELLED,
    }),
    MATCH_STATUS_LIVE: frozenset({
        MATCH_STATUS_FINISHED,
        MATCH_STATUS_CANCELLED,
    }),
    MATCH_STATUS_FINISHED: frozenset(),
    MATCH_STATUS_CANCELLED: frozenset(),
}


def normalize_match_status(value, default=None):
    """Map VLR and legacy status labels onto the canonical status set."""
    normalized = str(value or "").strip().lower()
    if "postpone" in normalized:
        return MATCH_STATUS_POSTPONED
    if "cancel" in normalized:
        return MATCH_STATUS_CANCELLED
    if "live" in normalized or "in progress" in normalized:
        return MATCH_STATUS_LIVE
    if any(marker in normalized for marker in ("completed", "finished", "final")):
        return MATCH_STATUS_FINISHED
    if normalized in {"upcoming", "tbd", "scheduled", "pending"}:
        return MATCH_STATUS_UPCOMING
    return default


def resolve_status_transition(current, incoming):
    """Return the status to store when ``incoming`` is observed for ``current``.

    Unknown or disallowed transitions keep the current status, so stale pages
    cannot move a match backwards (for example finished -> live).
    """
    current_status = normalize_match_status(current, MATCH_STATUS_UPCOMING)
    incoming_status = normalize_match_status(incoming)
    if incoming_status is None or incoming_status == current_status:
        return current_status
    if incoming_status in ALLOWED_STATUS_TRANSITIONS[current_status]:
        return incoming_status
    return current_status


def status_rank(status):
    """Progress order used when merging duplicate records of one match."""
    normalized = normalize_match_status(status)
    if normalized in {MATCH_STATUS_FINISHED, MATCH_STATUS_CANCELLED}:
        return 2
    if normalized == MATCH_STATUS_LIVE:
        return 1
    return 0
