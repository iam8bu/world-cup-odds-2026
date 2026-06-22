#!/usr/bin/env python3
"""Build the 2026 World Cup Watchability Dashboard and write index.html."""

import datetime
import math
import random
import sqlite3
import os
import time
from html import escape as esc

DB_PATH = "odds.db"
OUT_PATH = "index.html"

# ---------------------------------------------------------------------------
# Schedule — fallback hardcoded list; dates/times replaced by API once available
# ---------------------------------------------------------------------------
_SCHEDULE_FALLBACK = [
    {"date": "Thu, Jun 11", "grp": "A", "home": "Mexico",            "away": "South Africa",     "time": "3:00 PM ET",   "venue": "Estadio Azteca, Mexico City"},
    {"date": "Thu, Jun 11", "grp": "A", "home": "South Korea",       "away": "Czechia",           "time": "10:00 PM ET",  "venue": "Estadio Akron, Guadalajara"},
    {"date": "Fri, Jun 12", "grp": "B", "home": "Canada",            "away": "Bosnia-Herzegovina","time": "3:00 PM ET",   "venue": "BMO Field, Toronto"},
    {"date": "Fri, Jun 12", "grp": "D", "home": "United States",     "away": "Paraguay",          "time": "9:00 PM ET",   "venue": "SoFi Stadium, Inglewood"},
    {"date": "Sat, Jun 13", "grp": "B", "home": "Qatar",             "away": "Switzerland",       "time": "3:00 PM ET",   "venue": "Levi's Stadium, Santa Clara"},
    {"date": "Sat, Jun 13", "grp": "C", "home": "Brazil",            "away": "Morocco",           "time": "6:00 PM ET",   "venue": "MetLife Stadium, East Rutherford"},
    {"date": "Sat, Jun 13", "grp": "C", "home": "Haiti",             "away": "Scotland",          "time": "9:00 PM ET",   "venue": "Gillette Stadium, Foxboro"},
    {"date": "Sat, Jun 13", "grp": "D", "home": "Australia",         "away": "Turkiye",           "time": "12:00 AM ET",  "venue": "BC Place, Vancouver"},
    {"date": "Sun, Jun 14", "grp": "E", "home": "Germany",           "away": "Curacao",           "time": "1:00 PM ET",   "venue": "NRG Stadium, Houston"},
    {"date": "Sun, Jun 14", "grp": "F", "home": "Netherlands",       "away": "Japan",             "time": "4:00 PM ET",   "venue": "AT&T Stadium, Arlington"},
    {"date": "Sun, Jun 14", "grp": "E", "home": "Ivory Coast",       "away": "Ecuador",           "time": "7:00 PM ET",   "venue": "Lincoln Financial Field, Philadelphia"},
    {"date": "Sun, Jun 14", "grp": "F", "home": "Sweden",            "away": "Tunisia",           "time": "10:00 PM ET",  "venue": "Estadio BBVA, Monterrey"},
    {"date": "Mon, Jun 15", "grp": "H", "home": "Spain",             "away": "Cape Verde",        "time": "12:00 PM ET",  "venue": "Mercedes-Benz Stadium, Atlanta"},
    {"date": "Mon, Jun 15", "grp": "G", "home": "Belgium",           "away": "Egypt",             "time": "3:00 PM ET",   "venue": "Lumen Field, Seattle"},
    {"date": "Mon, Jun 15", "grp": "H", "home": "Saudi Arabia",      "away": "Uruguay",           "time": "6:00 PM ET",   "venue": "Hard Rock Stadium, Miami"},
    {"date": "Mon, Jun 15", "grp": "G", "home": "Iran",              "away": "New Zealand",       "time": "9:00 PM ET",   "venue": "SoFi Stadium, Inglewood"},
    {"date": "Tue, Jun 16", "grp": "I", "home": "France",            "away": "Senegal",           "time": "3:00 PM ET",   "venue": "MetLife Stadium, East Rutherford"},
    {"date": "Tue, Jun 16", "grp": "I", "home": "Iraq",              "away": "Norway",            "time": "6:00 PM ET",   "venue": "Gillette Stadium, Foxborough"},
    {"date": "Tue, Jun 16", "grp": "J", "home": "Argentina",         "away": "Algeria",           "time": "9:00 PM ET",   "venue": "Arrowhead Stadium, Kansas City"},
    {"date": "Tue, Jun 16", "grp": "J", "home": "Austria",           "away": "Jordan",            "time": "12:00 AM ET",  "venue": "Levi's Stadium, Santa Clara"},
    {"date": "Wed, Jun 17", "grp": "K", "home": "Portugal",          "away": "DR Congo",          "time": "1:00 PM ET",   "venue": "NRG Stadium, Houston"},
    {"date": "Wed, Jun 17", "grp": "L", "home": "England",           "away": "Croatia",           "time": "4:00 PM ET",   "venue": "AT&T Stadium, Arlington"},
    {"date": "Wed, Jun 17", "grp": "L", "home": "Ghana",             "away": "Panama",            "time": "7:00 PM ET",   "venue": "BMO Field, Toronto"},
    {"date": "Wed, Jun 17", "grp": "K", "home": "Uzbekistan",        "away": "Colombia",          "time": "10:00 PM ET",  "venue": "Estadio Azteca, Mexico City"},
    {"date": "Thu, Jun 18", "grp": "A", "home": "Czechia",           "away": "South Africa",      "time": "12:00 PM ET",  "venue": "Mercedes-Benz Stadium, Atlanta"},
    {"date": "Thu, Jun 18", "grp": "B", "home": "Switzerland",       "away": "Bosnia-Herzegovina","time": "3:00 PM ET",   "venue": "SoFi Stadium, Inglewood"},
    {"date": "Thu, Jun 18", "grp": "B", "home": "Canada",            "away": "Qatar",             "time": "6:00 PM ET",   "venue": "BC Place, Vancouver"},
    {"date": "Thu, Jun 18", "grp": "A", "home": "Mexico",            "away": "South Korea",       "time": "9:00 PM ET",   "venue": "Estadio Akron, Guadalajara"},
    {"date": "Fri, Jun 19", "grp": "D", "home": "United States",     "away": "Australia",         "time": "3:00 PM ET",   "venue": "Lumen Field, Seattle"},
    {"date": "Fri, Jun 19", "grp": "C", "home": "Scotland",          "away": "Morocco",           "time": "6:00 PM ET",   "venue": "Gillette Stadium, Foxboro"},
    {"date": "Fri, Jun 19", "grp": "C", "home": "Brazil",            "away": "Haiti",             "time": "8:30 PM ET",   "venue": "Lincoln Financial Field, Philadelphia"},
    {"date": "Fri, Jun 19", "grp": "D", "home": "Turkiye",           "away": "Paraguay",          "time": "11:00 PM ET",  "venue": "Levi's Stadium, Santa Clara"},
    {"date": "Sat, Jun 20", "grp": "F", "home": "Netherlands",       "away": "Sweden",            "time": "1:00 PM ET",   "venue": "NRG Stadium, Houston"},
    {"date": "Sat, Jun 20", "grp": "E", "home": "Germany",           "away": "Ivory Coast",       "time": "4:00 PM ET",   "venue": "BMO Field, Toronto"},
    {"date": "Sat, Jun 20", "grp": "E", "home": "Ecuador",           "away": "Curacao",           "time": "8:00 PM ET",   "venue": "Arrowhead Stadium, Kansas City"},
    {"date": "Sat, Jun 20", "grp": "F", "home": "Tunisia",           "away": "Japan",             "time": "12:00 AM ET",  "venue": "Estadio BBVA, Monterrey"},
    {"date": "Sun, Jun 21", "grp": "H", "home": "Spain",             "away": "Saudi Arabia",      "time": "12:00 PM ET",  "venue": "Mercedes-Benz Stadium, Atlanta"},
    {"date": "Sun, Jun 21", "grp": "G", "home": "Belgium",           "away": "Iran",              "time": "3:00 PM ET",   "venue": "SoFi Stadium, Inglewood"},
    {"date": "Sun, Jun 21", "grp": "H", "home": "Uruguay",           "away": "Cape Verde",        "time": "6:00 PM ET",   "venue": "Hard Rock Stadium, Miami"},
    {"date": "Sun, Jun 21", "grp": "G", "home": "New Zealand",       "away": "Egypt",             "time": "9:00 PM ET",   "venue": "BC Place, Vancouver"},
    {"date": "Mon, Jun 22", "grp": "J", "home": "Argentina",         "away": "Austria",           "time": "1:00 PM ET",   "venue": "AT&T Stadium, Arlington"},
    {"date": "Mon, Jun 22", "grp": "I", "home": "France",            "away": "Iraq",              "time": "5:00 PM ET",   "venue": "Lincoln Financial Field, Philadelphia"},
    {"date": "Mon, Jun 22", "grp": "I", "home": "Norway",            "away": "Senegal",           "time": "8:00 PM ET",   "venue": "MetLife Stadium, East Rutherford"},
    {"date": "Mon, Jun 22", "grp": "J", "home": "Jordan",            "away": "Algeria",           "time": "11:00 PM ET",  "venue": "Levi's Stadium, Santa Clara"},
    {"date": "Tue, Jun 23", "grp": "K", "home": "Portugal",          "away": "Uzbekistan",        "time": "1:00 PM ET",   "venue": "NRG Stadium, Houston"},
    {"date": "Tue, Jun 23", "grp": "L", "home": "England",           "away": "Ghana",             "time": "4:00 PM ET",   "venue": "Gillette Stadium, Foxborough"},
    {"date": "Tue, Jun 23", "grp": "L", "home": "Panama",            "away": "Croatia",           "time": "7:00 PM ET",   "venue": "BMO Field, Toronto"},
    {"date": "Tue, Jun 23", "grp": "K", "home": "Colombia",          "away": "DR Congo",          "time": "10:00 PM ET",  "venue": "Estadio Akron, Guadalajara"},
    {"date": "Wed, Jun 24", "grp": "B", "home": "Switzerland",       "away": "Canada",            "time": "3:00 PM ET",   "venue": "BC Place, Vancouver"},
    {"date": "Wed, Jun 24", "grp": "B", "home": "Bosnia-Herzegovina","away": "Qatar",             "time": "3:00 PM ET",   "venue": "Lumen Field, Seattle"},
    {"date": "Wed, Jun 24", "grp": "C", "home": "Scotland",          "away": "Brazil",            "time": "6:00 PM ET",   "venue": "Hard Rock Stadium, Miami"},
    {"date": "Wed, Jun 24", "grp": "C", "home": "Morocco",           "away": "Haiti",             "time": "6:00 PM ET",   "venue": "Mercedes-Benz Stadium, Atlanta"},
    {"date": "Wed, Jun 24", "grp": "A", "home": "Czechia",           "away": "Mexico",            "time": "9:00 PM ET",   "venue": "Estadio Azteca, Mexico City"},
    {"date": "Wed, Jun 24", "grp": "A", "home": "South Africa",      "away": "South Korea",       "time": "9:00 PM ET",   "venue": "Estadio BBVA, Monterrey"},
    {"date": "Thu, Jun 25", "grp": "E", "home": "Curacao",           "away": "Ivory Coast",       "time": "4:00 PM ET",   "venue": "Lincoln Financial Field, Philadelphia"},
    {"date": "Thu, Jun 25", "grp": "E", "home": "Ecuador",           "away": "Germany",           "time": "4:00 PM ET",   "venue": "MetLife Stadium, East Rutherford"},
    {"date": "Thu, Jun 25", "grp": "F", "home": "Japan",             "away": "Sweden",            "time": "7:00 PM ET",   "venue": "AT&T Stadium, Arlington"},
    {"date": "Thu, Jun 25", "grp": "F", "home": "Tunisia",           "away": "Netherlands",       "time": "7:00 PM ET",   "venue": "Arrowhead Stadium, Kansas City"},
    {"date": "Thu, Jun 25", "grp": "D", "home": "Turkiye",           "away": "United States",     "time": "10:00 PM ET",  "venue": "SoFi Stadium, Inglewood"},
    {"date": "Thu, Jun 25", "grp": "D", "home": "Paraguay",          "away": "Australia",         "time": "10:00 PM ET",  "venue": "Levi's Stadium, Santa Clara"},
    {"date": "Fri, Jun 26", "grp": "I", "home": "Norway",            "away": "France",            "time": "3:00 PM ET",   "venue": "Gillette Stadium, Foxborough"},
    {"date": "Fri, Jun 26", "grp": "I", "home": "Senegal",           "away": "Iraq",              "time": "3:00 PM ET",   "venue": "BMO Field, Toronto"},
    {"date": "Fri, Jun 26", "grp": "H", "home": "Cape Verde",        "away": "Saudi Arabia",      "time": "8:00 PM ET",   "venue": "NRG Stadium, Houston"},
    {"date": "Fri, Jun 26", "grp": "H", "home": "Uruguay",           "away": "Spain",             "time": "8:00 PM ET",   "venue": "Estadio Akron, Guadalajara"},
    {"date": "Fri, Jun 26", "grp": "G", "home": "Egypt",             "away": "Iran",              "time": "11:00 PM ET",  "venue": "Lumen Field, Seattle"},
    {"date": "Fri, Jun 26", "grp": "G", "home": "New Zealand",       "away": "Belgium",           "time": "11:00 PM ET",  "venue": "BC Place, Vancouver"},
    {"date": "Sat, Jun 27", "grp": "L", "home": "Panama",            "away": "England",           "time": "5:00 PM ET",   "venue": "MetLife Stadium, East Rutherford"},
    {"date": "Sat, Jun 27", "grp": "L", "home": "Croatia",           "away": "Ghana",             "time": "5:00 PM ET",   "venue": "Lincoln Financial Field, Philadelphia"},
    {"date": "Sat, Jun 27", "grp": "K", "home": "Colombia",          "away": "Portugal",          "time": "7:30 PM ET",   "venue": "Hard Rock Stadium, Miami"},
    {"date": "Sat, Jun 27", "grp": "K", "home": "DR Congo",          "away": "Uzbekistan",        "time": "7:30 PM ET",   "venue": "Mercedes-Benz Stadium, Atlanta"},
    {"date": "Sat, Jun 27", "grp": "J", "home": "Jordan",            "away": "Argentina",         "time": "10:00 PM ET",  "venue": "AT&T Stadium, Arlington"},
    {"date": "Sat, Jun 27", "grp": "J", "home": "Algeria",           "away": "Austria",           "time": "10:00 PM ET",  "venue": "Arrowhead Stadium, Kansas City"},
]

_VENUE_MAP = {(g["home"], g["away"]): g["venue"] for g in _SCHEDULE_FALLBACK}
_GROUP_MAP  = {team: g["grp"] for g in _SCHEDULE_FALLBACK for team in (g["home"], g["away"])}

_ET = datetime.timezone(datetime.timedelta(hours=-4))


def get_schedule(db_path: str) -> list:
    """Return all games: upcoming from match_odds (API commence_time), completed from match_results."""
    try:
        conn = sqlite3.connect(db_path)
        time_rows = conn.execute(
            "SELECT home_team, away_team, MIN(commence_time) AS ct "
            "FROM match_odds WHERE commence_time IS NOT NULL "
            "GROUP BY home_team, away_team"
        ).fetchall()
        completed_pairs = set(conn.execute(
            "SELECT home_team, away_team FROM match_results"
        ).fetchall())
        conn.close()
        time_map = {(h, a): ct for h, a, ct in time_rows}
    except Exception:
        time_map = {}
        completed_pairs = set()

    if not time_map:
        return list(_SCHEDULE_FALLBACK)

    schedule = []
    for g in _SCHEDULE_FALLBACK:
        pair = (g["home"], g["away"])
        ct = time_map.get(pair)
        if ct:
            dt = datetime.datetime.fromisoformat(ct.replace("Z", "+00:00")).astimezone(_ET)
            h = dt.hour % 12 or 12
            ampm = "AM" if dt.hour < 12 else "PM"
            schedule.append({**g,
                "date": f"{dt.strftime('%a, %b')} {dt.day}",
                "time": f"{h}:{dt.minute:02d} {ampm} ET",
            })
        elif pair in completed_pairs:
            # Completed game no longer in odds feed — keep hardcoded date/time
            schedule.append(g)
    return schedule


GROUPS = {
    "A": ["Mexico", "South Africa", "South Korea", "Czechia"],
    "B": ["Canada", "Bosnia-Herzegovina", "Qatar", "Switzerland"],
    "C": ["Brazil", "Morocco", "Haiti", "Scotland"],
    "D": ["United States", "Paraguay", "Australia", "Turkiye"],
    "E": ["Germany", "Curacao", "Ivory Coast", "Ecuador"],
    "F": ["Netherlands", "Japan", "Sweden", "Tunisia"],
    "G": ["Belgium", "Egypt", "Iran", "New Zealand"],
    "H": ["Spain", "Cape Verde", "Saudi Arabia", "Uruguay"],
    "I": ["France", "Senegal", "Iraq", "Norway"],
    "J": ["Argentina", "Algeria", "Austria", "Jordan"],
    "K": ["Portugal", "DR Congo", "Uzbekistan", "Colombia"],
    "L": ["England", "Croatia", "Ghana", "Panama"],
}

FLAGS = {
    "Mexico":             "🇲🇽",
    "South Africa":       "🇿🇦",
    "South Korea":        "🇰🇷",
    "Czechia":            "🇨🇿",
    "Canada":             "🇨🇦",
    "Bosnia-Herzegovina": "🇧🇦",
    "Qatar":              "🇶🇦",
    "Switzerland":        "🇨🇭",
    "Brazil":             "🇧🇷",
    "Morocco":            "🇲🇦",
    "Haiti":              "🇭🇹",
    "Scotland":           "🏴󠁧󠁢󠁳󠁣󠁴󠁿",
    "United States":      "🇺🇸",
    "Paraguay":           "🇵🇾",
    "Australia":          "🇦🇺",
    "Turkiye":            "🇹🇷",
    "Germany":            "🇩🇪",
    "Curacao":            "🇨🇼",
    "Ivory Coast":        "🇨🇮",
    "Ecuador":            "🇪🇨",
    "Netherlands":        "🇳🇱",
    "Japan":              "🇯🇵",
    "Sweden":             "🇸🇪",
    "Tunisia":            "🇹🇳",
    "Belgium":            "🇧🇪",
    "Egypt":              "🇪🇬",
    "Iran":               "🇮🇷",
    "New Zealand":        "🇳🇿",
    "Spain":              "🇪🇸",
    "Cape Verde":         "🇨🇻",
    "Saudi Arabia":       "🇸🇦",
    "Uruguay":            "🇺🇾",
    "France":             "🇫🇷",
    "Senegal":            "🇸🇳",
    "Iraq":               "🇮🇶",
    "Norway":             "🇳🇴",
    "Argentina":          "🇦🇷",
    "Algeria":            "🇩🇿",
    "Austria":            "🇦🇹",
    "Jordan":             "🇯🇴",
    "Portugal":           "🇵🇹",
    "DR Congo":           "🇨🇩",
    "Uzbekistan":         "🇺🇿",
    "Colombia":           "🇨🇴",
    "England":            "🏴󠁧󠁢󠁥󠁮󠁧󠁿",
    "Croatia":            "🇭🇷",
    "Ghana":              "🇬🇭",
    "Panama":             "🇵🇦",
}

# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------
CSS = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap');

:root {
  --bg:        #0d1117;
  --surface:   #161b22;
  --surface2:  #21262d;
  --border:    #30363d;
  --text:      #e6edf3;
  --muted:     #7d8590;
  --blue:      #2f81f7;
  --draw:      #6e7681;
  --orange:    #f0883e;
  --green:     #3fb950;
  --green-dim: rgba(63,185,80,.09);
  --green-bdr: rgba(63,185,80,.28);
  --amber:     #d29922;
  --amber-dim: rgba(210,153,34,.09);
  --amber-bdr: rgba(210,153,34,.28);
  --red:       #f85149;
  --blue-dim:  rgba(47,129,247,.09);
  --blue-bdr:  rgba(47,129,247,.28);
  --red-dim:   rgba(248,81,73,.07);
  --red-bdr:   rgba(248,81,73,.22);
  --gray-dim:  rgba(110,118,129,.07);
  --gray-bdr:  rgba(110,118,129,.20);
}
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
body {
  background: var(--bg);
  color: var(--text);
  font-family: "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
  font-size: 14px;
  line-height: 1.5;
  -webkit-font-smoothing: antialiased;
}

/* ── Header ── */
header {
  background: linear-gradient(180deg, #111d35 0%, #0d1117 100%);
  border-bottom: 1px solid var(--border);
  padding: 36px 32px 28px;
  text-align: center;
}
.header-eyebrow {
  font-size: 10px; font-weight: 700;
  letter-spacing: 2.5px; text-transform: uppercase;
  color: var(--blue); margin-bottom: 12px;
}
header h1 {
  font-size: clamp(1.6rem, 3.5vw, 2.4rem);
  font-weight: 900; letter-spacing: -.6px; line-height: 1.1;
  margin-bottom: 12px;
}
header h1 span { color: var(--blue); }
.subtitle {
  color: var(--muted); font-size: 13px; line-height: 1.6;
  max-width: 520px; margin: 0 auto;
}

/* ── Summary strip ── */
.summary-strip {
  background: var(--surface);
  border-bottom: 1px solid var(--border);
  display: flex;
  justify-content: center;
  flex-wrap: wrap;
}
.summary-item {
  padding: 15px 30px;
  text-align: center;
  border-right: 1px solid var(--border);
  min-width: 160px;
}
.summary-item:last-child { border-right: none; }
.s-label {
  display: block;
  color: var(--muted);
  font-size: 10px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 1.4px;
  margin-bottom: 5px;
}
.s-value { display: block; font-size: 1.2rem; font-weight: 800; letter-spacing: -.3px; }
.s-value.small { font-size: .9rem; font-weight: 700; }
.s-sub { display: block; font-size: 10px; color: var(--muted); margin-top: 4px; font-weight: 500; }

/* ── Legend ── */
.legend-bar {
  display: flex;
  justify-content: center;
  gap: 20px;
  flex-wrap: wrap;
  padding: 8px 16px;
  background: var(--surface2);
  border-bottom: 1px solid var(--border);
  font-size: 11px;
  color: var(--muted);
}
.legend-bar span { display: flex; align-items: center; gap: 5px; }
.dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.dot.green { background: var(--green); }
.dot.gray  { background: var(--muted); }
.dot.amber { background: var(--amber); }
.dot.red   { background: var(--red);   }

/* ── Schedule layout ── */
.schedule-wrap { max-width: 1440px; margin: 0 auto; padding: 22px 14px 48px; }
.section-label {
  font-size: 10px; font-weight: 700;
  text-transform: uppercase; letter-spacing: 1.4px;
  color: var(--muted); margin-bottom: 13px;
}

/* ── Date groups ── */
.date-group   { margin-bottom: 28px; }
.date-header  {
  display: flex; align-items: center; gap: 8px;
  font-size: 10px; font-weight: 700; color: var(--muted);
  text-transform: uppercase; letter-spacing: 1.4px;
  padding-bottom: 8px; border-bottom: 1px solid var(--border); margin-bottom: 12px;
}
.game-count { font-size: 10px; color: var(--muted); font-weight: 500; opacity: .7; }
.games-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(272px, 1fr)); gap: 10px; }

/* ── Game cards ── */
.game-card {
  background: var(--surface);
  border-radius: 10px;
  padding: 13px 14px 11px;
  border: 1px solid var(--border);
  border-left: 3px solid #30363d;
  transition: transform .12s ease, box-shadow .12s ease;
}
.game-card:hover { transform: translateY(-2px); box-shadow: 0 6px 24px rgba(0,0,0,.5); }
.game-card.green { border-left-color: var(--green); background: var(--green-dim); border-color: var(--green-bdr); }
.game-card.amber { border-left-color: var(--amber); background: var(--amber-dim); border-color: var(--amber-bdr); }
.game-card.blue  { border-left-color: var(--blue);  background: var(--blue-dim);  border-color: var(--blue-bdr);  }
.game-card.red   { border-left-color: var(--red);   background: var(--red-dim);   border-color: var(--red-bdr);   }
.game-card.gray  { border-left-color: #30363d;       background: var(--gray-dim);  border-color: var(--gray-bdr);  }

.card-top {
  display: flex; justify-content: space-between; align-items: center; gap: 6px; margin-bottom: 10px;
}
.grp-badge {
  background: rgba(47,129,247,.18); color: var(--blue);
  font-size: 9px; font-weight: 700;
  padding: 2px 7px; border-radius: 4px; letter-spacing: .6px;
  border: 1px solid rgba(47,129,247,.3);
}
.card-time { color: var(--muted); font-size: 11px; font-weight: 500; }

.matchup { margin-bottom: 10px; }
.team-row { display: flex; align-items: center; gap: 7px; padding: 3px 0; }
.team-flag { font-size: 16px; line-height: 1; flex-shrink: 0; }
.team-name-wrap { flex: 1; min-width: 0; }
.team-name { font-weight: 600; font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; display: block; }
.title-prob { display: block; font-size: 9px; color: var(--muted); margin-top: 1px; font-weight: 500; }
.vs-line { font-size: 10px; color: var(--muted); padding: 1px 0 1px 23px; font-weight: 500; }
.color-dot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }
.home-dot  { background: var(--blue); }
.away-dot  { background: var(--orange); }

/* Segmented probability bar */
.seg-bar-wrap { display: flex; height: 6px; border-radius: 4px; overflow: hidden; margin: 9px 0 7px; background: var(--border); }
.seg-home { background: var(--blue); }
.seg-draw { background: var(--draw); }
.seg-away { background: var(--orange); }

.prob-labels {
  display: flex;
  justify-content: space-between;
  margin: 4px 0 7px;
  font-size: 11px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}
.prob-label-home { color: var(--blue); }
.prob-label-draw { color: var(--draw); text-align: center; }
.prob-label-away { color: var(--orange); text-align: right; }
.no-odds-msg {
  font-size: 11px;
  color: var(--muted);
  font-style: italic;
  text-align: center;
  padding: 8px 0 6px;
}
.venue-row { font-size: 10px; color: var(--muted); margin-top: 2px; line-height: 1.35; }
.game-card { cursor: pointer; }
.watch-detail { display: none; border-top: 1px solid var(--border); margin-top: 8px; padding-top: 7px; }
.game-card.expanded .watch-detail { display: block; }
.wd-row { display: flex; align-items: center; gap: 6px; margin: 3px 0; font-size: 10px; }
.wd-label { color: var(--muted); width: 72px; flex-shrink: 0; }
.wd-track { flex: 1; height: 3px; background: var(--border); border-radius: 2px; overflow: hidden; }
.wd-fill  { height: 100%; border-radius: 2px; background: var(--green); }
.wd-val   { color: var(--text); font-weight: 600; width: 26px; text-align: right; flex-shrink: 0; }

/* ── Group standings sidebar ── */
.gs-panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 10px;
  overflow: hidden;
  max-height: calc(100vh - 120px);
  overflow-y: auto;
  scrollbar-width: thin;
  scrollbar-color: var(--border) transparent;
}
.gs-group { border-bottom: 1px solid var(--border); padding: 11px 12px; }
.gs-group:last-child { border-bottom: none; }
.gs-title {
  font-size: 9px; font-weight: 800;
  text-transform: uppercase; letter-spacing: 1.8px;
  color: var(--muted); margin-bottom: 8px;
}
.gs-row {
  display: grid;
  grid-template-columns: 19px 1fr 56px auto;
  align-items: center;
  gap: 5px;
  padding: 3px 0;
}
.gs-flag { font-size: 12px; text-align: center; }
.gs-name-wrap { min-width: 0; }
.gs-name {
  font-size: 11px; font-weight: 500;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; display: block;
  margin-bottom: 2px;
}
.gs-bar-track { background: var(--border); border-radius: 2px; height: 3px; overflow: hidden; }
.gs-bar-fill  { height: 100%; border-radius: 2px; background: var(--blue); }
.gs-pct { font-size: 10px; color: var(--muted); font-variant-numeric: tabular-nums; text-align: right; white-space: nowrap; }
.gs-no-odds { font-size: 10px; color: var(--muted); text-align: right; }

/* ── Completed result cards ── */
.final-badge {
  font-size: 9px; font-weight: 700; padding: 2px 7px; border-radius: 4px;
  letter-spacing: .6px; background: var(--surface2); color: var(--muted);
  border: 1px solid var(--border);
}
.upset-badge {
  font-size: 9px; font-weight: 800; padding: 2px 7px; border-radius: 4px;
  letter-spacing: .6px; background: var(--amber-dim); color: var(--amber);
  border: 1px solid var(--amber-bdr);
}
.game-card[data-completed] { opacity: 0.45; }
.completed-toggle {
  margin-left: auto; font-size: 10px; font-weight: 600;
  color: var(--muted); background: none; border: 1px solid var(--border);
  border-radius: 4px; padding: 2px 9px; cursor: pointer; font-family: inherit;
  white-space: nowrap; transition: color .12s, border-color .12s;
}
.completed-toggle:hover { color: var(--text); border-color: var(--muted); }
.team-score {
  margin-left: auto; font-size: 16px; font-weight: 800;
  font-variant-numeric: tabular-nums; color: var(--muted);
}
.team-row.winner .team-name { font-weight: 700; color: #fff; }
.team-row.winner .team-score { color: var(--green); }
.team-row.loser  { opacity: .65; }
.odds-hist {
  margin-top: 6px; padding-top: 6px; border-top: 1px solid var(--border);
  opacity: .42;
}
.odds-hist-label {
  font-size: 9px; color: var(--muted); text-transform: uppercase;
  letter-spacing: 1px; margin-bottom: 5px;
}

/* ── Footer ── */
footer {
  text-align: center; padding: 20px;
  color: var(--muted); font-size: 11px;
  border-top: 1px solid var(--border);
  line-height: 1.8;
}
footer a { color: var(--blue); text-decoration: none; }
footer a:hover { text-decoration: underline; }

/* ── Responsive ── */
@media (max-width: 960px) {
  .gs-panel     { max-height: none; }
}

/* Tablet (560–960px) */
@media (max-width: 760px) {
  header { padding: 28px 20px 22px; }
  .schedule-wrap { padding: 18px 12px 40px; }
}

/* Mobile (≤560px) */
@media (max-width: 560px) {
  /* Header */
  header { padding: 22px 16px 18px; }
  .header-eyebrow { font-size: 9px; letter-spacing: 1.5px; margin-bottom: 10px; }
  header h1 { margin-bottom: 10px; }
  .subtitle { font-size: 12px; }

  /* Summary strip — stack vertically */
  .summary-strip { flex-direction: column; }
  .summary-item  {
    border-right: none; border-bottom: 1px solid var(--border);
    padding: 12px 20px; min-width: 0;
  }
  .summary-item:last-child { border-bottom: none; }

  /* Legend — horizontal scroll instead of wrapping */
  .legend-bar {
    flex-wrap: nowrap; overflow-x: auto;
    justify-content: flex-start; gap: 14px;
    padding: 8px 14px;
    -webkit-overflow-scrolling: touch;
    scrollbar-width: none;
  }
  .legend-bar::-webkit-scrollbar { display: none; }

  /* Schedule layout */
  .schedule-wrap { padding: 14px 0 36px; }

  /* Re-add padding only to non-card elements */
  .sort-toggle   { padding: 0 10px; }
  .section-label { padding-left: 10px; }
  .date-header   { padding-left: 10px; padding-right: 10px; }

  /* Cards — full screen width, no margins needed */
  .games-grid { grid-template-columns: 1fr; gap: 6px; margin: 0; }
  .game-card  { padding: 11px 12px 9px; border-radius: 6px; }
  .game-card:hover { transform: none; }

  /* Bigger touch targets for sort buttons */
  .sort-btn    { padding: 9px 16px; font-size: 12px; }
  .sort-toggle { margin-bottom: 12px; }

  /* Sidebar */
  .section-label { margin-bottom: 10px; }
  .mc-sim-note   { font-size: 9px; }
  .gs-group      { padding: 10px 11px; }
}

/* ── Watchability ── */
.watch-row { display: flex; align-items: center; gap: 8px; margin: 7px 0 5px; }
.watch-label { font-size: 9px; text-transform: uppercase; letter-spacing: 1.1px; color: var(--muted); flex-shrink: 0; font-weight: 600; }
.watch-bar-wrap { flex: 1; height: 4px; background: rgba(255,255,255,.07); border-radius: 2px; overflow: hidden; }
.watch-bar-fill { height: 100%; border-radius: 2px; transition: width .3s ease; }
.game-card.green .watch-bar-fill { background: var(--green); }
.game-card.blue  .watch-bar-fill { background: var(--blue);  }
.game-card.amber .watch-bar-fill { background: var(--amber); }
.game-card.red   .watch-bar-fill { background: var(--red); }
.game-card.gray  .watch-bar-fill { background: var(--muted); opacity: .4; }
.watch-score { font-size: 14px; font-weight: 800; font-variant-numeric: tabular-nums; flex-shrink: 0; min-width: 22px; text-align: right; }
.game-card.green .watch-score { color: var(--green); }
.game-card.blue  .watch-score { color: var(--blue);  }
.game-card.amber .watch-score { color: var(--amber); }
.game-card.red   .watch-score { color: var(--red); }
.game-card.gray  .watch-score { color: var(--muted); }
.watch-pending { font-size: 9px; color: var(--amber); }
.faded { opacity: .4; }

/* ── Monte Carlo group standings ── */
.mc-sim-note {
  font-size: 10px;
  color: var(--muted);
  margin-bottom: 8px;
  line-height: 1.4;
  font-style: italic;
}
.mc-table {
  width: 100%;
  border-collapse: collapse;
  table-layout: fixed;
}
.mc-table thead th {
  font-size: 9px; font-weight: 700;
  text-transform: uppercase; letter-spacing: .5px;
  padding: 3px 0 5px;
  border-bottom: 1px solid var(--border);
  text-align: right;
}
.mc-table thead th:first-child { text-align: left; }
.mc-table thead th:not(:first-child) { padding-left: 6px; }
.mc-th-1st   { color: var(--green); width: 34px; }
.mc-th-2nd   { color: var(--amber); width: 34px; }
.mc-th-3rd   { color: var(--muted); width: 34px; }
.mc-th-4th   { color: var(--red);   width: 34px; }
.mc-table tbody td {
  padding: 4px 0 3px;
  border-bottom: 1px solid rgba(31,45,71,.5);
  text-align: right;
  font-variant-numeric: tabular-nums;
  font-size: 11px;
  color: var(--muted);
}
.mc-table tbody td:not(:first-child) { padding-left: 6px; }
.mc-table tbody tr:last-child td { border-bottom: none; }
.mc-td-team {
  text-align: left !important;
  color: var(--text);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  max-width: 0;
}
.mc-td-1st   { color: var(--green); font-weight: 600; }
.mc-td-2nd   { color: var(--amber); font-weight: 600; }

/* ── Date chip (visible in watchability sort only) ── */
.date-chip {
  display: none; font-size: 9px; color: var(--muted);
  background: var(--surface2); border: 1px solid var(--border);
  border-radius: 3px; padding: 1px 5px; white-space: nowrap;
}

/* ── Sort toggle ── */
.sort-toggle { display: flex; gap: 6px; margin-bottom: 13px; }
.sort-btn {
  padding: 6px 14px; border-radius: 6px;
  border: 1px solid var(--border); background: var(--surface);
  color: var(--muted); font-size: 11px; font-weight: 600;
  cursor: pointer; letter-spacing: .3px; font-family: inherit;
  transition: background .12s, color .12s, border-color .12s;
}
.sort-btn:hover { background: var(--surface2); color: var(--text); }
.sort-active { background: var(--blue) !important; color: #fff !important; border-color: var(--blue) !important; }

/* ── Tabs ── */
.tab-bar { display:flex; gap:8px; padding:16px 18px; background:var(--surface); border-bottom:2px solid var(--border); }
.tab-btn { padding:10px 24px; border-radius:8px; border:2px solid var(--border); background:var(--bg); color:var(--muted); font-size:14px; font-weight:700; cursor:pointer; font-family:inherit; letter-spacing:.3px; transition:color .15s,background .15s,border-color .15s; }
.tab-btn:hover { color:var(--text); border-color:var(--blue); }
.tab-btn.tab-active { background:var(--blue); color:#fff; border-color:var(--blue); }
.tab-panel { display:none; }
.tab-panel.tab-visible { display:block; }

/* ── Tournament table ── */
.tourn-wrap { max-width:960px; margin:0 auto; padding:20px 14px 48px; }
.tourn-scroll { overflow-x:auto; -webkit-overflow-scrolling:touch; }
.tourn-table { width:100%; border-collapse:collapse; font-size:13px; min-width:560px; }
.tourn-table th { cursor:pointer; padding:6px 8px; text-align:right; border-bottom:2px solid var(--border); color:var(--muted); font-weight:500; white-space:nowrap; user-select:none; }
.tourn-table th:nth-child(2) { text-align:left; }
.tourn-table td { padding:5px 8px; text-align:right; border-bottom:1px solid var(--border); font-size:12px; }
.tourn-table td:nth-child(2) { text-align:left; white-space:nowrap; }
.tourn-table th.sort-active { color:var(--text); }
.tourn-table tr:hover td { background:var(--surface2) !important; }
.tourn-note { font-size:11px; color:var(--muted); margin-top:8px; }
.pending { font-size:13px; color:var(--muted); padding:2rem 0; text-align:center; }
"""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_odds(db_path: str) -> tuple:
    """
    Return (odds_by_matchup, fetched_at) where odds_by_matchup is
    {(home, away): {"home_prob": float, "draw_prob": float, "away_prob": float}}.
    Uses the most recent fetched_at per individual match so completed games
    still display their last known line.
    """
    if not os.path.exists(db_path):
        return {}, None

    conn = sqlite3.connect(db_path)
    try:
        # Check if match_odds table exists
        tbl = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='match_odds'"
        ).fetchone()
        if not tbl:
            return {}, None

        rows = conn.execute("""
            SELECT home_team, away_team, home_prob, draw_prob, away_prob
            FROM match_odds m1
            WHERE fetched_at = (
                SELECT MAX(fetched_at) FROM match_odds m2
                WHERE m2.home_team = m1.home_team AND m2.away_team = m1.away_team
            )
        """).fetchall()

        latest = conn.execute("SELECT MAX(fetched_at) FROM match_odds").fetchone()
        fetched_at = latest[0] if latest else None

        odds = {}
        for home, away, hp, dp, ap in rows:
            odds[(home, away)] = {"home_prob": hp, "draw_prob": dp, "away_prob": ap}

        return odds, fetched_at
    finally:
        conn.close()


def get_results(db_path: str) -> dict:
    """Return {(home, away): {"home_score": int, "away_score": int}}."""
    if not os.path.exists(db_path):
        return {}
    conn = sqlite3.connect(db_path)
    try:
        tbl = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='match_results'"
        ).fetchone()
        if not tbl:
            return {}
        rows = conn.execute(
            "SELECT home_team, away_team, home_score, away_score FROM match_results"
        ).fetchall()
        return {(h, a): {"home_score": hs, "away_score": aws} for h, a, hs, aws in rows}
    finally:
        conn.close()


def fmt_pct(p, d: int = 1) -> str:
    return "—" if p is None else f"{p * 100:.{d}f}%"



def watch_cls(w) -> str:
    """Card color class based on normalized watchability score."""
    if w is None:
        return "gray"
    if w >= 65:
        return "green"
    if w >= 50:
        return "gray"
    return "red"


def flag(team: str) -> str:
    return FLAGS.get(team, "🏳️")


def get_leaderboard_data():
    """Return [(team, p_champion, spi_overall), ...] from spi_ratings.db, sorted by p_champion desc."""
    conn = get_spi_conn()
    if not conn:
        return []
    try:
        rows = conn.execute("""
            SELECT t.team, t.p_champion, r.spi_overall
            FROM tournament_probs t
            LEFT JOIN team_ratings r ON t.team = r.team
            ORDER BY t.p_champion DESC
        """).fetchall()
        return rows
    except Exception:
        return []
    finally:
        conn.close()


def get_completed_results(db_path: str) -> dict:
    """Return {(home, away): {'home_score': int, 'away_score': int}} for completed matches only."""
    if not os.path.exists(db_path):
        return {}
    conn = sqlite3.connect(db_path)
    try:
        tbl = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='match_results'"
        ).fetchone()
        if not tbl:
            return {}
        cols = [row[1] for row in conn.execute("PRAGMA table_info(match_results)").fetchall()]
        if 'completed' in cols:
            rows = conn.execute(
                "SELECT home_team, away_team, home_score, away_score "
                "FROM match_results WHERE completed = 1"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT home_team, away_team, home_score, away_score FROM match_results"
            ).fetchall()
        return {(h, a): {"home_score": hs, "away_score": aws} for h, a, hs, aws in rows}
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# SPI watchability helpers
# ---------------------------------------------------------------------------

SPI_DB_PATH = "spi_ratings.db"


def get_spi_conn():
    """Return a raw sqlite3 connection to spi_ratings.db, or None if unavailable."""
    if not os.path.exists(SPI_DB_PATH):
        return None
    return sqlite3.connect(SPI_DB_PATH)


def query_spi(sql: str, params=(), write: bool = False):
    """Execute a query against spi_ratings.db. Returns list of row dicts or None on error."""
    if not os.path.exists(SPI_DB_PATH):
        return None
    try:
        conn = sqlite3.connect(SPI_DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            cur = conn.execute(sql, params)
            if write:
                conn.commit()
                return []
            rows = cur.fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()
    except Exception:
        return None


def _ensure_match_predictions() -> None:
    """Populate match_predictions in spi_ratings.db from stored team_ratings if missing."""
    if not os.path.exists(SPI_DB_PATH):
        return
    try:
        conn = sqlite3.connect(SPI_DB_PATH)
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS match_predictions (
                    home_team         TEXT,
                    away_team         TEXT,
                    spi_home_win      REAL,
                    spi_draw          REAL,
                    spi_away_win      REAL,
                    mu_home           REAL,
                    mu_away           REAL,
                    most_likely_score TEXT,
                    PRIMARY KEY (home_team, away_team)
                )
            """)
            conn.commit()
            # Migrate: add any columns that are missing from an older schema
            existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(match_predictions)").fetchall()}
            for col, typedef in [("mu_home", "REAL"), ("mu_away", "REAL"), ("most_likely_score", "TEXT")]:
                if col not in existing_cols:
                    conn.execute(f"ALTER TABLE match_predictions ADD COLUMN {col} {typedef}")
            conn.commit()
            # Only skip if already populated with the extended schema
            if conn.execute("SELECT COUNT(*) FROM match_predictions WHERE mu_home IS NOT NULL").fetchone()[0] > 0:
                return
            rows = conn.execute(
                "SELECT team, attack_rating, defense_rating FROM team_ratings"
            ).fetchall()
            ratings = {t: (ar, dr) for t, ar, dr in rows}
            params_map = dict(conn.execute(
                "SELECT param, value FROM model_params"
            ).fetchall())
            baseline = math.exp(params_map.get("intercept", 0.0))
            rho = -0.13
            k = list(range(11))
            # Derive unique team lists per group from the fallback schedule
            teams_by_group: dict = {}
            for g in _SCHEDULE_FALLBACK:
                grp = g["grp"]
                if grp not in teams_by_group:
                    teams_by_group[grp] = []
                for t in (g["home"], g["away"]):
                    if t not in teams_by_group[grp]:
                        teams_by_group[grp].append(t)
            from itertools import combinations as _comb
            inserts = []
            for grp, teams in teams_by_group.items():
                for home, away in _comb(teams, 2):
                    if home not in ratings or away not in ratings:
                        continue
                    ar_a, dr_a = ratings[home]
                    ar_b, dr_b = ratings[away]
                    mu_a = ar_a * dr_b / baseline
                    mu_b = ar_b * dr_a / baseline
                    pa = [math.exp(-mu_a) * mu_a**i / math.factorial(i) for i in k]
                    pb = [math.exp(-mu_b) * mu_b**j / math.factorial(j) for j in k]
                    mat = [[pa[i] * pb[j] for j in k] for i in k]
                    mat[0][0] *= (1 - mu_a * mu_b * rho)
                    mat[1][0] *= (1 + mu_b * rho)
                    mat[0][1] *= (1 + mu_a * rho)
                    mat[1][1] *= (1 - rho)
                    total = sum(mat[i][j] for i in k for j in k)
                    if total > 0:
                        mat = [[mat[i][j] / total for j in k] for i in k]
                    a_win = sum(mat[i][j] for i in k for j in k if i > j)
                    draw  = sum(mat[i][j] for i in k for j in k if i == j)
                    b_win = 1.0 - a_win - draw
                    # Most likely scoreline
                    best_i, best_j, best_p = 0, 0, -1.0
                    for i in k:
                        for j in k:
                            if mat[i][j] > best_p:
                                best_p = mat[i][j]
                                best_i, best_j = i, j
                    inserts.append((home, away,
                                    round(a_win, 4), round(draw, 4), round(b_win, 4),
                                    round(mu_a, 4), round(mu_b, 4),
                                    f"{best_i}-{best_j}"))
            conn.executemany(
                "INSERT OR REPLACE INTO match_predictions VALUES (?,?,?,?,?,?,?,?)",
                inserts,
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        pass


def get_spi_prediction(home: str, away: str):
    """Return SPI prediction dict or None. Handles flipped table ordering."""
    sql = ("SELECT spi_home_win, spi_draw, spi_away_win, mu_home, mu_away, most_likely_score "
           "FROM match_predictions WHERE home_team=? AND away_team=?")
    rows = query_spi(sql, (home, away))
    if rows:
        return rows[0]
    rows = query_spi(sql, (away, home))
    if rows:
        r = rows[0]
        score = r.get("most_likely_score") or ""
        if "-" in score:
            a, b = score.split("-", 1)
            score = f"{b}-{a}"
        return {
            "spi_home_win":      r["spi_away_win"],
            "spi_draw":          r["spi_draw"],
            "spi_away_win":      r["spi_home_win"],
            "mu_home":           r.get("mu_away"),
            "mu_away":           r.get("mu_home"),
            "most_likely_score": score,
        }
    return None


def get_leverage(home: str, away: str):
    """Return leverage_score for this matchup or None. Handles flipped table ordering."""
    sql = "SELECT leverage_score FROM game_leverage WHERE home_team=? AND away_team=?"
    rows = query_spi(sql, (home, away))
    if rows:
        return rows[0].get("leverage_score")
    rows = query_spi(sql, (away, home))
    if rows:
        return rows[0].get("leverage_score")
    return None


def get_closeness(home: str, away: str) -> float:
    pred = get_spi_prediction(home, away)
    if not pred:
        return 0.5
    max_prob = max(pred["spi_home_win"], pred["spi_draw"], pred["spi_away_win"])
    return 1.0 - ((max_prob - 1/3) / (2/3))


def get_importance(home: str, away: str) -> float:
    lev = get_leverage(home, away)
    if lev is None:
        return 0.0
    max_rows = query_spi("SELECT value FROM model_params WHERE param='max_leverage'")
    if max_rows:
        max_lev = max_rows[0]["value"]
    else:
        agg = query_spi("SELECT MAX(leverage_score) AS m FROM game_leverage")
        max_lev = agg[0]["m"] if agg else 0.0
        if max_lev:
            query_spi(
                "INSERT OR REPLACE INTO model_params (param, value) VALUES ('max_leverage', ?)",
                (max_lev,), write=True
            )
    if not max_lev:
        return 0.0
    return min(lev / max_lev, 1.0)


def get_quality(home: str, away: str) -> float:
    h_rows = query_spi("SELECT spi_overall FROM team_ratings WHERE team=?", (home,))
    a_rows = query_spi("SELECT spi_overall FROM team_ratings WHERE team=?", (away,))
    home_val = h_rows[0]["spi_overall"] if h_rows else 50.0
    away_val = a_rows[0]["spi_overall"] if a_rows else 50.0
    top_two  = query_spi(
        "SELECT spi_overall FROM team_ratings ORDER BY spi_overall DESC LIMIT 2"
    )
    max_combined = sum(r["spi_overall"] for r in top_two) if top_two else 200.0
    return min((home_val + away_val) / max_combined, 1.0)


_ABBREV = {
    "United States":       "USA",
    "South Korea":         "KOR",
    "South Africa":        "RSA",
    "Bosnia-Herzegovina":  "BIH",
    "Saudi Arabia":        "KSA",
    "New Zealand":         "NZL",
    "Cape Verde":          "CPV",
    "Ivory Coast":         "CIV",
    "DR Congo":            "DRC",
}

def abbrev(name: str) -> str:
    return _ABBREV.get(name, name[:3].upper())


def watchability_score(home: str, away: str) -> dict:
    closeness  = get_closeness(home, away)
    importance = get_importance(home, away)
    quality    = get_quality(home, away)
    return {
        "score":      round(((closeness + importance + quality) / 3) * 100),
        "closeness":  round(closeness  * 100),
        "importance": round(importance * 100),
        "quality":    round(quality    * 100),
    }


def build_tournament_tab() -> str:
    conn = get_spi_conn()
    if not conn:
        return "<p class='pending'>Simulation pending — check back after the next scheduled update.</p>"
    try:
        rows = conn.execute("""
            SELECT t.team, t.p_group_advance, t.p_r16,
                   t.p_qf, t.p_sf, t.p_final, t.p_champion,
                   r.spi_overall
            FROM tournament_probs t
            LEFT JOIN team_ratings r ON t.team = r.team
            ORDER BY t.p_champion DESC
        """).fetchall()
    except Exception as e:
        return f"<p class='pending'>Data unavailable.</p>"
    finally:
        conn.close()

    if not rows:
        return "<p class='pending'>Simulation pending.</p>"

    col_keys = ['p_group_advance', 'p_r16', 'p_qf', 'p_sf', 'p_final', 'p_champion']
    maxes = {c: max((r[i + 1] for r in rows), default=1) or 1 for i, c in enumerate(col_keys)}

    def cell_bg(val, col):
        if not val:
            return ''
        intensity = round((val / maxes[col]) * 0.85, 3)
        return f'style="background:rgba(34,197,94,{intensity})"'

    header = (
        '<div class="tourn-wrap">'
        '<div class="tourn-scroll">'
        '<table id="tourn-table" class="tourn-table"><thead><tr>'
        '<th onclick="sortTourn(0)" data-col="0">#</th>'
        '<th onclick="sortTourn(1)" data-col="1">Team</th>'
        '<th onclick="sortTourn(2)" data-col="2">SPI</th>'
        '<th onclick="sortTourn(3)" data-col="3">Advance</th>'
        '<th onclick="sortTourn(4)" data-col="4">R16</th>'
        '<th onclick="sortTourn(5)" data-col="5">QF</th>'
        '<th onclick="sortTourn(6)" data-col="6">SF</th>'
        '<th onclick="sortTourn(7)" data-col="7">Final</th>'
        '<th onclick="sortTourn(8)" data-col="8" class="sort-active">Champion &#8595;</th>'
        '</tr></thead><tbody>'
    )

    body_rows = []
    for i, r in enumerate(rows):
        team, pa, pr16, pqf, psf, pf, pc, spi = r
        spi_str = f"{spi:.1f}" if spi is not None else "—"
        body_rows.append(
            f'<tr>'
            f'<td>{i + 1}</td>'
            f'<td>{flag(team)}&nbsp;{esc(team)}</td>'
            f'<td>{spi_str}</td>'
            f'<td {cell_bg(pa,  "p_group_advance")}>{pa  * 100:.1f}%</td>'
            f'<td {cell_bg(pr16,"p_r16"          )}>{pr16 * 100:.1f}%</td>'
            f'<td {cell_bg(pqf, "p_qf"           )}>{pqf  * 100:.1f}%</td>'
            f'<td {cell_bg(psf, "p_sf"            )}>{psf  * 100:.1f}%</td>'
            f'<td {cell_bg(pf,  "p_final"         )}>{pf   * 100:.1f}%</td>'
            f'<td {cell_bg(pc,  "p_champion"      )}>{pc   * 100:.1f}%</td>'
            f'</tr>'
        )

    js = (
        '<script>'
        'var _tDir=-1,_tCol=8;'
        'function sortTourn(col){'
        'var tbl=document.getElementById("tourn-table");'
        'var tbody=tbl.querySelector("tbody");'
        'var rows=Array.from(tbody.querySelectorAll("tr"));'
        'if(col===_tCol)_tDir*=-1;else{_tDir=-1;_tCol=col;}'
        'rows.sort(function(a,b){'
        'var av=a.cells[col].innerText.replace("%","").replace("—","0");'
        'var bv=b.cells[col].innerText.replace("%","").replace("—","0");'
        'return _tDir*(parseFloat(bv)-parseFloat(av));'
        '});'
        'rows.forEach(function(r,i){r.cells[0].innerText=i+1;tbody.appendChild(r);});'
        'tbl.querySelectorAll("th").forEach(function(th,i){'
        'th.className=i===_tCol?"sort-active":"";'
        'th.innerHTML=th.innerHTML.replace(/[ ↑↓↑↓]/g,"")+(i===_tCol?(_tDir===-1?" ↓":" ↑"):"");'
        '});'
        '}'
        '</script>'
    )

    return (
        header + "".join(body_rows) + '</tbody></table>'
        '</div>'
        '<p class="tourn-note">Probabilities from 10,000-run Monte Carlo simulation '
        'using SPI Poisson model. Updated daily.</p>'
        '</div>' + js
    )


def build_groups_data(schedule, groups, odds, completed_results):
    """
    Build simulation input data from schedule, groups, odds, and completed results.
    Returns (groups_data, missing_odds_matches, current_actual_points).
    """
    current_actual_points = {t: 0 for grp_teams in groups.values() for t in grp_teams}

    for (home, away), result in completed_results.items():
        hs = result["home_score"]
        aws = result["away_score"]
        if hs > aws:
            current_actual_points[home] = current_actual_points.get(home, 0) + 3
        elif aws > hs:
            current_actual_points[away] = current_actual_points.get(away, 0) + 3
        else:
            current_actual_points[home] = current_actual_points.get(home, 0) + 1
            current_actual_points[away] = current_actual_points.get(away, 0) + 1

    groups_data = {}
    missing_odds_matches = []

    for grp, teams in groups.items():
        fixed_points = {t: current_actual_points.get(t, 0) for t in teams}
        fixed_gf     = {t: 0 for t in teams}
        fixed_ga     = {t: 0 for t in teams}
        fixed_h2h    = {}

        for (home, away), result in completed_results.items():
            if home not in fixed_gf or away not in fixed_gf:
                continue
            hs, aws = result["home_score"], result["away_score"]
            fixed_gf[home] += hs;  fixed_ga[home] += aws
            fixed_gf[away] += aws; fixed_ga[away] += hs
            fixed_h2h[(home, away)] = (hs, aws)

        matches = []
        for g in schedule:
            if g["grp"] != grp:
                continue
            key = (g["home"], g["away"])
            if key in completed_results:
                continue
            pred = get_spi_prediction(g["home"], g["away"])
            if pred:
                hw       = pred["spi_home_win"]
                d        = pred["spi_draw"]
                aw       = pred["spi_away_win"]
                mu_home  = pred.get("mu_home") or 1.2
                mu_away  = pred.get("mu_away") or 1.0
            else:
                hw, d, aw       = 1 / 3, 1 / 3, 1 / 3
                mu_home, mu_away = 1.2, 1.0
            matches.append({
                "home": g["home"],
                "away": g["away"],
                "home_win_prob": hw,
                "draw_prob":     d,
                "away_win_prob": aw,
                "mu_home":       mu_home,
                "mu_away":       mu_away,
            })
        groups_data[grp] = {
            "teams":       teams,
            "matches":     matches,
            "fixed_points": fixed_points,
            "fixed_gf":    fixed_gf,
            "fixed_ga":    fixed_ga,
            "fixed_h2h":   fixed_h2h,
        }

    return groups_data, missing_odds_matches, current_actual_points


def _poisson_sample(lam: float) -> int:
    """Sample from Poisson(lam) using Knuth's algorithm."""
    if lam <= 0:
        return 0
    L = math.exp(-min(lam, 20))
    k, p = 0, 1.0
    while True:
        k += 1
        p *= random.random()
        if p <= L:
            return k - 1


def _rank_group_stage_tied(teams: list, h2h: dict, ogd: dict, ogf: dict) -> list:
    """
    Rank equal-points teams by FIFA 2026 Article 13 cascade:
      H2H pts → H2H GD → H2H GF* → overall GD → overall GF → random
    * H2H GF is skipped for 2-team subsets: in a single round-robin each pair
      plays exactly once, so H2H GD tied for two teams means the match was a
      draw (equal goals each way), making H2H GF identical as well.
      If the format ever allowed multiple H2H matches this skip would not hold.
    h2h : {(home, away): (home_score, away_score)} — either key order accepted.
    """
    from itertools import combinations

    def _h2h_stats(subset):
        pts = {t: 0 for t in subset}
        gd  = {t: 0 for t in subset}
        gf  = {t: 0 for t in subset}
        for a, b in combinations(subset, 2):
            if   (a, b) in h2h: ga, gb = h2h[(a, b)]
            elif (b, a) in h2h: gb, ga = h2h[(b, a)]
            else: continue
            gf[a] += ga; gf[b] += gb
            gd[a] += ga - gb; gd[b] += gb - ga
            if   ga > gb: pts[a] += 3
            elif gb > ga: pts[b] += 3
            else:         pts[a] += 1; pts[b] += 1
        return pts, gd, gf

    def _partition(lst, key_fn):
        vals = {t: key_fn(t) for t in lst}
        return [[t for t in lst if vals[t] == v]
                for v in sorted(set(vals.values()), reverse=True)]

    def _rank_overall(subset):
        result = []
        for g1 in _partition(subset, lambda t: ogd[t]):
            if len(g1) == 1:
                result.extend(g1)
            else:
                for g2 in _partition(g1, lambda t: ogf[t]):
                    if len(g2) == 1:
                        result.extend(g2)
                    else:
                        result.extend(sorted(g2, key=lambda _: random.random()))
        return result

    def _rank_h2h(subset, crit_idx):
        if len(subset) == 1:
            return list(subset)
        # Skip H2H GF for 2-team subsets (see docstring above).
        if crit_idx > 2 or (crit_idx == 2 and len(subset) == 2):
            return _rank_overall(subset)
        hp, hgd, hgf = _h2h_stats(subset)
        crit = (hp, hgd, hgf)[crit_idx]
        groups = _partition(subset, lambda t: crit[t])
        if len(groups) == 1:
            return _rank_h2h(subset, crit_idx + 1)
        result = []
        for group in groups:
            if len(group) == 1:
                result.extend(group)
            else:
                # Article 13: reduced sub-group restarts from H2H step 1.
                result.extend(_rank_h2h(group, 0))
        return result

    return _rank_h2h(list(teams), 0)


def run_all_simulations(groups_data, n=10000):
    """
    Run Monte Carlo simulations for all 12 groups simultaneously.
    Tracks cross-group best third-place advancement (top 8 of 12 third-place finishers advance).
    Returns {grp: {team: {1: float, 2: float, 3: float, '3adv': float, 4: float}}}
    """
    group_names = list(groups_data.keys())
    finish_counts = {
        grp: {t: {1: 0, 2: 0, 3: 0, 4: 0} for t in groups_data[grp]["teams"]}
        for grp in group_names
    }
    third_adv_counts = {
        grp: {t: 0 for t in groups_data[grp]["teams"]}
        for grp in group_names
    }

    for _ in range(n):
        third_place_info = []

        for grp in group_names:
            gd    = groups_data[grp]
            teams = gd["teams"]
            points = dict(gd["fixed_points"])
            gf     = dict(gd["fixed_gf"])
            ga     = dict(gd["fixed_ga"])
            h2h    = dict(gd["fixed_h2h"])

            for match in gd["matches"]:
                hs  = _poisson_sample(match["mu_home"])
                aws = _poisson_sample(match["mu_away"])
                h2h[(match["home"], match["away"])] = (hs, aws)
                gf[match["home"]] += hs;  ga[match["home"]] += aws
                gf[match["away"]] += aws; ga[match["away"]] += hs
                if hs > aws:
                    points[match["home"]] += 3
                elif aws > hs:
                    points[match["away"]] += 3
                else:
                    points[match["home"]] += 1
                    points[match["away"]] += 1

            ogd = {t: gf[t] - ga[t] for t in teams}

            # Rank: group by points, then apply FIFA 2026 Article 13 within ties.
            by_pts = {}
            for t in teams:
                by_pts.setdefault(points[t], []).append(t)
            standings = []
            for pt_val in sorted(by_pts, reverse=True):
                tied = by_pts[pt_val]
                if len(tied) == 1:
                    standings.extend(tied)
                else:
                    standings.extend(_rank_group_stage_tied(tied, h2h, ogd, gf))

            for pos, team in enumerate(standings, 1):
                finish_counts[grp][team][pos] += 1

            third_team = standings[2]
            third_ogd  = ogd[third_team]
            third_place_info.append((points[third_team], third_ogd, random.random(), grp, third_team))

        third_place_info.sort(key=lambda x: (x[0], x[1], x[2]), reverse=True)
        for *_, grp, team in third_place_info[:8]:
            third_adv_counts[grp][team] += 1

    results = {}
    for grp in group_names:
        results[grp] = {}
        for team in groups_data[grp]["teams"]:
            probs = {pos: finish_counts[grp][team][pos] / n for pos in [1, 2, 3, 4]}
            probs["3adv"] = third_adv_counts[grp][team] / n
            results[grp][team] = probs
    return results


# ---------------------------------------------------------------------------
# HTML builder
# ---------------------------------------------------------------------------

def build_html(odds: dict, fetched_at, schedule: list = None, results: dict = None,
               sim_results: dict = None, current_actual_points: dict = None) -> str:
    if schedule is None:
        schedule = _SCHEDULE_FALLBACK
    if results is None:
        results = {}

    # ---- pre-compute watchability for all 72 games (SPI 3-component model) ----
    _ensure_match_predictions()
    watchability: dict = {}
    for g in schedule:
        watchability[(g["home"], g["away"])] = watchability_score(g["home"], g["away"])

    # ---- schedule ----
    date_games: dict = {}
    for g in schedule:
        date_games.setdefault(g["date"], []).append(g)

    games_with_odds = sum(1 for g in schedule if (g["home"], g["away"]) in odds)

    # ---- game of the day (most competitive match today in ET) ----
    gotd_matchup = "No games today"
    gotd_time = ""
    try:
        from zoneinfo import ZoneInfo
        today_et = datetime.datetime.now(ZoneInfo("America/New_York"))
        today_fmt = today_et.strftime("%a, %b ") + str(today_et.day)
        today_with_odds = [
            (g, odds[(g["home"], g["away"])])
            for g in schedule
            if g["date"] == today_fmt and (g["home"], g["away"]) in odds
        ]
        if today_with_odds:
            best_g, best_o = max(
                today_with_odds,
                key=lambda x: (watchability.get((x[0]["home"], x[0]["away"])) or {}).get("score", 0),
            )
            gotd_matchup = f'{esc(best_g["home"])} vs {esc(best_g["away"])}'
            gotd_time = best_g["time"]
        elif any(g["date"] == today_fmt for g in schedule):
            gotd_matchup = "Odds pending"
    except Exception:
        pass

    if fetched_at:
        try:
            from zoneinfo import ZoneInfo
            dt = datetime.datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
            et = dt.astimezone(ZoneInfo("America/New_York"))
            tz_label = "EDT" if et.dst() else "EST"
            time_str = et.strftime("%I:%M %p").lstrip("0")
            updated_str = et.strftime("%b %d, %Y ") + time_str + " " + tz_label
        except Exception:
            updated_str = fetched_at
    else:
        updated_str = "No data yet"

    # ---- schedule HTML ----
    sched = []
    for date, games in date_games.items():
        n = len(games)
        sched.append(
            f'<div class="date-group">'
            f'<div class="date-header">{esc(date)}'
            f'<span class="game-count">({n} game{"s" if n != 1 else ""})</span>'
            f'</div><div class="games-grid">'
        )
        for g in games:
            game_key = (g["home"], g["away"])
            o = odds.get(game_key)
            hp = o["home_prob"] if o else None
            dp = o["draw_prob"] if o else None
            ap = o["away_prob"] if o else None
            w_data = watchability.get(game_key)
            w = w_data["score"] if w_data else None
            data_w = str(w) if w is not None else ""
            card_cls = watch_cls(w)
            watch_score_str = str(w) if w is not None else "—"

            r = results.get(game_key)

            if r:
                # ── completed game ──────────────────────────────────────────
                hs = r["home_score"]
                aws = r["away_score"]

                comp_pred = get_spi_prediction(g["home"], g["away"])
                if hs > aws:
                    home_cls, away_cls = "winner", "loser"
                    winning_prob = comp_pred["spi_home_win"] if comp_pred else None
                    losing_prob  = comp_pred["spi_away_win"] if comp_pred else None
                elif aws > hs:
                    home_cls, away_cls = "loser", "winner"
                    winning_prob = comp_pred["spi_away_win"] if comp_pred else None
                    losing_prob  = comp_pred["spi_home_win"] if comp_pred else None
                else:
                    home_cls = away_cls = ""
                    winning_prob = comp_pred["spi_draw"] if comp_pred else None
                    losing_prob  = max(comp_pred["spi_home_win"], comp_pred["spi_away_win"]) if comp_pred else None

                is_upset = (
                    winning_prob is not None and
                    losing_prob  is not None and
                    winning_prob < losing_prob
                )
                upset_badge = '<span class="upset-badge">UPSET</span>' if is_upset else ""

                sched.append(
                    f'<div class="game-card gray" data-w="" data-date="{esc(g["date"])}" data-completed="1">'
                    f'<div class="card-top">'
                    f'<span class="grp-badge">GRP {esc(g["grp"])}</span>'
                    + upset_badge +
                    f'<span class="date-chip">{esc(g["date"])}</span>'
                    f'<span class="final-badge">FINAL</span>'
                    f'</div>'
                    f'<div class="matchup">'
                    f'<div class="team-row {home_cls}">'
                    f'<span class="color-dot home-dot"></span>'
                    f'<span class="team-flag">{flag(g["home"])}</span>'
                    f'<div class="team-name-wrap">'
                    f'<span class="team-name">{esc(g["home"])}</span>'
                    f'</div>'
                    f'<span class="team-score">{hs}</span>'
                    f'</div>'
                    f'<div class="vs-line">vs</div>'
                    f'<div class="team-row {away_cls}">'
                    f'<span class="color-dot away-dot"></span>'
                    f'<span class="team-flag">{flag(g["away"])}</span>'
                    f'<div class="team-name-wrap">'
                    f'<span class="team-name">{esc(g["away"])}</span>'
                    f'</div>'
                    f'<span class="team-score">{aws}</span>'
                    f'</div>'
                    f'</div>'
                    f'<div class="venue-row">{esc(g["venue"])}</div>'
                    f'</div>'
                )
            else:
                # ── upcoming / no result yet ─────────────────────────────────
                pred = get_spi_prediction(g["home"], g["away"])
                if pred:
                    hw_pct = round(pred["spi_home_win"] * 100)
                    dr_pct = round(pred["spi_draw"] * 100)
                    aw_pct = 100 - hw_pct - dr_pct
                    prob_html = (
                        f'<div class="seg-bar-wrap">'
                        f'<div class="seg-home" style="width:{hw_pct}%"></div>'
                        f'<div class="seg-draw" style="width:{dr_pct}%"></div>'
                        f'<div class="seg-away" style="width:{aw_pct}%"></div>'
                        f'</div>'
                        f'<div class="prob-labels">'
                        f'<span class="prob-label-home">{esc(abbrev(g["home"]))}&nbsp;{hw_pct}%</span>'
                        f'<span class="prob-label-draw">Draw&nbsp;{dr_pct}%</span>'
                        f'<span class="prob-label-away">{esc(abbrev(g["away"]))}&nbsp;{aw_pct}%</span>'
                        f'</div>'
                    )
                else:
                    prob_html = '<div class="no-odds-msg">Model pending</div>'

                sched.append(
                    f'<div class="game-card {card_cls}" data-w="{data_w}" data-date="{esc(g["date"])}">'
                    f'<div class="card-top">'
                    f'<span class="grp-badge">GRP {esc(g["grp"])}</span>'
                    f'<span class="date-chip">{esc(g["date"])}</span>'
                    f'<span class="card-time">{esc(g["time"])}</span>'
                    f'</div>'
                    f'<div class="watch-row">'
                    f'<span class="watch-label">Watchability</span>'
                    f'<div class="watch-bar-wrap"><div class="watch-bar-fill" style="width:{data_w}%"></div></div>'
                    f'<span class="watch-score">{watch_score_str}</span>'
                    f'</div>'
                    f'<div class="matchup">'
                    f'<div class="team-row">'
                    f'<span class="color-dot home-dot"></span>'
                    f'<span class="team-flag">{flag(g["home"])}</span>'
                    f'<div class="team-name-wrap">'
                    f'<span class="team-name">{esc(g["home"])}</span>'
                    f'</div>'
                    f'</div>'
                    f'<div class="vs-line">vs</div>'
                    f'<div class="team-row">'
                    f'<span class="color-dot away-dot"></span>'
                    f'<span class="team-flag">{flag(g["away"])}</span>'
                    f'<div class="team-name-wrap">'
                    f'<span class="team-name">{esc(g["away"])}</span>'
                    f'</div>'
                    f'</div>'
                    f'</div>'
                    + prob_html +
                    f'<div class="venue-row">{esc(g["venue"])}</div>'
                    + (
                        f'<div class="watch-detail">'
                        f'<div class="wd-row"><span class="wd-label">Closeness</span>'
                        f'<div class="wd-track"><div class="wd-fill" style="width:{w_data["closeness"]}%"></div></div>'
                        f'<span class="wd-val">{w_data["closeness"]}</span></div>'
                        f'<div class="wd-row"><span class="wd-label">Importance</span>'
                        f'<div class="wd-track"><div class="wd-fill" style="width:{w_data["importance"]}%"></div></div>'
                        f'<span class="wd-val">{w_data["importance"]}</span></div>'
                        f'<div class="wd-row"><span class="wd-label">Quality</span>'
                        f'<div class="wd-track"><div class="wd-fill" style="width:{w_data["quality"]}%"></div></div>'
                        f'<span class="wd-val">{w_data["quality"]}</span></div>'
                        f'</div>'
                        if w_data else ''
                    ) +
                    f'</div>'
                )
        sched.append('</div></div>')

    # ---- group standings HTML (Monte Carlo) ----
    spi_champ_probs = {team: pc for team, pc, _ in get_leaderboard_data()}
    gs = []
    for grp, teams in GROUPS.items():
        gs.append(f'<div class="gs-group"><div class="gs-title">Group {esc(grp)}</div>')

        if sim_results and grp in sim_results:
            grp_sim = sim_results[grp]
            sorted_teams = sorted(
                teams,
                key=lambda t: grp_sim[t][1] + grp_sim[t][2],
                reverse=True,
            )
            gs.append(
                '<table class="mc-table">'
                '<thead><tr>'
                '<th>Team</th>'
                '<th class="mc-th-1st">1st</th>'
                '<th class="mc-th-2nd">2nd</th>'
                '<th class="mc-th-3rd">3rd</th>'
                '<th class="mc-th-4th">4th</th>'
                '</tr></thead><tbody>'
            )
            for team in sorted_teams:
                probs = grp_sim[team]
                p1, p2, p3, p4 = probs[1], probs[2], probs[3], probs[4]
                gs.append(
                    f'<tr>'
                    f'<td class="mc-td-team">{flag(team)}&nbsp;{esc(team)}</td>'
                    f'<td class="mc-td-1st">{p1 * 100:.0f}%</td>'
                    f'<td class="mc-td-2nd">{p2 * 100:.0f}%</td>'
                    f'<td>{p3 * 100:.0f}%</td>'
                    f'<td>{p4 * 100:.0f}%</td>'
                    f'</tr>'
                )
            gs.append('</tbody></table>')
        else:
            ranked = sorted(
                [(t, spi_champ_probs.get(t)) for t in teams],
                key=lambda x: -(x[1] if x[1] is not None else -1),
            )
            best = max((p for _, p in ranked if p is not None), default=None)
            for team, pc in ranked:
                bar_w = int((pc / best) * 100) if pc is not None and best else 0
                pct_str = f"{pc * 100:.1f}%" if pc is not None else "—"
                gs.append(
                    f'<div class="gs-row">'
                    f'<span class="gs-flag">{flag(team)}</span>'
                    f'<div class="gs-name-wrap">'
                    f'<span class="gs-name">{esc(team)}</span>'
                    f'<div class="gs-bar-track">'
                    f'<div class="gs-bar-fill" style="width:{bar_w}%"></div>'
                    f'</div></div>'
                    f'<span class="gs-pct">{pct_str}</span>'
                    f'</div>'
                )

        gs.append('</div>')

    # ---- assemble ----
    parts = [
        "<!DOCTYPE html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="UTF-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">',
        "<title>2026 FIFA World Cup &mdash; Watchability Dashboard</title>",
        f"<style>{CSS}</style>",
        "</head><body>",
        "<header>",
        '<p class="header-eyebrow">2026 FIFA World Cup &bull; Group Stage</p>',
        "<h1>&#9917; 2026 FIFA World Cup <span>&mdash; Watchability</span></h1>",
        '<p class="subtitle">All 72 group stage matches ranked by competitiveness and championship stakes &mdash; powered by the SPI model.</p>',
        "</header>",
        '<div class="summary-strip">',
        '<div class="summary-item"><span class="s-label">Game of the Day</span>',
        f'<span class="s-value small">{gotd_matchup}</span>',
        f'<span class="s-sub">{esc(gotd_time)}</span></div>',
        '<div class="summary-item"><span class="s-label">Last Updated</span>',
        f'<span class="s-value small">{esc(updated_str)}</span></div>',
        "</div>",
        '<div class="legend-bar">',
        '<span><span class="dot green"></span>High watchability (&ge;65)</span>',
        '<span><span class="dot gray"></span>Watchable (50&ndash;64)</span>',
        '<span><span class="dot red"></span>Lower watchability (&lt;50)</span>',
        '<span style="color:#2f81f7">&#9632;</span><span>Home win</span>',
        '<span style="color:#6e7681">&#9632;</span><span>Draw</span>',
        '<span style="color:var(--orange)">&#9632;</span><span>Away win</span>',
        "</div>",
        '<div class="tab-bar">',
        '<button class="tab-btn tab-active" onclick="showTab(\'schedule\')">Daily Schedule</button>',
        '<button class="tab-btn" onclick="showTab(\'tournament\')">Tournament</button>',
        '</div>',
        '<div id="tab-schedule" class="tab-panel tab-visible">',
        '<div class="schedule-wrap">',
        '<div class="section-label">Group Stage Schedule &mdash; 72 Games</div>',
        '<div class="sort-toggle">',
        '<button id="btn-date" class="sort-btn sort-active" onclick="setSort(\'date\')">By date</button>',
        '<button id="btn-watch" class="sort-btn" onclick="setSort(\'watch\')">By watchability</button>',
        '</div>',
        '<div id="schedule-content">',
        "".join(sched),
        "</div>",
        "</div>",
        "</div>",
        '<div id="tab-tournament" class="tab-panel">',
        build_tournament_tab(),
        '<div class="tourn-wrap">',
        '<div class="section-label" style="margin-bottom:12px">Group Stage Standings &amp; Projections</div>',
        '<p class="mc-sim-note">Simulated using 10,000 runs per group. Completed results are fixed; remaining games use SPI model probabilities.</p>',
        '<div class="gs-panel">',
        "".join(gs),
        "</div>",
        "</div>",
        "</div>",
        "<footer><p>Odds from "
        '<a href="https://the-odds-api.com" target="_blank" rel="noopener">The Odds API</a>'
        " &bull; Vig removed &bull; Win probabilities averaged across US bookmakers</p></footer>",
        "<script>",
        "window.showTab=function(id){",
        "  document.querySelectorAll('.tab-panel').forEach(function(p){p.classList.remove('tab-visible');});",
        "  document.querySelectorAll('.tab-btn').forEach(function(b){b.classList.remove('tab-active');});",
        "  var p=document.getElementById('tab-'+id);if(p)p.classList.add('tab-visible');",
        "  var label=id==='schedule'?'Daily Schedule':'Tournament';",
        "  document.querySelectorAll('.tab-btn').forEach(function(b){if(b.textContent.trim()===label)b.classList.add('tab-active');});",
        "};",
        "(function(){",
        "var s=document.getElementById('schedule-content');",
        "function initToggles(){",
        "  s.querySelectorAll('.date-group').forEach(function(grp){",
        "    if(grp.querySelector('.completed-toggle'))return;",
        "    var cards=grp.querySelectorAll('.game-card[data-completed]');",
        "    if(!cards.length)return;",
        "    cards.forEach(function(c){c.hidden=true;});",
        "    var btn=document.createElement('button');",
        "    btn.className='completed-toggle';",
        "    btn.textContent='Show '+cards.length+' completed';",
        "    grp.querySelector('.date-header').appendChild(btn);",
        "  });",
        "}",
        "initToggles();",
        "s.addEventListener('click',function(e){",
        "  var t=e.target;",
        "  if(!t.classList||!t.classList.contains('completed-toggle'))return;",
        "  var grp=t.parentNode;while(grp&&!grp.classList.contains('date-group'))grp=grp.parentNode;",
        "  if(!grp)return;",
        "  var cards=grp.querySelectorAll('.game-card[data-completed]');",
        "  var show=cards.length&&cards[0].hidden;",
        "  cards.forEach(function(c){c.hidden=!show;});",
        "  t.textContent=show?'Hide completed':'Show '+cards.length+' completed';",
        "});",
        "var snap=s.innerHTML;",
        "var mode='date';",
        "window.setSort=function(m){",
        "if(m===mode)return;",
        "mode=m;",
        "document.getElementById('btn-date').classList.toggle('sort-active',m==='date');",
        "document.getElementById('btn-watch').classList.toggle('sort-active',m==='watch');",
        "if(m==='date'){s.innerHTML=snap;}",
        "else{",
        "var cards=Array.prototype.slice.call(s.querySelectorAll('.game-card:not([data-completed])'));",
        "cards.sort(function(a,b){return(parseInt(b.dataset.w)||0)-(parseInt(a.dataset.w)||0);});",
        "cards.forEach(function(c){var d=c.querySelector('.date-chip');if(d)d.style.display='inline-flex';});",
        "var g=document.createElement('div');g.className='games-grid';",
        "cards.forEach(function(c){g.appendChild(c);});",
        "s.innerHTML='';s.appendChild(g);",
        "}};})();",
        "document.querySelectorAll('.game-card').forEach(function(card){",
        "  card.addEventListener('click',function(){card.classList.toggle('expanded');});",
        "});",
        "</script>",
        "</body></html>",
    ]
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    odds, fetched_at = get_odds(DB_PATH)
    results = get_results(DB_PATH)
    completed_results = get_completed_results(DB_PATH)
    schedule = get_schedule(DB_PATH)
    if not odds:
        print("WARNING: No match odds in DB — generating skeleton dashboard.")

    t0 = time.time()
    groups_data, missing_odds, current_actual_points = build_groups_data(
        schedule, GROUPS, odds, completed_results
    )
    sim_results = run_all_simulations(groups_data, n=10000)
    elapsed = time.time() - t0
    print(f"Monte Carlo simulation complete ({elapsed:.1f}s, {len(missing_odds)} matches missing odds)")
    if missing_odds:
        for m in missing_odds[:5]:
            print(f"  Using 33/33/33 for: {m}")
        if len(missing_odds) > 5:
            print(f"  ... and {len(missing_odds) - 5} more")

    html = build_html(odds, fetched_at, schedule, results, sim_results, current_actual_points)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write(html)

    size_kb = os.path.getsize(OUT_PATH) / 1024
    print(f"Wrote {OUT_PATH} ({size_kb:.1f} KB, {len(odds)} matches with odds)")


if __name__ == "__main__":
    main()
