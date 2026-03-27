import requests
from bs4 import BeautifulSoup
import time
from datetime import datetime
import json
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine
from database_setup import Match, Game, PlayerStat, Base


class VlrScraper:
    def __init__(self):
        self.headers = {
            'User-Agent': 'Mozilla/5.0'
        }
        self.base_url = "https://www.vlr.gg"

    def get_matches(self):
        url = f"{self.base_url}/matches"
        response = requests.get(url, headers=self.headers)
        soup = BeautifulSoup(response.text, 'html.parser')

        matches = []
        match_cards = soup.find_all('a', class_='match-item')

        for card in match_cards:
            match_url = self.base_url + card['href']

            teams = card.find_all('div', class_='match-item-vs-team-name')
            if len(teams) < 2:
                continue

            # 🔥 LIVE detection using ml-status
            ml_status = card.find('div', class_='ml-status')
            is_live = ml_status and "LIVE" in ml_status.text.upper()
            
            team1_round = "0"
            team2_round = "0"

            if is_live:
                try:
                    # 1. Fetch the specific match page to get live round scores
                    match_page = requests.get(match_url, headers=self.headers)
                    match_soup = BeautifulSoup(match_page.text, 'html.parser')
        
                    # 2. VLR usually puts the live round score in the header for active matches
                    score_container = match_soup.find('div', class_='js-spoiler')
        
                    if score_container:
                        # Extract the round scores
                        scores = score_container.find_all('span')
                        if len(scores) >= 2:
                            team1_round = scores[0].text.strip()
                            team2_round = scores[1].text.strip()
                except Exception as e:
                    print(f"Failed to fetch live round score for {match_url}: {e}")

            status_div = card.find('div', class_='match-item-status')
            status = "LIVE" if is_live else (status_div.text.strip() if status_div else "Unknown")

            # 🕒 Raw time string
            match_time_str = card.find('div', class_='match-item-time').text.strip()

            # 🔥 SCORE extraction from card (correct location)
            score_divs = card.find_all('div', class_='match-item-vs-team-score')

            team1_score = None
            team2_score = None

            if len(score_divs) >= 2:
                try:
                    team1_score = score_divs[0].text.strip()
                    team2_score = score_divs[1].text.strip()
                except:
                    pass

            matches.append({
                'team1': teams[0].text.strip(),
                'team2': teams[1].text.strip(),
                'time': match_time_str,
                'status': status,
                'is_live': is_live,
                'team1_score': team1_score,
                'team2_score': team2_score,
                'team1_round_score': team1_round,  # Pass the round scores to dictionary
                'team2_round_score': team2_round,
                'url': match_url
            })

        return matches

    def get_match_details(self, match_url):
        response = requests.get(match_url, headers=self.headers)
        soup = BeautifulSoup(response.text, 'html.parser')

        match_data = {
            'map_vetoes': [],
            'live_score': {},
            'player_stats': [],
            'exact_time': None
        }

        # 🕒 Exact timestamp
        time_div = soup.find('div', class_='moment-tz-convert')
        if time_div and time_div.has_attr('data-utc-ts'):
            match_data['exact_time'] = time_div['data-utc-ts']

        # 🗺️ Map vetoes
        veto_block = soup.find('div', class_='match-header-note')
        if veto_block:
            match_data['map_vetoes'] = [
                line.strip() for line in veto_block.text.split('\n') if line.strip()
            ]

        # ⚠️ Fallback score (less reliable than card)
        score_header = soup.find('div', class_='match-header-vs-score')
        if score_header:
            scores = score_header.find_all('div', class_='js-spoiler')
            if len(scores) >= 2:
                match_data['live_score'] = {
                    'team1': scores[0].text.strip(),
                    'team2': scores[1].text.strip()
                }

        # 👤 Player stats
        stats_container = soup.find('div', class_='vm-stats-game')
        if stats_container:
            rows = stats_container.find_all('tr')
            for row in rows[1:]:
                cols = row.find_all('td')
                if len(cols) > 5:
                    player_name_tag = cols[0].find('div', class_='text-of')
                    if not player_name_tag:
                        continue

                    deaths = cols[4].find('span', class_='mod-both').text.strip()
                    kills = cols[3].find('span', class_='mod-both').text.strip()

                    kd_ratio = "0.0"
                    try:
                        kd_ratio = str(round(int(kills) / int(deaths), 2)) if int(deaths) > 0 else kills
                    except:
                        pass

                    match_data['player_stats'].append({
                        'player': player_name_tag.text.strip(),
                        'team': cols[0].find('div', class_='ge-text-light').text.strip(),
                        'acs': cols[2].find('span', class_='mod-both').text.strip(),
                        'k_d': kd_ratio,
                        'adr': cols[8].find('span', class_='mod-both').text.strip() if len(cols) > 8 else "0"
                    })

        return match_data


# 🔌 DB setup
engine = create_engine('sqlite:///valorant_stats.db')
Session = sessionmaker(bind=engine)


def save_to_database(match_dict, details_dict):
    session = Session()
    try:
        match_id_string = match_dict['url'].replace("https://www.vlr.gg", "")
        db_match = session.query(Match).filter_by(vlr_match_id=match_id_string).first()

        best_time = details_dict.get('exact_time') or match_dict['time']

        if not db_match:
            db_match = Match(
                vlr_match_id=match_id_string,
                team1_name=match_dict['team1'],
                team2_name=match_dict['team2'],
                start_time=best_time,
                status=match_dict['status']
            )
            session.add(db_match)
        else:
            db_match.status = match_dict['status']
            db_match.start_time = best_time

        # 🔥 Assign the Round Scores from the dictionary
        db_match.team1_round_score = match_dict.get('team1_round_score', "0")
        db_match.team2_round_score = match_dict.get('team2_round_score', "0")

        # 🔥 PRIORITY: Use card score (best for LIVE)
        if match_dict.get('team1_score') and match_dict.get('team2_score'):
            try:
                db_match.team1_series_score = int(match_dict['team1_score'])
                db_match.team2_series_score = int(match_dict['team2_score'])
            except:
                pass

        # 🔁 Fallback: use match page score
        elif details_dict.get('live_score'):
            try:
                db_match.team1_series_score = int(details_dict['live_score'].get('team1', 0))
                db_match.team2_series_score = int(details_dict['live_score'].get('team2', 0))
            except:
                pass

        if details_dict.get('map_vetoes'):
            db_match.map_vetoes_raw = json.dumps(details_dict['map_vetoes'])

        session.flush()

        # 🎮 Ensure game exists
        db_game = session.query(Game).filter_by(match_id=db_match.id, map_name="Overall").first()
        if not db_game:
            db_game = Game(match_id=db_match.id, map_name="Overall")
            session.add(db_game)
            session.flush()

        # 👤 Save players
        for p_data in details_dict.get('player_stats', []):
            db_player = session.query(PlayerStat).filter_by(
                game_id=db_game.id,
                player_name=p_data['player']
            ).first()

            if not db_player:
                db_player = PlayerStat(
                    game_id=db_game.id,
                    player_name=p_data['player']
                )
                session.add(db_player)

            db_player.team_name = p_data['team']
            db_player.acs = int(p_data['acs']) if p_data['acs'].isdigit() else 0

            try:
                db_player.kd_ratio = float(p_data.get('k_d', '0'))
            except:
                db_player.kd_ratio = 0.0

            db_player.adr = int(p_data.get('adr', '0')) if p_data.get('adr', '0').isdigit() else 0

        session.commit()
        print(f"✅ Saved: {db_match.team1_name} vs {db_match.team2_name} | {db_match.team1_series_score}-{db_match.team2_series_score}")

    except Exception as e:
        session.rollback()
        print(f"❌ Error: {e}")
    finally:
        session.close()


if __name__ == "__main__":
    scraper = VlrScraper()
    matches = scraper.get_matches()

    for match in matches[:10]:  # grab more matches
        details = scraper.get_match_details(match['url'])
        save_to_database(match, details)
        time.sleep(1.5)
