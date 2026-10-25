"""Baseline: the schema SQLAlchemy create_all() produced before Alembic.

Existing installations already have exactly this schema and are stamped at this
revision by ``python -m valoreal.database baseline``; empty databases create it.
tests/fixtures/database/pre_alembic_schema.sql is the pg_dump it reproduces.

Revision ID: 0001
Revises:
Create Date: 2026-10-25
"""

from alembic import op
import sqlalchemy as sa


revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "matches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("vlr_match_id", sa.String(), nullable=False),
        sa.Column("team1_name", sa.String(), nullable=False),
        sa.Column("team2_name", sa.String(), nullable=False),
        sa.Column("team1_round_score", sa.String(), nullable=True),
        sa.Column("team2_round_score", sa.String(), nullable=True),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("legacy_start_time", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=True),
        sa.Column("team1_series_score", sa.Integer(), nullable=True),
        sa.Column("team2_series_score", sa.Integer(), nullable=True),
        sa.Column("map_vetoes_raw", sa.String(), nullable=True),
    )
    op.create_index("ix_matches_vlr_match_id", "matches", ["vlr_match_id"], unique=True)

    op.create_table(
        "games",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("match_id", sa.Integer(), nullable=False),
        sa.Column("vlr_game_id", sa.String(), nullable=False),
        sa.Column("map_number", sa.Integer(), nullable=True),
        sa.Column("map_name", sa.String(), nullable=False),
        sa.Column("team1_round_score", sa.Integer(), nullable=True),
        sa.Column("team2_round_score", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["match_id"], ["matches.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "uq_games_match_id_vlr_game_id", "games", ["match_id", "vlr_game_id"], unique=True
    )
    op.create_index("ix_games_vlr_game_id", "games", ["vlr_game_id"])

    op.create_table(
        "player_stats",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("game_id", sa.Integer(), nullable=False),
        sa.Column("player_name", sa.String(), nullable=False),
        sa.Column("team_name", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=True),
        sa.Column("acs", sa.Integer(), nullable=True),
        sa.Column("kd_ratio", sa.Float(), nullable=True),
        sa.Column("adr", sa.Integer(), nullable=True),
        sa.Column("kills", sa.Integer(), nullable=True),
        sa.Column("deaths", sa.Integer(), nullable=True),
        sa.Column("assists", sa.Integer(), nullable=True),
        sa.Column("plus_minus", sa.String(), nullable=True),
        sa.Column("kast", sa.String(), nullable=True),
        sa.Column("first_kills", sa.Integer(), nullable=True),
        sa.Column("first_deaths", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["game_id"], ["games.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "uq_player_stats_game_player_identity",
        "player_stats",
        ["game_id", "team_name", "player_name"],
        unique=True,
    )


def downgrade():
    # Destroys all data. Only meaningful for an otherwise empty database.
    op.drop_table("player_stats")
    op.drop_table("games")
    op.drop_table("matches")
