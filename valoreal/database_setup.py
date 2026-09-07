import os
from pathlib import Path

from sqlalchemy import Column, Float, ForeignKey, Index, Integer, String, create_engine, event
from sqlalchemy.orm import declarative_base, relationship

from .migrations import run_migrations


DB_PATH = Path(__file__).resolve().parent / "valorant_stats.db"
_configured_database_path = os.environ.get("VALSCORES_DATABASE_PATH")
DATABASE_URL = os.environ.get(
    "VALSCORES_DATABASE_URL",
    f"sqlite:///{_configured_database_path or DB_PATH}",
)

Base = declarative_base()


class Match(Base):
    __tablename__ = "matches"
    __table_args__ = (Index("ix_matches_vlr_match_id", "vlr_match_id", unique=True),)

    id = Column(Integer, primary_key=True)
    vlr_match_id = Column(String, nullable=False)
    team1_name = Column(String, nullable=False)
    team2_name = Column(String, nullable=False)
    team1_round_score = Column(String, nullable=True, default="0")
    team2_round_score = Column(String, nullable=True, default="0")
    # Canonical ISO-8601 UTC timestamp, for example 2026-09-06T13:00:00Z.
    start_time = Column(String, nullable=True)
    # Preserves pre-contract values that cannot be interpreted safely.
    legacy_start_time = Column(String, nullable=True)
    status = Column(String, nullable=True)
    # NULL means the series has not started or no trustworthy score is known.
    team1_series_score = Column(Integer, nullable=True)
    team2_series_score = Column(Integer, nullable=True)
    map_vetoes_raw = Column(String, nullable=True)

    games = relationship(
        "Game", back_populates="match", cascade="all, delete-orphan", passive_deletes=True
    )


class Game(Base):
    __tablename__ = "games"
    __table_args__ = (
        Index("uq_games_match_id_vlr_game_id", "match_id", "vlr_game_id", unique=True),
        Index("ix_games_vlr_game_id", "vlr_game_id"),
    )

    id = Column(Integer, primary_key=True)
    match_id = Column(Integer, ForeignKey("matches.id", ondelete="CASCADE"), nullable=False)
    vlr_game_id = Column(String, nullable=False)
    map_number = Column(Integer, nullable=True)
    map_name = Column(String, nullable=False)
    team1_round_score = Column(Integer, nullable=True, default=0)
    team2_round_score = Column(Integer, nullable=True, default=0)

    match = relationship("Match", back_populates="games")
    player_stats = relationship(
        "PlayerStat", back_populates="game", cascade="all, delete-orphan", passive_deletes=True
    )


class PlayerStat(Base):
    __tablename__ = "player_stats"
    __table_args__ = (
        # No stable player ID is currently persisted. Team plus display name is
        # therefore the strongest available player identity.
        Index(
            "uq_player_stats_game_player_identity",
            "game_id",
            "team_name",
            "player_name",
            unique=True,
        ),
    )

    id = Column(Integer, primary_key=True)
    game_id = Column(Integer, ForeignKey("games.id", ondelete="CASCADE"), nullable=False)
    player_name = Column(String, nullable=False)
    team_name = Column(String, nullable=False)
    role = Column(String, nullable=True)
    acs = Column(Integer, nullable=True, default=0)
    kd_ratio = Column(Float, nullable=True, default=0.0)
    adr = Column(Integer, nullable=True, default=0)
    kills = Column(Integer, nullable=True, default=0)
    deaths = Column(Integer, nullable=True, default=0)
    assists = Column(Integer, nullable=True, default=0)
    plus_minus = Column(String, nullable=True)
    kast = Column(String, nullable=True)
    first_kills = Column(Integer, nullable=True, default=0)
    first_deaths = Column(Integer, nullable=True, default=0)

    game = relationship("Game", back_populates="player_stats")


def create_sqlite_engine(database_url=DATABASE_URL, **kwargs):
    database_engine = create_engine(database_url, **kwargs)

    @event.listens_for(database_engine, "connect")
    def enable_sqlite_foreign_keys(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return database_engine


engine = create_sqlite_engine()
run_migrations(engine)


def migrate_match_time_contract():
    """Compatibility entry point; timestamp migration is now schema-versioned."""
    run_migrations(engine)
