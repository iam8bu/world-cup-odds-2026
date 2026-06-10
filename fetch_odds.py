import os
import sqlite3
import requests
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Team name normalization
# ---------------------------------------------------------------------------
NAME_MAP = {
    # Group A
    "Mexico": "Mexico",
    "South Africa": "South Africa",
    "Korea Republic": "South Korea",
    "South Korea": "South Korea",
    "Czech Republic": "Czechia",
    "Czechia": "Czechia",

    # Group B
    "Canada": "Canada",
    "Bosnia & Herzegovina": "Bosnia-Herzegovina",
    "Bosnia and Herzegovina": "Bosnia-Herzegovina",
    "Bosnia-Herzegovina": "Bosnia-Herzegovina",
    "Qatar": "Qatar",
    "Switzerland": "Switzerland",

    # Group C
    "Brazil": "Brazil",
    "Morocco": "Morocco",
    "Haiti": "Haiti",
    "Scotland": "Scotland",

    # Group D
    "United States": "United States",
    "USA": "United States",
    "Paraguay": "Paraguay",
    "Australia": "Australia",
    "Turkey": "Turkiye",
    "Turkiye": "Turkiye",
    "Türkiye": "Turkiye",

    # Group E
    "Germany": "Germany",
    "Curacao": "Curacao",
    "Curaçao": "Curacao",
    "Ivory Coast": "Ivory Coast",
    "Cote d'Ivoire": "Ivory Coast",
    "Côte d'Ivoire": "Ivory Coast",
    "Ecuador": "Ecuador",

    # Group F
    "Netherlands": "Netherlands",
    "Japan": "Japan",
    "Sweden": "Sweden",
    "Tunisia": "Tunisia",

    # Group G
    "Belgium": "Belgium",
    "Egypt": "Egypt",
    "Iran": "Iran",
    "New Zealand": "New Zealand",

    # Group H
    "Spain": "Spain",
    "Cape Verde": "Cape Verde",
    "Cabo Verde": "Cape Verde",
    "Saudi Arabia": "Saudi Arabia",
    "Uruguay": "Uruguay",

    # Group I
    "France": "France",
    "Senegal": "Senegal",
    "Iraq": "Iraq",
    "Norway": "Norway",

    # Group J
    "Argentina": "Argentina",
    "Algeria": "Algeria",
    "Austria": "Austria",
    "Jordan": "Jordan",

    # Group K
    "Portugal": "Portugal",
    "DR Congo": "DR Congo",
    "Congo DR": "DR Congo",
    "Democratic Republic of the Congo": "DR Congo",
    "Uzbekistan": "Uzbekistan",
    "Colombia": "Colombia",

    # Group L
    "England": "England",
    "Croatia": "Croatia",
    "Ghana": "Ghana",
    "Panama": "Panama",
}


def normalize(name: str) -> str:
    return NAME_MAP.get(name, name)


def american_to_implied(odds: int) -> float:
    if odds >= 0:
        return 100 / (odds + 100)
    return abs(odds) / (abs(odds) + 100)


def init_db(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS match_odds (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id    TEXT NOT NULL,
            home_team   TEXT NOT NULL,
            away_team   TEXT NOT NULL,
            home_prob   REAL NOT NULL,
            draw_prob   REAL NOT NULL,
            away_prob   REAL NOT NULL,
            fetched_at  TEXT NOT NULL
        )
    """)
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


def fetch_and_store(api_key: str, db_path: str = "odds.db") -> None:
    url = "https://api.the-odds-api.com/v4/sports/soccer_fifa_world_cup/odds"
    params = {
        "apiKey": api_key,
        "regions": "us",
        "markets": "h2h",
        "oddsFormat": "american",
    }

    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    remaining = resp.headers.get("x-requests-remaining", "?")
    used = resp.headers.get("x-requests-used", "?")
    print(f"API quota — used: {used}, remaining: {remaining}")

    if not data:
        print("WARNING: API returned an empty list — no matches available yet.")
        return

    fetched_at = datetime.now(timezone.utc).isoformat()
    rows = []

    for event in data:
        home_raw = event["home_team"]
        away_raw = event["away_team"]
        home = normalize(home_raw)
        away = normalize(away_raw)
        event_id = event["id"]

        home_probs, draw_probs, away_probs = [], [], []

        for bookmaker in event.get("bookmakers", []):
            for market in bookmaker.get("markets", []):
                if market.get("key") != "h2h":
                    continue
                outcome_map = {
                    o["name"]: american_to_implied(o["price"])
                    for o in market.get("outcomes", [])
                }
                hp = outcome_map.get(home_raw)
                ap = outcome_map.get(away_raw)
                dp = outcome_map.get("Draw", 0.0)

                if hp is not None and ap is not None:
                    home_probs.append(hp)
                    away_probs.append(ap)
                    draw_probs.append(dp)

        if not home_probs:
            print(f"  No h2h odds found for {home} vs {away} — skipping")
            continue

        # Average across bookmakers then normalize to remove the vig
        home_avg = sum(home_probs) / len(home_probs)
        away_avg = sum(away_probs) / len(away_probs)
        draw_avg = sum(draw_probs) / len(draw_probs) if draw_probs else 0.0
        total = home_avg + draw_avg + away_avg

        home_norm = home_avg / total
        draw_norm = draw_avg / total
        away_norm = away_avg / total

        rows.append((event_id, home, away, home_norm, draw_norm, away_norm, fetched_at))
        print(
            f"  {home:<22} vs {away:<22}  "
            f"{home_norm*100:5.1f}% / {draw_norm*100:5.1f}% / {away_norm*100:5.1f}%"
        )

    if not rows:
        print("WARNING: no h2h odds were processable — nothing written to DB.")
        return

    conn = sqlite3.connect(db_path)
    try:
        init_db(conn)
        conn.executemany(
            "INSERT INTO match_odds "
            "(event_id, home_team, away_team, home_prob, draw_prob, away_prob, fetched_at) "
            "VALUES (?,?,?,?,?,?,?)",
            rows,
        )
        conn.commit()
        print(f"\nStored odds for {len(rows)} matches at {fetched_at}")
    finally:
        conn.close()


def fetch_and_store_scores(api_key: str, db_path: str = "odds.db") -> None:
    url = "https://api.the-odds-api.com/v4/sports/soccer_fifa_world_cup/scores"
    params = {
        "apiKey": api_key,
        "daysFrom": 3,
    }

    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
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
    fetch_and_store(key)
    fetch_and_store_scores(key)
