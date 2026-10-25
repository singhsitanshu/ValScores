# Database schema and migrations

ValScores stores matches in PostgreSQL 17. The schema is versioned with
[Alembic](https://alembic.sqlalchemy.org/) revisions in
`valoreal/database/migrations/versions/`. Every schema change ships as a
revision, and the API never creates or alters tables itself.

All commands below read `DATABASE_URL`. Pass `--env-file .env` to load it from
your `.env` file, or export it first.

## Commands

| Command | Use it to |
| --- | --- |
| `python -m valoreal.database upgrade` | Create the schema in an empty database, or apply pending revisions. Safe to re-run: at the latest revision it changes nothing. |
| `python -m valoreal.database baseline` | Adopt a database created before Alembic (see below). Verifies the schema first and only records revision `0001`. |
| `python -m valoreal.database status` | Print the current and required revisions. Exits `0` when current, `1` when an upgrade or baseline is needed, `2` on errors. |

Each `upgrade` runs all pending revisions in **one transaction**. If any step
fails, PostgreSQL rolls everything back and the database stays at its previous
revision.

### API startup

The API checks the schema revision at startup and refuses to start unless the
database is exactly at the latest revision. The error names the command to run:

| Database state | Startup error says |
| --- | --- |
| Empty | Run `python -m valoreal.database upgrade`. |
| Tables but no migration history | Back up, run `baseline`, then `upgrade`. |
| Older revision | Back up, then run `upgrade`. |
| Unknown (newer) revision | Deploy the matching release or restore a compatible backup. |

## Initialize an empty database

```bash
docker compose up -d --wait db
python -m valoreal.database --env-file .env upgrade
```

## Adopt an existing installation (created before Alembic)

Databases created before overhaul ticket 04 were built by SQLAlchemy's
`create_all()` at API startup, so they have tables but no `alembic_version` table.
`upgrade` refuses to touch them until they are baselined:

1. **Back up** (see below).
2. `python -m valoreal.database --env-file .env baseline` compares the tables,
   columns, unique indexes and foreign keys with revision `0001`
   (`tests/fixtures/database/pre_alembic_schema.sql` is the captured original). If
   anything differs, it lists the differences and records nothing. Otherwise it
   records revision `0001` without changing any table.
3. `python -m valoreal.database --env-file .env upgrade` applies `0002` and later.

## Revisions

| Revision | Change |
| --- | --- |
| `0001` | Baseline: the three tables exactly as `create_all()` built them before Alembic. |
| `0002` | Enforces the [API contract](API-CONTRACT.md) and indexes hot queries (details below). |

### 0002: contract constraints

Data changes, all reversible in meaning:

- `matches.status` values are normalized with the same rules the scraper uses
  (`'LIVE'` → `live`, `'Finished'` → `finished`, `NULL` → `upcoming`, which is how
  the API already reported `NULL`). The column then becomes `NOT NULL` and limited to
  `upcoming`, `live`, `postponed`, `finished` and `cancelled`.
- `matches.team1_round_score` and `team2_round_score` change from text to integer.
  Numeric text keeps its value (`' 3 '` → `3`); blank text becomes `NULL`.

New constraints and indexes:

| Object | Purpose |
| --- | --- |
| `ck_matches_status_known` | Only contract statuses. |
| `ck_matches_scores_non_negative`, `ck_games_values_non_negative` | No negative scores or map numbers (`NULL` still means unknown). |
| `ix_matches_start_time_id` | Timeline range filter and ordering (`start_time`, `id`). |
| `ix_matches_vlr_match_id_pattern` | Upstream ID lookup, including the legacy `LIKE '/<id>/%'` prefix search, which the plain unique index cannot serve. |

**Conflict detection.** Before changing anything, `0002` checks every row that a
new constraint would reject and reports all problems at once. The upgrade then
stops and nothing is changed:

```text
error: Revision 0002 was not applied because existing data conflicts with its constraints.
Nothing was changed. Fix these rows, then run the upgrade again:
  - matches.status 'forfeited' is not a recognized status (match ids 1). Set it to one of
    cancelled, finished, live, postponed, upcoming, e.g. UPDATE matches SET status = 'upcoming' WHERE id IN (1);
  - matches.team1_round_score contains text that is not a non-negative integer (match ids 2). ...
```

Fix the listed rows (after a backup), then run `upgrade` again.

### Schema audit (ticket 04)

The pre-Alembic schema was checked against the ticket-02 contract:

| Area | Finding | Result |
| --- | --- | --- |
| Match → map → player relationships | Foreign keys with `ON DELETE CASCADE` already existed. | Kept; tested (no orphans, cascading deletes). |
| Uniqueness | Upstream match ID, `(match_id, vlr_game_id)` and `(game_id, team_name, player_name)` were already unique. | Kept; tested. |
| Match status | Nullable free text. | `0002`: normalized, `NOT NULL`, constrained. |
| Match round scores | Text, although the contract has integers. | `0002`: integer. |
| Score ranges | Negative values were possible. | `0002`: non-negative checks. |
| Timeline queries | No index on `start_time`. | `0002`: `ix_matches_start_time_id`. |
| Match-detail queries | Map and player lookups by parent ID. | Already served by the unique indexes' leading columns. |
| Player `plus_minus`, `kast` | Stored as VLR text (`'+5'`, `'76%'`). | Unchanged; the API converts them to numbers. |
| `map_vetoes_raw` | JSON stored as text. | Unchanged. |

## Persisting scraped data

`valoreal/database/match_persistence.py` writes one match per call with
`persist_match`. Its rules keep repeated and partial scrapes safe.

**Identity and atomicity**

- A match is identified by its canonical upstream ID (`/<id>`). Legacy
  `/<id>/<slug>` rows are merged into the canonical row on first sight. Maps are
  identified by `(match, vlr_game_id)` and players by `(map, team, player name)`;
  unique constraints back all three.
- Each call is one transaction. Any error rolls back every row it touched, so a
  failed update leaves the stored match exactly as it was.
- Replaying identical input issues no `INSERT`, `UPDATE` or `DELETE` and reports
  `unchanged`.

**Merge rules**

| Field | Rule |
| --- | --- |
| Team names | A placeholder (`TBD`, blank) never replaces a real name; a different real name replaces it (correction). The match page's names win over the list card's. |
| Status | Changes only through the [allowed transitions](#0002-contract-constraints) (`finished` and `cancelled` are final). An unreadable status (`None`) is not an observation and leaves the stored status alone; a new match without one starts as `upcoming`. When the list and match pages disagree, the match page wins only through an allowed transition. |
| Start time | A trustworthy timestamp replaces the stored one; a missing one keeps it. |
| Series score | A score present on the list card (including `0`) replaces the stored one. Otherwise the match page score is used; upcoming matches have none. |
| Map and live round scores | Kept when the incoming score is missing or `0 - 0` and a real score is stored; otherwise replaced. |
| Player statistics | A missing (`None`) value keeps the stored value. A real value, including `0`, replaces it. An authoritative page (all statistics published) replaces every value, including with `None`. |
| Maps and players not in the scrape | Deleted only when the match page is authoritative. Partial or empty snapshots never delete stored maps or players. |
| Schedule vs results page | Records for the same match are merged before saving: non-empty values from the later page win, and status moves only forward. |

## Backups

Take a backup before every `upgrade` and `baseline` on a database whose data you
care about. With the Compose service:

```bash
docker compose exec -T db pg_dump -U valscores -d valscores --format=custom > valscores-$(date +%Y%m%d-%H%M%S).dump
```

Keep the dump until the upgraded API has been running correctly. The match data
can also be rebuilt from VLR with `POST /api/matches/refresh`, but only for
matches VLR still lists.

## Recovery

- **Upgrade failed.** Nothing was applied, because each upgrade is one
  transaction. Read the error, fix the reported rows or setting, and re-run.
- **Upgraded, but the new release misbehaves.** Prefer restoring the backup, which
  returns the schema and data to the exact pre-upgrade state, together with the
  previous release:

  ```bash
  docker compose exec -T db dropdb -U valscores valscores
  docker compose exec -T db createdb -U valscores valscores
  docker compose exec -T db pg_restore -U valscores -d valscores --no-owner < valscores-YYYYMMDD-HHMMSS.dump
  ```

- **Downgrade in place** (development only). Revisions implement `downgrade()`.
  `0002 → 0001` drops the new constraints and indexes and turns round scores back
  into text; normalized statuses stay normalized. Downgrading below `0001` drops
  every table.

  ```bash
  alembic downgrade 0001    # uses alembic.ini and DATABASE_URL
  ```

## Writing a new revision

1. Change `valoreal/database/models.py`.
2. `alembic revision -m "describe the change"` (uses `alembic.ini` and
   `DATABASE_URL`), then write `upgrade()` and `downgrade()` by hand. Revisions
   are frozen history: copy any rules they need instead of importing application
   code that may change later.
3. If a new constraint could reject existing rows, check for them first and
   raise `MigrationConflictError` with ids and a suggested fix, as `0002` does.
4. Run the PostgreSQL test suite. `tests/test_migrations.py` fails if the
   migrated schema differs from `models.py`, if re-running changes anything, or if
   existing data is not preserved.

## SQLite

SQLite is not a runtime database. `valoreal/database/legacy_sqlite.py` keeps the
historical SQLite migrations for compatibility tests only. Nothing in the API or
the migration command imports it, and `tests/test_project_structure.py` enforces
that. Fast unit tests still create throwaway SQLite schemas from the models. The
Alembic migration tests run only with `TEST_DATABASE_URL` (always in CI) and are
reported as skipped otherwise.
