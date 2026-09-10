# VS-012 backend regression-suite coverage

The suite is intentionally offline. Scraper tests read HTML from `tests/fixtures`,
HTTP tests use an injected fake session, persistence tests use temporary SQLite
files, and API tests use an isolated in-memory SQLite database.

| Area | Regression coverage |
| --- | --- |
| Match lists | Schedule, results, live, completed, TBD teams, full and abbreviated month names, malformed cards |
| Match details | Completed and live pages, pending stats, map names and scores, vetoes, exact UTC time, current `ovw-row` / `data-col` players, malformed markup |
| Network failures | Timeout, 404, 429, 500, malformed fetched HTML |
| Persistence | Idempotent match/game/player upserts, lifecycle updates, logical uniqueness, canonical duplicate merge, transaction rollback, authoritative stale-child deletion, partial-data preservation, repeatable migration |
| API | Typed response schemas, invalid match/map errors, bounded timeline ranges, explicit nullable scores, side-effect-free reads, partial refresh results, serialized refresh locking |

Run the complete backend safety net from the repository root:

```bash
python -m pip install -e '.[test]'
PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s tests -p 'test_*.py' -v
```

No test in this command may make a request to VLR. New VLR markup examples should
be committed as minimal frozen fixtures and parsed through the parser's pure
`parse_match_list` or `parse_match_details` entry points.
