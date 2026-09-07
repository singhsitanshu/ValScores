"""Serialized orchestration for one complete VLR refresh operation."""

import threading

from . import vlreal
from .database_setup import Match
from .vlreal import (
    MATCH_STATUS_FINISHED,
    MATCH_STATUS_LIVE,
    MATCH_STATUS_UPCOMING,
    MatchListParseError,
    VlrScraper,
    is_placeholder_team,
    normalize_match_status,
    persist_match,
    status_rank,
)


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
        failures = []

        schedule = self._load_source(
            scraper,
            "schedule",
            scraper.get_matches,
            limit,
            failures,
        )
        results = self._load_source(
            scraper,
            "results",
            scraper.get_results,
            results_limit,
            failures,
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
                    failures.append({
                        "stage": "detail_warning",
                        "vlr_match_id": match_id,
                        "url": record["url"],
                        "error": warning,
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
        }

    def _load_source(self, scraper, source, loader, item_limit, failures):
        try:
            records = loader()
        except MatchListParseError as exc:
            failures.append(self._failure(f"{source}_parse", exc))
            return []
        except Exception as exc:
            failures.append(self._failure(f"{source}_fetch", exc))
            return []

        parse_failures = list(scraper.last_list_parse_failures)
        for failure in parse_failures:
            failures.append({
                "stage": "list_parse",
                "source": source,
                **failure,
            })
        return records[:item_limit]

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

            if status_rank(candidate.get("status")) >= status_rank(existing.get("status")):
                existing["status"] = normalize_match_status(
                    candidate.get("status"), MATCH_STATUS_UPCOMING
                )
            existing["is_live"] = existing["status"] == MATCH_STATUS_LIVE

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

        session = (self.session_factory or vlreal.Session)()
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
