"""Canonical SQLAlchemy schema for ValScores."""

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.types import TypeDecorator

from ..domain.time_contract import format_utc_timestamp, parse_utc_datetime


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
    # Current-map round score while live. NULL means unknown, never 0-0.
    team1_round_score = Column(String, nullable=True)
    team2_round_score = Column(String, nullable=True)
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
    team1_round_score = Column(Integer, nullable=True)
    team2_round_score = Column(Integer, nullable=True)

    match = relationship("Match", back_populates="games")
    player_stats = relationship(
        "PlayerStat", back_populates="game", cascade="all, delete-orphan", passive_deletes=True
    )


class PlayerStat(Base):
    """Per-map player statistics. NULL means VLR did not report the value."""

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
    acs = Column(Integer, nullable=True)
    kd_ratio = Column(Float, nullable=True)
    adr = Column(Integer, nullable=True)
    kills = Column(Integer, nullable=True)
    deaths = Column(Integer, nullable=True)
    assists = Column(Integer, nullable=True)
    plus_minus = Column(String, nullable=True)
    kast = Column(String, nullable=True)
    first_kills = Column(Integer, nullable=True)
    first_deaths = Column(Integer, nullable=True)

    game = relationship("Game", back_populates="player_stats")
