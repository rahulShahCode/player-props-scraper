import sqlite3
import pandas as pd
import numpy as np
from datetime import datetime

def calculate_implied_probability(american_odds):
    if american_odds > 0:
        return 100 / (american_odds + 100)
    else:
        return abs(american_odds) / (abs(american_odds) + 100)

def get_projected_value(over_odds, under_odds, point_value):
    over_prob = calculate_implied_probability(over_odds)
    under_prob = calculate_implied_probability(under_odds)
    total_prob = over_prob + under_prob
    normalized_over_prob = over_prob / total_prob
    normalized_under_prob = under_prob / total_prob
    return (normalized_over_prob * (point_value + 0.5)) + (normalized_under_prob * (point_value - 0.5))

# Connect to the SQLite database
conn = sqlite3.connect('odds.db')

# Fetch data from the player_props table, selecting only the latest odds for each player, market, and outcome
query = """
    SELECT p1.*
    FROM player_props p1
    INNER JOIN (
        SELECT event_name, player_name, market_type, outcome_type, MAX(updated_dttm) as max_updated_dttm
        FROM player_props
        WHERE market_type IN ('player_anytime_td', 'player_pass_yds', 'player_pass_tds', 'player_pass_interceptions',
                              'player_reception_yds', 'player_receptions', 'player_rush_yds', 'player_kicking_points')
        GROUP BY event_name, player_name, market_type, outcome_type
    ) p2
    ON p1.event_name = p2.event_name
    AND p1.player_name = p2.player_name
    AND p1.market_type = p2.market_type
    AND p1.outcome_type = p2.outcome_type
    AND p1.updated_dttm = p2.max_updated_dttm
"""

# Read the data into a DataFrame
df = pd.read_sql_query(query, conn)

# Group the data by event, player, and market_type
grouped = df.groupby(['event_name', 'player_name', 'market_type'])

projections = []

for (event, player, market), group in grouped:
    if market == 'player_anytime_td':
        yes_odds = group[group['outcome_type'] == 'Yes']['odds'].values[0]
        td_prob = calculate_implied_probability(yes_odds)
        projections.append({'event': event, 'player': player, 'market_type': market, 'projected_value': td_prob})
    else:
        over_row = group[group['outcome_type'] == 'Over'].iloc[0]
        under_row = group[group['outcome_type'] == 'Under'].iloc[0]
        projected_value = get_projected_value(over_row['odds'], under_row['odds'], over_row['point_value'])
        projections.append({'event': event, 'player': player, 'market_type': market, 'projected_value': projected_value})

# Convert projections to DataFrame
projections_df = pd.DataFrame(projections)

# Pivot the DataFrame to have one row per player
pivot_df = projections_df.pivot(index=['event', 'player'], columns='market_type', values='projected_value')
pivot_df = pivot_df.reset_index()

# Calculate PPR projections
pivot_df['projected_fantasy_points'] = 0

if 'player_pass_yds' in pivot_df.columns:
    pivot_df['projected_fantasy_points'] += pivot_df['player_pass_yds'].fillna(0) / 25

if 'player_pass_tds' in pivot_df.columns:
    pivot_df['projected_fantasy_points'] += pivot_df['player_pass_tds'].fillna(0) * 4

if 'player_pass_interceptions' in pivot_df.columns:
    pivot_df['projected_fantasy_points'] += pivot_df['player_pass_interceptions'].fillna(0) * -2

if 'player_reception_yds' in pivot_df.columns:
    pivot_df['projected_fantasy_points'] += pivot_df['player_reception_yds'].fillna(0) / 10

if 'player_receptions' in pivot_df.columns:
    pivot_df['projected_fantasy_points'] += pivot_df['player_receptions'].fillna(0)

if 'player_rush_yds' in pivot_df.columns:
    pivot_df['projected_fantasy_points'] += pivot_df['player_rush_yds'].fillna(0) / 10

if 'player_anytime_td' in pivot_df.columns:
    pivot_df['projected_fantasy_points'] += pivot_df['player_anytime_td'].fillna(0) * 6

if 'player_kicking_points' in pivot_df.columns:
    pivot_df['projected_fantasy_points'] += pivot_df['player_kicking_points'].fillna(0)

# Sort by projected fantasy points
pivot_df = pivot_df.sort_values('projected_fantasy_points', ascending=False)

# Prepare the final DataFrame for output
output_df = pivot_df[['event', 'player', 'projected_fantasy_points'] + 
                     [col for col in pivot_df.columns if col.startswith('player_')]]

# Generate a timestamp for the filename
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
filename = f"ppr_projections_{timestamp}.csv"

# Save the DataFrame to a CSV file
output_df.to_csv(filename, index=False)

print(f"PPR projections have been saved to {filename}")

# Display the top 20 projections in the console
print(output_df.head(20).to_string(index=False))

# Close the database connection
conn.close()