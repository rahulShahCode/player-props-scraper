import requests 
import os 
import pandas as pd 

API_KEY = os.getenv('THE_ODDS_API_KEY')
MARKETS = ['team_totals']
SPORT = 'americanfootball_nfl'

def get_events(sport): 
    params = {'apiKey': API_KEY}
    url = f'https://api.the-odds-api.com/v4/sports/{sport}/events'
    resp = requests.get(url, params=params).json()
    return resp 

def fetch_props(eventId, sport): 
    url = f"https://api.the-odds-api.com/v4/sports/{sport}/events/{eventId}/odds"
    params = {
        "apiKey": API_KEY, 
        "bookmakers": "pinnacle",
        "markets": ','.join(MARKETS),
        "oddsFormat": "decimal",  
    }
    return requests.get(url, params=params).json()

def calculate_implied_probability(odds):
    return 1 / odds 

def estimate_points(over_prob, under_prob, point_total):
    total_prob = over_prob + under_prob
    over_prob_normalized = over_prob / total_prob 
    under_prob_normalized = under_prob / total_prob  
    expected_value = (over_prob_normalized * (point_total + 0.5)) + (under_prob_normalized * (point_total - 0.5))
    return expected_value

def create_projections(betting_lines, matchups):
    projections = {}

    for line in betting_lines:
        team = line['description']
        if team not in projections: 
            projections[team] = {'over': None, 'under': None, 'point': None, 'opponent': matchups.get(team, 'Unknown')}

        if line['name'] == 'Over':
            projections[team]['over'] = calculate_implied_probability(line['price'])
        elif line['name'] == 'Under':
            projections[team]['under'] = calculate_implied_probability(line['price'])
        
        projections[team]['point'] = line['point']
    
    for team, data in projections.items():
        estimated_points = estimate_points(data['over'], data['under'], data['point'])
        projections[team]['projected_points'] = estimated_points
    
    return projections

def main(): 
    events = get_events(SPORT)
    all_lines = []
    matchups = {}

    for event in events: 
        props = fetch_props(event['id'], SPORT)
        if props.get('bookmakers') and props['bookmakers']:
            home_team = props['home_team']
            away_team = props['away_team']
            matchups[home_team] = away_team
            matchups[away_team] = home_team
            all_lines.extend(props['bookmakers'][0]['markets'][0]['outcomes'])
    
    projections = create_projections(all_lines, matchups)
    
    # Convert to pandas DataFrame
    df = pd.DataFrame.from_dict(projections, orient='index')
    df.reset_index(inplace=True)
    df.columns = ['Team', 'Over Prob', 'Under Prob', 'Point Total', 'Opponent', 'Projected Points']

    # Sort the DataFrame by Projected Points in descending order
    df_sorted = df.sort_values('Projected Points', ascending=False)

    # Save to CSV
    csv_filename = 'team_total_projections.csv'
    df_sorted.to_csv(csv_filename, index=False)

    print(df_sorted)
    print(f"\nData has been saved to {csv_filename}")        

if __name__ == "__main__":
    main()