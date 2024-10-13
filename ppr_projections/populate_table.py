import requests 
import sqlite3 
from datetime import datetime 
import os 
import pytz

SELECTED_BOOK = 'fanduel'
DATABASE_NAME = 'odds.db'
TABLE_NAME = 'fanduel_props'
API_KEY = os.getenv('THE_ODDS_API_KEY')  # Ensure this environment variable is set
SPORT = 'americanfootball_nfl'
MARKETS = [
    'player_anytime_td', 'player_pass_tds', 'player_pass_yds', 'player_pass_completions',
    'player_pass_attempts', 'player_pass_interceptions', 'player_rush_yds',
    'player_rush_attempts', 'player_receptions', 'player_reception_yds',
    'player_kicking_points','player_tds_over'
]

def remove_commenced_games():
    """
    Removes games from the database that have already commenced based on the current Eastern Time.
    """
    try:
        conn = sqlite3.connect(DATABASE_NAME)
        c = conn.cursor()

        # Get current time in ET
        current_time = datetime.now(pytz.timezone('US/Eastern'))

        # Remove games that have already commenced
        c.execute(f'DELETE FROM {TABLE_NAME} WHERE event_commence_time < ?', (current_time,))

        conn.commit()
        conn.close()
        print("Removed commenced games from the database.")
    except Exception as e:
        print(f"Error removing commenced games: {e}")
def convert_utc_to_et(utc_time_str):
    """
    Convert UTC time string to Eastern Time (ET).

    Parameters:
        utc_time_str (str): UTC time in the format "%Y-%m-%dT%H:%M:%SZ".

    Returns:
        str: Converted ET time in the format "%Y-%m-%d %H:%M:%S %Z".
    """
    try:
        utc_time = datetime.strptime(utc_time_str, "%Y-%m-%dT%H:%M:%SZ")
        utc_time = pytz.utc.localize(utc_time)
        et_time = utc_time.astimezone(pytz.timezone('America/New_York'))
        return et_time.strftime("%Y-%m-%d %H:%M:%S %Z")
    except Exception as e:
        print(f"Error converting UTC to ET: {e}")
        return ""

def fetch_props(eventId, sport):
    """
    Fetch player props for a specific event and sport from The Odds API.

    Parameters:
        eventId (str): The ID of the event.
        sport (str): The sport key.

    Returns:
        list: A list of props data or an empty list if an error occurs.
    """
    url =  f"https://api.the-odds-api.com/v4/sports/{sport}/events/{eventId}/odds"
    params = {
        "apiKey": API_KEY,
        "regions": "us",
        "markets": ','.join(MARKETS),
        "oddsFormat": "american",
        "bookmakers": SELECTED_BOOK
    }
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.HTTPError as http_err:
        print(f"HTTP error occurred while fetching props for event ID {eventId}: {http_err}")
        return []
    except Exception as err:
        print(f"Other error occurred while fetching props for event ID {eventId}: {err}")
        return []

def get_events(sport):
    """
    Fetch all events for a specific sport from The Odds API and convert their commence times to ET.

    Parameters:
        sport (str): The sport key.

    Returns:
        list: A list of events with their commence times in ET.
    """
    params = {'apiKey': API_KEY}
    url = f'https://api.the-odds-api.com/v4/sports/{sport}/events'
    try:
        response = requests.get(url, params=params)
        eastern = pytz.timezone('America/New_York')
        now_eastern = datetime.now(eastern)
        today_date = now_eastern.date()
        response.raise_for_status()
        events = response.json()
        filtered_events = []
        for game in events:
            game['commence_time_edt'] = convert_utc_to_et(game['commence_time'])[:-4]
            if not game['commence_time_edt']:
                continue  # Skip if conversion failed
            game_time_edt = datetime.strptime(game['commence_time_edt'], '%Y-%m-%d %H:%M:%S')
            game_time_eastern = eastern.localize(game_time_edt)
            if (game_time_eastern.date() == today_date and game_time_eastern > now_eastern) or game_time_eastern.date() != today_date:
                filtered_events.append(game)
        print(f"Fetched and filtered {len(filtered_events)} events for sport: {sport}")
        return filtered_events
    except requests.exceptions.HTTPError as http_err:
        print(f"HTTP error occurred while fetching events: {http_err}")
        return []
    except Exception as err:
        print(f"Other error occurred while fetching events: {err}")
        return []

def store_props(props):
    """
    Store player props data into the SQLite database.

    Parameters:
        props (dict): Props data fetched from the API.
    """
    global TABLE_NAME
    try:
        conn = sqlite3.connect(DATABASE_NAME)
        c = conn.cursor()

        bookmakers = props.get('bookmakers', [])
        event_commence_time = convert_utc_to_et(props.get('commence_time', ''))
        event_name = f"{props.get('away_team', '')} @ {props.get('home_team', '')}"
        sport_key = props.get('sport_key', '')
        event_id = props.get('id', '')


        # Create table if it doesn't exist
        c.execute(f'''
            CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
                event_id TEXT,
                event_name TEXT,
                sport_key TEXT,
                market_type TEXT,
                outcome_type TEXT,
                player_name TEXT,
                point_value REAL,
                odds REAL,
                event_commence_time TEXT,
                updated_dttm TEXT,
                PRIMARY KEY (event_id, market_type, outcome_type, player_name)
            )
        ''')

        for bookmaker in bookmakers:
            if bookmaker['key'] != SELECTED_BOOK:
                continue  # Only store props for the selected bookmaker

            markets = bookmaker.get('markets', [])
            for m in markets:
                market_type = m.get('key', '')
                updated_dttm = convert_utc_to_et(m.get('last_update', ''))
                outcomes = m.get('outcomes', [])
                for o in outcomes:
                    player_name = o.get('description', '')
                    outcome_type = o.get('name', '')
                    odds = o.get('price', None)
                    point_value = o.get('point', None)
                    c.execute(f'''
                        INSERT OR REPLACE INTO {TABLE_NAME} 
                        (event_id, event_name, sport_key, market_type, outcome_type, player_name, point_value, odds, event_commence_time, updated_dttm)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', 
                    (event_id, event_name, sport_key, market_type, outcome_type, player_name, point_value, odds, event_commence_time, updated_dttm))
        
        conn.commit()
        conn.close()
        print(f"Stored props for event ID: {event_id}")
    except Exception as e:
        print(f"Error storing props to database: {e}")

def main(): 
    if not API_KEY:
        print("API key for The Odds API not found. Please set 'THE_ODDS_API_KEY' environment variable.")
        raise EnvironmentError("API key for The Odds API not found. Please set 'THE_ODDS_API_KEY' environment variable.")
    
    events = get_events(SPORT)
    for event in events: 
        event_name = f"{event.get('away_team', '')} @ {event.get('home_team', '')}"
        props = fetch_props(event['id'], event['sport_key'])
        if not props:
            continue 
        remove_commenced_games()
        store_props(props)

        print(f"Props stored for: {event_name}")


if __name__ == "__main__":
    main()
