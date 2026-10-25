# Architecture

ValScores has two programs: a FastAPI backend that scrapes VLR into PostgreSQL,
and a SwiftUI app that reads the backend's API. They share only the HTTP contract
in [API-CONTRACT.md](API-CONTRACT.md).

`tests/test_project_structure.py` enforces the dependency rules below, so a
change that breaks them fails the backend suite.

## Repository layout

```text
valoreal/                  Python backend package (uvicorn valoreal.api:app)
  domain/                  Pure rules, no I/O
    match_status.py          statuses and allowed transitions
    time_contract.py         UTC timestamp parsing and normalization
    normalization.py         team, score and match-ID normalization
  scraper/                 VLR access; never touches the database
    client.py                HTTP fetching (the only network I/O): retries, rate limit
    page_checks.py           error/bot-check page detection
    match_list.py            schedule/results page parser
    match_details.py         match page parser
    vlr_scraper.py           VlrScraper facade: client + parsers
    errors.py
  database/                Persistence; never touches the network
    models.py                SQLAlchemy schema (must match the Alembic head)
    connection.py            DATABASE_URL, engine, SessionLocal
    match_persistence.py     atomic match/map/player upserts (persist_match)
    migrations/              Alembic env.py and versioned PostgreSQL revisions
    migrator.py              upgrade / baseline / status, startup schema check
    schema_inspection.py     catalog snapshots for baseline checks and tests
    migration_errors.py      conflict and schema-version errors
    legacy_sqlite.py         historical SQLite migrations (tests only)
    __main__.py              python -m valoreal.database {upgrade,baseline,status}
  services/                Application logic used by routes
    timeline.py              timeline query and response assembly
    match_stats.py           match statistics response assembly
    stats_aggregation.py     whole-series player totals
    rosters.py               player-to-team assignment
    match_summary.py         derived match status and map wins
    values.py                column values -> contract values
    refresh.py               RefreshService: scrape, then persist, serialized
    errors.py                errors routes translate to HTTP
  api/                     HTTP layer
    app.py                   FastAPI app, lifespan, router and handlers
    routes.py                request validation; calls services
    schemas.py               Pydantic response models (the OpenAPI schema)
    errors.py                error envelope and exception handlers
    dependencies.py          injectable session factory and refresh service

ValScores/                 SwiftUI app sources (Xcode target "valoreal")
  App/                       app entry point and root view
  Shared/
    Networking/              APIClient, API error codes: the only HTTP code
    Models/                  Decodable contract models
    Time/                    timestamp decoding and calendar grouping
    UI/                      components shared by features
  Features/
    Timeline/                VLRDataManager (timeline state), list, cards, date strip
    MatchDetail/             MatchDetailState, detail screen, player rows
  Resources/                 asset catalog
  Info.plist

ValScoresTests/            XCTest target (runs in the simulator)
tests/                     Backend unittest suite, VLR HTML and API JSON fixtures,
                           and portable swiftc checks (tests/ValScores*Tests)
scripts/                   ios-test.sh, swift-checks.sh
docs/                      Contract, architecture and ticket notes
```

## Backend dependency direction

```text
api  ──▶  services  ──▶  scraper  ──▶  domain
                    └──▶  database ──▶  domain
```

- **Routes call services.** `api/routes.py` validates input, calls one service
  function, and turns service errors into the error envelope. It holds no query or
  aggregation logic.
- **Services coordinate parsing and persistence.** `RefreshService` fetches with
  the scraper and writes with `database.match_persistence`; the timeline and stats
  services read the database and assemble contract dictionaries.
- **The scraper and database never import each other.** Parsers are pure functions
  of HTML and can run without `DATABASE_URL` or SQLAlchemy loaded.
- **`domain` imports nothing else from the package.**
- `api` may import `database` only for wiring (engine startup and the injectable
  session factory in `dependencies.py`).

Only `database/connection.py` creates an engine, and it requires `DATABASE_URL`
at import. The API checks the schema revision at startup but never changes the
schema; see [DATABASE.md](DATABASE.md). Tests replace route collaborators with
`app.dependency_overrides[get_session_factory]` and `[get_refresh_service]`
instead of patching module globals.

Useful entry points:

```bash
python -m uvicorn valoreal.api:app --reload --env-file .env   # serve the API
python -m valoreal.database --env-file .env upgrade           # apply migrations
python -m valoreal.services.refresh                           # one refresh from the shell
```

## Scraper behavior

**Fetching** (`scraper/client.py`). Every request goes through
`VlrHttpClient.fetch_html`:

| Concern | Behavior |
| --- | --- |
| Connections | One `requests.Session` per scraper, so connections are reused. |
| Timeouts | 5 s to connect, 20 s to read (`DEFAULT_HTTP_TIMEOUT`). |
| Identity | `User-Agent: ValScores/1.0 (+https://github.com/singhsitanshu/ValScores)`. |
| Rate | At least 1 s between requests (`DEFAULT_MIN_INTERVAL`). |
| Retries | Up to 3 attempts for timeouts, connection errors and HTTP 429/500/502/503/504, waiting 1 s then 2 s (capped at 10 s). |
| `Retry-After` | Honored (seconds or HTTP date) up to 60 s; a longer request fails immediately instead of stalling a refresh. |
| Never retried | Other 4xx responses, invalid requests, and every parse error. |

Failures raise `VlrUpstreamError` with `url`, `status_code` and `attempts`.

**Parsing** (`match_list.py`, `match_details.py`) is pure: HTML in, records
out, with no network or database access. Each page is classified before
records are extracted:

| Page | Result |
| --- | --- |
| CDN or VLR error page / bot check served with HTTP 200 | `VlrErrorPageError` (a `VlrUpstreamError`) |
| List page without the `div.col.mod-1` match column, or with match links in unfamiliar markup | `MatchListParseError` |
| Match page without the `.match-header-vs` header | `MatchDetailParseError` |
| Recognized list page with no matches | `[]`, the only successful empty result |

Within a list page, a card missing identity data (match link, either team name)
is skipped and reported in `last_list_parse_failures`. If every card is skipped,
the page fails. A card whose optional fields cannot be read (status, time, scores)
is kept and reported in `last_list_parse_warnings`. Both carry the page `url`,
`card_index` and `href`. A refresh reports skipped cards as `failures` and kept
cards' problems as `warnings` (see the [API contract](API-CONTRACT.md)).

**Records** follow the [API contract](API-CONTRACT.md):

- match IDs are canonical (`/<id>`);
- statuses are one of the five contract values, or `None` when a card's status is unreadable;
- times are ISO-8601 UTC;
- scores and counting stats are `int`, and `k_d` is a `float`;
- `plus_minus` is signed text (`"+7"`) and `kast` is percent text (`"78%"`);
- anything VLR does not show is `None`, including the `0 - 0` placeholders of unplayed maps.

## App dependency direction

```text
Features (views) ──▶ feature state (VLRDataManager, MatchDetailState)
                       ──▶ Shared/Networking (APIClient) ──▶ Shared/Models, Shared/Time
```

- **Views consume client state.** Views read published state from
  `VLRDataManager` or `MatchDetailState` and call their methods; they never build
  URLs or requests. Only `Shared/Networking` may use `URLRequest`, `URLSession` or
  `URLComponents`.
- Shared models and time utilities are defined once (`Shared/Models`,
  `Shared/Time`) and used by both features.

The Xcode target uses a file-system-synchronized group rooted at `ValScores/`, so
new Swift files are picked up automatically wherever they are placed in that tree.
The folder contains no backend files.

## Changing the layout

After pulling a change that adds or moves backend packages, reinstall the
editable package so new subpackages are importable:

```bash
python -m pip install -e '.[test]'
```

When moving Swift files that the portable checks compile, update
`scripts/swift-checks.sh`.
