"""Fetch completed FIFA World Cup 2026 match results from the-odds-api.com
and store them in odds.db so spi_model.py can train on them as they come in."""

import os
import sqlite3
import requests
from datetime import datetime, timezone

DB_PATH = "odds.db"             # shared with spi_model.py and build_dashboard.py
SCORES_DAYS_FROM = 3            # rolling window for the completed-scores endpoint
API_TIMEOUT_SECONDS = 30        # request timeout, in seconds

# ---------------------------------------------------------------------------
# Team name normalization
# ---------------------------------------------------------------------------
NAME_MAP = {
    # Group A
    "Korea Republic": "South Korea",
    "Czech Republic": "Czechia",

    # Group B
    "Bosnia & Herzegovina": "Bosnia-Herzegovina",
    "Bosnia and Herzegovina": "Bosnia-Herzegovina",

    # Group D
    "USA": "United States",
    "Turkey": "Turkiye",
    "Türkiye": "Turkiye",

    # Group E
    "Curaçao": "Curacao",
    "Cote d'Ivoire": "Ivory Coast",
    "Côte d'Ivoire": "Ivory Coast",

    # Group H
    "Cabo Verde": "Cape Verde",

    # Group K
    "Congo DR": "DR Congo",
    "Democratic Republic of the Congo": "DR Congo",
}


def normalize(name: str) -> str:
    """Map a sportsbook API team name to its canonical name; unknown names pass through unchanged."""
    return NAME_MAP.get(name, name)


def init_db(conn: sqlite3.Connection) -> None:
    """Create the match_results table that this module owns."""
    # Note: match_odds is not created or written by this file (h2h odds fetching
    # was removed), but build_dashboard.py's get_schedule() still reads
    # match_odds.commence_time for kickoff times — that table and its existing
    # data in odds.db are still live and should not be dropped.
    # odds_snapshots (the old outright-odds table) had no remaining readers and
    # was removed entirely, along with the "vs market" comparison it fed in
    # spi_model.py.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS match_results (
            event_id    TEXT PRIMARY KEY,
            home_team   TEXT NOT NULL,
            away_team   TEXT NOT NULL,
            home_score  INTEGER NOT NULL,
            away_score  INTEGER NOT NULL,
            fetched_at  TEXT NOT NULL
        )
    """)
    conn.commit()


def fetch_and_store_scores(api_key: str, db_path: str = DB_PATH) -> None:
    """Fetch completed WC2026 match results from the-odds-api.com and upsert them into match_results."""
    url = "https://api.the-odds-api.com/v4/sports/soccer_fifa_world_cup/scores"
    params = {
        "apiKey": api_key,
        "daysFrom": SCORES_DAYS_FROM,
    }

    try:
        resp = requests.get(url, params=params, timeout=API_TIMEOUT_SECONDS)
        resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        raise SystemExit(f"ERROR: failed to fetch scores from the-odds-api.com: {e}")

    data = resp.json()

    remaining = resp.headers.get("x-requests-remaining", "?")
    used = resp.headers.get("x-requests-used", "?")
    print(f"Scores API quota — used: {used}, remaining: {remaining}")

    completed = [e for e in data if e.get("completed") and e.get("scores")]
    if not completed:
        print("No completed matches found.")
        return

    fetched_at = datetime.now(timezone.utc).isoformat()
    conn = sqlite3.connect(db_path)
    try:
        init_db(conn)
        count = 0
        for event in completed:
            home_raw = event["home_team"]
            away_raw = event["away_team"]
            home = normalize(home_raw)
            away = normalize(away_raw)
            event_id = event["id"]

            score_map = {
                s["name"]: s["score"]
                for s in event["scores"]
                if s.get("score") is not None
            }
            home_score_raw = score_map.get(home_raw)
            away_score_raw = score_map.get(away_raw)
            if home_score_raw is None or away_score_raw is None:
                print(f"  Skipping {home} vs {away} — score data incomplete")
                continue

            try:
                home_score = int(home_score_raw)
                away_score = int(away_score_raw)
            except (ValueError, TypeError):
                print(f"  Skipping {home} vs {away} — non-integer score: {home_score_raw}/{away_score_raw}")
                continue

            conn.execute(
                """INSERT OR REPLACE INTO match_results
                   (event_id, home_team, away_team, home_score, away_score, fetched_at)
                   VALUES (?,?,?,?,?,?)""",
                (event_id, home, away, home_score, away_score, fetched_at),
            )
            count += 1
            print(f"  Result: {home:<22} {home_score}–{away_score}  {away}")

        conn.commit()
        print(f"Stored {count} completed result(s).")
    finally:
        conn.close()


if __name__ == "__main__":
    key = os.environ.get("ODDS_API_KEY")
    if not key:
        raise SystemExit("ERROR: ODDS_API_KEY environment variable not set.")
    fetch_and_store_scores(key)
