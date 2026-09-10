# ValScores

ValScores includes an iOS client and a local FastAPI backend. This document covers the minimal backend development setup.

## Prerequisites

- Git
- Python 3.12 or 3.13; Python 3.12 is the development baseline recorded in `.python-version`

Run all commands below from the repository root.

## Backend setup

```bash
git clone https://github.com/singhsitanshu/ValScores.git
cd ValScores
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
```

The editable install reads the pinned runtime dependencies from `pyproject.toml`. No separate requirements file or manual `PYTHONPATH` configuration is needed.

## Start the backend

```bash
python -m uvicorn valoreal.api:app --reload --host 127.0.0.1 --port 8000
```

The API is available at <http://127.0.0.1:8000>. FastAPI's interactive OpenAPI documentation is at <http://127.0.0.1:8000/docs>, and the raw schema is at <http://127.0.0.1:8000/openapi.json>.

Stop the development server with `Ctrl-C`.

## SQLite database

Importing the backend creates any missing tables and applies the application's existing lightweight column initialization automatically. The SQLite database is always read from and created at:

```text
valoreal/valorant_stats.db
```

No manual database command or Python source edit is required for a clean checkout.
Automated tests can isolate database state by setting `VALSCORES_DATABASE_PATH` to
an alternate SQLite file.

Schema changes use ordered, transactional migrations recorded in SQLite's
`PRAGMA user_version`. Startup applies each pending version once. Version 2
canonicalizes legacy match IDs, preserves and merges duplicate data, and enforces
logical uniqueness plus cascading foreign keys. SQLite foreign-key enforcement is
enabled for every application connection.

## Match timestamp contract

- VLR's exact `data-utc-ts` value is preferred and normalized to ISO-8601 UTC.
- The unauthenticated VLR list page is parsed using its America/Chicago display timezone only as a fallback.
- `matches.start_time` stores canonical values such as `2026-09-06T13:00:00Z`.
- Ambiguous legacy values are moved to `matches.legacy_start_time`; they are not guessed or returned as canonical timestamps.
- The timeline API returns `start_time` as an ISO-8601 UTC string or `null`.
- Swift decodes `start_time` into `Date` and uses the device's current `Calendar` and timezone for grouping and display.

## Client API contract

- `GET /api/matches/timeline` requires timezone-aware `start` and `end` query
  parameters. The interval is start-inclusive, end-exclusive, and limited to 31 days.
- `GET /api/matches/{match_id}/stats?game_id=all` reads only persisted data.
  Supplying a specific game ID selects that exact game or returns `404`.
- Both GET endpoints are read-only: they never scrape VLR or mutate SQLite.
- `POST /api/matches/refresh` is the only endpoint that fetches and persists
  external match data. Its `limit`, `details_limit`, and `results_limit` query
  parameters are bounded and documented in OpenAPI.
- Errors use the stable shape `{"error":{"code":"...","message":"..."}}`.

Timeline scores and map round scores are JSON integers or `null`. Player-stat
numeric fields always contain a number; unavailable values are serialized as zero.

## iOS backend configuration

All app requests go through `APIClient`. Its base URL is resolved once using the
first non-empty value from:

1. the `VALSCORES_API_BASE_URL` Xcode scheme environment variable;
2. the `VALSCORES_API_BASE_URL` user default (which can be supplied as an Xcode
   launch argument: `-VALSCORES_API_BASE_URL http://192.168.1.20:8000`);
3. the `VALSCORES_API_BASE_URL` value in `valoreal/Info.plist`;
4. the simulator default, `http://127.0.0.1:8000`.

For the iOS Simulator, start the backend with the documented localhost command.
For a physical iPhone, put the Mac and phone on the same LAN, replace the sample
address below with the Mac's LAN IP, and start Uvicorn on all interfaces:

```bash
python -m uvicorn valoreal.api:app --reload --host 0.0.0.0 --port 8000
```

Then set the scheme environment variable or launch argument described above. The
committed Info.plist contains the local-network permission required for this V1
development setup. No view or data manager needs to be edited when the host changes.

## Backend regression suite

```bash
python -m pip install -e '.[test]'
PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s tests -p 'test_*.py' -v
```

The backend suite uses frozen VLR HTML fixtures and isolated temporary or in-memory
SQLite databases. It does not require VLR or any other network service to be online.
It covers list and detail parsing, persistence and migrations, typed API contracts,
refresh concurrency, and representative upstream failures.

## iOS unit tests

```bash
swiftc -parse-as-library valoreal/MatchTimeContract.swift tests/ValScoresTimeContractTests/MatchTimeContractTests.swift -o /tmp/valscores-time-contract-tests
/tmp/valscores-time-contract-tests
swiftc -parse-as-library valoreal/MatchTimeContract.swift valoreal/APIModels.swift valoreal/APIClient.swift tests/ValScoresAPIClientTests/APIClientTests.swift -o /tmp/valscores-api-client-tests
/tmp/valscores-api-client-tests
swiftc -parse-as-library valoreal/MatchTimeContract.swift valoreal/APIModels.swift valoreal/APIClient.swift valoreal/VLRDataManager.swift tests/ValScoresTimelineStateTests/TimelineStateTests.swift -o /tmp/valscores-timeline-state-tests
/tmp/valscores-timeline-state-tests
swiftc -parse-as-library valoreal/MatchTimeContract.swift valoreal/APIModels.swift valoreal/APIClient.swift valoreal/MatchDetailState.swift tests/ValScoresMatchDetailTests/MatchDetailStateTests.swift -o /tmp/valscores-match-detail-tests
/tmp/valscores-match-detail-tests
```
