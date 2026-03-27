from fastapi import FastAPI, HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from typing import List
from datetime import datetime
from vlreal import VlrScraper, save_to_database
import time

from database_setup import Match, Game, PlayerStat

app = FastAPI()

engine = create_engine('sqlite:///valorant_stats.db')
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

@app.get("/api/matches/timeline")
def get_timeline():
    """Powers the main Games Timeline view."""
    session = SessionLocal()
    try:
        matches = session.query(Match).order_by(Match.start_time).all()
        
        result = []
        for match in matches:
            display_time = "TBD"
            date_label = "TBD"
            
            try:
                if match.start_time:
                    # Replace space with T to normalize format
                    normalized_time = match.start_time.replace(" ", "T")
                    dt_object = datetime.fromisoformat(normalized_time)

                    display_time = dt_object.strftime("%I:%M %p")
                    date_label = dt_object.strftime("%b ") + str(dt_object.day)
            except ValueError:
                pass

            status_upper = match.status.upper() if match.status else ""
            show_score = "LIVE" in status_upper or "COMPLETED" in status_upper
            is_live = "LIVE" in status_upper

            result.append({
                "id": match.id,
                "team1": match.team1_name,
                "team2": match.team2_name,
                "team1_score": str(match.team1_series_score or ""),
                "team2_score": str(match.team2_series_score or ""),
                "team1_round_score": match.team1_round_score,
                "team2_round_score": match.team2_round_score,
                "status": match.status,
                "time": display_time,
                "date_label": date_label,
                "is_live": is_live
                 # <--- NEW: Send the date label to Swift!
            })
        return result
    finally:
        session.close()

@app.get("/api/matches/{match_id}/stats")
def get_match_stats(match_id: int):
    """Powers the 'Game', 'SEN', and 'PRX' tabs."""
    session = SessionLocal()
    try:
        match = session.query(Match).filter(Match.id == match_id).first()
        if not match:
            raise HTTPException(status_code=404, detail="Match not found")
            
        # Get the first game (map) for this example
        game = session.query(Game).filter(Game.match_id == match.id).first()
        
        if not game:
            return {"message": "No map data available yet."}

        # Get players
        players = session.query(PlayerStat).filter(PlayerStat.game_id == game.id).all()
        
        team1_stats = [p for p in players if p.team_name == match.team1_name]
        team2_stats = [p for p in players if p.team_name == match.team2_name]

        import json

        return {
            "match_info": {
                "team1": match.team1_name,
                "team2": match.team2_name,
                "map_vetoes": json.loads(match.map_vetoes_raw) if match.map_vetoes_raw else []
            },
            "team1_roster": [{"name": p.player_name, "acs": p.acs, "kd": p.kd_ratio} for p in team1_stats],
            "team2_roster": [{"name": p.player_name, "acs": p.acs, "kd": p.kd_ratio} for p in team2_stats]
        }
    finally:
        session.close()

@app.get("/api/matches/refresh")
def force_refresh_matches():
    print("Forcing a manual scrape...")
    scraper = VlrScraper()
    matches = scraper.get_matches()
    
    # 👇 Add this loop to actually save the data to your database
    for match in matches[:10]:  # limiting to 10 to keep the API response reasonably fast
        details = scraper.get_match_details(match['url'])
        save_to_database(match, details)
        time.sleep(1) # Be nice to VLR to avoid rate limits!

    return {"message": "Database successfully updated!"}
