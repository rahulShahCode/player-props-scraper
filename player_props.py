import requests
from datetime import datetime
import pytz
import os
from dotenv import load_dotenv
import pandas as pd
import sqlite3
import openpyxl
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,  # Set the logging level to INFO
    format='%(asctime)s - %(levelname)s - %(message)s',  # Define the log message format
    datefmt='%Y-%m-%d %H:%M:%S',  # Define the date format
    handlers=[
        logging.FileHandler("scraper.log"),  # Log messages will be written to 'scraper.log'
        logging.StreamHandler()  # Also output logs to the console
    ]
)

logger = logging.getLogger(__name__)

# Define Constants
MY_BOOKMAKERS = ['fanduel', 'draftkings', 'espnbet', 'williamhill_us', 'betmgm', 'betrivers', 'hardrockbet', 'pinnacle']
SELECTED_BOOK = 'pinnacle'
ATD_DELTA = 0.01
load_dotenv()
API_KEY = os.getenv('THE_ODDS_API_KEY')  # Ensure this environment variable is set
SPORTS = ['americanfootball_nfl']
QUOTA_USED = 0
MARKETS = [
    'player_anytime_td', 'player_pass_tds', 'player_pass_yds', 'player_pass_completions',
    'player_pass_attempts', 'player_pass_interceptions', 'player_rush_yds',
    'player_rush_attempts', 'player_receptions', 'player_reception_yds',
    'player_kicking_points'
]
DATABASE_NAME = 'odds.db'
HTML_OUTPUT = "index.html"
EXCEL_OUTPUT = "player_props.xlsx"

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
        c.execute('DELETE FROM player_props WHERE event_commence_time < ?', (current_time,))

        conn.commit()
        conn.close()
        logger.info("Removed commenced games from the database.")
    except Exception as e:
        logger.error(f"Error removing commenced games: {e}")

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
        logger.error(f"Error converting UTC to ET: {e}")
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
    global QUOTA_USED
    url =  f"https://api.the-odds-api.com/v4/sports/{sport}/events/{eventId}/odds"
    params = {
        "apiKey": API_KEY,
        "regions": "us",
        "markets": ','.join(MARKETS),
        "oddsFormat": "american",
        "bookmakers": ','.join(MY_BOOKMAKERS)
    }
    try:
        response = requests.get(url, params=params)
        quota = int(response.headers.get('x-requests-last', 0))
        QUOTA_USED += quota

        response.raise_for_status()
        return response.json()
    except requests.exceptions.HTTPError as http_err:
        logger.error(f"HTTP error occurred while fetching props for event ID {eventId}: {http_err}")
        return []
    except Exception as err:
        logger.error(f"Other error occurred while fetching props for event ID {eventId}: {err}")
        return []

def get_events(sport):
    """
    Fetch all events for a specific sport from The Odds API and convert their commence times to ET.

    Parameters:
        sport (str): The sport key.

    Returns:
        list: A list of events with their commence times in ET.
    """
    global QUOTA_USED 
    params = {'apiKey': API_KEY}
    url = f'https://api.the-odds-api.com/v4/sports/{sport}/events'
    try:
        response = requests.get(url, params=params)
        quota = int(response.headers.get('x-requests-last', 0))
        QUOTA_USED += quota

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
        logger.info(f"Fetched and filtered {len(filtered_events)} events for sport: {sport}")
        return filtered_events
    except requests.exceptions.HTTPError as http_err:
        logger.error(f"HTTP error occurred while fetching events: {http_err}")
        return []
    except Exception as err:
        logger.error(f"Other error occurred while fetching events: {err}")
        return []

def get_todays_events(events):
    """
    Filter events to include only those occurring today and have not yet commenced.

    Parameters:
        events (list): A list of events with ET commence times.

    Returns:
        list: A list of today's upcoming events.
    """
    eastern = pytz.timezone('America/New_York')
    now_eastern = datetime.now(eastern)
    today_date = now_eastern.date()

    today_events = []
    for game in events:
        try:
            game_time_edt = datetime.strptime(game['commence_time_edt'], '%Y-%m-%d %H:%M:%S')
            game_time_eastern = eastern.localize(game_time_edt)
            if game_time_eastern.date() == today_date and game_time_eastern > now_eastern:
                today_events.append(game)
        except Exception as e:
            logger.error(f"Error parsing game time: {e}")
            continue
    logger.info(f"Filtered down to {len(today_events)} today's events.")
    return today_events

def american_to_implied(odds):
    """
    Convert American odds to implied probability.

    Parameters:
        odds (int): The American odds.

    Returns:
        float: The implied probability.
    """
    if odds == 0:
        raise ValueError("Odds cannot be zero.")
    if odds > 0:
        return 100 / (odds + 100)
    else:
        return abs(odds) / (abs(odds) + 100)
    
def get_projected_value(over_odds, under_odds, point_value):
    over_prob = american_to_implied(over_odds)
    under_prob = american_to_implied(under_odds)
    total_prob = over_prob + under_prob
    normalized_over_prob = over_prob / total_prob
    normalized_under_prob = under_prob / total_prob
    return (normalized_over_prob * (point_value + 0.5)) + (normalized_under_prob * (point_value - 0.5))

def add_projected_values(outcomes):
    result = []
    # Group by description and check for Over/Under
    descriptions = set([outcome['description'] for outcome in outcomes])
    for desc in descriptions:
        over = next((o for o in outcomes if o['description'] == desc and o['name'].lower() == 'over'), None)
        under = next((u for u in outcomes if u['description'] == desc and u['name'].lower() == 'under'), None)
        
        if over and under:
            projected_value = get_projected_value(over['price'], under['price'], over['point'])
            over['projected_value'] = projected_value
            under['projected_value'] = projected_value
            result.append(over)
            result.append(under)
    if len(result) == 0:
        result = outcomes
    return result


def transform_string(input_str):
    """
    Transform a market key string into a more readable format.

    Parameters:
        input_str (str): The market key string.

    Returns:
        str: The transformed string.
    """
    parts = input_str.split('_')
    if len(parts) > 1:
        transformed_str = parts[1].capitalize()
    else:
        transformed_str = parts[0].capitalize()
    if len(parts) > 2:
        transformed_str += ' ' + ' '.join([word.capitalize() for word in parts[2:]])
    return transformed_str

def calculate_point_delta(outcome, pin_outcome):
    """
    Calculate the point delta between current outcome and pinnacle outcome.

    Parameters:
        outcome (dict): Current outcome data.
        pin_outcome (dict): Pinnacle outcome data.

    Returns:
        float or None: The point delta or None if not applicable.
    """
    point_delta = None 
    has_point_val = 'point' in outcome 
    if outcome.get('name') == 'Over' and has_point_val:
        point_delta = pin_outcome.get('point', 0) - outcome.get('point', 0)
    elif has_point_val: 
        point_delta = outcome.get('point', 0) - pin_outcome.get('point', 0)
    return point_delta

def find_favorable_lines(props, event_name: str, commence_time: str):
    """
    Identify favorable betting lines by comparing current props with earliest entries in the database.

    Parameters:
        props (dict): Props data fetched from the API.
        event_name (str): The name of the event.
        commence_time (str): The commencement time of the event.

    Returns:
        list: A list containing two lists - [results_with_different_points, results_with_same_points]
    """
    results_with_different_points = []
    results_with_same_points = []
    bookmakers = props.get('bookmakers', [])

    pinnacle_data = next((b for b in bookmakers if b['key'] == 'pinnacle'), None)

    if not pinnacle_data:
        logger.warning("Pinnacle data not found for event.")
        return None 

    try:
        conn = sqlite3.connect(DATABASE_NAME)
        c = conn.cursor()

        for bookmaker in bookmakers:
            if bookmaker['key'] == 'pinnacle':
                continue  # Skip Pinnacle

            for market in bookmaker.get('markets', []):
                pinnacle_market = next((m for m in pinnacle_data.get('markets', []) if m['key'] == market['key']), None)
                if not pinnacle_market:
                    continue  # Pinnacle lines don't exist

                bet_type = transform_string(market['key'])  
                outcomes = market.get('outcomes',[])
                outcomes = add_projected_values(outcomes)
                pinnacle_outcomes = add_projected_values(pinnacle_market.get('outcomes', []))
                for outcome in outcomes:
                    pin_outcome = next((o for o in pinnacle_outcomes
                                        if o['description'] == outcome.get('description') and o['name'] == outcome.get('name')), None)
                    if not pin_outcome:
                        continue  
                     # over_under_exists = any(d['name'] == 'Over' for d in outcome) and any(d['name'] == 'Under' for d in outcome)
                    try:
                        pin_prob = american_to_implied(pin_outcome['price'])
                        other_prob = american_to_implied(outcome['price'])
                    except ValueError as ve:
                        logger.error(f"Error calculating implied probability: {ve}")
                        continue

                    prob_delta = pin_prob - other_prob  # Now a decimal

                    point_delta = calculate_point_delta(outcome, pin_outcome)

                    # Initialize is_favorable as None
                    is_favorable = None

                    # Determine is_favorable based on conditions
                    outcome_type = outcome.get('name')
                    player_name = outcome.get('description')
                    market_type = market.get('key')
                    current_point = outcome.get('point', None)
                    current_odds = outcome.get('price', None)
                    projected_value = outcome.get('projected_value', None)
                    pin_projected_value = pin_outcome.get('projected_value', None)
                    projected_val_delta = None 
                    pin_current_point = pin_outcome.get('point', None)
                    pin_current_odds = pin_outcome.get('price', None)
                    point_move = None 
                    odds_pct_move = None 

                    if pin_projected_value is not None and projected_value is not None: 
                        projected_val_delta = pin_projected_value - projected_value

                    if outcome_type in ['Over', 'Under', 'Yes']:
                        # Fetch earliest matching entry from the database
                        c.execute('''
                            SELECT point_value, odds FROM player_props 
                            WHERE market_type=? AND outcome_type=? AND player_name=?
                            ORDER BY updated_dttm ASC LIMIT 1
                        ''', (market_type, outcome_type, player_name))
                        earliest = c.fetchone()

                        if earliest:
                            earliest_point, earliest_odds = earliest
                            if pin_current_point is not None and earliest_point is not None:
                                point_move = pin_current_point - earliest_point
                            odds_pct_move = american_to_implied(pin_current_odds) - american_to_implied(earliest_odds)
                            if outcome_type == 'Over':
                                if pin_current_point is not None and earliest_point is not None:
                                    if pin_current_point > earliest_point:
                                        is_favorable = 'Y'
                                    elif pin_current_point == earliest_point and pin_current_odds < earliest_odds:
                                        is_favorable = 'Y'
                                    else:
                                        is_favorable = 'N'
                            elif outcome_type == 'Under':
                                if pin_current_point is not None and earliest_point is not None:
                                    if pin_current_point < earliest_point:
                                        is_favorable = 'Y'
                                    elif pin_current_point == earliest_point and pin_current_odds < earliest_odds:
                                        is_favorable = 'Y'
                                    else:
                                        is_favorable = 'N'
                            elif outcome_type == 'Yes':
                                if pin_current_odds is not None and earliest_odds is not None:
                                    if pin_current_odds < earliest_odds:
                                        is_favorable = 'Y'
                                    else:
                                        is_favorable = 'N'
                        else:
                            is_favorable = None  # No earlier entry to compare
                    else:
                        is_favorable = None  # Ignore 'No' scenario
                    abs_point_move, abs_proj_delta = None, None
                    if point_move is not None: 
                        abs_point_move = abs(point_move)
                    if projected_val_delta is not None:
                        abs_proj_delta = abs(projected_val_delta)
                    # Prepare result entry
                    result_entry = {
                        "commence_time": commence_time,
                        "event_name": event_name,
                        "source": bookmaker.get('title'),
                        "player": outcome.get('description'),
                        "type": outcome.get('name'),
                        "bet_type": bet_type,
                        "odds": outcome.get('price'),
                        "delta": prob_delta,  # Now a decimal
                        "is_favorable": is_favorable,
                        "point_move" : point_move,
                        "projected_value" : projected_value,
                        "pinnacle_projected_val" : pin_projected_value,
                        "projected_val_delta" : projected_val_delta,
                        "point_move" : point_move,
                        "odds_pct_move" : odds_pct_move,
                        "abs_point_move" : abs_point_move,
                        "abs_proj_delta" : abs_proj_delta
                    }

                    if 'point' in outcome and outcome['point'] is not None:
                        result_entry['point'] = outcome['point']
                        result_entry['pinnacle'] = f"{pin_outcome['description']} {pin_outcome['name']} {pin_outcome.get('point', '')} @ {pin_outcome['price']}"
                    else:
                        result_entry['pinnacle'] = f"{pin_outcome['description']} {pin_outcome['name']} @ {pin_outcome['price']}"

                    if point_delta is not None:
                        result_entry["point_delta"] = point_delta
                    else:
                        result_entry["point_delta"] = 0  # Default value when point_delta is not applicable

                    # Determine if the line is more favorable for inclusion in results
                    if outcome_type not in ['No', 'Yes', 'Under', 'Over']:
                        continue  # Skip irrelevant types

                    # Categorize results based on existing logic
                    if not ('point' in outcome and outcome['point'] is not None):
                        if outcome_type != 'No' and prob_delta >= ATD_DELTA and pin_outcome['price'] <= 300:
                            results_with_same_points.append(result_entry)
                    else:
                        if ((outcome_type == "Over" and current_point < pin_outcome.get('point', 0)) or
                            (outcome_type == "Under" and current_point > pin_outcome.get('point', 0))) and \
                            pin_prob >= 0.5 and (point_delta >= 1 or prob_delta >= 2):
                            results_with_different_points.append(result_entry)
                        elif current_point == pin_outcome.get('point', 0) and prob_delta > 3:
                            results_with_same_points.append(result_entry)
    except Exception as e:
        logger.error(f"Error finding favorable lines: {e}")
    finally:
        conn.close()

    # Sort results by Point Delta descending, then by Odds Percentage Delta descending
    results_with_different_points.sort(key=lambda x: (x.get('point_delta', 0), x['delta']), reverse=True)
    results_with_same_points.sort(key=lambda x: (x.get('point_delta', 0), x['delta']), reverse=True)

    return [results_with_different_points, results_with_same_points]

def output_to_html(diff_pts: list, same_pts: list):
    """
    Generate HTML tables for the filtered and sorted betting lines.

    Parameters:
        diff_pts (list): List of results with different points.
        same_pts (list): List of results with same points.
    """
    df_diff_pts = pd.DataFrame(diff_pts)
    df_same_pts = pd.DataFrame(same_pts)
    col_names = {
        'commence_time': 'Start Time', 
        'event_name': 'Event',
        'source': 'Book',
        'player': 'Player',
        'type': 'Outcome',
        'bet_type': 'Prop',
        'point': 'Point',
        'odds': 'Odds',
        'pinnacle': 'Pinnacle Odds',
        'delta': 'Odds % Delta',
        'point_delta': 'Point Delta',
        'is_favorable': 'Is Favorable'
    }
    # Data Cleaning 
    if not df_diff_pts.empty:
        df_diff_pts = df_diff_pts.rename(columns=col_names)
        # Define desired column order
        desired_order = [
            'Start Time',
            'Event',
            'Book',
            'Player',
            'Outcome',
            'Prop',
            'Point',
            'Odds',
            'Pinnacle Odds',
            'Point Delta',
            'Odds % Delta',
            'Is Favorable'
        ]
        df_diff_pts = df_diff_pts[desired_order]
        df_diff_pts['Start Time'] = pd.to_datetime(df_diff_pts['Start Time'])
        df_diff_pts['Odds % Delta'] = df_diff_pts['Odds % Delta'].apply(lambda x: f"{round(x, 2)}%")
    
    if not df_same_pts.empty:
        df_same_pts = df_same_pts.rename(columns=col_names)
        # Define desired column order
        desired_order = [
            'Start Time',
            'Event',
            'Book',
            'Player',
            'Outcome',
            'Prop',
            'Point',
            'Odds',
            'Pinnacle Odds',
            'Point Delta',
            'Odds % Delta',
            'Is Favorable'
        ]
        # Ensure all columns in desired_order exist in the dataframe
        for col in desired_order:
            if col not in df_same_pts.columns:
                df_same_pts[col] = 0  # or a default value like 0 or pd.NA
        df_same_pts = df_same_pts[desired_order]
        df_same_pts['Start Time'] = pd.to_datetime(df_same_pts['Start Time'])
        df_same_pts['Odds % Delta'] = df_same_pts['Odds % Delta'].apply(lambda x: f"{round(x, 2)}%")

    # Convert DataFrames to HTML tables
    diff_pts_html = df_diff_pts.to_html(index=False, classes='table table-striped table-bordered diff-pts-table') if not df_diff_pts.empty else "<p>No Diff Points available.</p>"
    same_pts_html = df_same_pts.to_html(index=False, classes='table table-striped table-bordered same-pts-table') if not df_same_pts.empty else "<p>No Same Points available.</p>"

    # Bootstrap and DataTables CSS and JS
    bootstrap_css = """
    <link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/4.0.0/css/bootstrap.min.css">
    <link rel="stylesheet" href="https://cdn.datatables.net/1.11.5/css/jquery.dataTables.min.css">
    <script src="https://code.jquery.com/jquery-3.5.1.js"></script>
    <script src="https://cdn.datatables.net/1.11.5/js/jquery.dataTables.min.js"></script>
    <script>
        $(document).ready(function() {
            if ($('.diff-pts-table thead tr th').length) {
                $('.diff-pts-table').DataTable();
            }
            
            if ($('.same-pts-table thead tr th').length) {
                $('.same-pts-table').DataTable();
            }
        });
    </script>
    <style>
    body {
        font-family: Arial, sans-serif;
        margin: 20px;
        background-color: #f9f9f9;
    }
    h2 {
        color: #4A90E2;
        font-family: 'Trebuchet MS', sans-serif;
        text-align: center;
        font-size: 1.5em;
        margin-top: 20px;
    }
    .container {
        width: 90%;
        margin: auto;
        padding: 20px;
        background-color: white;
        border-radius: 8px;
        box-shadow: 0 0 10px rgba(0, 0, 0, 0.1);
    }
    .table {
        margin: 20px 0;
        width: 100%;
    }
    </style>
    """

    html_content = f"""
    {bootstrap_css}
    <div class='container'>
        <h2>Diff Points</h2>
        {diff_pts_html}
        <h2>Same Points</h2>
        {same_pts_html}
    </div>
    """

    # Write HTML to a file
    try:
        with open(HTML_OUTPUT, "w") as file:
            file.write(html_content)
        logger.info(f"HTML file with combined bets has been saved as '{HTML_OUTPUT}'")
    except Exception as e:
        logger.error(f"Error writing HTML file: {e}")

    # Proceed to save data to Excel
    save_to_excel(diff_pts, same_pts)

def save_to_excel(diff_pts, same_pts, filename=EXCEL_OUTPUT):
    """
    Save the filtered and sorted betting lines to an Excel file with proper formatting, filters, and sorting.

    Parameters:
        diff_pts (list): List of results with different points.
        same_pts (list): List of results with same points.
        filename (str): The name of the Excel file to create.
    """
    try:
        # Convert lists to DataFrames
        df_diff = pd.DataFrame(diff_pts)
        df_same = pd.DataFrame(same_pts)
        df_diff = df_diff[df_diff['is_favorable'] == 'Y']
        # Define column renaming
        col_names = {
            'commence_time': 'Start Time', 
            'event_name': 'Event',
            'source': 'Book',
            'player': 'Player',
            'type': 'Outcome',
            'bet_type': 'Prop',
            'point': 'Point',
            'odds': 'Odds',
            'pinnacle': 'Pinnacle Odds',
            'delta': 'Odds % Delta',
            'point_delta': 'Point Delta',
            'is_favorable': 'Is Favorable',
            'projected_value' : 'Projected Value',
            'pinnacle_projected_val' : 'Pinnacle Projected Value',
            'projected_val_delta' : 'Projected Value Delta',
            "point_move" : "Point Move",
            "odds_pct_move" : "Odds % Move",
            "abs_point_move" : "Abs Point Move",
            "abs_proj_delta" : "Abs Proj Delta" 
        }

        # Rename columns
        df_diff = df_diff.rename(columns=col_names)
        df_same = df_same.rename(columns=col_names)

        # Define desired column order
        diff_desired_order = [
            'Start Time',
            'Event',
            'Book',
            'Player',
            'Outcome',
            'Prop',
            'Point',
            'Odds',
            'Pinnacle Odds',
            'Point Delta',
            'Odds % Delta',
            'Is Favorable',
            "Abs Proj Delta",
            "Abs Point Move"
        ]
        same_desired_order = [
            'Start Time',
            'Event',
            'Book',
            'Player',
            'Outcome',
            'Prop',
            'Point',
            'Odds',
            'Pinnacle Odds',
            'Odds % Delta',
            'Is Favorable',
            'Odds % Move'
        ]
        # Reorder columns if they exist, else add them with default values
        for col in diff_desired_order:
            if col not in df_diff.columns:
                df_diff[col] = 0  # Set default value as 0 or pd.NA
        for col in same_desired_order:
            if col not in df_same.columns:
                df_same[col] = 0  # Set default value as 0 or pd.NA

        # Sort DataFrames: first by 'Point Delta' descending, then by 'Odds Percentage Delta' descending
        df_diff_sorted = df_diff.sort_values(by=['Abs Point Move', 'Point Delta'], ascending=[False, False])
        df_same_sorted = df_same.sort_values(by=['Odds % Move', 'Odds % Delta'], ascending=[False, False])

        # Reorder columns
        df_diff_sorted = df_diff_sorted[diff_desired_order]
        df_same_sorted = df_same_sorted[same_desired_order]

        # Create a Pandas Excel writer using openpyxl as the engine
        with pd.ExcelWriter(filename, engine='openpyxl') as writer:
            # Write Diff Points sheet
            df_diff_sorted.to_excel(writer, sheet_name='Diff Points', index=False)
            # Write Same Points sheet
            df_same_sorted.to_excel(writer, sheet_name='Same Points', index=False)

            # Access the workbook and sheets
            for sheet_name in ['Diff Points', 'Same Points']:
                worksheet = writer.sheets[sheet_name]
                
                # Apply filters
                worksheet.auto_filter.ref = worksheet.dimensions

                # Apply formatting
                for column_cells in worksheet.columns:
                    # Determine the maximum length in the column for setting column width
                    length = max(len(str(cell.value)) if cell.value is not None else 0 for cell in column_cells)
                    column_letter = column_cells[0].column_letter
                    worksheet.column_dimensions[column_letter].width = length + 2  # Adding extra space

                    # Apply percentage format to 'Odds Percentage Delta'
                    header_cell = worksheet[f"{column_letter}1"].value
                    if header_cell == 'Odds % Delta':
                        for cell in column_cells[1:]:  # Skip header
                            if isinstance(cell.value, (int, float)):
                                cell.number_format = '0.00%'

        logger.info(f"Excel file '{filename}' has been created with filters, sorting, and adjusted column widths.")
    except Exception as e:
        logger.error(f"Error saving Excel file: {e}")

def store_props(props):
    """
    Store player props data into the SQLite database.

    Parameters:
        props (dict): Props data fetched from the API.
    """
    try:
        conn = sqlite3.connect(DATABASE_NAME)
        c = conn.cursor()

        bookmakers = props.get('bookmakers', [])
        event_commence_time = convert_utc_to_et(props.get('commence_time', ''))
        event_name = f"{props.get('away_team', '')} @ {props.get('home_team', '')}"
        sport_key = props.get('sport_key', '')
        event_id = props.get('id', '')

        table_name = 'player_props'

        # Create table if it doesn't exist
        c.execute(f'''
            CREATE TABLE IF NOT EXISTS {table_name} (
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
                        INSERT OR REPLACE INTO {table_name} 
                        (event_id, event_name, sport_key, market_type, outcome_type, player_name, point_value, odds, event_commence_time, updated_dttm)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', 
                    (event_id, event_name, sport_key, market_type, outcome_type, player_name, point_value, odds, event_commence_time, updated_dttm))
        
        conn.commit()
        conn.close()
        logger.info(f"Stored props for event ID: {event_id}")
    except Exception as e:
        logger.error(f"Error storing props to database: {e}")

def main():
    """
    Main function to orchestrate fetching, processing, storing, and exporting betting lines.
    """
    # Ensure API_KEY is set
    if not API_KEY:
        logger.error("API key for The Odds API not found. Please set 'THE_ODDS_API_KEY' environment variable.")
        raise EnvironmentError("API key for The Odds API not found. Please set 'THE_ODDS_API_KEY' environment variable.")

    global QUOTA_USED
    sport = SPORTS[0]

    logger.info("Processing started.")
    start_time = datetime.now()

    events = get_events(sport)
    diff_pts = [] 
    same_pts = []
    remove_commenced_games()
    for event in events: 
        props = fetch_props(event['id'], event['sport_key'])
        if not props:
            continue
        store_props(props)
        event_name = f"{event.get('away_team', '')} @ {event.get('home_team', '')}"
        commence_time = convert_utc_to_et(event.get('commence_time', ''))[:-4]
        results = find_favorable_lines(props, event_name, commence_time)  # Process the data
        if results:
            if results[0]:
                diff_pts.extend(results[0])
            if results[1]:
                same_pts.extend(results[1])

    output_to_html(diff_pts, same_pts)

    end_time = datetime.now()
    elapsed_time = end_time - start_time
    logger.info(f"Processing completed in {elapsed_time}.")
    logger.info(f"Quota Used: {QUOTA_USED}")
    QUOTA_USED = 0

if __name__ == "__main__":
    main()
