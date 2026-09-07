"""Small, repeatable SQLite schema migrations.

SQLite's ``user_version`` is the migration ledger. Each migration and its version
update commit together, so an interrupted migration is safe to retry.
"""

import re
from collections import defaultdict

from sqlalchemy import inspect, text

from .time_contract import normalize_explicit_utc_timestamp


LATEST_SCHEMA_VERSION = 2


def _column_names(connection, table_name):
    return {column["name"] for column in inspect(connection).get_columns(table_name)}


def _add_missing_columns(connection, table_name, columns):
    existing = _column_names(connection, table_name)
    for name, definition in columns.items():
        if name not in existing:
            connection.exec_driver_sql(
                f'ALTER TABLE "{table_name}" ADD COLUMN "{name}" {definition}'
            )


def _migration_1_legacy_baseline(connection):
    """Make all known legacy schemas readable before the constrained rebuild."""
    connection.exec_driver_sql(
        """
        CREATE TABLE IF NOT EXISTS matches (
            id INTEGER NOT NULL PRIMARY KEY,
            vlr_match_id VARCHAR,
            team1_name VARCHAR NOT NULL,
            team2_name VARCHAR NOT NULL,
            team1_round_score VARCHAR,
            team2_round_score VARCHAR,
            start_time VARCHAR,
            status VARCHAR,
            team1_series_score INTEGER,
            team2_series_score INTEGER,
            map_vetoes_raw VARCHAR,
            legacy_start_time VARCHAR
        )
        """
    )
    connection.exec_driver_sql(
        """
        CREATE TABLE IF NOT EXISTS games (
            id INTEGER NOT NULL PRIMARY KEY,
            match_id INTEGER,
            map_name VARCHAR NOT NULL,
            team1_round_score INTEGER,
            team2_round_score INTEGER,
            vlr_game_id VARCHAR,
            map_number INTEGER,
            FOREIGN KEY(match_id) REFERENCES matches(id)
        )
        """
    )
    connection.exec_driver_sql(
        """
        CREATE TABLE IF NOT EXISTS player_stats (
            id INTEGER NOT NULL PRIMARY KEY,
            game_id INTEGER,
            player_name VARCHAR NOT NULL,
            team_name VARCHAR NOT NULL,
            role VARCHAR,
            acs INTEGER,
            kd_ratio FLOAT,
            adr INTEGER,
            kills INTEGER DEFAULT 0,
            deaths INTEGER DEFAULT 0,
            assists INTEGER DEFAULT 0,
            plus_minus VARCHAR,
            kast VARCHAR,
            first_kills INTEGER DEFAULT 0,
            first_deaths INTEGER DEFAULT 0,
            FOREIGN KEY(game_id) REFERENCES games(id)
        )
        """
    )

    _add_missing_columns(
        connection,
        "matches",
        {
            "vlr_match_id": "VARCHAR",
            "team1_name": "VARCHAR NOT NULL DEFAULT 'Unknown'",
            "team2_name": "VARCHAR NOT NULL DEFAULT 'Unknown'",
            "team1_round_score": "VARCHAR",
            "team2_round_score": "VARCHAR",
            "start_time": "VARCHAR",
            "status": "VARCHAR",
            "team1_series_score": "INTEGER",
            "team2_series_score": "INTEGER",
            "map_vetoes_raw": "VARCHAR",
            "legacy_start_time": "VARCHAR",
        },
    )
    _add_missing_columns(
        connection,
        "games",
        {
            "match_id": "INTEGER",
            "map_name": "VARCHAR NOT NULL DEFAULT 'Map'",
            "team1_round_score": "INTEGER",
            "team2_round_score": "INTEGER",
            "vlr_game_id": "VARCHAR",
            "map_number": "INTEGER",
        },
    )
    _add_missing_columns(
        connection,
        "player_stats",
        {
            "game_id": "INTEGER",
            "player_name": "VARCHAR NOT NULL DEFAULT 'Unknown'",
            "team_name": "VARCHAR NOT NULL DEFAULT 'Unknown'",
            "role": "VARCHAR",
            "acs": "INTEGER",
            "kd_ratio": "FLOAT",
            "adr": "INTEGER",
            "kills": "INTEGER DEFAULT 0",
            "deaths": "INTEGER DEFAULT 0",
            "assists": "INTEGER DEFAULT 0",
            "plus_minus": "VARCHAR",
            "kast": "VARCHAR",
            "first_kills": "INTEGER DEFAULT 0",
            "first_deaths": "INTEGER DEFAULT 0",
        },
    )

    rows = list(
        connection.execute(
            text("SELECT id, start_time, legacy_start_time FROM matches")
        ).mappings()
    )
    for row in rows:
        original = row["start_time"]
        if not original:
            continue
        normalized = normalize_explicit_utc_timestamp(original)
        if normalized:
            if normalized != original:
                connection.execute(
                    text("UPDATE matches SET start_time=:value WHERE id=:id"),
                    {"value": normalized, "id": row["id"]},
                )
        else:
            connection.execute(
                text(
                    "UPDATE matches SET start_time=NULL, legacy_start_time=:legacy "
                    "WHERE id=:id"
                ),
                {"legacy": row["legacy_start_time"] or original, "id": row["id"]},
            )


def _canonical_match_id(value):
    value = (value or "").replace("https://www.vlr.gg", "")
    match = re.match(r"^/(\d+)", value)
    return f"/{match.group(1)}" if match else value


def _placeholder(value):
    return not value or value.strip().upper() == "TBD"


def _meaningful_pair(first, second):
    try:
        return first is not None and second is not None and not (
            int(first or 0) == 0 and int(second or 0) == 0
        )
    except (TypeError, ValueError):
        return bool(first or second)


def _status_rank(value):
    value = (value or "").upper()
    if "FINISHED" in value or "COMPLETED" in value or "FINAL" in value:
        return 2
    if "LIVE" in value:
        return 1
    return 0


def _match_richness(row):
    return (
        int(_meaningful_pair(row["team1_series_score"], row["team2_series_score"])),
        int(not _placeholder(row["team1_name"]))
        + int(not _placeholder(row["team2_name"])),
        int(bool(row["map_vetoes_raw"])),
        -row["id"],
    )


def _merge_match_rows(primary, candidate):
    merged = dict(primary)
    if _match_richness(candidate) > _match_richness(primary):
        if not _placeholder(candidate["team1_name"]):
            merged["team1_name"] = candidate["team1_name"]
        if not _placeholder(candidate["team2_name"]):
            merged["team2_name"] = candidate["team2_name"]

    if _status_rank(candidate["status"]) > _status_rank(merged["status"]):
        merged["status"] = candidate["status"]
    if candidate["start_time"] and not merged["start_time"]:
        merged["start_time"] = candidate["start_time"]
    if candidate["legacy_start_time"] and not merged["legacy_start_time"]:
        merged["legacy_start_time"] = candidate["legacy_start_time"]
    if candidate["map_vetoes_raw"] and not merged["map_vetoes_raw"]:
        merged["map_vetoes_raw"] = candidate["map_vetoes_raw"]
    if _meaningful_pair(
        candidate["team1_series_score"], candidate["team2_series_score"]
    ) and not _meaningful_pair(
        merged["team1_series_score"], merged["team2_series_score"]
    ):
        merged["team1_series_score"] = candidate["team1_series_score"]
        merged["team2_series_score"] = candidate["team2_series_score"]
    if _meaningful_pair(
        candidate["team1_round_score"], candidate["team2_round_score"]
    ) and not _meaningful_pair(
        merged["team1_round_score"], merged["team2_round_score"]
    ):
        merged["team1_round_score"] = candidate["team1_round_score"]
        merged["team2_round_score"] = candidate["team2_round_score"]
    return merged


def _game_richness(row, player_counts):
    return (
        player_counts[row["id"]],
        int(_meaningful_pair(row["team1_round_score"], row["team2_round_score"])),
        int(
            (row["map_name"] or "").strip().upper()
            not in {"", "MAP", "TBD", "N/A", "OVERALL"}
        ),
        -row["id"],
    )


def _merge_game_rows(primary, candidate, player_counts):
    richer = (
        candidate
        if _game_richness(candidate, player_counts)
        > _game_richness(primary, player_counts)
        else primary
    )
    merged = dict(richer)
    merged["id"] = primary["id"]
    merged["match_id"] = primary["match_id"]
    merged["vlr_game_id"] = primary["vlr_game_id"]
    if merged["map_number"] is None:
        merged["map_number"] = candidate["map_number"]
    return merged


def _player_richness(row):
    fields = (
        "acs",
        "kd_ratio",
        "adr",
        "kills",
        "deaths",
        "assists",
        "plus_minus",
        "kast",
        "first_kills",
        "first_deaths",
        "role",
    )
    meaningful = sum(
        row[field] not in (None, "", 0, 0.0, "0", "0%") for field in fields
    )
    return meaningful, -row["id"]


def _read_and_merge_legacy_data(connection):
    matches = [
        dict(row)
        for row in connection.execute(text("SELECT * FROM matches ORDER BY id")).mappings()
    ]
    games = [
        dict(row)
        for row in connection.execute(text("SELECT * FROM games ORDER BY id")).mappings()
    ]
    players = [
        dict(row)
        for row in connection.execute(
            text("SELECT * FROM player_stats ORDER BY id")
        ).mappings()
    ]

    match_groups = defaultdict(list)
    for row in matches:
        canonical_id = _canonical_match_id(row["vlr_match_id"])
        if not canonical_id:
            canonical_id = f"legacy-match-{row['id']}"
        match_groups[canonical_id].append(row)

    merged_matches = []
    old_to_new_match = {}
    for canonical_id, group in match_groups.items():
        primary = next(
            (row for row in group if row["vlr_match_id"] == canonical_id), None
        )
        primary = primary or max(group, key=_match_richness)
        merged = dict(primary)
        for candidate in group:
            if candidate["id"] != primary["id"]:
                merged = _merge_match_rows(merged, candidate)
        merged["vlr_match_id"] = canonical_id
        merged_matches.append(merged)
        for row in group:
            old_to_new_match[row["id"]] = primary["id"]

    player_counts = defaultdict(int)
    for row in players:
        player_counts[row["game_id"]] += 1

    game_groups = defaultdict(list)
    for row in games:
        target_match = old_to_new_match.get(row["match_id"])
        if target_match is None:
            # Preserve orphan data under a deterministic recovery parent.
            recovery_id = f"legacy-orphan-match-{row['match_id']}"
            recovery = next(
                (m for m in merged_matches if m["vlr_match_id"] == recovery_id), None
            )
            if recovery is None:
                recovery_pk = max([m["id"] for m in merged_matches] + [0]) + 1
                recovery = _recovery_match(recovery_pk, recovery_id)
                merged_matches.append(recovery)
            target_match = recovery["id"]

        identity = row["vlr_game_id"]
        if not identity and (row["map_name"] or "").strip().upper() == "OVERALL":
            identity = "all"
        if not identity:
            identity = f"legacy-game-{row['id']}"
        row["match_id"] = target_match
        row["vlr_game_id"] = str(identity)
        game_groups[(target_match, str(identity))].append(row)

    merged_games = []
    old_to_new_game = {}
    for _identity, group in game_groups.items():
        primary = max(group, key=lambda row: _game_richness(row, player_counts))
        merged = dict(primary)
        for candidate in group:
            if candidate["id"] != primary["id"]:
                merged = _merge_game_rows(merged, candidate, player_counts)
        merged_games.append(merged)
        for row in group:
            old_to_new_game[row["id"]] = primary["id"]

    player_groups = defaultdict(list)
    orphan_player_games = {}
    for row in players:
        target_game = old_to_new_game.get(row["game_id"])
        if target_game is None:
            orphan_key = row["game_id"]
            if orphan_key not in orphan_player_games:
                recovery_match_pk = max([m["id"] for m in merged_matches] + [0]) + 1
                recovery_game_pk = max([g["id"] for g in merged_games] + [0]) + 1
                merged_matches.append(
                    _recovery_match(
                        recovery_match_pk, f"legacy-orphan-player-match-{orphan_key}"
                    )
                )
                merged_games.append(
                    {
                        "id": recovery_game_pk,
                        "match_id": recovery_match_pk,
                        "vlr_game_id": f"legacy-orphan-game-{orphan_key}",
                        "map_number": None,
                        "map_name": "Legacy recovery",
                        "team1_round_score": 0,
                        "team2_round_score": 0,
                    }
                )
                orphan_player_games[orphan_key] = recovery_game_pk
            target_game = orphan_player_games[orphan_key]
        row["game_id"] = target_game
        row["team_name"] = row["team_name"] or "Unknown"
        row["player_name"] = row["player_name"] or f"Unknown player {row['id']}"
        player_groups[(target_game, row["team_name"], row["player_name"])].append(row)

    merged_players = []
    for _identity, group in player_groups.items():
        merged_players.append(max(group, key=_player_richness))

    return merged_matches, merged_games, merged_players


def _recovery_match(primary_key, identity):
    return {
        "id": primary_key,
        "vlr_match_id": identity,
        "team1_name": "Unknown",
        "team2_name": "Unknown",
        "team1_round_score": "0",
        "team2_round_score": "0",
        "start_time": None,
        "legacy_start_time": None,
        "status": None,
        "team1_series_score": None,
        "team2_series_score": None,
        "map_vetoes_raw": None,
    }


def _insert_rows(connection, table, columns, rows):
    if not rows:
        return
    column_sql = ", ".join(columns)
    value_sql = ", ".join(f":{column}" for column in columns)
    connection.execute(
        text(f"INSERT INTO {table} ({column_sql}) VALUES ({value_sql})"),
        [{column: row.get(column) for column in columns} for row in rows],
    )


def _migration_2_identity_and_foreign_keys(connection):
    matches, games, players = _read_and_merge_legacy_data(connection)

    connection.exec_driver_sql("DROP TABLE IF EXISTS player_stats_v2")
    connection.exec_driver_sql("DROP TABLE IF EXISTS games_v2")
    connection.exec_driver_sql("DROP TABLE IF EXISTS matches_v2")
    connection.exec_driver_sql(
        """
        CREATE TABLE matches_v2 (
            id INTEGER NOT NULL PRIMARY KEY,
            vlr_match_id VARCHAR NOT NULL,
            team1_name VARCHAR NOT NULL,
            team2_name VARCHAR NOT NULL,
            team1_round_score VARCHAR,
            team2_round_score VARCHAR,
            start_time VARCHAR,
            legacy_start_time VARCHAR,
            status VARCHAR,
            team1_series_score INTEGER,
            team2_series_score INTEGER,
            map_vetoes_raw VARCHAR
        )
        """
    )
    connection.exec_driver_sql(
        """
        CREATE TABLE games_v2 (
            id INTEGER NOT NULL PRIMARY KEY,
            match_id INTEGER NOT NULL,
            vlr_game_id VARCHAR NOT NULL,
            map_number INTEGER,
            map_name VARCHAR NOT NULL,
            team1_round_score INTEGER,
            team2_round_score INTEGER,
            FOREIGN KEY(match_id) REFERENCES matches_v2(id) ON DELETE CASCADE
        )
        """
    )
    connection.exec_driver_sql(
        """
        CREATE TABLE player_stats_v2 (
            id INTEGER NOT NULL PRIMARY KEY,
            game_id INTEGER NOT NULL,
            player_name VARCHAR NOT NULL,
            team_name VARCHAR NOT NULL,
            role VARCHAR,
            acs INTEGER,
            kd_ratio FLOAT,
            adr INTEGER,
            kills INTEGER DEFAULT 0,
            deaths INTEGER DEFAULT 0,
            assists INTEGER DEFAULT 0,
            plus_minus VARCHAR,
            kast VARCHAR,
            first_kills INTEGER DEFAULT 0,
            first_deaths INTEGER DEFAULT 0,
            FOREIGN KEY(game_id) REFERENCES games_v2(id) ON DELETE CASCADE
        )
        """
    )

    _insert_rows(
        connection,
        "matches_v2",
        (
            "id",
            "vlr_match_id",
            "team1_name",
            "team2_name",
            "team1_round_score",
            "team2_round_score",
            "start_time",
            "legacy_start_time",
            "status",
            "team1_series_score",
            "team2_series_score",
            "map_vetoes_raw",
        ),
        matches,
    )
    _insert_rows(
        connection,
        "games_v2",
        (
            "id",
            "match_id",
            "vlr_game_id",
            "map_number",
            "map_name",
            "team1_round_score",
            "team2_round_score",
        ),
        games,
    )
    _insert_rows(
        connection,
        "player_stats_v2",
        (
            "id",
            "game_id",
            "player_name",
            "team_name",
            "role",
            "acs",
            "kd_ratio",
            "adr",
            "kills",
            "deaths",
            "assists",
            "plus_minus",
            "kast",
            "first_kills",
            "first_deaths",
        ),
        players,
    )

    connection.exec_driver_sql("DROP TABLE player_stats")
    connection.exec_driver_sql("DROP TABLE games")
    connection.exec_driver_sql("DROP TABLE matches")
    connection.exec_driver_sql("ALTER TABLE matches_v2 RENAME TO matches")
    connection.exec_driver_sql("ALTER TABLE games_v2 RENAME TO games")
    connection.exec_driver_sql("ALTER TABLE player_stats_v2 RENAME TO player_stats")
    connection.exec_driver_sql(
        "CREATE UNIQUE INDEX ix_matches_vlr_match_id ON matches(vlr_match_id)"
    )
    connection.exec_driver_sql(
        "CREATE UNIQUE INDEX uq_games_match_id_vlr_game_id "
        "ON games(match_id, vlr_game_id)"
    )
    connection.exec_driver_sql(
        "CREATE INDEX ix_games_vlr_game_id ON games(vlr_game_id)"
    )
    connection.exec_driver_sql(
        "CREATE UNIQUE INDEX uq_player_stats_game_player_identity "
        "ON player_stats(game_id, team_name, player_name)"
    )


MIGRATIONS = {1: _migration_1_legacy_baseline, 2: _migration_2_identity_and_foreign_keys}


def schema_version(connection):
    return connection.exec_driver_sql("PRAGMA user_version").scalar_one()


def run_migrations(engine):
    """Apply pending SQLite migrations exactly once and validate their FKs."""
    if engine.dialect.name != "sqlite":
        raise ValueError("ValScores migrations support SQLite only")

    with engine.connect() as connection:
        current = schema_version(connection)
        connection.commit()
        if current > LATEST_SCHEMA_VERSION:
            raise RuntimeError(
                f"Database schema version {current} is newer than supported "
                f"version {LATEST_SCHEMA_VERSION}"
            )

        # Referenced tables can only be rebuilt with this changed outside a
        # transaction. New application connections independently enable it.
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        connection.commit()
        try:
            for version in range(current + 1, LATEST_SCHEMA_VERSION + 1):
                with connection.begin():
                    MIGRATIONS[version](connection)
                    connection.exec_driver_sql(f"PRAGMA user_version={version}")
        finally:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            connection.commit()

        violations = connection.exec_driver_sql("PRAGMA foreign_key_check").all()
        if violations:
            raise RuntimeError(f"Foreign-key violations after migration: {violations}")
