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
    client.py                HTTP fetching (the only network I/O)
    match_list.py            schedule/results page parser
    match_details.py         match page parser
    vlr_scraper.py           VlrScraper facade: client + parsers
    errors.py
  database/                Persistence; never touches the network
    models.py                SQLAlchemy schema
    connection.py            DATABASE_URL, engine, SessionLocal, initialize_database
    match_persistence.py     atomic match/map/player upserts (persist_match)
    migrations.py            legacy SQLite migrations (tests and explicit use only)
    __main__.py              python -m valoreal.database
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
at import. Tests replace route collaborators with
`app.dependency_overrides[get_session_factory]` and `[get_refresh_service]`
instead of patching module globals.

Useful entry points:

```bash
python -m uvicorn valoreal.api:app --reload --env-file .env   # serve the API
python -m valoreal.database                                   # create the schema
python -m valoreal.services.refresh                           # one refresh from the shell
```

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
