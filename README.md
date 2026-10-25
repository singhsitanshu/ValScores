# ValScores

ValScores includes a SwiftUI iOS client and a local FastAPI backend backed by
PostgreSQL. This document takes a fresh checkout to a running backend, a running
app, and passing tests.

Known setup issues and the current state of every check are recorded in
[docs/OVERHAUL-01-baseline.md](docs/OVERHAUL-01-baseline.md).

## Prerequisites

- Git
- Python 3.12 or 3.13. Python 3.12 is the baseline recorded in `.python-version`;
  CI runs both.
- Docker Desktop (or another Docker Engine with Compose v2), **running**
- Xcode 26 or newer with an iOS Simulator runtime installed (Xcode > Settings >
  Components). The project uses Xcode 26 build settings and will not open in
  older versions.

`xcodebuild` must point at Xcode rather than the Command Line Tools. Check with
`xcode-select -p`; if it prints `/Library/Developer/CommandLineTools`, run:

```bash
sudo xcode-select -s /Applications/Xcode.app/Contents/Developer
```

Run all commands below from the repository root.

## Quick start

### 1. Clone and configure

```bash
git clone https://github.com/singhsitanshu/ValScores.git
cd ValScores
cp .env.example .env
```

`.env` is ignored by Git. The defaults match the local-only credentials in
`compose.yaml`; nothing in the repository is a real secret. Docker Compose reads
`.env` automatically for its port settings.

### 2. Start PostgreSQL

```bash
docker compose up -d --wait db
```

If port 5432 is already in use (for example by a local PostgreSQL install or
another container), set `VALSCORES_DB_PORT` in `.env` to a free port, update the
port in `DATABASE_URL` to match, and rerun the command.

### 3. Install the backend

Use whichever supported interpreter you have (`python3.12` or `python3.13`):

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[test]'
```

The editable install reads the pinned dependencies from `pyproject.toml`. No
separate requirements file or `PYTHONPATH` configuration is needed.

### 4. Start the backend

```bash
python -m uvicorn valoreal.api:app --reload --env-file .env --host 127.0.0.1 --port 8000
```

Startup creates the schema in an empty database. The API is at
<http://127.0.0.1:8000>, interactive OpenAPI docs at <http://127.0.0.1:8000/docs>,
and the raw schema at <http://127.0.0.1:8000/openapi.json>. Stop it with `Ctrl-C`.

A fresh database has no matches. To load current matches from VLR (this is the
only endpoint that contacts VLR):

```bash
curl -X POST 'http://127.0.0.1:8000/api/matches/refresh'
```

### 5. Launch the iOS app

Open `valoreal.xcodeproj` in Xcode, select the shared **valoreal** scheme and any
iPhone simulator, and press Run (`Command-R`). The simulator reaches the backend
at `http://127.0.0.1:8000` with no extra configuration. See
[iOS backend configuration](#ios-backend-configuration) for physical devices.

## Configuration

| Variable | Used by | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | backend | Required runtime PostgreSQL URL. |
| `TEST_DATABASE_URL` | backend tests | Optional disposable PostgreSQL URL; the database name must contain `test`. |
| `VALSCORES_DB_PORT` | Compose | Host port for the development database (default 5432). |
| `VALSCORES_TEST_DB_PORT` | Compose | Host port for the test database (default 5433). |
| `VALSCORES_API_BASE_URL` | iOS app | Backend URL; see below. Listed in `.env.example` for reference only. |

Uvicorn loads `.env` through `--env-file`. For other commands, export it into your
shell first:

```bash
set -a && source .env && set +a
```

For example, to initialize the schema without starting the server:

```bash
python -m valoreal.database_setup
```

## Tests

All suites are offline: scraper tests read frozen HTML from `tests/fixtures/`, and
the iOS tests use an injected `URLProtocol`. Neither VLR nor a running backend is
needed.

### Backend regression suite

Tests never use `DATABASE_URL`. The test helpers replace it before importing the
backend, so a development database configured in your shell or `.env` is never
opened.

Fast feedback with isolated, throwaway SQLite databases:

```bash
PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s tests -p 'test_*.py' -v
```

Canonical PostgreSQL verification against the disposable `test-db` service. It
stores data in tmpfs and is separate from the development `db` service:

```bash
docker compose --profile test up -d --wait test-db
TEST_DATABASE_URL='postgresql+psycopg://valscores:valscores@localhost:5433/valscores_test' \
PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s tests -p 'test_*.py' -v
```

To make PostgreSQL the default, uncomment `TEST_DATABASE_URL` in `.env`; tests
then fail with `Connection refused` whenever `test-db` is not running.

Each database-backed test creates its own schema and drops it on teardown. The
helpers refuse a `TEST_DATABASE_URL` whose database name does not contain `test`
or that equals `DATABASE_URL`. Stop the test database with
`docker compose --profile test down`.

The suite covers list/detail parsing, persistence identity and rollback,
constraints and cascades, UTC timestamps, typed API contracts, refresh
transitions/concurrency, and representative partial failures. SQLite-only legacy
migration tests document the historical data format and are not part of runtime
startup. One test deliberately triggers an `IntegrityError`, so a logged
`Could not persist VLR match ... NotNullViolation` line in passing output is
expected.

### iOS unit tests

The shared `valoreal` scheme builds the app and runs the `ValScoresTests` XCTest
target. Use Xcode's Test action (`Command-U`), or:

```bash
scripts/ios-test.sh
```

The script picks the first available iPhone simulator; set
`IOS_SIMULATOR="iPhone 16e"` to choose one. Extra arguments are passed to
`xcodebuild`. If you cannot change `xcode-select`, prefix the command with
`DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer`.

The earlier portable Swift regression executables remain available as
lightweight compiler checks:

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

### Continuous integration

`.github/workflows/ci.yml` runs on every pull request and on pushes to `main`:

- **Backend** (Ubuntu, Python 3.12 and 3.13): the regression suite against a
  per-job PostgreSQL 17 service container, then again in SQLite mode.
- **iOS** (macOS 26): the portable Swift checks, then `scripts/ios-test.sh`. The
  `.xcresult` bundle is uploaded when tests fail.

## PostgreSQL database

PostgreSQL is the canonical development and runtime database. Starting the FastAPI
application creates the current SQLAlchemy schema when the configured database is
empty.

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
python -m uvicorn valoreal.api:app --reload --env-file .env --host 0.0.0.0 --port 8000
```

Then supply the URL as a scheme environment variable or launch argument. The
`valoreal` scheme is shared and committed, so do not save a personal LAN address
in it: use Product > Scheme > Manage Schemes to duplicate it, leave the copy
unshared (it is stored under the ignored `xcuserdata/`), and set the value there.
The committed Info.plist contains the local-network permission required for this
V1 development setup. No view or data manager needs to be edited when the host
changes.
