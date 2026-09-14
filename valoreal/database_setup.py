"""Database configuration and canonical SQLAlchemy schema for ValScores."""

import os
from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    create_engine,
    event,
)
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.types import TypeDecorator

from .time_contract import format_utc_timestamp, parse_utc_datetime


DATABASE_URL = os.environ.get("DATABASE_URL")


def configured_database_url() -> str:
    """Return the required runtime database URL with a useful startup error."""
    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL is required; configure a PostgreSQL URL such as "
            "postgresql+psycopg://user:password@localhost:5432/valscores"
        )
    return DATABASE_URL


Base = declarative_base()


class UTCDateTime(TypeDecorator):
    """Aware UTC datetime stored as TIMESTAMPTZ on PostgreSQL.

    SQLite's string representation exists solely so isolated unit tests exercise
    the same timezone-aware Python contract as production.
    """

    impl = DateTime
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "sqlite":
            return dialect.type_descriptor(String(32))
        return dialect.type_descriptor(DateTime(timezone=True))

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        parsed = parse_utc_datetime(value)
        if parsed is None:
            raise ValueError("start_time must be a timezone-aware datetime")
        if dialect.name == "sqlite":
            return format_utc_timestamp(parsed)
        return parsed

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if dialect.name == "sqlite":
            return parse_utc_datetime(value)
        if not isinstance(value, datetime):
            raise TypeError("database returned a non-datetime start_time")
        if value.tzinfo is None:
            raise ValueError("database returned a timezone-naive start_time")
        return value.astimezone(timezone.utc)


class Match(Base):
    __tablename__ = "matches"
    __table_args__ = (Index("ix_matches_vlr_match_id", "vlr_match_id", unique=True),)

    id = Column(Integer, primary_key=True)
    vlr_match_id = Column(String, nullable=False)
    team1_name = Column(String, nullable=False)
    team2_name = Column(String, nullable=False)
    team1_round_score = Column(String, nullable=True, default="0")
    team2_round_score = Column(String, nullable=True, default="0")
    # PostgreSQL stores an instant (TIMESTAMP WITH TIME ZONE); Python sees an
    # aware datetime and the API serializes that value as UTC.
    start_time = Column(UTCDateTime(), nullable=True)
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


def create_database_engine(database_url: str | None = None, **kwargs):
    """Build an engine for the configured database or an explicit test URL."""
    url = database_url or configured_database_url()
    kwargs.setdefault("pool_pre_ping", True)
    database_engine = create_engine(url, **kwargs)

    # SQLite is retained only for fast, isolated unit and legacy-migration tests.
    # PostgreSQL enforces foreign keys without a connection hook.
    if database_engine.dialect.name == "sqlite":
        @event.listens_for(database_engine, "connect")
        def enable_sqlite_foreign_keys(dbapi_connection, _connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return database_engine


def create_sqlite_engine(database_url: str, **kwargs):
    """Compatibility helper for explicitly isolated SQLite-only tests."""
    if not database_url.startswith("sqlite:"):
        raise ValueError("create_sqlite_engine accepts SQLite URLs only")
    return create_database_engine(database_url, **kwargs)


engine = create_database_engine()


def initialize_database(database_engine=engine) -> None:
    """Create the canonical schema in a fresh PostgreSQL database."""
    Base.metadata.create_all(database_engine)


def migrate_match_time_contract(database_engine=engine):
    """Explicit compatibility entry point for a legacy SQLite database only."""
    from .migrations import run_migrations

    run_migrations(database_engine)


if __name__ == "__main__":
    initialize_database()
