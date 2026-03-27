# database_setup.py
from sqlalchemy import Column, Integer, String, Float, ForeignKey, DateTime
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy import create_engine
import datetime
from sqlalchemy import Column, Integer, String, Float, ForeignKey
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy import create_engine

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
    
    game = relationship("Game", back_populates="player_stats")

engine = create_engine('sqlite:///valorant_stats.db')
Base.metadata.create_all(engine)
print("Database created successfully!")
