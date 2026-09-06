from sqlalchemy import Column, Integer, String, Float, ForeignKey, inspect, text
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy import create_engine
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "valorant_stats.db"
DATABASE_URL = f"sqlite:///{DB_PATH}"

Base = declarative_base()

class Match(Base):
    __tablename__ = 'matches'
    
    id = Column(Integer, primary_key=True)
    vlr_match_id = Column(String, unique=True, index=True)
    team1_name = Column(String, nullable=False)
    team2_name = Column(String, nullable=False)
    
    team1_round_score = Column(String, nullable=True, default="0")
    team2_round_score = Column(String, nullable=True, default="0")
    
    # --- CHANGED BACK TO STRING ---
    start_time = Column(String)
    
    status = Column(String)
    team1_series_score = Column(Integer, default=0)
    team2_series_score = Column(Integer, default=0)
    map_vetoes_raw = Column(String, nullable=True)
    
    games = relationship("Game", back_populates="match", cascade="all, delete-orphan")
class Game(Base):
    __tablename__ = 'games'
    
    id = Column(Integer, primary_key=True)
    match_id = Column(Integer, ForeignKey('matches.id'))
    vlr_game_id = Column(String, nullable=True, index=True)
    map_number = Column(Integer, nullable=True)
    map_name = Column(String, nullable=False) 
    
    team1_round_score = Column(Integer, default=0)
    team2_round_score = Column(Integer, default=0)
    
    match = relationship("Match", back_populates="games")
    player_stats = relationship("PlayerStat", back_populates="game", cascade="all, delete-orphan")

class PlayerStat(Base):
    __tablename__ = 'player_stats'
    
    id = Column(Integer, primary_key=True)
    game_id = Column(Integer, ForeignKey('games.id'))
    
    player_name = Column(String, nullable=False)
    team_name = Column(String, nullable=False)
    role = Column(String, nullable=True) 
    
    acs = Column(Integer, default=0)
    kd_ratio = Column(Float, default=0.0)
    adr = Column(Integer, default=0)
    kills = Column(Integer, default=0)
    deaths = Column(Integer, default=0)
    assists = Column(Integer, default=0)
    plus_minus = Column(String, nullable=True)
    kast = Column(String, nullable=True)
    first_kills = Column(Integer, default=0)
    first_deaths = Column(Integer, default=0)
    
    game = relationship("Game", back_populates="player_stats")

engine = create_engine(DATABASE_URL)
Base.metadata.create_all(engine)

def migrate_player_stats_columns():
    existing_columns = {column["name"] for column in inspect(engine).get_columns("player_stats")}
    columns_to_add = {
        "kills": "INTEGER DEFAULT 0",
        "deaths": "INTEGER DEFAULT 0",
        "assists": "INTEGER DEFAULT 0",
        "plus_minus": "VARCHAR",
        "kast": "VARCHAR",
        "first_kills": "INTEGER DEFAULT 0",
        "first_deaths": "INTEGER DEFAULT 0"
    }

    with engine.begin() as connection:
        for column_name, column_type in columns_to_add.items():
            if column_name not in existing_columns:
                connection.execute(text(f"ALTER TABLE player_stats ADD COLUMN {column_name} {column_type}"))

migrate_player_stats_columns()

def migrate_game_columns():
    existing_columns = {column["name"] for column in inspect(engine).get_columns("games")}
    columns_to_add = {
        "vlr_game_id": "VARCHAR",
        "map_number": "INTEGER"
    }

    with engine.begin() as connection:
        for column_name, column_type in columns_to_add.items():
            if column_name not in existing_columns:
                connection.execute(text(f"ALTER TABLE games ADD COLUMN {column_name} {column_type}"))

migrate_game_columns()
