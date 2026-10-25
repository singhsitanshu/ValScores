"""Enforce the ticket-02 API contract in the schema and index hot queries.

- matches.status: legacy labels normalized, NOT NULL, limited to canonical values.
- matches round scores: varchar -> integer ('' becomes NULL).
- Scores and map numbers may not be negative.
- Indexes for timeline range filtering and legacy upstream-ID prefix lookup.

Every conflict is collected and reported before anything changes.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-25
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

from valoreal.database.migration_errors import MigrationConflictError


revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

STATUSES = ("cancelled", "finished", "live", "postponed", "upcoming")
STATUS_CHECK = "status IN ('cancelled', 'finished', 'live', 'postponed', 'upcoming')"
MATCH_SCORES_CHECK = (
    "team1_round_score >= 0 AND team2_round_score >= 0"
    " AND team1_series_score >= 0 AND team2_series_score >= 0"
)
GAME_VALUES_CHECK = "map_number >= 0 AND team1_round_score >= 0 AND team2_round_score >= 0"
NON_INTEGER_TEXT = r"btrim({column}) <> '' AND btrim({column}) !~ '^[0-9]+$'"
SAMPLE_SIZE = 10


def normalized_status(label):
    """Frozen copy of the status rules at this revision (see domain/match_status.py).

    NULL was always served as upcoming, so it becomes upcoming. Returns None for
    labels that cannot be interpreted safely.
    """
    if label is None:
        return "upcoming"
    normalized = label.strip().lower()
    if "postpone" in normalized:
        return "postponed"
    if "cancel" in normalized:
        return "cancelled"
    if "live" in normalized or "in progress" in normalized:
        return "live"
    if any(marker in normalized for marker in ("completed", "finished", "final")):
        return "finished"
    if normalized in {"upcoming", "tbd", "scheduled", "pending"}:
        return "upcoming"
    return None


def ids_text(ids):
    shown = ", ".join(str(row_id) for row_id in ids[:SAMPLE_SIZE])
    return shown + (f", ... ({len(ids)} total)" if len(ids) > SAMPLE_SIZE else "")


def find_conflicts(bind):
    conflicts = []

    unknown = {}
    for row_id, label in bind.execute(text("SELECT id, status FROM matches ORDER BY id")):
        if normalized_status(label) is None:
            unknown.setdefault(label, []).append(row_id)
    for label, ids in unknown.items():
        conflicts.append(
            f"matches.status {label!r} is not a recognized status (match ids {ids_text(ids)}). "
            f"Set it to one of {', '.join(STATUSES)}, e.g. "
            f"UPDATE matches SET status = 'upcoming' WHERE id IN ({ids_text(ids)});"
        )

    for column in ("team1_round_score", "team2_round_score"):
        ids = list(bind.execute(text(
            f"SELECT id FROM matches WHERE {NON_INTEGER_TEXT.format(column=column)} ORDER BY id"
        )).scalars())
        if ids:
            conflicts.append(
                f"matches.{column} contains text that is not a non-negative integer "
                f"(match ids {ids_text(ids)}). Correct the value or set it to NULL if unknown."
            )

    for table, columns in (
        ("matches", ("team1_series_score", "team2_series_score")),
        ("games", ("map_number", "team1_round_score", "team2_round_score")),
    ):
        for column in columns:
            ids = list(bind.execute(text(
                f"SELECT id FROM {table} WHERE {column} < 0 ORDER BY id"
            )).scalars())
            if ids:
                conflicts.append(
                    f"{table}.{column} is negative ({table} ids {ids_text(ids)}). "
                    f"Correct the value or set it to NULL if unknown."
                )
    return conflicts


def upgrade():
    bind = op.get_bind()
    conflicts = find_conflicts(bind)
    if conflicts:
        raise MigrationConflictError(revision, conflicts)

    labels = bind.execute(text("SELECT DISTINCT status FROM matches")).scalars().all()
    for label in labels:
        canonical = normalized_status(label)
        if canonical != label:
            bind.execute(
                text("UPDATE matches SET status = :canonical WHERE status IS NOT DISTINCT FROM :label"),
                {"canonical": canonical, "label": label},
            )

    for column in ("team1_round_score", "team2_round_score"):
        op.alter_column(
            "matches",
            column,
            type_=sa.Integer(),
            existing_type=sa.String(),
            existing_nullable=True,
            postgresql_using=f"NULLIF(btrim({column}), '')::integer",
        )
    op.alter_column("matches", "status", nullable=False, existing_type=sa.String())

    op.create_check_constraint("ck_matches_status_known", "matches", STATUS_CHECK)
    op.create_check_constraint("ck_matches_scores_non_negative", "matches", MATCH_SCORES_CHECK)
    op.create_check_constraint("ck_games_values_non_negative", "games", GAME_VALUES_CHECK)

    op.create_index(
        "ix_matches_vlr_match_id_pattern",
        "matches",
        ["vlr_match_id"],
        postgresql_ops={"vlr_match_id": "varchar_pattern_ops"},
    )
    op.create_index("ix_matches_start_time_id", "matches", ["start_time", "id"])


def downgrade():
    # Status normalization is not reversed: canonical labels are valid in 0001.
    op.drop_index("ix_matches_start_time_id", table_name="matches")
    op.drop_index("ix_matches_vlr_match_id_pattern", table_name="matches")
    op.drop_constraint("ck_games_values_non_negative", "games", type_="check")
    op.drop_constraint("ck_matches_scores_non_negative", "matches", type_="check")
    op.drop_constraint("ck_matches_status_known", "matches", type_="check")
    op.alter_column("matches", "status", nullable=True, existing_type=sa.String())
    for column in ("team1_round_score", "team2_round_score"):
        op.alter_column(
            "matches",
            column,
            type_=sa.String(),
            existing_type=sa.Integer(),
            existing_nullable=True,
            postgresql_using=f"{column}::varchar",
        )
