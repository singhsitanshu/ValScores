"""Serialized orchestration for one complete VLR refresh operation."""

import threading

from ..database import connection
from ..database.match_persistence import persist_match
from ..database.models import Match
from ..domain.match_status import (
    MATCH_STATUS_FINISHED,
    MATCH_STATUS_LIVE,
    MATCH_STATUS_UPCOMING,
    normalize_match_status,
    status_rank,
)
from ..domain.normalization import is_placeholder_team
from ..scraper import MatchListParseError, VlrScraper
from .values import public_vlr_match_id


_PROCESS_REFRESH_LOCK = threading.Lock()


class RefreshInProgressError(RuntimeError):
    """Raised when another process-local refresh already owns the mutation lock."""


class RefreshService:
    """Coordinate list ingestion, detail enrichment, and atomic match upserts."""

    def __init__(
        self,
        scraper_factory=VlrScraper,
        session_factory=None,
        persistence=persist_match,
        lock=None,
    ):
        self.scraper_factory = scraper_factory
        self.session_factory = session_factory
        self.persistence = persistence
        self.lock = lock or _PROCESS_REFRESH_LOCK

    def refresh(self, limit=50, details_limit=12, results_limit=100):
        if not self.lock.acquire(blocking=False):
            raise RefreshInProgressError("A match refresh is already in progress")

        try:
            return self._refresh(
                limit=max(0, limit),
                details_limit=max(0, details_limit),
                results_limit=max(0, results_limit),
            )
        finally:
            self.lock.release()

    def _refresh(self, limit, details_limit, results_limit):
        scraper = self.scraper_factory()
        # Failures: something could not be fetched, parsed or stored. Warnings:
        # data was stored, but VLR left some optional fields unreadable or empty.
        failures = []
        warnings = []

        schedule = self._load_source(
            scraper,
            "schedule",
            scraper.get_matches,
            limit,
            failures,
            warnings,
        )
        results = self._load_source(
            scraper,
            "results",
            scraper.get_results,
            results_limit,
            failures,
            warnings,
        )

        matches_examined = len(schedule) + len(results) + sum(
            1 for failure in failures if failure["stage"] == "list_parse"
        )
        records = self._merge_records(schedule + results)
        detail_targets = self._detail_targets(records, details_limit, failures)

        counters = {
            "inserted": 0,
            "updated": 0,
            "unchanged": 0,
            "details_refreshed": 0,
        }

        for record in records:
            match_id = record["vlr_match_id"]
            details = {}
            detail_loaded = False
            if match_id in detail_targets:
                try:
                    details = scraper.get_match_details(record["url"])
                    detail_loaded = True
                except Exception as exc:
                    failures.append(self._failure(
                        "detail_fetch",
                        exc,
                        vlr_match_id=match_id,
                        url=record["url"],
                    ))

            try:
                outcome = self.persistence(
                    record,
                    details,
                    session_factory=self.session_factory,
                )
            except Exception as exc:
                failures.append(self._failure(
                    "persistence",
                    exc,
                    vlr_match_id=match_id,
                    url=record["url"],
                ))
                continue

            if outcome.action not in {"inserted", "updated", "unchanged"}:
                failures.append({
                    "stage": "persistence",
                    "vlr_match_id": match_id,
                    "url": record["url"],
                    "error": f"Unsupported persistence outcome: {outcome.action!r}",
                })
                continue

            counters[outcome.action] += 1
            if detail_loaded:
                counters["details_refreshed"] += 1
                for warning in details.get("parse_warnings", []):
                    warnings.append({
                        "stage": "detail_warning",
                        "vlr_match_id": match_id,
                        "url": record["url"],
                        "message": warning,
                    })

        persisted_count = counters["inserted"] + counters["updated"] + counters["unchanged"]
        if failures and persisted_count == 0:
            operation_status = "failed"
        elif failures:
            operation_status = "partial"
        else:
            operation_status = "success"

        return {
            "status": operation_status,
            "matches_examined": matches_examined,
            **counters,
            "failure_count": len(failures),
            "failures": failures,
            "warning_count": len(warnings),
            "warnings": warnings,
        }

    def _load_source(self, scraper, source, loader, item_limit, failures, warnings):
        try:
            records = loader()
        except MatchListParseError as exc:
            failures.append(self._failure(f"{source}_parse", exc))
            return []
        except Exception as exc:
            failures.append(self._failure(f"{source}_fetch", exc))
            return []

        # A skipped card is a match that was not ingested, so it is a failure.
        for failure in scraper.last_list_parse_failures:
            failures.append({
                "stage": "list_parse",
                "source": source,
                **failure,
            })
        records = records[:item_limit]
        kept_ids = {record["vlr_match_id"] for record in records}
        for warning in scraper.last_list_parse_warnings:
            if warning.get("vlr_match_id") in kept_ids:
                warnings.append({"stage": "list_warning", "source": source, **warning})
        return records

    def _merge_records(self, records):
        merged_by_id = {}
        order = []
        for record in records:
            match_id = record["vlr_match_id"]
            if match_id not in merged_by_id:
                merged_by_id[match_id] = dict(record)
                order.append(match_id)
                continue

            existing = merged_by_id[match_id]
            candidate = dict(record)
            for team_key in ("team1", "team2"):
                if (
                    is_placeholder_team(existing.get(team_key))
                    and not is_placeholder_team(candidate.get(team_key))
                ):
                    existing[team_key] = candidate[team_key]

            for key in (
                "scheduled_time",
                "time",
                "team1_score",
                "team2_score",
                "team1_round_score",
                "team2_round_score",
                "url",
            ):
                if candidate.get(key) is not None:
                    existing[key] = candidate[key]

            candidate_status = normalize_match_status(candidate.get("status"))
            if candidate_status is not None and (
                existing.get("status") is None
                or status_rank(candidate_status) >= status_rank(existing.get("status"))
            ):
                existing["status"] = candidate_status
            existing["is_live"] = existing.get("status") == MATCH_STATUS_LIVE

        return [merged_by_id[match_id] for match_id in order]

    def _detail_targets(self, records, details_limit, failures):
        candidates = []
        for record in records:
            try:
                if self._needs_detail(record):
                    candidates.append(record)
            except Exception as exc:
                failures.append(self._failure(
                    "detail_planning",
                    exc,
                    vlr_match_id=record["vlr_match_id"],
                    url=record["url"],
                ))

        candidates.sort(key=self._detail_priority)
        return {
            record["vlr_match_id"]
            for record in candidates[:details_limit]
        }

    def _needs_detail(self, record):
        status = normalize_match_status(record.get("status"), MATCH_STATUS_UPCOMING)
        if status == MATCH_STATUS_LIVE:
            return True
        if is_placeholder_team(record.get("team1")) or is_placeholder_team(record.get("team2")):
            return True
        if status != MATCH_STATUS_FINISHED:
            return False

        session = (self.session_factory or connection.SessionLocal)()
        try:
            match_id = record["vlr_match_id"]
            existing = (
                session.query(Match)
                .filter(
                    (Match.vlr_match_id == match_id)
                    | (Match.vlr_match_id.like(f"{match_id}/%"))
                )
                .first()
            )
            if existing is None:
                return True
            if normalize_match_status(existing.status) != MATCH_STATUS_FINISHED:
                return True

            games = list(existing.games)
            if not games:
                return True
            return not any(game.player_stats for game in games)
        finally:
            session.close()

    def _detail_priority(self, record):
        status = normalize_match_status(record.get("status"), MATCH_STATUS_UPCOMING)
        if status == MATCH_STATUS_LIVE:
            return 0
        if status == MATCH_STATUS_FINISHED:
            return 1
        return 2

    def _failure(self, stage, exc, **context):
        return {
            "stage": stage,
            **context,
            "error": str(exc),
        }


def public_refresh_result(result):
    """Present a refresh result with slash-free upstream match IDs."""
    def public(entries):
        return [
            {**entry, "vlr_match_id": public_vlr_match_id(entry["vlr_match_id"])}
            if entry.get("vlr_match_id")
            else entry
            for entry in entries
        ]

    return {
        **result,
        "failures": public(result.get("failures", [])),
        "warnings": public(result.get("warnings", [])),
    }


if __name__ == "__main__":
    import json

    print(json.dumps(public_refresh_result(RefreshService().refresh()), indent=2))
