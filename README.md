# ValScores

ValScores includes an iOS client and a local FastAPI backend. This document covers the minimal backend development setup.

## Prerequisites

- Git
- Python 3.12 or 3.13; Python 3.12 is the development baseline recorded in `.python-version`
- PostgreSQL 17 (the included Compose service is the supported development setup)

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

Start PostgreSQL and configure the backend connection:

```bash
docker compose up -d db
export DATABASE_URL='postgresql+psycopg://valscores:valscores@localhost:5432/valscores'
```

`DATABASE_URL` is required. Tests may use `TEST_DATABASE_URL` to override it with
a dedicated PostgreSQL database. Credentials are supplied through environment
configuration and are not embedded in Python source.

## Start the backend

```bash
python -m uvicorn valoreal.api:app --reload --host 127.0.0.1 --port 8000
```

The API is available at <http://127.0.0.1:8000>. FastAPI's interactive OpenAPI documentation is at <http://127.0.0.1:8000/docs>, and the raw schema is at <http://127.0.0.1:8000/openapi.json>.

Stop the development server with `Ctrl-C`.

## PostgreSQL database

PostgreSQL is the canonical development and runtime database. Starting the FastAPI
application creates the current SQLAlchemy schema when the configured database is
empty. You can initialize it explicitly without starting the server:

```bash
python -m valoreal.database_setup
```

Runtime startup never reads, copies, migrates, or deletes
`valoreal/valorant_stats.db`. The historical SQLite migration code remains only for
isolated compatibility tests and an explicit legacy migration entry point; SQLite
is not a supported runtime backend.

### Repository data policy

The database is mutable local state and is intentionally not tracked by Git. There
is no authoritative SQLite seed snapshot and the stale local `.db` file is not a
source of truth. Optional deterministic sample data belongs under
`tests/fixtures/sample/` in a reviewable text format such as JSON. Frozen scraper
inputs remain under `tests/fixtures/`.

## Match timestamp contract

- VLR's exact `data-utc-ts` value is preferred and normalized to ISO-8601 UTC.
- The unauthenticated VLR list page is parsed using its America/Chicago display timezone only as a fallback.
- `matches.start_time` is PostgreSQL `TIMESTAMP WITH TIME ZONE`; SQLAlchemy exposes
  an aware UTC `datetime` and the API emits values such as `2026-09-06T13:00:00Z`.
- Ambiguous legacy values are moved to `matches.legacy_start_time`; they are not guessed or returned as canonical timestamps.
- The timeline API returns `start_time` as an ISO-8601 UTC string or `null`.
- Swift decodes `start_time` into `Date` and uses the device's current `Calendar` and timezone for grouping and display.

## Client API contract

- `GET /api/matches/timeline` requires timezone-aware `start` and `end` query
  parameters. The interval is start-inclusive, end-exclusive, and limited to 31 days.
- `GET /api/matches/{match_id}/stats?game_id=all` reads only persisted data.
  Supplying a specific game ID selects that exact game or returns `404`.
- Both GET endpoints are read-only: they never scrape VLR or mutate PostgreSQL.
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
```

For fast feedback, the suite defaults to isolated SQLite databases:

```bash
PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s tests -p 'test_*.py' -v
```

For canonical persistence and API verification, point `TEST_DATABASE_URL` at a
disposable PostgreSQL database. Each database-backed test creates a unique schema,
so it does not truncate or drop existing schemas:

```bash
TEST_DATABASE_URL='postgresql+psycopg://valscores:valscores@localhost:5432/valscores' \
PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s tests -p 'test_*.py' -v
```

Both modes use frozen VLR HTML and require no upstream network access. The suite
covers list/detail parsing, persistence identity and rollback, constraints and
cascades, UTC timestamps, typed API contracts, refresh transitions/concurrency,
and representative partial failures. SQLite-only legacy migration tests remain to
document the historical data format; they are not part of runtime startup.

## iOS unit tests

The shared `valoreal` scheme includes the `ValScoresTests` XCTest target. Run it
with Xcode's Test action (`Command-U`) or from the repository root with an
installed simulator destination:

```bash
xcodebuild -project valoreal.xcodeproj -scheme valoreal -destination 'platform=iOS Simulator,name=iPhone 16e,OS=latest' test
```

These tests use an injected `URLProtocol`; neither VLR nor the Python backend
needs to be running. The earlier portable Swift regression executables remain
available as lightweight compiler checks:

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
