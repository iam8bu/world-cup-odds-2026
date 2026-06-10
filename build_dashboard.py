#!/usr/bin/env python3
"""Read the latest h2h match odds from odds.db and write index.html."""

import sqlite3
import os
from html import escape as esc

DB_PATH = "odds.db"
OUT_PATH = "index.html"

# ---------------------------------------------------------------------------
# Schedule — 72 group-stage games
# ---------------------------------------------------------------------------
SCHEDULE = [
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
:root {
  --bg:        #080c18;
  --surface:   #111827;
  --surface2:  #1a2236;
  --border:    #1f2d47;
  --text:      #e2e8f0;
  --muted:     #7a8ba0;
  --blue:      #3b82f6;
  --draw:      #6b7280;
  --orange:    #f97316;
  --green:     #10b981;
  --green-dim: rgba(16,185,129,.11);
  --green-bdr: rgba(16,185,129,.35);
  --amber:     #f59e0b;
  --amber-dim: rgba(245,158,11,.10);
  --amber-bdr: rgba(245,158,11,.32);
  --red:       #ef4444;
  --red-dim:   rgba(239,68,68,.08);
  --red-bdr:   rgba(239,68,68,.25);
  --gray-dim:  rgba(75,85,99,.10);
  --gray-bdr:  rgba(75,85,99,.28);
}
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
body {
  background: var(--bg);
  color: var(--text);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
               "Helvetica Neue", Arial, sans-serif;
  font-size: 14px;
  line-height: 1.5;
}

/* ── Header ── */
header {
  background: linear-gradient(160deg, #0c1528 0%, #162040 100%);
  border-bottom: 1px solid var(--border);
  padding: 26px 32px 20px;
  text-align: center;
}
header h1 { font-size: clamp(1.3rem, 3vw, 1.9rem); font-weight: 800; letter-spacing: -.4px; }
header h1 span { color: var(--blue); }
.subtitle { color: var(--muted); font-size: 12px; margin-top: 4px; }

/* ── Summary strip ── */
.summary-strip {
  background: var(--surface);
  border-bottom: 1px solid var(--border);
  display: flex;
  justify-content: center;
  flex-wrap: wrap;
}
.summary-item {
  padding: 13px 26px;
  text-align: center;
  border-right: 1px solid var(--border);
  min-width: 150px;
}
.summary-item:last-child { border-right: none; }
.s-label {
  display: block;
  color: var(--muted);
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 1.2px;
  margin-bottom: 3px;
}
.s-value { display: block; font-size: 1.25rem; font-weight: 700; }
.s-value.small { font-size: .95rem; }

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
.dot.amber { background: var(--amber); }
.dot.red   { background: var(--red);   }

/* ── Main layout ── */
.main-layout {
  display: flex;
  max-width: 1440px;
  margin: 0 auto;
  padding: 22px 14px 48px;
  gap: 18px;
  align-items: flex-start;
}
.schedule-col { flex: 1; min-width: 0; }
.sidebar-col  { width: 272px; flex-shrink: 0; position: sticky; top: 14px; }
.section-label {
  font-size: 10px; font-weight: 700;
  text-transform: uppercase; letter-spacing: 1.4px;
  color: var(--muted); margin-bottom: 13px;
}

/* ── Date groups ── */
.date-group   { margin-bottom: 26px; }
.date-header  {
  display: flex; align-items: center; gap: 8px;
  font-size: 14px; font-weight: 600; color: var(--blue);
  padding-bottom: 7px; border-bottom: 1px solid var(--border); margin-bottom: 10px;
}
.game-count { font-size: 11px; color: var(--muted); font-weight: 400; }
.games-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(268px, 1fr)); gap: 10px; }

/* ── Game cards ── */
.game-card {
  background: var(--surface);
  border-radius: 8px;
  padding: 12px 13px 10px;
  border: 1px solid var(--border);
  border-left: 3px solid #374151;
  transition: transform .1s, box-shadow .1s;
}
.game-card:hover { transform: translateY(-2px); box-shadow: 0 4px 18px rgba(0,0,0,.4); }
.game-card.green { border-left-color: var(--green); background: var(--green-dim); border-color: var(--green-bdr); }
.game-card.amber { border-left-color: var(--amber); background: var(--amber-dim); border-color: var(--amber-bdr); }
.game-card.red   { border-left-color: var(--red);   background: var(--red-dim);   border-color: var(--red-bdr);   }
.game-card.gray  { border-left-color: #374151;       background: var(--gray-dim);  border-color: var(--gray-bdr);  }

.card-top {
  display: flex; justify-content: space-between; align-items: center; margin-bottom: 9px;
}
.grp-badge {
  background: var(--blue); color: #fff;
  font-size: 9px; font-weight: 700;
  padding: 2px 6px; border-radius: 3px; letter-spacing: .5px;
}
.card-time { color: var(--muted); font-size: 11px; }

.matchup { margin-bottom: 9px; }
.team-row { display: flex; align-items: center; gap: 7px; padding: 3px 0; }
.team-flag { font-size: 16px; line-height: 1; flex-shrink: 0; }
.team-name { flex: 1; font-weight: 500; font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.team-prob { font-variant-numeric: tabular-nums; font-size: 12px; font-weight: 700; white-space: nowrap; }
.team-prob.home-col { color: var(--blue); }
.team-prob.away-col { color: var(--orange); }
.team-prob.na       { color: var(--muted); font-weight: 400; }
.vs-line { font-size: 10px; color: var(--muted); padding: 1px 0 1px 23px; }

/* Segmented probability bar */
.seg-bar-wrap { display: flex; height: 5px; border-radius: 3px; overflow: hidden; margin: 8px 0 7px; background: var(--border); }
.seg-home { background: var(--blue); }
.seg-draw { background: var(--draw); }
.seg-away { background: var(--orange); }

.card-bottom { display: flex; justify-content: space-between; align-items: flex-start; gap: 8px; }
.draw-lbl { font-size: 11px; color: var(--muted); white-space: nowrap; font-variant-numeric: tabular-nums; }
.venue-lbl { font-size: 10px; color: var(--muted); text-align: right; line-height: 1.35; }

/* ── Group standings sidebar ── */
.gs-panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  overflow: hidden;
  max-height: calc(100vh - 110px);
  overflow-y: auto;
  scrollbar-width: thin;
  scrollbar-color: var(--border) transparent;
}
.gs-group { border-bottom: 1px solid var(--border); padding: 10px 11px; }
.gs-group:last-child { border-bottom: none; }
.gs-title {
  font-size: 9px; font-weight: 800;
  text-transform: uppercase; letter-spacing: 1.5px;
  color: var(--blue); margin-bottom: 7px;
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

/* ── Footer ── */
footer {
  text-align: center; padding: 18px;
  color: var(--muted); font-size: 11px;
  border-top: 1px solid var(--border);
}
footer a { color: var(--blue); text-decoration: none; }

/* ── Responsive ── */
@media (max-width: 960px) {
  .main-layout { flex-direction: column; }
  .sidebar-col  { width: 100%; position: static; }
  .gs-panel     { max-height: 380px; }
}
@media (max-width: 560px) {
  .summary-strip { flex-direction: column; }
  .summary-item  { border-right: none; border-bottom: 1px solid var(--border); }
  .games-grid    { grid-template-columns: 1fr; }
}
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


def fmt_pct(p, d: int = 1) -> str:
    return "—" if p is None else f"{p * 100:.{d}f}%"


def color_cls(home_prob, away_prob) -> str:
    """Color by match competitiveness (favorite's win probability)."""
    if home_prob is None:
        return "gray"
    fav = max(home_prob, away_prob)
    if fav < 0.55:
        return "green"   # tight match
    if fav < 0.72:
        return "amber"   # clear favorite
    return "red"         # heavy mismatch


def flag(team: str) -> str:
    return FLAGS.get(team, "🏳️")


def team_avg_win(team: str, odds: dict):
    """Average win probability for a team across all their group games with odds."""
    probs = []
    for g in SCHEDULE:
        if g["home"] == team:
            o = odds.get((g["home"], g["away"]))
            if o:
                probs.append(o["home_prob"])
        elif g["away"] == team:
            o = odds.get((g["home"], g["away"]))
            if o:
                probs.append(o["away_prob"])
    return sum(probs) / len(probs) if probs else None


# ---------------------------------------------------------------------------
# HTML builder
# ---------------------------------------------------------------------------

def build_html(odds: dict, fetched_at) -> str:
    # ---- schedule ----
    date_games: dict = {}
    for g in SCHEDULE:
        date_games.setdefault(g["date"], []).append(g)

    games_with_odds = sum(1 for g in SCHEDULE if (g["home"], g["away"]) in odds)

    if fetched_at:
        try:
            from datetime import datetime, timezone
            dt = datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
            updated_str = dt.strftime("%b %d, %Y %H:%M UTC")
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
            o = odds.get((g["home"], g["away"]))
            hp = o["home_prob"] if o else None
            dp = o["draw_prob"] if o else None
            ap = o["away_prob"] if o else None
            cls = color_cls(hp, ap)

            home_w = int(hp * 100) if hp is not None else 0
            draw_w = int(dp * 100) if dp is not None else 0
            away_w = 100 - home_w - draw_w if hp is not None else 0

            hp_cls = "home-col" if hp is not None else "na"
            ap_cls = "away-col" if ap is not None else "na"

            draw_text = f"Draw {fmt_pct(dp)}" if dp is not None else "No odds"

            sched.append(
                f'<div class="game-card {cls}">'
                f'<div class="card-top">'
                f'<span class="grp-badge">GRP {esc(g["grp"])}</span>'
                f'<span class="card-time">{esc(g["time"])}</span>'
                f'</div>'
                f'<div class="matchup">'
                f'<div class="team-row">'
                f'<span class="team-flag">{flag(g["home"])}</span>'
                f'<span class="team-name">{esc(g["home"])}</span>'
                f'<span class="team-prob {hp_cls}">{fmt_pct(hp)}</span>'
                f'</div>'
                f'<div class="vs-line">vs</div>'
                f'<div class="team-row">'
                f'<span class="team-flag">{flag(g["away"])}</span>'
                f'<span class="team-name">{esc(g["away"])}</span>'
                f'<span class="team-prob {ap_cls}">{fmt_pct(ap)}</span>'
                f'</div>'
                f'</div>'
                f'<div class="seg-bar-wrap">'
                f'<div class="seg-home" style="width:{home_w}%"></div>'
                f'<div class="seg-draw" style="width:{draw_w}%"></div>'
                f'<div class="seg-away" style="width:{away_w}%"></div>'
                f'</div>'
                f'<div class="card-bottom">'
                f'<span class="draw-lbl">{esc(draw_text)}</span>'
                f'<span class="venue-lbl">{esc(g["venue"])}</span>'
                f'</div>'
                f'</div>'
            )
        sched.append('</div></div>')

    # ---- group standings HTML ----
    gs = []
    for grp, teams in GROUPS.items():
        ranked = sorted(
            [(t, team_avg_win(t, odds)) for t in teams],
            key=lambda x: -(x[1] if x[1] is not None else -1),
        )
        best = max((p for _, p in ranked if p is not None), default=None)

        gs.append(f'<div class="gs-group"><div class="gs-title">Group {esc(grp)}</div>')
        for team, avg in ranked:
            bar_w = int((avg / best) * 100) if avg is not None and best else 0
            gs.append(
                f'<div class="gs-row">'
                f'<span class="gs-flag">{flag(team)}</span>'
                f'<div class="gs-name-wrap">'
                f'<span class="gs-name">{esc(team)}</span>'
                f'<div class="gs-bar-track">'
                f'<div class="gs-bar-fill" style="width:{bar_w}%"></div>'
                f'</div></div>'
                f'<span class="gs-pct">{fmt_pct(avg) if avg is not None else "—"}</span>'
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
        "<title>2026 FIFA World Cup &mdash; Match Odds Dashboard</title>",
        f"<style>{CSS}</style>",
        "</head><body>",
        "<header>",
        "<h1>&#9917; 2026 FIFA World Cup <span>&mdash; Match Odds</span></h1>",
        '<p class="subtitle">Group Stage Dashboard &bull; h2h win probabilities averaged across US bookmakers &bull; Updated daily</p>',
        "</header>",
        '<div class="summary-strip">',
        '<div class="summary-item"><span class="s-label">Matches Covered</span>',
        f'<span class="s-value">{games_with_odds}&thinsp;/&thinsp;72</span></div>',
        '<div class="summary-item"><span class="s-label">Color Key</span>',
        '<span class="s-value small">Competitiveness</span></div>',
        '<div class="summary-item"><span class="s-label">Last Updated</span>',
        f'<span class="s-value small">{esc(updated_str)}</span></div>',
        "</div>",
        '<div class="legend-bar">',
        '<span><span class="dot green"></span>Tight (&lt;55% favorite)</span>',
        '<span><span class="dot amber"></span>Clear favorite (55&ndash;72%)</span>',
        '<span><span class="dot red"></span>Heavy mismatch (&gt;72%)</span>',
        '<span style="color:#3b82f6">&#9632;</span><span>Home win</span>',
        '<span style="color:#6b7280">&#9632;</span><span>Draw</span>',
        '<span style="color:#f97316">&#9632;</span><span>Away win</span>',
        "</div>",
        '<div class="main-layout">',
        '<div class="schedule-col">',
        '<div class="section-label">Group Stage Schedule &mdash; 72 Games</div>',
        "".join(sched),
        "</div>",
        '<div class="sidebar-col">',
        '<div class="section-label">Group Standings &mdash; Avg Win %</div>',
        '<div class="gs-panel">',
        "".join(gs),
        "</div></div>",
        "</div>",
        "<footer><p>Odds from "
        '<a href="https://the-odds-api.com" target="_blank" rel="noopener">The Odds API</a>'
        " &bull; Vig removed &bull; Probabilities averaged across available US bookmakers</p></footer>",
        "</body></html>",
    ]
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    odds, fetched_at = get_odds(DB_PATH)
    if not odds:
        print("WARNING: No match odds in DB — generating skeleton dashboard.")

    html = build_html(odds, fetched_at)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write(html)

    size_kb = os.path.getsize(OUT_PATH) / 1024
    print(f"Wrote {OUT_PATH} ({size_kb:.1f} KB, {len(odds)} matches with odds)")


if __name__ == "__main__":
    main()
