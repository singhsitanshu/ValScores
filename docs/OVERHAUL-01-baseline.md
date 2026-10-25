# Overhaul 01: development baseline

Recorded 2026-10-25 on macOS 26.6.2 (Apple silicon), Xcode 26.0.1, Docker 29.7.2,
Compose 5.3.1, Python 3.13. The baseline is the `main` branch at `6c53738`, before
any overhaul changes.

## Check results

| Check | Command | Before | After |
| --- | --- | --- | --- |
| Backend, SQLite mode | `python -m unittest discover -s tests -p 'test_*.py'` | 66 passed | 66 passed |
| Backend, PostgreSQL 17 | same, with `TEST_DATABASE_URL` set | 66 passed, 30 schemas leaked | 66 passed, 0 schemas left |
| iOS XCTest (`valoreal` scheme) | `scripts/ios-test.sh` | 13 passed | 13 passed |
| Portable Swift checks | the four `swiftc` commands in the README | 5 + 5 + 6 + 7 passed | unchanged |
| Fresh clone → backend → app | README quick start | see setup problems | backend serves `/api/matches/timeline`, a bounded refresh inserts 20 matches, the app renders them in the iPhone 16e simulator |

No existing test was failing, skipped, or removed. The shared `valoreal` scheme
already builds `ValScores.app` and lists `ValScoresTests` as its only testable,
with `VALSCORES_XCTEST=1` set for the test action.

## Setup and infrastructure problems (fixed in this ticket)

### S1. Tests could bind to the development database

Reproduce on `6c53738`: follow the old README (`export DATABASE_URL=...valscores`),
then run the regression suite without `TEST_DATABASE_URL`. `tests/database_support.py`
and the two parser test modules used `os.environ.setdefault("DATABASE_URL", ...)`, so
the exported development URL was kept and `valoreal.database_setup.engine`,
`valoreal.api.SessionLocal`, and `valoreal.vlreal.Session` all pointed at the
development database. Current tests replace these session factories before use, so
no write was observed, but any test that reached the module-level engine (for
example by entering the `TestClient` lifespan) would have created tables in, or
written to, the development database.

Fix: `database_support` now always overwrites `DATABASE_URL` with the test URL (or
in-memory SQLite) before any backend import, and the parser tests import it first.
Verified by running both modes with `DATABASE_URL` pointing at an unreachable host.

### S2. The documented PostgreSQL test URL was the development database

The old README and `docs/VS-012-regression-suite.md` set `TEST_DATABASE_URL` to
`.../valscores`, the same database as `DATABASE_URL`. Each test created a
`valscores_test_<uuid>` schema and never dropped it, so every run left 30 schemas
in the development database.

Fix: a `test-db` Compose service (profile `test`, port 5433, tmpfs storage,
database `valscores_test`). Test helpers drop each schema on teardown and refuse a
`TEST_DATABASE_URL` whose database name lacks `test` or that equals `DATABASE_URL`.

### S3. README assumed a `python3.12` binary

`pyproject.toml` accepts 3.12 and 3.13, but the README only showed
`python3.12 -m venv`, which fails on machines with 3.13 alone (as on the machine
used for this baseline). The README now allows either interpreter, and CI tests both.

### S4. `xcodebuild` fails when the Command Line Tools are selected

Reproduce: `xcode-select -p` prints `/Library/Developer/CommandLineTools`, then
run the README's `xcodebuild ... test`. It fails with
`tool 'xcodebuild' requires Xcode, but active developer directory ... is a command
line tools instance`. Not a project defect: the README now explains
`xcode-select -s`, and `scripts/ios-test.sh` detects the problem and prints the fix
(or accepts `DEVELOPER_DIR`).

### S5. Hard-coded simulator destination

The README's `name=iPhone 16e,OS=latest` destination fails on any machine or CI
image without that simulator. `scripts/ios-test.sh` picks the first available
iPhone, or the one named by `IOS_SIMULATOR`.

### S6. Port 5432 conflicts

`docker compose up -d db` fails when another PostgreSQL already listens on 5432
(the baseline machine had an unrelated container there). Host ports are now
configurable through `VALSCORES_DB_PORT` / `VALSCORES_TEST_DB_PORT` in `.env`.

### S7. No environment example and no CI

There was no `.env.example`, `.env` was not ignored, and no workflow ran the
checks. Both now exist; `.env*` (except the example) is ignored.

## Application bugs and observations (deferred to later tickets)

These are functional issues, not setup problems. They are recorded here and not
fixed in this ticket.

### A1. Team names are truncated to a few characters on the timeline

Reproduce: start the backend, run
`curl -X POST 'http://127.0.0.1:8000/api/matches/refresh'`, and launch the app on
an iPhone 16e simulator. Cards show names such as "Dra go…" and "Nov a…": the
name column wraps after two or three characters and then truncates, so most team
names are unreadable. (`GameCardView.swift`.)

### A2. Finished series report `0`–`0` round scores on the timeline

**Resolved in ticket 02** ([API contract](API-CONTRACT.md)): round scores are now
`null` unless the match is live, and unknown scores are stored as `NULL`.

Reproduce: after a refresh, `GET /api/matches/timeline` returns finished matches
such as `"team1_score": 1, "team2_score": 2, "team1_round_score": 0,
"team2_round_score": 0`. The API contract says unknown scores are `null`, but
match-level round scores default to the string `"0"` in `matches` and are
serialized as `0`. Confirm the intended meaning of match-level round scores
before changing either side.

### A3. Matches past their start time remain "Upcoming" until the next refresh

Reproduce: refresh, then wait until an upcoming match's `start_time` passes. The
app still shows it as "Upcoming" because status is only updated by
`POST /api/matches/refresh`, and nothing triggers a refresh automatically. This may
be intended for V1, but it is visible to users.

### A4. Expected-failure test logs an `IntegrityError`

A persistence test intentionally violates a `NOT NULL` constraint, and
`vlreal.persist_match` logs the full SQL error to stderr. Passing runs therefore
print a scary `Could not persist VLR match ...` line. Test-output noise only; the
README now notes it is expected.

### A5. Team colors change on every app launch

Found during ticket 03. Reproduce: launch the app twice and compare a team's badge
and card gradient. `Color.forTeam` (now `ValScores/Shared/UI/TeamColor.swift`)
sums `scalar.value.hashValue`, and Swift seeds `hashValue` randomly per process,
so the same team gets a different palette entry each launch. A deterministic hash
(for example summing the scalar values directly) would fix it.

