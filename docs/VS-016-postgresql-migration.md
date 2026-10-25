# VS-016 PostgreSQL migration notes

## SQLite assumption audit

The pre-migration backend contained these SQLite-specific behaviors:

- `database_setup.py` defaulted to `valoreal/valorant_stats.db` through a
  `sqlite:///` URL and supported a second path setting,
  `VALSCORES_DATABASE_PATH`.
- Every SQLite connection ran `PRAGMA foreign_keys=ON`.
- Importing `database_setup.py` immediately ran the custom migration system.
- `migrations.py` uses SQLite's `PRAGMA user_version`, temporarily disables
  foreign keys, rebuilds tables, and executes SQLite-oriented DDL.
- `tests/test_database_identity.py` and
  `tests/test_database_time_contract.py` directly use `sqlite3`, PRAGMAs, `.db`
  files, and the legacy migration ledger.
- API, refresh, match-detail, and persistence tests created temporary or in-memory
  SQLite engines, including SQLite's `check_same_thread` setting.
- Documentation described the local `.db` file as the runtime source of truth.
- Integer primary keys relied on SQLAlchemy's portable generated-key behavior;
  no application SQL depended on SQLite's `AUTOINCREMENT` keyword.

No application query outside the legacy migration module used SQLite-only SQL.
Foreign-key cascades, unique identities, nullability, indexes, session commits,
and rollback behavior were already expressed through SQLAlchemy.

## Resulting architecture

- `DATABASE_URL` is the only runtime database setting and must contain a
  SQLAlchemy-compatible URL. The supported driver is Psycopg 3.
- FastAPI startup calls `Base.metadata.create_all` to initialize a clean database
  from the canonical model. This does not replay legacy SQLite DDL and remains
  compatible with introducing versioned migration tooling later.
- `matches.start_time` uses `TIMESTAMP WITH TIME ZONE` on PostgreSQL. Bind values
  must be timezone-aware, are normalized to UTC, and round-trip as aware UTC
  `datetime` objects before Pydantic and Swift decoding.
- Match, game, and player identities retain their unique indexes. Both foreign
  keys are non-null and use `ON DELETE CASCADE`.
- Status remains a portable string normalized by the existing application status
  contract, and `map_vetoes_raw` remains serialized text; neither API shape changes.
- Each match upsert keeps its existing single-session transaction boundary and
  rolls back the complete match/game/player write on failure.
- Runtime startup has no dependency on `valorant_stats.db`. No automatic import is
  performed because the checked-in/local SQLite file is stale and non-authoritative.

## Retained SQLite compatibility

SQLite remains available only for fast isolated tests and explicit tests of the
historical schema migration. The PRAGMA connection hook and `migrations.py` are not
executed on the PostgreSQL runtime path. Set `TEST_DATABASE_URL` to run persistence,
refresh, and API coverage against a disposable PostgreSQL database whose name
contains `test`; each test creates a new schema and drops it on teardown, without
touching pre-existing schemas.
