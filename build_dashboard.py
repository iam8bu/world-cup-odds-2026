#!/usr/bin/env python3
"""Read the latest h2h match odds from odds.db and write index.html."""

import math
import random
import sqlite3
import os
import time
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
.s-sub { display: block; font-size: 10px; color: var(--muted); margin-top: 3px; }

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
.sidebar-col  { width: 310px; flex-shrink: 0; position: sticky; top: 14px; }
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
  display: flex; justify-content: space-between; align-items: center; gap: 6px; margin-bottom: 9px;
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
.team-name-wrap { flex: 1; min-width: 0; }
.team-name { font-weight: 500; font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; display: block; }
.title-prob { display: block; font-size: 9px; color: var(--muted); margin-top: 1px; }
.vs-line { font-size: 10px; color: var(--muted); padding: 1px 0 1px 23px; }
.color-dot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }
.home-dot  { background: var(--blue); }
.away-dot  { background: var(--orange); }

/* Segmented probability bar */
.seg-bar-wrap { display: flex; height: 5px; border-radius: 3px; overflow: hidden; margin: 8px 0 7px; background: var(--border); }
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

/* ── Completed result cards ── */
.final-badge {
  font-size: 9px; font-weight: 700; padding: 2px 6px; border-radius: 3px;
  letter-spacing: .5px; background: var(--surface2); color: var(--muted);
  border: 1px solid var(--border);
}
.upset-badge {
  font-size: 9px; font-weight: 800; padding: 2px 6px; border-radius: 3px;
  letter-spacing: .5px; background: var(--amber-dim); color: var(--amber);
  border: 1px solid var(--amber-bdr);
}
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

/* ── Watchability ── */
.watch-row { display: flex; align-items: center; gap: 6px; margin: 6px 0 4px; }
.watch-label { font-size: 9px; text-transform: uppercase; letter-spacing: 1px; color: var(--muted); flex-shrink: 0; }
.watch-score { font-size: 15px; font-weight: 800; font-variant-numeric: tabular-nums; }
.game-card.green .watch-score { color: var(--green); }
.game-card.amber .watch-score { color: var(--amber); }
.game-card.red   .watch-score { color: var(--red); }
.game-card.gray  .watch-score { color: var(--muted); }
.watch-pending { font-size: 9px; color: var(--amber); margin-left: 2px; }
.faded { opacity: .42; }

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
.mc-th-champ { color: #fbbf24;      width: 44px; }
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
.mc-td-champ { color: #fbbf24; }

/* ── Date chip (visible in watchability sort only) ── */
.date-chip {
  display: none; font-size: 9px; color: var(--muted);
  background: var(--surface2); border: 1px solid var(--border);
  border-radius: 3px; padding: 1px 5px; white-space: nowrap;
}

/* ── Sort toggle ── */
.sort-toggle { display: flex; gap: 6px; margin-bottom: 13px; }
.sort-btn {
  padding: 5px 12px; border-radius: 5px;
  border: 1px solid var(--border); background: var(--surface);
  color: var(--muted); font-size: 11px; font-weight: 600;
  cursor: pointer; letter-spacing: .3px;
  transition: background .12s, color .12s;
}
.sort-btn:hover { background: var(--surface2); color: var(--text); }
.sort-active { background: var(--blue) !important; color: #fff !important; border-color: var(--blue) !important; }
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
    if w >= 60:
        return "green"
    if w >= 30:
        return "amber"
    return "red"


def flag(team: str) -> str:
    return FLAGS.get(team, "🏳️")


def get_title_probs(db_path: str) -> dict:
    """Return {team: implied_prob} from the most recent odds_snapshots row per team."""
    if not os.path.exists(db_path):
        return {}
    conn = sqlite3.connect(db_path)
    try:
        tbl = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='odds_snapshots'"
        ).fetchone()
        if not tbl:
            return {}
        rows = conn.execute("""
            SELECT team, implied_prob FROM odds_snapshots o1
            WHERE fetched_at = (
                SELECT MAX(fetched_at) FROM odds_snapshots o2
                WHERE o2.team = o1.team
            )
        """).fetchall()
        return {team: prob for team, prob in rows}
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
        matches = []
        for g in schedule:
            if g["grp"] != grp:
                continue
            key = (g["home"], g["away"])
            if key in completed_results:
                continue
            o = odds.get(key)
            if o:
                matches.append({
                    "home": g["home"],
                    "away": g["away"],
                    "home_win_prob": o["home_prob"],
                    "draw_prob": o["draw_prob"],
                    "away_win_prob": o["away_prob"],
                })
            else:
                matches.append({
                    "home": g["home"],
                    "away": g["away"],
                    "home_win_prob": 1 / 3,
                    "draw_prob": 1 / 3,
                    "away_win_prob": 1 / 3,
                })
                missing_odds_matches.append(f"{g['home']} vs {g['away']} (Group {grp})")
        groups_data[grp] = {"teams": teams, "matches": matches, "fixed_points": fixed_points}

    return groups_data, missing_odds_matches, current_actual_points


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
            gd = groups_data[grp]
            teams = gd["teams"]
            points = {t: gd["fixed_points"].get(t, 0) for t in teams}

            for match in gd["matches"]:
                result = random.choices(
                    ["home", "draw", "away"],
                    weights=[match["home_win_prob"], match["draw_prob"], match["away_win_prob"]],
                )[0]
                if result == "home":
                    points[match["home"]] += 3
                elif result == "draw":
                    points[match["home"]] += 1
                    points[match["away"]] += 1
                else:
                    points[match["away"]] += 3

            standings = sorted(
                teams, key=lambda t: (points[t], random.random()), reverse=True
            )
            for pos, team in enumerate(standings, 1):
                finish_counts[grp][team][pos] += 1

            third_team = standings[2]
            third_place_info.append((points[third_team], random.random(), grp, third_team))

        third_place_info.sort(key=lambda x: (x[0], x[1]), reverse=True)
        for _, _, grp, team in third_place_info[:8]:
            third_adv_counts[grp][team] += 1

    results = {}
    for grp in group_names:
        results[grp] = {}
        for team in groups_data[grp]["teams"]:
            probs = {pos: finish_counts[grp][team][pos] / n for pos in [1, 2, 3, 4]}
            probs["3adv"] = third_adv_counts[grp][team] / n
            results[grp][team] = probs
    return results


def team_expected_wins(team: str, odds: dict):
    """Sum of win probabilities across all group games with available odds (0–3 scale)."""
    total = 0.0
    found = 0
    for g in SCHEDULE:
        if g["home"] == team:
            o = odds.get((g["home"], g["away"]))
            if o:
                total += o["home_prob"]
                found += 1
        elif g["away"] == team:
            o = odds.get((g["home"], g["away"]))
            if o:
                total += o["away_prob"]
                found += 1
    return total if found > 0 else None


# ---------------------------------------------------------------------------
# HTML builder
# ---------------------------------------------------------------------------

def build_html(odds: dict, fetched_at, results: dict = None, title_probs: dict = None,
               sim_results: dict = None, current_actual_points: dict = None) -> str:
    if results is None:
        results = {}
    if title_probs is None:
        title_probs = {}

    # ---- pre-compute watchability for all 72 games ----
    # competitiveness: 1.0 = perfect 33/33/33 split, 0.0 = one outcome at 100%
    # stakes: Spain+France combined title prob as the ceiling (always 0–1)
    tp_spain  = title_probs.get("Spain",  0.0) or 0.0
    tp_france = title_probs.get("France", 0.0) or 0.0
    max_combined = tp_spain + tp_france

    ceiling = max_combined if max_combined > 0 else 0.349
    # ref is the zero-anchor: derived so that combined=2/48 (one avg team each)
    # maps to exactly 0.5. formula: log(combined/ref) / log(ceiling/ref)
    # solving for ref given score(2/48)=0.5 → ref = (2/48)² / ceiling
    baseline = 2 / 48
    ref = (baseline ** 2) / ceiling

    watchability: dict = {}
    for g in SCHEDULE:
        key = (g["home"], g["away"])
        o = odds.get(key)
        if not o:
            watchability[key] = None
            continue
        max_outcome = max(o["home_prob"], o["draw_prob"], o["away_prob"])
        competitiveness = 1.0 - ((max_outcome - 1/3) / (2/3))

        tp_h = title_probs.get(g["home"], 0.0) or 0.0
        tp_a = title_probs.get(g["away"], 0.0) or 0.0
        combined = tp_h + tp_a
        if combined <= ref:
            stakes = 0.0
        else:
            stakes = max(0.0, min(math.log(combined / ref) / math.log(ceiling / ref), 1.0))

        watchability[key] = round(((competitiveness + stakes) / 2) * 100)

    # ---- schedule ----
    date_games: dict = {}
    for g in SCHEDULE:
        date_games.setdefault(g["date"], []).append(g)

    games_with_odds = sum(1 for g in SCHEDULE if (g["home"], g["away"]) in odds)

    # ---- game of the day (most competitive match today in ET) ----
    gotd_matchup = "No games today"
    gotd_time = ""
    try:
        from datetime import datetime
        from zoneinfo import ZoneInfo
        today_et = datetime.now(ZoneInfo("America/New_York"))
        today_fmt = today_et.strftime("%a, %b ") + str(today_et.day)
        today_with_odds = [
            (g, odds[(g["home"], g["away"])])
            for g in SCHEDULE
            if g["date"] == today_fmt and (g["home"], g["away"]) in odds
        ]
        if today_with_odds:
            best_g, best_o = min(
                today_with_odds,
                key=lambda x: max(x[1]["home_prob"], x[1]["away_prob"]),
            )
            gotd_matchup = f'{esc(best_g["home"])} vs {esc(best_g["away"])}'
            gotd_time = best_g["time"]
        elif any(g["date"] == today_fmt for g in SCHEDULE):
            gotd_matchup = "Odds pending"
    except Exception:
        pass

    if fetched_at:
        try:
            from datetime import datetime, timezone
            from zoneinfo import ZoneInfo
            dt = datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
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
            w = watchability.get(game_key)
            data_w = str(w) if w is not None else ""
            card_cls = watch_cls(w)
            tp_h = title_probs.get(g["home"])
            tp_a = title_probs.get(g["away"])
            watch_score_str = str(w) if w is not None else "—"
            watch_pending_html = (
                '<span class="watch-pending">⚠ title odds pending</span>'
                if o and (tp_h is None or tp_a is None) else ""
            )

            r = results.get(game_key)

            if r:
                # ── completed game ──────────────────────────────────────────
                hs = r["home_score"]
                aws = r["away_score"]

                if hs > aws:
                    home_cls, away_cls = "winner", "loser"
                    winning_prob = hp
                    losing_prob  = ap
                elif aws > hs:
                    home_cls, away_cls = "loser", "winner"
                    winning_prob = ap
                    losing_prob  = hp
                else:
                    home_cls = away_cls = ""
                    winning_prob = dp
                    losing_prob  = max(hp, ap) if hp is not None else None

                is_upset = (
                    winning_prob is not None and
                    losing_prob  is not None and
                    winning_prob < losing_prob
                )
                upset_badge = '<span class="upset-badge">UPSET</span>' if is_upset else ""

                if hp is not None:
                    home_w = int(hp * 100)
                    draw_w = int(dp * 100)
                    away_w = 100 - home_w - draw_w
                    hist_html = (
                        f'<div class="odds-hist">'
                        f'<div class="odds-hist-label">Pre-game odds</div>'
                        f'<div class="seg-bar-wrap">'
                        f'<div class="seg-home" style="width:{home_w}%"></div>'
                        f'<div class="seg-draw" style="width:{draw_w}%"></div>'
                        f'<div class="seg-away" style="width:{away_w}%"></div>'
                        f'</div>'
                        f'<div class="prob-labels">'
                        f'<span class="prob-label-home">Home&nbsp;{fmt_pct(hp)}</span>'
                        f'<span class="prob-label-draw">Draw&nbsp;{fmt_pct(dp)}</span>'
                        f'<span class="prob-label-away">Away&nbsp;{fmt_pct(ap)}</span>'
                        f'</div></div>'
                    )
                else:
                    hist_html = ""

                home_tp_html = (
                    f'<span class="title-prob faded">{tp_h*100:.1f}% title odds</span>'
                    if tp_h is not None else ""
                )
                away_tp_html = (
                    f'<span class="title-prob faded">{tp_a*100:.1f}% title odds</span>'
                    if tp_a is not None else ""
                )

                sched.append(
                    f'<div class="game-card {card_cls}" data-w="{data_w}" data-date="{esc(g["date"])}">'
                    f'<div class="card-top">'
                    f'<span class="grp-badge">GRP {esc(g["grp"])}</span>'
                    + upset_badge +
                    f'<span class="date-chip">{esc(g["date"])}</span>'
                    f'<span class="final-badge">FINAL</span>'
                    f'</div>'
                    f'<div class="watch-row faded">'
                    f'<span class="watch-label">Watchability</span>'
                    f'<span class="watch-score">{watch_score_str}</span>'
                    f'</div>'
                    f'<div class="matchup">'
                    f'<div class="team-row {home_cls}">'
                    f'<span class="color-dot home-dot"></span>'
                    f'<span class="team-flag">{flag(g["home"])}</span>'
                    f'<div class="team-name-wrap">'
                    f'<span class="team-name">{esc(g["home"])}</span>'
                    + home_tp_html +
                    f'</div>'
                    f'<span class="team-score">{hs}</span>'
                    f'</div>'
                    f'<div class="vs-line">vs</div>'
                    f'<div class="team-row {away_cls}">'
                    f'<span class="color-dot away-dot"></span>'
                    f'<span class="team-flag">{flag(g["away"])}</span>'
                    f'<div class="team-name-wrap">'
                    f'<span class="team-name">{esc(g["away"])}</span>'
                    + away_tp_html +
                    f'</div>'
                    f'<span class="team-score">{aws}</span>'
                    f'</div>'
                    f'</div>'
                    + hist_html +
                    f'<div class="venue-row">{esc(g["venue"])}</div>'
                    f'</div>'
                )
            else:
                # ── upcoming / no result yet ─────────────────────────────────
                if hp is not None:
                    home_w = int(hp * 100)
                    draw_w = int(dp * 100)
                    away_w = 100 - home_w - draw_w
                    prob_html = (
                        f'<div class="seg-bar-wrap">'
                        f'<div class="seg-home" style="width:{home_w}%"></div>'
                        f'<div class="seg-draw" style="width:{draw_w}%"></div>'
                        f'<div class="seg-away" style="width:{away_w}%"></div>'
                        f'</div>'
                        f'<div class="prob-labels">'
                        f'<span class="prob-label-home">Home&nbsp;{fmt_pct(hp)}</span>'
                        f'<span class="prob-label-draw">Draw&nbsp;{fmt_pct(dp)}</span>'
                        f'<span class="prob-label-away">Away&nbsp;{fmt_pct(ap)}</span>'
                        f'</div>'
                    )
                else:
                    prob_html = '<div class="no-odds-msg">Odds not yet available</div>'

                home_tp_html = (
                    f'<span class="title-prob">{tp_h*100:.1f}% title odds</span>'
                    if tp_h is not None else ""
                )
                away_tp_html = (
                    f'<span class="title-prob">{tp_a*100:.1f}% title odds</span>'
                    if tp_a is not None else ""
                )

                sched.append(
                    f'<div class="game-card {card_cls}" data-w="{data_w}" data-date="{esc(g["date"])}">'
                    f'<div class="card-top">'
                    f'<span class="grp-badge">GRP {esc(g["grp"])}</span>'
                    f'<span class="date-chip">{esc(g["date"])}</span>'
                    f'<span class="card-time">{esc(g["time"])}</span>'
                    f'</div>'
                    f'<div class="watch-row">'
                    f'<span class="watch-label">Watchability</span>'
                    f'<span class="watch-score">{watch_score_str}</span>'
                    + watch_pending_html +
                    f'</div>'
                    f'<div class="matchup">'
                    f'<div class="team-row">'
                    f'<span class="color-dot home-dot"></span>'
                    f'<span class="team-flag">{flag(g["home"])}</span>'
                    f'<div class="team-name-wrap">'
                    f'<span class="team-name">{esc(g["home"])}</span>'
                    + home_tp_html +
                    f'</div>'
                    f'</div>'
                    f'<div class="vs-line">vs</div>'
                    f'<div class="team-row">'
                    f'<span class="color-dot away-dot"></span>'
                    f'<span class="team-flag">{flag(g["away"])}</span>'
                    f'<div class="team-name-wrap">'
                    f'<span class="team-name">{esc(g["away"])}</span>'
                    + away_tp_html +
                    f'</div>'
                    f'</div>'
                    f'</div>'
                    + prob_html +
                    f'<div class="venue-row">{esc(g["venue"])}</div>'
                    f'</div>'
                )
        sched.append('</div></div>')

    # ---- group standings HTML (Monte Carlo) ----
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
                '<th class="mc-th-champ">Champ</th>'
                '</tr></thead><tbody>'
            )
            for team in sorted_teams:
                probs = grp_sim[team]
                p1, p2, p3, p4 = probs[1], probs[2], probs[3], probs[4]
                tp = title_probs.get(team)
                champ_str = f"{tp * 100:.1f}%" if tp is not None else "&mdash;"
                gs.append(
                    f'<tr>'
                    f'<td class="mc-td-team">{flag(team)}&nbsp;{esc(team)}</td>'
                    f'<td class="mc-td-1st">{p1 * 100:.0f}%</td>'
                    f'<td class="mc-td-2nd">{p2 * 100:.0f}%</td>'
                    f'<td>{p3 * 100:.0f}%</td>'
                    f'<td>{p4 * 100:.0f}%</td>'
                    f'<td class="mc-td-champ">{champ_str}</td>'
                    f'</tr>'
                )
            gs.append('</tbody></table>')
        else:
            ranked = sorted(
                [(t, team_expected_wins(t, odds)) for t in teams],
                key=lambda x: -(x[1] if x[1] is not None else -1),
            )
            best = max((p for _, p in ranked if p is not None), default=None)
            for team, xw in ranked:
                bar_w = int((xw / best) * 100) if xw is not None and best else 0
                gs.append(
                    f'<div class="gs-row">'
                    f'<span class="gs-flag">{flag(team)}</span>'
                    f'<div class="gs-name-wrap">'
                    f'<span class="gs-name">{esc(team)}</span>'
                    f'<div class="gs-bar-track">'
                    f'<div class="gs-bar-fill" style="width:{bar_w}%"></div>'
                    f'</div></div>'
                    f'<span class="gs-pct">{f"{xw:.2f}" if xw is not None else "—"}</span>'
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
        '<div class="summary-item"><span class="s-label">Game of the Day</span>',
        f'<span class="s-value small">{gotd_matchup}</span>',
        f'<span class="s-sub">{esc(gotd_time)}</span></div>',
        '<div class="summary-item"><span class="s-label">Last Updated</span>',
        f'<span class="s-value small">{esc(updated_str)}</span></div>',
        "</div>",
        '<div class="legend-bar">',
        '<span><span class="dot green"></span>High watchability (&ge;60)</span>',
        '<span><span class="dot amber"></span>Moderate watchability (30&ndash;59)</span>',
        '<span><span class="dot red"></span>Low watchability (&lt;30)</span>',
        '<span style="color:#3b82f6">&#9632;</span><span>Home win</span>',
        '<span style="color:#6b7280">&#9632;</span><span>Draw</span>',
        '<span style="color:#f97316">&#9632;</span><span>Away win</span>',
        '<span style="opacity:.5">&#9632;</span><span style="opacity:.5">Faded bar = pre-game odds</span>',
        "</div>",
        '<div class="main-layout">',
        '<div class="schedule-col">',
        '<div class="section-label">Group Stage Schedule &mdash; 72 Games</div>',
        '<div class="sort-toggle">',
        '<button id="btn-date" class="sort-btn sort-active" onclick="setSort(\'date\')">By date</button>',
        '<button id="btn-watch" class="sort-btn" onclick="setSort(\'watch\')">By watchability</button>',
        '</div>',
        '<div id="schedule-content">',
        "".join(sched),
        "</div>",
        "</div>",
        '<div class="sidebar-col">',
        '<div class="section-label">Group Standings &mdash; Monte Carlo Simulator</div>',
        '<p class="mc-sim-note">Simulated using 10,000 runs per group. Completed results are fixed; remaining games use bookmaker h2h odds.</p>',
        '<div class="gs-panel">',
        "".join(gs),
        "</div></div>",
        "</div>",
        "<footer><p>Odds from "
        '<a href="https://the-odds-api.com" target="_blank" rel="noopener">The Odds API</a>'
        " &bull; Vig removed &bull; Probabilities averaged across available US bookmakers</p></footer>",
        "<script>",
        "(function(){",
        "var s=document.getElementById('schedule-content');",
        "var snap=s.innerHTML;",
        "var mode='date';",
        "window.setSort=function(m){",
        "if(m===mode)return;",
        "mode=m;",
        "document.getElementById('btn-date').classList.toggle('sort-active',m==='date');",
        "document.getElementById('btn-watch').classList.toggle('sort-active',m==='watch');",
        "if(m==='date'){s.innerHTML=snap;}",
        "else{",
        "var cards=Array.prototype.slice.call(s.querySelectorAll('.game-card'));",
        "cards.sort(function(a,b){return(parseInt(b.dataset.w)||0)-(parseInt(a.dataset.w)||0);});",
        "cards.forEach(function(c){var d=c.querySelector('.date-chip');if(d)d.style.display='inline-flex';});",
        "var g=document.createElement('div');g.className='games-grid';",
        "cards.forEach(function(c){g.appendChild(c);});",
        "s.innerHTML='';s.appendChild(g);",
        "}};})();",
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
    title_probs = get_title_probs(DB_PATH)
    if not odds:
        print("WARNING: No match odds in DB — generating skeleton dashboard.")

    t0 = time.time()
    groups_data, missing_odds, current_actual_points = build_groups_data(
        SCHEDULE, GROUPS, odds, completed_results
    )
    sim_results = run_all_simulations(groups_data, n=10000)
    elapsed = time.time() - t0
    print(f"Monte Carlo simulation complete ({elapsed:.1f}s, {len(missing_odds)} matches missing odds)")
    if missing_odds:
        for m in missing_odds[:5]:
            print(f"  Using 33/33/33 for: {m}")
        if len(missing_odds) > 5:
            print(f"  ... and {len(missing_odds) - 5} more")

    html = build_html(odds, fetched_at, results, title_probs, sim_results, current_actual_points)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write(html)

    size_kb = os.path.getsize(OUT_PATH) / 1024
    print(f"Wrote {OUT_PATH} ({size_kb:.1f} KB, {len(odds)} matches with odds)")


if __name__ == "__main__":
    main()
