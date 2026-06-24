# 2026 FIFA World Cup — Watchability Dashboard

**[Live dashboard →](https://iam8bu.github.io/world-cup-watchability-dashboard-2026/)**

All 72 group-stage matches ranked by how worth watching they are. Uses a custom Soccer Power Index (SPI) ratings model (based on past FiveThirtyEight models) to score every match on competitiveness, stakes, and team quality.

## What it does

- **Rates all 48 teams** with a Poisson GLM (attack/defense fixed effects per team, home-advantage term), fit on international results since 2010 and updated as World Cup results come in.
- **Simulates the tournament** thousands of times from current ratings to get each team's probability of advancing out of the group, reaching each knockout round, and winning it all.
- **Scores every match on watchability** as the average of three components, each normalized 0–100:
  - **Closeness** — how far the model's win/draw/loss split is from a coin-flip
  - **Importance** — how much the match result moves a team's odds of advancing (leverage)
  - **Quality** — combined SPI rating of both teams

## How it's built

| File | Role |
|---|---|
| `spi_model.py` | Core SPI rating model — Poisson GLM with Dixon-Coles correction, tournament simulation, leverage calculation |
| `fetch_odds.py` | Pulls live odds from a sportsbook API, normalizes team names across data sources |
| `build_dashboard.py` | Computes watchability scores and renders the static `index.html` |
| `.github/workflows/daily.yml` | Scheduled job: fetch odds → refit ratings → re-simulate → rebuild dashboard → commit |
| `odds.db`, `spi_ratings.db` | SQLite stores for fetched odds and model output |

Historical match data comes from the [Kaggle international football results dataset](https://www.kaggle.com/datasets/martj42/international-football-results-from-1872-to-2017).

## Running it locally

```bash
pip install requests scipy statsmodels pandas numpy
python spi_model.py              # fit ratings
python spi_model.py --simulate   # run tournament simulation
python spi_model.py --leverage   # compute match leverage
python fetch_odds.py             # pull live odds (requires ODDS_API_KEY)
python build_dashboard.py        # render index.html
```
