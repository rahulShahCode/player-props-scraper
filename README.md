# Player Props Scraper

A scraper that fetches player prop lines from The Odds API and writes results to `index.html`, `player_props.xlsx`, and `odds.db`.

## Setup

1. Get an API key from https://the-odds-api.com/ (create an account and copy the key).

2. Local run options:

- One-off run (shell):

```bash
THE_ODDS_API_KEY="your_key_here" python player_props.py
```

- Persistent local (recommended):

```bash
cp .env.example .env
# edit .env and set THE_ODDS_API_KEY
python -m pip install -r requirements.txt
python player_props.py
```

Note: `.env` is ignored by git. Do NOT commit it.

## GitHub Actions

To run on CI (workflow in `.github/workflows/schedule.yml`):

1. Go to your repository Settings → Secrets and variables → Actions → New repository secret.
2. Add a secret named `THE_ODDS_API_KEY` with your API key value.
3. (Optional) Add `GIT_USER_NAME` and `GIT_USER_EMAIL` if you want authored commits from the workflow.

## Notes
- The script uses `python-dotenv` to load `.env` automatically.
- Free plans on The Odds API have quota limits; check your dashboard for usage.
