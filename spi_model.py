#!/usr/bin/env python3
"""
SPI-style (Soccer Power Index) model for international football.
Poisson GLM with team-level attack/defense fixed effects.
Inspired by FiveThirtyEight's SPI methodology.

Model structure (per match, two rows):
  log(E[goals]) = intercept + α[attack_team] + δ[defense_team] + γ·home_adv
  α > ref → scores more than avg; δ < ref → concedes fewer than avg (better defense)

Data: Kaggle 'martj42/international-football-results-from-1872-to-2017'

Install:
  pip install "kagglehub[pandas-datasets]" statsmodels
Credentials: ~/.kaggle/kaggle.json  (https://www.kaggle.com/settings > API)
"""

import math
import os
import sqlite3
import time
from datetime import date, datetime, timezone

import numpy as np
import pandas as pd
import statsmodels.api as sm
import statsmodels.formula.api as smf
from scipy.stats import poisson

from fetch_results import NAME_MAP as _BASE_NAME_MAP

KAGGLE_DATASET = "martj42/international-football-results-from-1872-to-2017"
DB_PATH = "spi_ratings.db"
ODDS_DB_PATH = "odds.db"
START_DATE = date(2010, 1, 1)
WC2026_START = date(2026, 6, 11)

DIXON_COLES_RHO = -0.13  # Empirically fitted correction for low-score clustering
                          # in soccer. Original value from Dixon & Coles (1997),
                          # validated against this dataset in backtest.py Part 3.
                          # Best-fit for this data: -0.08 (LL) / -0.03 (SSD),
                          # difference negligible (<0.001 LL). -0.13 retained.

RECENCY_DECAY_YEARS = 5.0     # Half-life for match recency weighting.
                               # Tested vs /3, /7, /10 in backtest.py — differences
                               # negligible (<0.006 log loss). /5 retained.

HOME_ADVANTAGE_FALLBACK = 0.249  # Log-space home advantage used if model_params
                                  # table is missing. Fitted value from GLM (+28.2%
                                  # expected goals at home). See spi_model.py Phase 1.

WC2026_TEAMS = {
    "Mexico", "South Africa", "South Korea", "Czechia",
    "Canada", "Bosnia-Herzegovina", "Qatar", "Switzerland",
    "Brazil", "Morocco", "Haiti", "Scotland",
    "United States", "Paraguay", "Australia", "Turkiye",
    "Germany", "Curacao", "Ivory Coast", "Ecuador",
    "Netherlands", "Japan", "Sweden", "Tunisia",
    "Belgium", "Egypt", "Iran", "New Zealand",
    "Spain", "Cape Verde", "Saudi Arabia", "Uruguay",
    "France", "Senegal", "Iraq", "Norway",
    "Argentina", "Algeria", "Austria", "Jordan",
    "Portugal", "DR Congo", "Uzbekistan", "Colombia",
    "England", "Croatia", "Ghana", "Panama",
}

# Extend base NAME_MAP with extra aliases the Kaggle CSV uses post-2010
NAME_MAP: dict[str, str] = {
    **_BASE_NAME_MAP,
    "IR Iran": "Iran",
    "Cape Verde Islands": "Cape Verde",
    "China PR": "China",
    "Republic of Ireland": "Ireland",
    "Macedonia": "North Macedonia",
    "Kyrgyz Republic": "Kyrgyzstan",
    "The Gambia": "Gambia",
    "Korea DPR": "North Korea",
}


def normalize(name: str) -> str:
    """Map a raw team name from an external source to the canonical
    WC2026 team name used throughout this project. Falls back to the
    input name unchanged if no mapping exists."""
    return NAME_MAP.get(name.strip(), name.strip())


def tournament_weight(tournament: str) -> float:
    t = tournament.lower()
    qualif = "qualif" in t or "qualifying" in t or "qualification" in t
    if "world cup" in t and not qualif:
        return 4.0
    if any(k in t for k in (
        "uefa euro", "uefa european championship",
        "copa am", "copa áme",
        "africa cup of nations",
        "afc asian cup",
        "concacaf gold cup", "gold cup",
        "ofc nations cup",
        "confederations cup",
    )) and not qualif:
        return 3.0
    if qualif:
        return 2.0
    return 1.0  # friendly / other


def load_kaggle(filename: str) -> pd.DataFrame:
    """Download `filename` from the KAGGLE_DATASET via kagglehub and return it
    as a raw, unfiltered DataFrame. Date filtering and name normalization are
    done by the caller (see seed_historical())."""
    import kagglehub
    from kagglehub import KaggleDatasetAdapter
    return kagglehub.dataset_load(
        KaggleDatasetAdapter.PANDAS,
        KAGGLE_DATASET,
        filename,
    )


def seed_historical() -> None:
    """
    One-time setup: download Kaggle CSV, filter to [START_DATE, WC2026_START),
    normalize team names, and store as 'historical_matches' in spi_ratings.db.
    Requires Kaggle credentials (~/.kaggle/kaggle.json). Run locally once.
    """
    print("Seeding historical_matches from Kaggle (one-time setup)...")
    try:
        raw_df = load_kaggle("results.csv")
    except Exception as e:
        import sys
        print(f"ERROR fetching from Kaggle: {e}")
        sys.exit(1)

    raw_df["date"] = pd.to_datetime(raw_df["date"]).dt.date
    df = raw_df[(raw_df["date"] >= START_DATE) & (raw_df["date"] < WC2026_START)].copy()
    df["home_team"] = df["home_team"].apply(normalize)
    df["away_team"] = df["away_team"].apply(normalize)

    conn = sqlite3.connect(DB_PATH)
    df.to_sql("historical_matches", conn, if_exists="replace", index=False)
    conn.close()
    print(f"  Stored {len(df):,} matches ({df['date'].min()} → {df['date'].max()}) in spi_ratings.db")
    print("  Run 'python spi_model.py' to fit SPI0 baseline from stored data.")


def load_historical_from_db() -> pd.DataFrame:
    """
    Read pre-tournament training data from spi_ratings.db.
    Exits with a clear error if the table is missing — never falls back to Kaggle.
    Seed it once with: python spi_model.py --init
    """
    import sys
    missing_msg = (
        "ERROR: 'historical_matches' table not found in spi_ratings.db.\n"
        "Run once (requires Kaggle credentials): python spi_model.py --init"
    )
    if not os.path.exists(DB_PATH):
        print(missing_msg)
        sys.exit(1)
    conn = sqlite3.connect(DB_PATH)
    try:
        tbl = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='historical_matches'"
        ).fetchone()
        if not tbl:
            print(missing_msg)
            sys.exit(1)
        df = pd.read_sql("SELECT * FROM historical_matches", conn)
    finally:
        conn.close()
    if df.empty:
        print(missing_msg)
        sys.exit(1)
    df["date"] = pd.to_datetime(df["date"]).dt.date
    return df


def load_wc2026_results() -> pd.DataFrame:
    """Load completed WC2026 match results from odds.db as a training DataFrame."""
    if not os.path.exists(ODDS_DB_PATH):
        return pd.DataFrame()
    conn = sqlite3.connect(ODDS_DB_PATH)
    try:
        tbl = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='match_results'"
        ).fetchone()
        if not tbl:
            return pd.DataFrame()
        cols = [r[1] for r in conn.execute("PRAGMA table_info(match_results)").fetchall()]
        where = "WHERE completed = 1" if "completed" in cols else ""
        df = pd.read_sql(
            f"SELECT home_team, away_team, home_score, away_score, fetched_at AS date "
            f"FROM match_results {where}",
            conn,
        )
    finally:
        conn.close()
    if df.empty:
        return pd.DataFrame()
    df["tournament"] = "FIFA World Cup"
    df["neutral"] = "True"  # WC convention: neutral venue for all teams
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df["home_team"] = df["home_team"].map(lambda x: normalize(x))
    df["away_team"] = df["away_team"].map(lambda x: normalize(x))
    df["home_score"] = df["home_score"].astype(int)
    df["away_score"] = df["away_score"].astype(int)
    return df


def _load_completed_wc2026_matches(conn=None) -> list[dict]:
    """Load completed WC2026 match results from odds.db.
    Returns list of dicts with keys: home, away, home_score, away_score.
    Names are normalized via normalize(). Returns empty list if none found.

    Note: match_results only ever contains completed matches (fetch_results.py
    filters to completed=True before inserting), so there is no completed-flag
    column to filter on here.
    """
    close_conn = conn is None
    if conn is None:
        if not os.path.exists(ODDS_DB_PATH):
            return []
        conn = sqlite3.connect(ODDS_DB_PATH)
    try:
        rows = conn.execute("""
            SELECT home_team, away_team, home_score, away_score
            FROM match_results
        """).fetchall()
        return [
            {
                "home": normalize(r[0]),
                "away": normalize(r[1]),
                "home_score": int(r[2]),
                "away_score": int(r[3]),
            }
            for r in rows
        ]
    except sqlite3.Error:
        return []
    finally:
        if close_conn:
            conn.close()


def main() -> None:
    # Pre-tournament ratings are frozen in historical_matches (seeded once via --init).
    # WC2026 results are appended fresh each run so ratings update permanently as games finish.
    df = load_historical_from_db()
    print(f"  Loaded {len(df):,} historical matches from spi_ratings.db ({df['date'].min()} → {df['date'].max()})")

    # Append completed WC2026 results — teams that played get permanently updated ratings
    wc2026_df = load_wc2026_results()
    if not wc2026_df.empty:
        print(f"  Appending {len(wc2026_df)} WC2026 results from odds.db")
        all_wc_names = set(wc2026_df["home_team"].tolist() + wc2026_df["away_team"].tolist())
        unmatched = all_wc_names - WC2026_TEAMS
        if unmatched:
            print(f"  WARNING: WC2026 team names not in WC2026_TEAMS: {sorted(unmatched)}")
        else:
            print(f"  ✓ All WC2026 team names matched to WC2026_TEAMS")
        df = pd.concat([df, wc2026_df], ignore_index=True)
    else:
        print("  No WC2026 results in odds.db yet — using SPI0 baseline only")

    reference_date = df["date"].max()
    print(f"  {len(df):,} matches from {df['date'].min()} to {reference_date}")

    # Build two-row-per-match dataset
    # Row 1: home team scoring  → attack=home, defense=away, home_adv=(1 if not neutral)
    # Row 2: away team scoring  → attack=away, defense=home, home_adv=0
    rows = []
    for row in df.itertuples(index=False):
        try:
            hs = int(row.home_score)
            aws = int(row.away_score)
        except (ValueError, TypeError):
            continue

        years_ago = (reference_date - row.date).days / 365.25
        recency = math.exp(-years_ago / RECENCY_DECAY_YEARS)
        imp = tournament_weight(str(row.tournament))
        w = imp * recency
        neutral = str(getattr(row, "neutral", "False")).strip().lower() == "true"

        rows.append({
            "goals": hs,
            "attack": row.home_team,
            "defense": row.away_team,
            "home_adv": 0.0 if neutral else 1.0,
            "weight": w,
        })
        rows.append({
            "goals": aws,
            "attack": row.away_team,
            "defense": row.home_team,
            "home_adv": 0.0,
            "weight": w,
        })

    model_df = pd.DataFrame(rows)
    print(f"  {len(model_df):,} observations (2 per match)")

    # Validate weights — drop rows where weight is non-finite or non-positive
    w = model_df["weight"].values.astype(float)
    bad = ~np.isfinite(w) | (w <= 0)
    if bad.any():
        print(f"  Warning: dropping {int(bad.sum())} rows with invalid weights")
        model_df = model_df[~bad].copy()
        w = model_df["weight"].values.astype(float)

    # Normalise weights to mean=1 (doesn't change estimates, avoids scale issues)
    model_df = model_df.copy()
    model_df["weight"] = w / w.mean()

    # Fit Poisson GLM with attack + defense fixed effects.
    # We use fit_regularized (L-BFGS-B) instead of the default IRLS because
    # IRLS overflows on this many categorical columns (~600 dummies). The tiny
    # alpha (1e-4) prevents perfect separation without meaningfully shrinking
    # the estimates (team effects are typically on the order of ±1).
    print("Fitting Poisson GLM via L-BFGS-B (this may take ~60s)...")
    formula = "goals ~ home_adv + C(attack) + C(defense)"
    glm_result = smf.glm(
        formula,
        data=model_df,
        family=sm.families.Poisson(),
        freq_weights=model_df["weight"],
    ).fit_regularized(alpha=1e-4, L1_wt=0, disp=False)

    print("  Fit complete.")

    # Extract coefficients
    params = glm_result.params
    intercept = float(params["Intercept"])
    home_adv_coef = float(params.get("home_adv", 0.0))

    all_teams = set(model_df["attack"].unique())
    # ref_team is an arbitrary identifiability constraint for the GLM
    # (one team's attack coefficient is fixed to zero so the intercept
    # is well-defined). The choice of which team doesn't affect final
    # SPI ratings — only relative differences between coefficients matter.
    ref_team = min(all_teams)  # statsmodels reference (alphabetically first)

    attack_coef: dict[str, float] = {}
    defense_coef: dict[str, float] = {}
    for team in all_teams:
        attack_coef[team] = float(params.get(f"C(attack)[T.{team}]", 0.0))
        defense_coef[team] = float(params.get(f"C(defense)[T.{team}]", 0.0))

    # Compute ratings (all relative to the reference team on a neutral field)
    # attack_rating  = exp(intercept + α[team]):  higher → scores more
    # defense_rating = exp(intercept + δ[team]):  lower  → concedes fewer (better)
    # defense_strength = 1 / defense_rating:      higher → better defense
    ratings: dict[str, dict] = {}
    for team in all_teams:
        ar = math.exp(intercept + attack_coef[team])
        dr = math.exp(intercept + defense_coef[team])
        ratings[team] = {
            "attack_rating": ar,
            "defense_rating": dr,
            "defense_strength": 1.0 / dr,
        }

    # SPI: normalized (attack_rating + defense_strength) over the 48-team WC field
    wc_found = {t: ratings[t] for t in WC2026_TEAMS if t in ratings}
    missing = sorted(t for t in WC2026_TEAMS if t not in ratings)

    if wc_found:
        combined = {t: v["attack_rating"] + v["defense_strength"] for t, v in wc_found.items()}
        max_combined = max(combined.values())
        for team, v in wc_found.items():
            v["spi_overall"] = round(combined[team] / max_combined * 100, 1)

    # ── Sanity checks ──────────────────────────────────────────────────────────
    W = 66
    print(f"\n{'='*W}")
    print("  SPI model — sanity check")
    print(f"{'='*W}")
    print(f"  Matches (post-{START_DATE.year})   : {len(df):,}")
    print(f"  Date range              : {df['date'].min()}  →  {reference_date}")
    print(f"  Observations (rows)     : {len(model_df):,}")
    print(f"  Teams in model          : {len(all_teams):,}")
    print(f"  Home advantage coef     : {home_adv_coef:.4f}"
          f"  (+{(math.exp(home_adv_coef)-1)*100:.1f}% goals when not neutral)")
    print(f"  Reference team (α=0)    : {ref_team}")
    print(f"  WC2026 teams found      : {len(wc_found)}/48")

    def top10(key: str, label: str, reverse: bool = True) -> None:
        ranked = sorted(wc_found.items(), key=lambda x: x[1][key], reverse=reverse)
        print(f"\n  Top 10 by {label}:")
        for i, (t, v) in enumerate(ranked[:10], 1):
            print(f"    {i:2}. {t:<30}  {v[key]:.4f}")

    top10("attack_rating", "attack_rating  (goals scored vs ref defense, neutral)")
    top10("defense_strength", "defense_strength  (higher = harder to score on)")
    top10("spi_overall", "SPI overall  (normalized 0–100 within WC2026 field)")

    print(f"\n  Bottom 5 WC2026 teams by SPI:")
    for t, v in sorted(wc_found.items(), key=lambda x: x[1]["spi_overall"])[:5]:
        print(f"    {t:<30}  SPI = {v['spi_overall']:.1f}")

    print(f"\n  Full WC2026 leaderboard:")
    print(f"  {'Rk':<4} {'Team':<30} {'Attack':>7} {'Def Str':>8} {'SPI':>6}")
    print(f"  {'─'*W}")
    for i, (t, v) in enumerate(
        sorted(wc_found.items(), key=lambda x: -x[1].get("spi_overall", 0)), 1
    ):
        print(
            f"  {i:<4} {t:<30} "
            f"{v['attack_rating']:7.4f} "
            f"{v['defense_strength']:8.4f} "
            f"{v.get('spi_overall', 0):6.1f}"
        )

    if missing:
        print(f"\n  WARNING: {len(missing)} WC2026 team(s) not in model:")
        for t in missing:
            print(f"    ⚠  {t}")
    else:
        print("\n  ✓ All 48 WC2026 teams matched.")
    print(f"{'='*W}\n")

    # ── Save to SQLite ─────────────────────────────────────────────────────────
    if not wc_found:
        print("Nothing to save — no WC2026 teams found in model.")
        return

    last_updated = datetime.now(timezone.utc).isoformat()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DROP TABLE IF EXISTS team_ratings")
    conn.execute("""
        CREATE TABLE team_ratings (
            team             TEXT PRIMARY KEY,
            attack_rating    REAL NOT NULL,
            defense_rating   REAL NOT NULL,
            defense_strength REAL NOT NULL,
            spi_overall      REAL NOT NULL,
            last_updated     TEXT NOT NULL
        )
    """)
    conn.executemany(
        "INSERT INTO team_ratings VALUES (?,?,?,?,?,?)",
        [
            (
                t,
                round(v["attack_rating"], 6),
                round(v["defense_rating"], 6),
                round(v["defense_strength"], 6),
                v["spi_overall"],
                last_updated,
            )
            for t, v in wc_found.items()
        ],
    )
    conn.execute("DROP TABLE IF EXISTS model_params")
    conn.execute("""
        CREATE TABLE model_params (
            param TEXT PRIMARY KEY,
            value REAL NOT NULL
        )
    """)
    conn.executemany("INSERT INTO model_params VALUES (?, ?)", [
        ("home_advantage_coef", round(home_adv_coef, 6)),
        ("intercept",           round(intercept,       6)),
    ])
    conn.commit()
    conn.close()
    print(f"Saved {len(wc_found)} WC2026 team ratings + model_params → {DB_PATH}")


# ── Phase 2: Match Prediction Layer ──────────────────────────────────────────


def _load_ratings(db_path: str = DB_PATH) -> tuple[dict, float, float]:
    """Return ({team: (attack_rating, defense_rating)}, home_advantage_coef, intercept).

    Both attack_rating and defense_rating are stored as exp(intercept + coef),
    so the correct expected-goals formula is:
        mu = attack_rating[A] * defense_rating[B] / exp(intercept)
    """
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT team, attack_rating, defense_rating FROM team_ratings"
        ).fetchall()
        ratings = {team: (ar, dr) for team, ar, dr in rows}
        try:
            prows = conn.execute("SELECT param, value FROM model_params").fetchall()
            p = {k: v for k, v in prows}
            home_adv = p.get("home_advantage_coef", HOME_ADVANTAGE_FALLBACK)
            intercept = p.get("intercept", 0.0)
        except sqlite3.OperationalError as e:
            if "no such table" not in str(e) and "no such column" not in str(e):
                raise
            home_adv = HOME_ADVANTAGE_FALLBACK
            intercept = 0.0
    finally:
        conn.close()
    return ratings, home_adv, intercept


def score_matrix(mu_a: float, mu_b: float, max_goals: int = 10) -> np.ndarray:
    """(max_goals+1)×(max_goals+1) independent Poisson scoreline probabilities.
    matrix[i][j] = P(team_a scores i, team_b scores j).
    """
    mat = np.zeros((max_goals + 1, max_goals + 1))
    for i in range(max_goals + 1):
        for j in range(max_goals + 1):
            mat[i][j] = poisson.pmf(i, mu_a) * poisson.pmf(j, mu_b)
    return mat


def dixon_coles_correction(
    matrix: np.ndarray, mu_a: float, mu_b: float, rho: float = DIXON_COLES_RHO
) -> np.ndarray:
    """Apply Dixon-Coles rho correction to the four low-scoring cells.
    See DIXON_COLES_RHO for the value's provenance.
    Renormalises the matrix after adjustment.
    """
    mat = matrix.copy()
    mat[0][0] *= (1 - mu_a * mu_b * rho)
    mat[1][0] *= (1 + mu_b * rho)
    mat[0][1] *= (1 + mu_a * rho)
    mat[1][1] *= (1 - rho)
    mat /= mat.sum()
    return mat


def match_probs(matrix: np.ndarray) -> tuple[float, float, float]:
    """Collapse score matrix to (team_a_win, draw, team_b_win) probabilities."""
    a_win = float(np.tril(matrix, -1).sum())   # i > j  → A scores more
    draw  = float(np.trace(matrix))             # i == j → equal
    b_win = float(np.triu(matrix, 1).sum())     # j > i  → B scores more
    return a_win, draw, b_win


def predict_match(
    team_a: str,
    team_b: str,
    neutral: bool = True,
    db_path: str = DB_PATH,
) -> dict:
    """Predict win/draw/loss for team_a vs team_b using SPI ratings.

    Parameters
    ----------
    team_a  : attacking/home team
    team_b  : defending/away team
    neutral : True = no home advantage (default for World Cup)
    db_path : path to spi_ratings.db
    """
    ratings, home_adv_coef, intercept = _load_ratings(db_path)

    for t in (team_a, team_b):
        if t not in ratings:
            raise ValueError(f"Team not found in spi_ratings.db: {t!r}")

    ar_a, dr_a = ratings[team_a]
    ar_b, dr_b = ratings[team_b]

    # Both ar and dr are stored as exp(intercept + coef), so their product
    # double-counts the intercept. Divide once to correct:
    #   mu = exp(intercept + α_A) * exp(intercept + δ_B) / exp(intercept)
    #      = exp(intercept + α_A + δ_B)  ← correct Poisson mean
    baseline = math.exp(intercept)
    mu_a = ar_a * dr_b / baseline
    mu_b = ar_b * dr_a / baseline

    if not neutral:
        mu_a *= math.exp(home_adv_coef)

    raw_mat = score_matrix(mu_a, mu_b)
    mat     = dixon_coles_correction(raw_mat, mu_a, mu_b)

    a_win, draw, b_win = match_probs(mat)

    best_i, best_j = np.unravel_index(np.argmax(mat), mat.shape)
    most_likely = f"{best_i}-{best_j}"

    return {
        "home_team":         team_a,
        "away_team":         team_b,
        "home_win":          round(a_win, 4),
        "draw":              round(draw, 4),
        "away_win":          round(b_win, 4),
        "mu_a":              round(mu_a, 3),
        "mu_b":              round(mu_b, 3),
        "most_likely_score": most_likely,
        "neutral":           neutral,
        "_raw_mat":          raw_mat,
        "_dc_mat":           mat,
    }


def validate_predictions(db_path: str = DB_PATH) -> None:
    """Run Phase 2 validation matchups and print results."""
    W = 78
    print(f"\n{'='*W}")
    print("  Phase 2 — Bivariate Poisson + Dixon-Coles prediction validation")
    print(f"{'='*W}")

    # ── Formula diagnostic ────────────────────────────────────────────────────
    ratings, home_adv_coef, intercept = _load_ratings(db_path)
    baseline = math.exp(intercept)
    ar_sp, dr_sp = ratings["Spain"]
    ar_cv, dr_cv = ratings["Cape Verde"]
    mu_sp_diag = ar_sp * dr_cv / baseline
    mu_cv_diag = ar_cv * dr_sp / baseline
    print(f"  Formula diagnostic — Spain vs Cape Verde (neutral):")
    print(f"    intercept              = {intercept:.4f}  →  exp(intercept) = {baseline:.4f}")
    print(f"    attack_rating[Spain]   = {ar_sp:.4f}  (= exp(intercept + α_Spain))")
    print(f"    defense_rating[CapeV]  = {dr_cv:.4f}  (= exp(intercept + δ_CapeVerde))")
    print(f"    attack_rating[CapeV]   = {ar_cv:.4f}")
    print(f"    defense_rating[Spain]  = {dr_sp:.4f}")
    print(f"    μ_Spain  = {ar_sp:.4f} × {dr_cv:.4f} / {baseline:.4f} = {mu_sp_diag:.3f}")
    print(f"    μ_CapeV  = {ar_cv:.4f} × {dr_sp:.4f} / {baseline:.4f} = {mu_cv_diag:.3f}")
    target_ok = (2.5 <= mu_sp_diag <= 3.5) and (0.3 <= mu_cv_diag <= 0.6)
    print(f"    Target ranges: Spain 2.5–3.5, CapeV 0.3–0.6  {'✓' if target_ok else '⚠ out of range'}")
    print()

    matchups = [
        ("Spain",         "Cape Verde",    True,  "heavily Spain"),
        ("France",        "Senegal",       True,  "heavily France"),
        ("Argentina",     "Algeria",       True,  "heavily Argentina"),
        ("Germany",       "Netherlands",   True,  "competitive (~40/25/35)"),
        ("Brazil",        "Morocco",       True,  "interesting — Morocco #11 SPI"),
        ("England",       "Croatia",       True,  "moderate England favor"),
        ("United States", "Paraguay",      True,  "probably close"),
        ("Belgium",       "Egypt",         True,  "moderate Belgium favor"),
        ("Norway",        "Iraq",          True,  "Norway favor"),
        ("Mexico",        "South Africa",  True,  "slight Mexico favor"),
        ("Mexico",        "South Africa",  False, "Mexico HOME (opener, Mexico City)"),
    ]

    hdr = f"  {'Team A':<20} {'Team B':<20} {'Win':>6} {'Draw':>6} {'Loss':>6}  {'μA':>5} {'μB':>5}  {'Score':<7} {'N?'}"
    print(hdr)
    print(f"  {'─'*W}")

    germany_result = None
    dc_demo_result = None

    for team_a, team_b, neutral, note in matchups:
        try:
            r = predict_match(team_a, team_b, neutral=neutral, db_path=db_path)
        except ValueError as e:
            print(f"  ERROR: {e}")
            continue

        n_flag = "Y" if neutral else "N"
        print(
            f"  {team_a:<20} {team_b:<20} "
            f"{r['home_win']*100:5.1f}% "
            f"{r['draw']*100:5.1f}% "
            f"{r['away_win']*100:5.1f}%  "
            f"{r['mu_a']:5.2f} {r['mu_b']:5.2f}  "
            f"{r['most_likely_score']:<7} {n_flag}  ← {note}"
        )

        if team_a == "Germany" and team_b == "Netherlands" and neutral:
            germany_result = r
        if team_a == "Spain" and team_b == "Cape Verde" and neutral:
            dc_demo_result = r

    # ── Sanity check 1: probabilities sum to 1 ──────────────────────────────
    print(f"\n  {'─'*W}")
    print("  Sanity check A — do all three probs sum to 1.0?")
    all_ok = True
    for team_a, team_b, neutral, _ in matchups:
        try:
            r = predict_match(team_a, team_b, neutral=neutral, db_path=db_path)
        except ValueError:
            continue
        total = r["home_win"] + r["draw"] + r["away_win"]
        ok = abs(total - 1.0) < 2e-4  # 4-dp rounding can shift sum by up to ~1.5e-4
        if not ok:
            print(f"    ✗ {team_a} vs {team_b}: sum = {total:.8f}")
            all_ok = False
    if all_ok:
        print("    ✓ All matchups sum to 1.000000")

    # ── Sanity check 2: Dixon-Coles effect on 0-0 probability ───────────────
    if dc_demo_result is not None:
        raw = dc_demo_result["_raw_mat"]
        dc  = dc_demo_result["_dc_mat"]
        r   = dc_demo_result
        print(f"\n  Sanity check B — Dixon-Coles effect on Spain vs Cape Verde:")
        print(f"    Raw Poisson  0-0 prob : {raw[0][0]:.4f}")
        print(f"    After DC correction  : {dc[0][0]:.4f}")
        print(f"    Change               : {(dc[0][0]-raw[0][0])*100:+.2f}pp")
        print(f"    (μ_Spain={r['mu_a']:.2f}, μ_Cape Verde={r['mu_b']:.2f},"
              f" rho=-0.13)")

    # ── Sanity check 3: Germany vs Netherlands vs bookmaker lines ───────────
    if germany_result is not None:
        r = germany_result
        print(f"\n  Sanity check C — Germany vs Netherlands vs typical book lines:")
        print(f"    SPI model  : {r['home_win']*100:.1f}% / {r['draw']*100:.1f}%"
              f" / {r['away_win']*100:.1f}%")
        print(f"    Book lines : ~40% / ~25% / ~35%  (benchmark)")
        diff_win  = abs(r['home_win']  - 0.40)
        diff_draw = abs(r['draw']      - 0.25)
        diff_loss = abs(r['away_win']  - 0.35)
        max_diff  = max(diff_win, diff_draw, diff_loss)
        flag = "✓" if max_diff < 0.08 else "⚠"
        print(f"    Max deviation: {max_diff*100:.1f}pp  {flag}")

    print(f"{'='*W}\n")


# ── Phase 3: Full Tournament Monte Carlo ──────────────────────────────────────

from itertools import combinations as _combinations

WC2026_GROUPS = {
    "A": ["Mexico",        "South Africa",      "South Korea",  "Czechia"],
    "B": ["Canada",        "Bosnia-Herzegovina","Qatar",        "Switzerland"],
    "C": ["Brazil",        "Morocco",           "Haiti",        "Scotland"],
    "D": ["United States", "Paraguay",          "Australia",    "Turkiye"],
    "E": ["Germany",       "Curacao",           "Ivory Coast",  "Ecuador"],
    "F": ["Netherlands",   "Japan",             "Sweden",       "Tunisia"],
    "G": ["Belgium",       "Egypt",             "Iran",         "New Zealand"],
    "H": ["Spain",         "Cape Verde",        "Saudi Arabia", "Uruguay"],
    "I": ["France",        "Senegal",           "Iraq",         "Norway"],
    "J": ["Argentina",     "Algeria",           "Austria",      "Jordan"],
    "K": ["Portugal",      "DR Congo",          "Uzbekistan",   "Colombia"],
    "L": ["England",       "Croatia",           "Ghana",        "Panama"],
}

_groups_teams = {t for teams in WC2026_GROUPS.values() for t in teams}
assert _groups_teams == WC2026_TEAMS, (
    f"WC2026_TEAMS and WC2026_GROUPS are out of sync.\n"
    f"In GROUPS not in TEAMS: {_groups_teams - WC2026_TEAMS}\n"
    f"In TEAMS not in GROUPS: {WC2026_TEAMS - _groups_teams}"
)

# Official FIFA 2026 R32 bracket structure (matches M73–M88)
# Source: FIFA 2026 tournament regulations + wikipedia.org/wiki/2026_FIFA_World_Cup_knockout_stage
# Variable slots (3rd-place teams) are resolved via ANNEX_C lookup below.
# Fixed R32 matchups (no 3rd-place dependency):
#   M73: R_A vs R_B   M75: W_F vs R_C   M76: W_C vs R_F   M78: R_E vs R_I
#   M83: R_K vs R_L   M84: W_H vs R_J   M86: W_J vs R_H   M88: R_D vs R_G
# Variable R32 matchups (3rd-place slot resolved by ANNEX_C):
#   M74: W_E vs 3rd(pool A/B/C/D/F)   M77: W_I vs 3rd(pool C/D/F/G/H)
#   M79: W_A vs 3rd(pool C/E/F/H/I)   M80: W_L vs 3rd(pool E/H/I/J/K)
#   M81: W_D vs 3rd(pool B/E/F/I/J)   M82: W_G vs 3rd(pool A/E/H/I/J)
#   M85: W_B vs 3rd(pool E/F/G/I/J)   M87: W_K vs 3rd(pool D/E/I/J/L)
# R16 bracket (M89–M96): M89=W73vW75  M90=W74vW77  M91=W76vW78  M92=W79vW80
#                         M93=W83vW84  M94=W81vW82  M95=W86vW88  M96=W85vW87
# QF (M97–M100): M97=W89vW90  M98=W93vW94  M99=W91vW92  M100=W95vW96
# SF (M101–M102): M101=W97vW98  M102=W99vW100   Final: W101 vs W102

# Annex C — official FIFA 2026 third-place placement table (all 495 combinations)
# Keys: frozenset of 8 group letters whose 3rd-place teams advance
# Values: {match_id: group_letter} for the 8 variable R32 slots
# Source: wikipedia.org/wiki/Template:2026_FIFA_World_Cup_third-place_table
ANNEX_C: dict = {
    frozenset(['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H']): {'M79': 'H', 'M85': 'G', 'M81': 'B', 'M74': 'C', 'M82': 'A', 'M77': 'F', 'M87': 'D', 'M80': 'E'},
    frozenset(['A', 'B', 'C', 'D', 'E', 'F', 'G', 'I']): {'M79': 'C', 'M85': 'G', 'M81': 'B', 'M74': 'D', 'M82': 'A', 'M77': 'F', 'M87': 'E', 'M80': 'I'},
    frozenset(['A', 'B', 'C', 'D', 'E', 'F', 'G', 'J']): {'M79': 'C', 'M85': 'G', 'M81': 'B', 'M74': 'D', 'M82': 'A', 'M77': 'F', 'M87': 'E', 'M80': 'J'},
    frozenset(['A', 'B', 'C', 'D', 'E', 'F', 'G', 'K']): {'M79': 'C', 'M85': 'G', 'M81': 'B', 'M74': 'D', 'M82': 'A', 'M77': 'F', 'M87': 'E', 'M80': 'K'},
    frozenset(['A', 'B', 'C', 'D', 'E', 'F', 'G', 'L']): {'M79': 'C', 'M85': 'G', 'M81': 'B', 'M74': 'D', 'M82': 'A', 'M77': 'F', 'M87': 'L', 'M80': 'E'},
    frozenset(['A', 'B', 'C', 'D', 'E', 'F', 'H', 'I']): {'M79': 'H', 'M85': 'E', 'M81': 'B', 'M74': 'C', 'M82': 'A', 'M77': 'F', 'M87': 'D', 'M80': 'I'},
    frozenset(['A', 'B', 'C', 'D', 'E', 'F', 'H', 'J']): {'M79': 'H', 'M85': 'J', 'M81': 'B', 'M74': 'C', 'M82': 'A', 'M77': 'F', 'M87': 'D', 'M80': 'E'},
    frozenset(['A', 'B', 'C', 'D', 'E', 'F', 'H', 'K']): {'M79': 'H', 'M85': 'E', 'M81': 'B', 'M74': 'C', 'M82': 'A', 'M77': 'F', 'M87': 'D', 'M80': 'K'},
    frozenset(['A', 'B', 'C', 'D', 'E', 'F', 'H', 'L']): {'M79': 'H', 'M85': 'F', 'M81': 'B', 'M74': 'C', 'M82': 'A', 'M77': 'D', 'M87': 'L', 'M80': 'E'},
    frozenset(['A', 'B', 'C', 'D', 'E', 'F', 'I', 'J']): {'M79': 'C', 'M85': 'J', 'M81': 'B', 'M74': 'D', 'M82': 'A', 'M77': 'F', 'M87': 'E', 'M80': 'I'},
    frozenset(['A', 'B', 'C', 'D', 'E', 'F', 'I', 'K']): {'M79': 'C', 'M85': 'E', 'M81': 'B', 'M74': 'D', 'M82': 'A', 'M77': 'F', 'M87': 'I', 'M80': 'K'},
    frozenset(['A', 'B', 'C', 'D', 'E', 'F', 'I', 'L']): {'M79': 'C', 'M85': 'E', 'M81': 'B', 'M74': 'D', 'M82': 'A', 'M77': 'F', 'M87': 'L', 'M80': 'I'},
    frozenset(['A', 'B', 'C', 'D', 'E', 'F', 'J', 'K']): {'M79': 'C', 'M85': 'J', 'M81': 'B', 'M74': 'D', 'M82': 'A', 'M77': 'F', 'M87': 'E', 'M80': 'K'},
    frozenset(['A', 'B', 'C', 'D', 'E', 'F', 'J', 'L']): {'M79': 'C', 'M85': 'J', 'M81': 'B', 'M74': 'D', 'M82': 'A', 'M77': 'F', 'M87': 'L', 'M80': 'E'},
    frozenset(['A', 'B', 'C', 'D', 'E', 'F', 'K', 'L']): {'M79': 'C', 'M85': 'E', 'M81': 'B', 'M74': 'D', 'M82': 'A', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'B', 'C', 'D', 'E', 'G', 'H', 'I']): {'M79': 'H', 'M85': 'G', 'M81': 'B', 'M74': 'C', 'M82': 'A', 'M77': 'D', 'M87': 'E', 'M80': 'I'},
    frozenset(['A', 'B', 'C', 'D', 'E', 'G', 'H', 'J']): {'M79': 'H', 'M85': 'G', 'M81': 'B', 'M74': 'C', 'M82': 'A', 'M77': 'D', 'M87': 'E', 'M80': 'J'},
    frozenset(['A', 'B', 'C', 'D', 'E', 'G', 'H', 'K']): {'M79': 'H', 'M85': 'G', 'M81': 'B', 'M74': 'C', 'M82': 'A', 'M77': 'D', 'M87': 'E', 'M80': 'K'},
    frozenset(['A', 'B', 'C', 'D', 'E', 'G', 'H', 'L']): {'M79': 'H', 'M85': 'G', 'M81': 'B', 'M74': 'C', 'M82': 'A', 'M77': 'D', 'M87': 'L', 'M80': 'E'},
    frozenset(['A', 'B', 'C', 'D', 'E', 'G', 'I', 'J']): {'M79': 'E', 'M85': 'G', 'M81': 'B', 'M74': 'C', 'M82': 'A', 'M77': 'D', 'M87': 'I', 'M80': 'J'},
    frozenset(['A', 'B', 'C', 'D', 'E', 'G', 'I', 'K']): {'M79': 'E', 'M85': 'G', 'M81': 'B', 'M74': 'C', 'M82': 'A', 'M77': 'D', 'M87': 'I', 'M80': 'K'},
    frozenset(['A', 'B', 'C', 'D', 'E', 'G', 'I', 'L']): {'M79': 'E', 'M85': 'G', 'M81': 'B', 'M74': 'C', 'M82': 'A', 'M77': 'D', 'M87': 'L', 'M80': 'I'},
    frozenset(['A', 'B', 'C', 'D', 'E', 'G', 'J', 'K']): {'M79': 'E', 'M85': 'G', 'M81': 'B', 'M74': 'C', 'M82': 'A', 'M77': 'D', 'M87': 'J', 'M80': 'K'},
    frozenset(['A', 'B', 'C', 'D', 'E', 'G', 'J', 'L']): {'M79': 'E', 'M85': 'G', 'M81': 'B', 'M74': 'C', 'M82': 'A', 'M77': 'D', 'M87': 'L', 'M80': 'J'},
    frozenset(['A', 'B', 'C', 'D', 'E', 'G', 'K', 'L']): {'M79': 'E', 'M85': 'G', 'M81': 'B', 'M74': 'C', 'M82': 'A', 'M77': 'D', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'B', 'C', 'D', 'E', 'H', 'I', 'J']): {'M79': 'H', 'M85': 'J', 'M81': 'B', 'M74': 'C', 'M82': 'A', 'M77': 'D', 'M87': 'E', 'M80': 'I'},
    frozenset(['A', 'B', 'C', 'D', 'E', 'H', 'I', 'K']): {'M79': 'H', 'M85': 'E', 'M81': 'B', 'M74': 'C', 'M82': 'A', 'M77': 'D', 'M87': 'I', 'M80': 'K'},
    frozenset(['A', 'B', 'C', 'D', 'E', 'H', 'I', 'L']): {'M79': 'H', 'M85': 'E', 'M81': 'B', 'M74': 'C', 'M82': 'A', 'M77': 'D', 'M87': 'L', 'M80': 'I'},
    frozenset(['A', 'B', 'C', 'D', 'E', 'H', 'J', 'K']): {'M79': 'H', 'M85': 'J', 'M81': 'B', 'M74': 'C', 'M82': 'A', 'M77': 'D', 'M87': 'E', 'M80': 'K'},
    frozenset(['A', 'B', 'C', 'D', 'E', 'H', 'J', 'L']): {'M79': 'H', 'M85': 'J', 'M81': 'B', 'M74': 'C', 'M82': 'A', 'M77': 'D', 'M87': 'L', 'M80': 'E'},
    frozenset(['A', 'B', 'C', 'D', 'E', 'H', 'K', 'L']): {'M79': 'H', 'M85': 'E', 'M81': 'B', 'M74': 'C', 'M82': 'A', 'M77': 'D', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'B', 'C', 'D', 'E', 'I', 'J', 'K']): {'M79': 'E', 'M85': 'J', 'M81': 'B', 'M74': 'C', 'M82': 'A', 'M77': 'D', 'M87': 'I', 'M80': 'K'},
    frozenset(['A', 'B', 'C', 'D', 'E', 'I', 'J', 'L']): {'M79': 'E', 'M85': 'J', 'M81': 'B', 'M74': 'C', 'M82': 'A', 'M77': 'D', 'M87': 'L', 'M80': 'I'},
    frozenset(['A', 'B', 'C', 'D', 'E', 'I', 'K', 'L']): {'M79': 'E', 'M85': 'I', 'M81': 'B', 'M74': 'C', 'M82': 'A', 'M77': 'D', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'B', 'C', 'D', 'E', 'J', 'K', 'L']): {'M79': 'E', 'M85': 'J', 'M81': 'B', 'M74': 'C', 'M82': 'A', 'M77': 'D', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'B', 'C', 'D', 'F', 'G', 'H', 'I']): {'M79': 'H', 'M85': 'G', 'M81': 'B', 'M74': 'C', 'M82': 'A', 'M77': 'F', 'M87': 'D', 'M80': 'I'},
    frozenset(['A', 'B', 'C', 'D', 'F', 'G', 'H', 'J']): {'M79': 'H', 'M85': 'G', 'M81': 'B', 'M74': 'C', 'M82': 'A', 'M77': 'F', 'M87': 'D', 'M80': 'J'},
    frozenset(['A', 'B', 'C', 'D', 'F', 'G', 'H', 'K']): {'M79': 'H', 'M85': 'G', 'M81': 'B', 'M74': 'C', 'M82': 'A', 'M77': 'F', 'M87': 'D', 'M80': 'K'},
    frozenset(['A', 'B', 'C', 'D', 'F', 'G', 'H', 'L']): {'M79': 'C', 'M85': 'G', 'M81': 'B', 'M74': 'D', 'M82': 'A', 'M77': 'F', 'M87': 'L', 'M80': 'H'},
    frozenset(['A', 'B', 'C', 'D', 'F', 'G', 'I', 'J']): {'M79': 'C', 'M85': 'G', 'M81': 'B', 'M74': 'D', 'M82': 'A', 'M77': 'F', 'M87': 'I', 'M80': 'J'},
    frozenset(['A', 'B', 'C', 'D', 'F', 'G', 'I', 'K']): {'M79': 'C', 'M85': 'G', 'M81': 'B', 'M74': 'D', 'M82': 'A', 'M77': 'F', 'M87': 'I', 'M80': 'K'},
    frozenset(['A', 'B', 'C', 'D', 'F', 'G', 'I', 'L']): {'M79': 'C', 'M85': 'G', 'M81': 'B', 'M74': 'D', 'M82': 'A', 'M77': 'F', 'M87': 'L', 'M80': 'I'},
    frozenset(['A', 'B', 'C', 'D', 'F', 'G', 'J', 'K']): {'M79': 'C', 'M85': 'G', 'M81': 'B', 'M74': 'D', 'M82': 'A', 'M77': 'F', 'M87': 'J', 'M80': 'K'},
    frozenset(['A', 'B', 'C', 'D', 'F', 'G', 'J', 'L']): {'M79': 'C', 'M85': 'G', 'M81': 'B', 'M74': 'D', 'M82': 'A', 'M77': 'F', 'M87': 'L', 'M80': 'J'},
    frozenset(['A', 'B', 'C', 'D', 'F', 'G', 'K', 'L']): {'M79': 'C', 'M85': 'G', 'M81': 'B', 'M74': 'D', 'M82': 'A', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'B', 'C', 'D', 'F', 'H', 'I', 'J']): {'M79': 'H', 'M85': 'J', 'M81': 'B', 'M74': 'C', 'M82': 'A', 'M77': 'F', 'M87': 'D', 'M80': 'I'},
    frozenset(['A', 'B', 'C', 'D', 'F', 'H', 'I', 'K']): {'M79': 'H', 'M85': 'F', 'M81': 'B', 'M74': 'C', 'M82': 'A', 'M77': 'D', 'M87': 'I', 'M80': 'K'},
    frozenset(['A', 'B', 'C', 'D', 'F', 'H', 'I', 'L']): {'M79': 'H', 'M85': 'F', 'M81': 'B', 'M74': 'C', 'M82': 'A', 'M77': 'D', 'M87': 'L', 'M80': 'I'},
    frozenset(['A', 'B', 'C', 'D', 'F', 'H', 'J', 'K']): {'M79': 'H', 'M85': 'J', 'M81': 'B', 'M74': 'C', 'M82': 'A', 'M77': 'F', 'M87': 'D', 'M80': 'K'},
    frozenset(['A', 'B', 'C', 'D', 'F', 'H', 'J', 'L']): {'M79': 'C', 'M85': 'J', 'M81': 'B', 'M74': 'D', 'M82': 'A', 'M77': 'F', 'M87': 'L', 'M80': 'H'},
    frozenset(['A', 'B', 'C', 'D', 'F', 'H', 'K', 'L']): {'M79': 'H', 'M85': 'F', 'M81': 'B', 'M74': 'C', 'M82': 'A', 'M77': 'D', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'B', 'C', 'D', 'F', 'I', 'J', 'K']): {'M79': 'C', 'M85': 'J', 'M81': 'B', 'M74': 'D', 'M82': 'A', 'M77': 'F', 'M87': 'I', 'M80': 'K'},
    frozenset(['A', 'B', 'C', 'D', 'F', 'I', 'J', 'L']): {'M79': 'C', 'M85': 'J', 'M81': 'B', 'M74': 'D', 'M82': 'A', 'M77': 'F', 'M87': 'L', 'M80': 'I'},
    frozenset(['A', 'B', 'C', 'D', 'F', 'I', 'K', 'L']): {'M79': 'C', 'M85': 'I', 'M81': 'B', 'M74': 'D', 'M82': 'A', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'B', 'C', 'D', 'F', 'J', 'K', 'L']): {'M79': 'C', 'M85': 'J', 'M81': 'B', 'M74': 'D', 'M82': 'A', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'B', 'C', 'D', 'G', 'H', 'I', 'J']): {'M79': 'H', 'M85': 'G', 'M81': 'B', 'M74': 'C', 'M82': 'A', 'M77': 'D', 'M87': 'I', 'M80': 'J'},
    frozenset(['A', 'B', 'C', 'D', 'G', 'H', 'I', 'K']): {'M79': 'H', 'M85': 'G', 'M81': 'B', 'M74': 'C', 'M82': 'A', 'M77': 'D', 'M87': 'I', 'M80': 'K'},
    frozenset(['A', 'B', 'C', 'D', 'G', 'H', 'I', 'L']): {'M79': 'H', 'M85': 'G', 'M81': 'B', 'M74': 'C', 'M82': 'A', 'M77': 'D', 'M87': 'L', 'M80': 'I'},
    frozenset(['A', 'B', 'C', 'D', 'G', 'H', 'J', 'K']): {'M79': 'H', 'M85': 'G', 'M81': 'B', 'M74': 'C', 'M82': 'A', 'M77': 'D', 'M87': 'J', 'M80': 'K'},
    frozenset(['A', 'B', 'C', 'D', 'G', 'H', 'J', 'L']): {'M79': 'H', 'M85': 'G', 'M81': 'B', 'M74': 'C', 'M82': 'A', 'M77': 'D', 'M87': 'L', 'M80': 'J'},
    frozenset(['A', 'B', 'C', 'D', 'G', 'H', 'K', 'L']): {'M79': 'H', 'M85': 'G', 'M81': 'B', 'M74': 'C', 'M82': 'A', 'M77': 'D', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'B', 'C', 'D', 'G', 'I', 'J', 'K']): {'M79': 'C', 'M85': 'J', 'M81': 'B', 'M74': 'D', 'M82': 'A', 'M77': 'G', 'M87': 'I', 'M80': 'K'},
    frozenset(['A', 'B', 'C', 'D', 'G', 'I', 'J', 'L']): {'M79': 'C', 'M85': 'J', 'M81': 'B', 'M74': 'D', 'M82': 'A', 'M77': 'G', 'M87': 'L', 'M80': 'I'},
    frozenset(['A', 'B', 'C', 'D', 'G', 'I', 'K', 'L']): {'M79': 'I', 'M85': 'G', 'M81': 'B', 'M74': 'C', 'M82': 'A', 'M77': 'D', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'B', 'C', 'D', 'G', 'J', 'K', 'L']): {'M79': 'C', 'M85': 'J', 'M81': 'B', 'M74': 'D', 'M82': 'A', 'M77': 'G', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'B', 'C', 'D', 'H', 'I', 'J', 'K']): {'M79': 'H', 'M85': 'J', 'M81': 'B', 'M74': 'C', 'M82': 'A', 'M77': 'D', 'M87': 'I', 'M80': 'K'},
    frozenset(['A', 'B', 'C', 'D', 'H', 'I', 'J', 'L']): {'M79': 'H', 'M85': 'J', 'M81': 'B', 'M74': 'C', 'M82': 'A', 'M77': 'D', 'M87': 'L', 'M80': 'I'},
    frozenset(['A', 'B', 'C', 'D', 'H', 'I', 'K', 'L']): {'M79': 'H', 'M85': 'I', 'M81': 'B', 'M74': 'C', 'M82': 'A', 'M77': 'D', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'B', 'C', 'D', 'H', 'J', 'K', 'L']): {'M79': 'H', 'M85': 'J', 'M81': 'B', 'M74': 'C', 'M82': 'A', 'M77': 'D', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'B', 'C', 'D', 'I', 'J', 'K', 'L']): {'M79': 'I', 'M85': 'J', 'M81': 'B', 'M74': 'C', 'M82': 'A', 'M77': 'D', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'B', 'C', 'E', 'F', 'G', 'H', 'I']): {'M79': 'H', 'M85': 'G', 'M81': 'B', 'M74': 'C', 'M82': 'A', 'M77': 'F', 'M87': 'E', 'M80': 'I'},
    frozenset(['A', 'B', 'C', 'E', 'F', 'G', 'H', 'J']): {'M79': 'H', 'M85': 'G', 'M81': 'B', 'M74': 'C', 'M82': 'A', 'M77': 'F', 'M87': 'E', 'M80': 'J'},
    frozenset(['A', 'B', 'C', 'E', 'F', 'G', 'H', 'K']): {'M79': 'H', 'M85': 'G', 'M81': 'B', 'M74': 'C', 'M82': 'A', 'M77': 'F', 'M87': 'E', 'M80': 'K'},
    frozenset(['A', 'B', 'C', 'E', 'F', 'G', 'H', 'L']): {'M79': 'H', 'M85': 'G', 'M81': 'B', 'M74': 'C', 'M82': 'A', 'M77': 'F', 'M87': 'L', 'M80': 'E'},
    frozenset(['A', 'B', 'C', 'E', 'F', 'G', 'I', 'J']): {'M79': 'E', 'M85': 'G', 'M81': 'B', 'M74': 'C', 'M82': 'A', 'M77': 'F', 'M87': 'I', 'M80': 'J'},
    frozenset(['A', 'B', 'C', 'E', 'F', 'G', 'I', 'K']): {'M79': 'E', 'M85': 'G', 'M81': 'B', 'M74': 'C', 'M82': 'A', 'M77': 'F', 'M87': 'I', 'M80': 'K'},
    frozenset(['A', 'B', 'C', 'E', 'F', 'G', 'I', 'L']): {'M79': 'E', 'M85': 'G', 'M81': 'B', 'M74': 'C', 'M82': 'A', 'M77': 'F', 'M87': 'L', 'M80': 'I'},
    frozenset(['A', 'B', 'C', 'E', 'F', 'G', 'J', 'K']): {'M79': 'E', 'M85': 'G', 'M81': 'B', 'M74': 'C', 'M82': 'A', 'M77': 'F', 'M87': 'J', 'M80': 'K'},
    frozenset(['A', 'B', 'C', 'E', 'F', 'G', 'J', 'L']): {'M79': 'E', 'M85': 'G', 'M81': 'B', 'M74': 'C', 'M82': 'A', 'M77': 'F', 'M87': 'L', 'M80': 'J'},
    frozenset(['A', 'B', 'C', 'E', 'F', 'G', 'K', 'L']): {'M79': 'E', 'M85': 'G', 'M81': 'B', 'M74': 'C', 'M82': 'A', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'B', 'C', 'E', 'F', 'H', 'I', 'J']): {'M79': 'H', 'M85': 'J', 'M81': 'B', 'M74': 'C', 'M82': 'A', 'M77': 'F', 'M87': 'E', 'M80': 'I'},
    frozenset(['A', 'B', 'C', 'E', 'F', 'H', 'I', 'K']): {'M79': 'H', 'M85': 'E', 'M81': 'B', 'M74': 'C', 'M82': 'A', 'M77': 'F', 'M87': 'I', 'M80': 'K'},
    frozenset(['A', 'B', 'C', 'E', 'F', 'H', 'I', 'L']): {'M79': 'H', 'M85': 'E', 'M81': 'B', 'M74': 'C', 'M82': 'A', 'M77': 'F', 'M87': 'L', 'M80': 'I'},
    frozenset(['A', 'B', 'C', 'E', 'F', 'H', 'J', 'K']): {'M79': 'H', 'M85': 'J', 'M81': 'B', 'M74': 'C', 'M82': 'A', 'M77': 'F', 'M87': 'E', 'M80': 'K'},
    frozenset(['A', 'B', 'C', 'E', 'F', 'H', 'J', 'L']): {'M79': 'H', 'M85': 'J', 'M81': 'B', 'M74': 'C', 'M82': 'A', 'M77': 'F', 'M87': 'L', 'M80': 'E'},
    frozenset(['A', 'B', 'C', 'E', 'F', 'H', 'K', 'L']): {'M79': 'H', 'M85': 'E', 'M81': 'B', 'M74': 'C', 'M82': 'A', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'B', 'C', 'E', 'F', 'I', 'J', 'K']): {'M79': 'E', 'M85': 'J', 'M81': 'B', 'M74': 'C', 'M82': 'A', 'M77': 'F', 'M87': 'I', 'M80': 'K'},
    frozenset(['A', 'B', 'C', 'E', 'F', 'I', 'J', 'L']): {'M79': 'E', 'M85': 'J', 'M81': 'B', 'M74': 'C', 'M82': 'A', 'M77': 'F', 'M87': 'L', 'M80': 'I'},
    frozenset(['A', 'B', 'C', 'E', 'F', 'I', 'K', 'L']): {'M79': 'E', 'M85': 'I', 'M81': 'B', 'M74': 'C', 'M82': 'A', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'B', 'C', 'E', 'F', 'J', 'K', 'L']): {'M79': 'E', 'M85': 'J', 'M81': 'B', 'M74': 'C', 'M82': 'A', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'B', 'C', 'E', 'G', 'H', 'I', 'J']): {'M79': 'H', 'M85': 'J', 'M81': 'B', 'M74': 'C', 'M82': 'A', 'M77': 'G', 'M87': 'E', 'M80': 'I'},
    frozenset(['A', 'B', 'C', 'E', 'G', 'H', 'I', 'K']): {'M79': 'E', 'M85': 'G', 'M81': 'B', 'M74': 'C', 'M82': 'A', 'M77': 'H', 'M87': 'I', 'M80': 'K'},
    frozenset(['A', 'B', 'C', 'E', 'G', 'H', 'I', 'L']): {'M79': 'E', 'M85': 'G', 'M81': 'B', 'M74': 'C', 'M82': 'A', 'M77': 'H', 'M87': 'L', 'M80': 'I'},
    frozenset(['A', 'B', 'C', 'E', 'G', 'H', 'J', 'K']): {'M79': 'H', 'M85': 'J', 'M81': 'B', 'M74': 'C', 'M82': 'A', 'M77': 'G', 'M87': 'E', 'M80': 'K'},
    frozenset(['A', 'B', 'C', 'E', 'G', 'H', 'J', 'L']): {'M79': 'H', 'M85': 'J', 'M81': 'B', 'M74': 'C', 'M82': 'A', 'M77': 'G', 'M87': 'L', 'M80': 'E'},
    frozenset(['A', 'B', 'C', 'E', 'G', 'H', 'K', 'L']): {'M79': 'E', 'M85': 'G', 'M81': 'B', 'M74': 'C', 'M82': 'A', 'M77': 'H', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'B', 'C', 'E', 'G', 'I', 'J', 'K']): {'M79': 'E', 'M85': 'J', 'M81': 'B', 'M74': 'C', 'M82': 'A', 'M77': 'G', 'M87': 'I', 'M80': 'K'},
    frozenset(['A', 'B', 'C', 'E', 'G', 'I', 'J', 'L']): {'M79': 'E', 'M85': 'J', 'M81': 'B', 'M74': 'C', 'M82': 'A', 'M77': 'G', 'M87': 'L', 'M80': 'I'},
    frozenset(['A', 'B', 'C', 'E', 'G', 'I', 'K', 'L']): {'M79': 'E', 'M85': 'G', 'M81': 'B', 'M74': 'A', 'M82': 'I', 'M77': 'C', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'B', 'C', 'E', 'G', 'J', 'K', 'L']): {'M79': 'E', 'M85': 'J', 'M81': 'B', 'M74': 'C', 'M82': 'A', 'M77': 'G', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'B', 'C', 'E', 'H', 'I', 'J', 'K']): {'M79': 'E', 'M85': 'J', 'M81': 'B', 'M74': 'C', 'M82': 'A', 'M77': 'H', 'M87': 'I', 'M80': 'K'},
    frozenset(['A', 'B', 'C', 'E', 'H', 'I', 'J', 'L']): {'M79': 'E', 'M85': 'J', 'M81': 'B', 'M74': 'C', 'M82': 'A', 'M77': 'H', 'M87': 'L', 'M80': 'I'},
    frozenset(['A', 'B', 'C', 'E', 'H', 'I', 'K', 'L']): {'M79': 'E', 'M85': 'I', 'M81': 'B', 'M74': 'C', 'M82': 'A', 'M77': 'H', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'B', 'C', 'E', 'H', 'J', 'K', 'L']): {'M79': 'E', 'M85': 'J', 'M81': 'B', 'M74': 'C', 'M82': 'A', 'M77': 'H', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'B', 'C', 'E', 'I', 'J', 'K', 'L']): {'M79': 'E', 'M85': 'J', 'M81': 'B', 'M74': 'A', 'M82': 'I', 'M77': 'C', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'B', 'C', 'F', 'G', 'H', 'I', 'J']): {'M79': 'H', 'M85': 'G', 'M81': 'B', 'M74': 'C', 'M82': 'A', 'M77': 'F', 'M87': 'I', 'M80': 'J'},
    frozenset(['A', 'B', 'C', 'F', 'G', 'H', 'I', 'K']): {'M79': 'H', 'M85': 'G', 'M81': 'B', 'M74': 'C', 'M82': 'A', 'M77': 'F', 'M87': 'I', 'M80': 'K'},
    frozenset(['A', 'B', 'C', 'F', 'G', 'H', 'I', 'L']): {'M79': 'H', 'M85': 'G', 'M81': 'B', 'M74': 'C', 'M82': 'A', 'M77': 'F', 'M87': 'L', 'M80': 'I'},
    frozenset(['A', 'B', 'C', 'F', 'G', 'H', 'J', 'K']): {'M79': 'H', 'M85': 'G', 'M81': 'B', 'M74': 'C', 'M82': 'A', 'M77': 'F', 'M87': 'J', 'M80': 'K'},
    frozenset(['A', 'B', 'C', 'F', 'G', 'H', 'J', 'L']): {'M79': 'H', 'M85': 'G', 'M81': 'B', 'M74': 'C', 'M82': 'A', 'M77': 'F', 'M87': 'L', 'M80': 'J'},
    frozenset(['A', 'B', 'C', 'F', 'G', 'H', 'K', 'L']): {'M79': 'H', 'M85': 'G', 'M81': 'B', 'M74': 'C', 'M82': 'A', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'B', 'C', 'F', 'G', 'I', 'J', 'K']): {'M79': 'C', 'M85': 'J', 'M81': 'B', 'M74': 'F', 'M82': 'A', 'M77': 'G', 'M87': 'I', 'M80': 'K'},
    frozenset(['A', 'B', 'C', 'F', 'G', 'I', 'J', 'L']): {'M79': 'C', 'M85': 'J', 'M81': 'B', 'M74': 'F', 'M82': 'A', 'M77': 'G', 'M87': 'L', 'M80': 'I'},
    frozenset(['A', 'B', 'C', 'F', 'G', 'I', 'K', 'L']): {'M79': 'I', 'M85': 'G', 'M81': 'B', 'M74': 'C', 'M82': 'A', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'B', 'C', 'F', 'G', 'J', 'K', 'L']): {'M79': 'C', 'M85': 'J', 'M81': 'B', 'M74': 'F', 'M82': 'A', 'M77': 'G', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'B', 'C', 'F', 'H', 'I', 'J', 'K']): {'M79': 'H', 'M85': 'J', 'M81': 'B', 'M74': 'C', 'M82': 'A', 'M77': 'F', 'M87': 'I', 'M80': 'K'},
    frozenset(['A', 'B', 'C', 'F', 'H', 'I', 'J', 'L']): {'M79': 'H', 'M85': 'J', 'M81': 'B', 'M74': 'C', 'M82': 'A', 'M77': 'F', 'M87': 'L', 'M80': 'I'},
    frozenset(['A', 'B', 'C', 'F', 'H', 'I', 'K', 'L']): {'M79': 'H', 'M85': 'I', 'M81': 'B', 'M74': 'C', 'M82': 'A', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'B', 'C', 'F', 'H', 'J', 'K', 'L']): {'M79': 'H', 'M85': 'J', 'M81': 'B', 'M74': 'C', 'M82': 'A', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'B', 'C', 'F', 'I', 'J', 'K', 'L']): {'M79': 'I', 'M85': 'J', 'M81': 'B', 'M74': 'C', 'M82': 'A', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'B', 'C', 'G', 'H', 'I', 'J', 'K']): {'M79': 'H', 'M85': 'J', 'M81': 'B', 'M74': 'C', 'M82': 'A', 'M77': 'G', 'M87': 'I', 'M80': 'K'},
    frozenset(['A', 'B', 'C', 'G', 'H', 'I', 'J', 'L']): {'M79': 'H', 'M85': 'J', 'M81': 'B', 'M74': 'C', 'M82': 'A', 'M77': 'G', 'M87': 'L', 'M80': 'I'},
    frozenset(['A', 'B', 'C', 'G', 'H', 'I', 'K', 'L']): {'M79': 'I', 'M85': 'G', 'M81': 'B', 'M74': 'C', 'M82': 'A', 'M77': 'H', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'B', 'C', 'G', 'H', 'J', 'K', 'L']): {'M79': 'H', 'M85': 'J', 'M81': 'B', 'M74': 'C', 'M82': 'A', 'M77': 'G', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'B', 'C', 'G', 'I', 'J', 'K', 'L']): {'M79': 'I', 'M85': 'J', 'M81': 'B', 'M74': 'C', 'M82': 'A', 'M77': 'G', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'B', 'C', 'H', 'I', 'J', 'K', 'L']): {'M79': 'I', 'M85': 'J', 'M81': 'B', 'M74': 'C', 'M82': 'A', 'M77': 'H', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'B', 'D', 'E', 'F', 'G', 'H', 'I']): {'M79': 'H', 'M85': 'G', 'M81': 'B', 'M74': 'D', 'M82': 'A', 'M77': 'F', 'M87': 'E', 'M80': 'I'},
    frozenset(['A', 'B', 'D', 'E', 'F', 'G', 'H', 'J']): {'M79': 'H', 'M85': 'G', 'M81': 'B', 'M74': 'D', 'M82': 'A', 'M77': 'F', 'M87': 'E', 'M80': 'J'},
    frozenset(['A', 'B', 'D', 'E', 'F', 'G', 'H', 'K']): {'M79': 'H', 'M85': 'G', 'M81': 'B', 'M74': 'D', 'M82': 'A', 'M77': 'F', 'M87': 'E', 'M80': 'K'},
    frozenset(['A', 'B', 'D', 'E', 'F', 'G', 'H', 'L']): {'M79': 'H', 'M85': 'G', 'M81': 'B', 'M74': 'D', 'M82': 'A', 'M77': 'F', 'M87': 'L', 'M80': 'E'},
    frozenset(['A', 'B', 'D', 'E', 'F', 'G', 'I', 'J']): {'M79': 'E', 'M85': 'G', 'M81': 'B', 'M74': 'D', 'M82': 'A', 'M77': 'F', 'M87': 'I', 'M80': 'J'},
    frozenset(['A', 'B', 'D', 'E', 'F', 'G', 'I', 'K']): {'M79': 'E', 'M85': 'G', 'M81': 'B', 'M74': 'D', 'M82': 'A', 'M77': 'F', 'M87': 'I', 'M80': 'K'},
    frozenset(['A', 'B', 'D', 'E', 'F', 'G', 'I', 'L']): {'M79': 'E', 'M85': 'G', 'M81': 'B', 'M74': 'D', 'M82': 'A', 'M77': 'F', 'M87': 'L', 'M80': 'I'},
    frozenset(['A', 'B', 'D', 'E', 'F', 'G', 'J', 'K']): {'M79': 'E', 'M85': 'G', 'M81': 'B', 'M74': 'D', 'M82': 'A', 'M77': 'F', 'M87': 'J', 'M80': 'K'},
    frozenset(['A', 'B', 'D', 'E', 'F', 'G', 'J', 'L']): {'M79': 'E', 'M85': 'G', 'M81': 'B', 'M74': 'D', 'M82': 'A', 'M77': 'F', 'M87': 'L', 'M80': 'J'},
    frozenset(['A', 'B', 'D', 'E', 'F', 'G', 'K', 'L']): {'M79': 'E', 'M85': 'G', 'M81': 'B', 'M74': 'D', 'M82': 'A', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'B', 'D', 'E', 'F', 'H', 'I', 'J']): {'M79': 'H', 'M85': 'J', 'M81': 'B', 'M74': 'D', 'M82': 'A', 'M77': 'F', 'M87': 'E', 'M80': 'I'},
    frozenset(['A', 'B', 'D', 'E', 'F', 'H', 'I', 'K']): {'M79': 'H', 'M85': 'E', 'M81': 'B', 'M74': 'D', 'M82': 'A', 'M77': 'F', 'M87': 'I', 'M80': 'K'},
    frozenset(['A', 'B', 'D', 'E', 'F', 'H', 'I', 'L']): {'M79': 'H', 'M85': 'E', 'M81': 'B', 'M74': 'D', 'M82': 'A', 'M77': 'F', 'M87': 'L', 'M80': 'I'},
    frozenset(['A', 'B', 'D', 'E', 'F', 'H', 'J', 'K']): {'M79': 'H', 'M85': 'J', 'M81': 'B', 'M74': 'D', 'M82': 'A', 'M77': 'F', 'M87': 'E', 'M80': 'K'},
    frozenset(['A', 'B', 'D', 'E', 'F', 'H', 'J', 'L']): {'M79': 'H', 'M85': 'J', 'M81': 'B', 'M74': 'D', 'M82': 'A', 'M77': 'F', 'M87': 'L', 'M80': 'E'},
    frozenset(['A', 'B', 'D', 'E', 'F', 'H', 'K', 'L']): {'M79': 'H', 'M85': 'E', 'M81': 'B', 'M74': 'D', 'M82': 'A', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'B', 'D', 'E', 'F', 'I', 'J', 'K']): {'M79': 'E', 'M85': 'J', 'M81': 'B', 'M74': 'D', 'M82': 'A', 'M77': 'F', 'M87': 'I', 'M80': 'K'},
    frozenset(['A', 'B', 'D', 'E', 'F', 'I', 'J', 'L']): {'M79': 'E', 'M85': 'J', 'M81': 'B', 'M74': 'D', 'M82': 'A', 'M77': 'F', 'M87': 'L', 'M80': 'I'},
    frozenset(['A', 'B', 'D', 'E', 'F', 'I', 'K', 'L']): {'M79': 'E', 'M85': 'I', 'M81': 'B', 'M74': 'D', 'M82': 'A', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'B', 'D', 'E', 'F', 'J', 'K', 'L']): {'M79': 'E', 'M85': 'J', 'M81': 'B', 'M74': 'D', 'M82': 'A', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'B', 'D', 'E', 'G', 'H', 'I', 'J']): {'M79': 'H', 'M85': 'J', 'M81': 'B', 'M74': 'D', 'M82': 'A', 'M77': 'G', 'M87': 'E', 'M80': 'I'},
    frozenset(['A', 'B', 'D', 'E', 'G', 'H', 'I', 'K']): {'M79': 'E', 'M85': 'G', 'M81': 'B', 'M74': 'D', 'M82': 'A', 'M77': 'H', 'M87': 'I', 'M80': 'K'},
    frozenset(['A', 'B', 'D', 'E', 'G', 'H', 'I', 'L']): {'M79': 'E', 'M85': 'G', 'M81': 'B', 'M74': 'D', 'M82': 'A', 'M77': 'H', 'M87': 'L', 'M80': 'I'},
    frozenset(['A', 'B', 'D', 'E', 'G', 'H', 'J', 'K']): {'M79': 'H', 'M85': 'J', 'M81': 'B', 'M74': 'D', 'M82': 'A', 'M77': 'G', 'M87': 'E', 'M80': 'K'},
    frozenset(['A', 'B', 'D', 'E', 'G', 'H', 'J', 'L']): {'M79': 'H', 'M85': 'J', 'M81': 'B', 'M74': 'D', 'M82': 'A', 'M77': 'G', 'M87': 'L', 'M80': 'E'},
    frozenset(['A', 'B', 'D', 'E', 'G', 'H', 'K', 'L']): {'M79': 'E', 'M85': 'G', 'M81': 'B', 'M74': 'D', 'M82': 'A', 'M77': 'H', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'B', 'D', 'E', 'G', 'I', 'J', 'K']): {'M79': 'E', 'M85': 'J', 'M81': 'B', 'M74': 'D', 'M82': 'A', 'M77': 'G', 'M87': 'I', 'M80': 'K'},
    frozenset(['A', 'B', 'D', 'E', 'G', 'I', 'J', 'L']): {'M79': 'E', 'M85': 'J', 'M81': 'B', 'M74': 'D', 'M82': 'A', 'M77': 'G', 'M87': 'L', 'M80': 'I'},
    frozenset(['A', 'B', 'D', 'E', 'G', 'I', 'K', 'L']): {'M79': 'E', 'M85': 'G', 'M81': 'B', 'M74': 'A', 'M82': 'I', 'M77': 'D', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'B', 'D', 'E', 'G', 'J', 'K', 'L']): {'M79': 'E', 'M85': 'J', 'M81': 'B', 'M74': 'D', 'M82': 'A', 'M77': 'G', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'B', 'D', 'E', 'H', 'I', 'J', 'K']): {'M79': 'E', 'M85': 'J', 'M81': 'B', 'M74': 'D', 'M82': 'A', 'M77': 'H', 'M87': 'I', 'M80': 'K'},
    frozenset(['A', 'B', 'D', 'E', 'H', 'I', 'J', 'L']): {'M79': 'E', 'M85': 'J', 'M81': 'B', 'M74': 'D', 'M82': 'A', 'M77': 'H', 'M87': 'L', 'M80': 'I'},
    frozenset(['A', 'B', 'D', 'E', 'H', 'I', 'K', 'L']): {'M79': 'E', 'M85': 'I', 'M81': 'B', 'M74': 'D', 'M82': 'A', 'M77': 'H', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'B', 'D', 'E', 'H', 'J', 'K', 'L']): {'M79': 'E', 'M85': 'J', 'M81': 'B', 'M74': 'D', 'M82': 'A', 'M77': 'H', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'B', 'D', 'E', 'I', 'J', 'K', 'L']): {'M79': 'E', 'M85': 'J', 'M81': 'B', 'M74': 'A', 'M82': 'I', 'M77': 'D', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'B', 'D', 'F', 'G', 'H', 'I', 'J']): {'M79': 'H', 'M85': 'G', 'M81': 'B', 'M74': 'D', 'M82': 'A', 'M77': 'F', 'M87': 'I', 'M80': 'J'},
    frozenset(['A', 'B', 'D', 'F', 'G', 'H', 'I', 'K']): {'M79': 'H', 'M85': 'G', 'M81': 'B', 'M74': 'D', 'M82': 'A', 'M77': 'F', 'M87': 'I', 'M80': 'K'},
    frozenset(['A', 'B', 'D', 'F', 'G', 'H', 'I', 'L']): {'M79': 'H', 'M85': 'G', 'M81': 'B', 'M74': 'D', 'M82': 'A', 'M77': 'F', 'M87': 'L', 'M80': 'I'},
    frozenset(['A', 'B', 'D', 'F', 'G', 'H', 'J', 'K']): {'M79': 'H', 'M85': 'G', 'M81': 'B', 'M74': 'D', 'M82': 'A', 'M77': 'F', 'M87': 'J', 'M80': 'K'},
    frozenset(['A', 'B', 'D', 'F', 'G', 'H', 'J', 'L']): {'M79': 'H', 'M85': 'G', 'M81': 'B', 'M74': 'D', 'M82': 'A', 'M77': 'F', 'M87': 'L', 'M80': 'J'},
    frozenset(['A', 'B', 'D', 'F', 'G', 'H', 'K', 'L']): {'M79': 'H', 'M85': 'G', 'M81': 'B', 'M74': 'D', 'M82': 'A', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'B', 'D', 'F', 'G', 'I', 'J', 'K']): {'M79': 'F', 'M85': 'J', 'M81': 'B', 'M74': 'D', 'M82': 'A', 'M77': 'G', 'M87': 'I', 'M80': 'K'},
    frozenset(['A', 'B', 'D', 'F', 'G', 'I', 'J', 'L']): {'M79': 'F', 'M85': 'J', 'M81': 'B', 'M74': 'D', 'M82': 'A', 'M77': 'G', 'M87': 'L', 'M80': 'I'},
    frozenset(['A', 'B', 'D', 'F', 'G', 'I', 'K', 'L']): {'M79': 'I', 'M85': 'G', 'M81': 'B', 'M74': 'D', 'M82': 'A', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'B', 'D', 'F', 'G', 'J', 'K', 'L']): {'M79': 'F', 'M85': 'J', 'M81': 'B', 'M74': 'D', 'M82': 'A', 'M77': 'G', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'B', 'D', 'F', 'H', 'I', 'J', 'K']): {'M79': 'H', 'M85': 'J', 'M81': 'B', 'M74': 'D', 'M82': 'A', 'M77': 'F', 'M87': 'I', 'M80': 'K'},
    frozenset(['A', 'B', 'D', 'F', 'H', 'I', 'J', 'L']): {'M79': 'H', 'M85': 'J', 'M81': 'B', 'M74': 'D', 'M82': 'A', 'M77': 'F', 'M87': 'L', 'M80': 'I'},
    frozenset(['A', 'B', 'D', 'F', 'H', 'I', 'K', 'L']): {'M79': 'H', 'M85': 'I', 'M81': 'B', 'M74': 'D', 'M82': 'A', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'B', 'D', 'F', 'H', 'J', 'K', 'L']): {'M79': 'H', 'M85': 'J', 'M81': 'B', 'M74': 'D', 'M82': 'A', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'B', 'D', 'F', 'I', 'J', 'K', 'L']): {'M79': 'I', 'M85': 'J', 'M81': 'B', 'M74': 'D', 'M82': 'A', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'B', 'D', 'G', 'H', 'I', 'J', 'K']): {'M79': 'H', 'M85': 'J', 'M81': 'B', 'M74': 'D', 'M82': 'A', 'M77': 'G', 'M87': 'I', 'M80': 'K'},
    frozenset(['A', 'B', 'D', 'G', 'H', 'I', 'J', 'L']): {'M79': 'H', 'M85': 'J', 'M81': 'B', 'M74': 'D', 'M82': 'A', 'M77': 'G', 'M87': 'L', 'M80': 'I'},
    frozenset(['A', 'B', 'D', 'G', 'H', 'I', 'K', 'L']): {'M79': 'I', 'M85': 'G', 'M81': 'B', 'M74': 'D', 'M82': 'A', 'M77': 'H', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'B', 'D', 'G', 'H', 'J', 'K', 'L']): {'M79': 'H', 'M85': 'J', 'M81': 'B', 'M74': 'D', 'M82': 'A', 'M77': 'G', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'B', 'D', 'G', 'I', 'J', 'K', 'L']): {'M79': 'I', 'M85': 'J', 'M81': 'B', 'M74': 'D', 'M82': 'A', 'M77': 'G', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'B', 'D', 'H', 'I', 'J', 'K', 'L']): {'M79': 'I', 'M85': 'J', 'M81': 'B', 'M74': 'D', 'M82': 'A', 'M77': 'H', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'B', 'E', 'F', 'G', 'H', 'I', 'J']): {'M79': 'H', 'M85': 'J', 'M81': 'B', 'M74': 'F', 'M82': 'A', 'M77': 'G', 'M87': 'E', 'M80': 'I'},
    frozenset(['A', 'B', 'E', 'F', 'G', 'H', 'I', 'K']): {'M79': 'E', 'M85': 'G', 'M81': 'B', 'M74': 'F', 'M82': 'A', 'M77': 'H', 'M87': 'I', 'M80': 'K'},
    frozenset(['A', 'B', 'E', 'F', 'G', 'H', 'I', 'L']): {'M79': 'E', 'M85': 'G', 'M81': 'B', 'M74': 'F', 'M82': 'A', 'M77': 'H', 'M87': 'L', 'M80': 'I'},
    frozenset(['A', 'B', 'E', 'F', 'G', 'H', 'J', 'K']): {'M79': 'H', 'M85': 'J', 'M81': 'B', 'M74': 'F', 'M82': 'A', 'M77': 'G', 'M87': 'E', 'M80': 'K'},
    frozenset(['A', 'B', 'E', 'F', 'G', 'H', 'J', 'L']): {'M79': 'H', 'M85': 'J', 'M81': 'B', 'M74': 'F', 'M82': 'A', 'M77': 'G', 'M87': 'L', 'M80': 'E'},
    frozenset(['A', 'B', 'E', 'F', 'G', 'H', 'K', 'L']): {'M79': 'E', 'M85': 'G', 'M81': 'B', 'M74': 'F', 'M82': 'A', 'M77': 'H', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'B', 'E', 'F', 'G', 'I', 'J', 'K']): {'M79': 'E', 'M85': 'J', 'M81': 'B', 'M74': 'F', 'M82': 'A', 'M77': 'G', 'M87': 'I', 'M80': 'K'},
    frozenset(['A', 'B', 'E', 'F', 'G', 'I', 'J', 'L']): {'M79': 'E', 'M85': 'J', 'M81': 'B', 'M74': 'F', 'M82': 'A', 'M77': 'G', 'M87': 'L', 'M80': 'I'},
    frozenset(['A', 'B', 'E', 'F', 'G', 'I', 'K', 'L']): {'M79': 'E', 'M85': 'G', 'M81': 'B', 'M74': 'A', 'M82': 'I', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'B', 'E', 'F', 'G', 'J', 'K', 'L']): {'M79': 'E', 'M85': 'J', 'M81': 'B', 'M74': 'F', 'M82': 'A', 'M77': 'G', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'B', 'E', 'F', 'H', 'I', 'J', 'K']): {'M79': 'E', 'M85': 'J', 'M81': 'B', 'M74': 'F', 'M82': 'A', 'M77': 'H', 'M87': 'I', 'M80': 'K'},
    frozenset(['A', 'B', 'E', 'F', 'H', 'I', 'J', 'L']): {'M79': 'E', 'M85': 'J', 'M81': 'B', 'M74': 'F', 'M82': 'A', 'M77': 'H', 'M87': 'L', 'M80': 'I'},
    frozenset(['A', 'B', 'E', 'F', 'H', 'I', 'K', 'L']): {'M79': 'E', 'M85': 'I', 'M81': 'B', 'M74': 'F', 'M82': 'A', 'M77': 'H', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'B', 'E', 'F', 'H', 'J', 'K', 'L']): {'M79': 'E', 'M85': 'J', 'M81': 'B', 'M74': 'F', 'M82': 'A', 'M77': 'H', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'B', 'E', 'F', 'I', 'J', 'K', 'L']): {'M79': 'E', 'M85': 'J', 'M81': 'B', 'M74': 'A', 'M82': 'I', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'B', 'E', 'G', 'H', 'I', 'J', 'K']): {'M79': 'E', 'M85': 'J', 'M81': 'B', 'M74': 'A', 'M82': 'H', 'M77': 'G', 'M87': 'I', 'M80': 'K'},
    frozenset(['A', 'B', 'E', 'G', 'H', 'I', 'J', 'L']): {'M79': 'E', 'M85': 'J', 'M81': 'B', 'M74': 'A', 'M82': 'H', 'M77': 'G', 'M87': 'L', 'M80': 'I'},
    frozenset(['A', 'B', 'E', 'G', 'H', 'I', 'K', 'L']): {'M79': 'E', 'M85': 'G', 'M81': 'B', 'M74': 'A', 'M82': 'I', 'M77': 'H', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'B', 'E', 'G', 'H', 'J', 'K', 'L']): {'M79': 'E', 'M85': 'J', 'M81': 'B', 'M74': 'A', 'M82': 'H', 'M77': 'G', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'B', 'E', 'G', 'I', 'J', 'K', 'L']): {'M79': 'E', 'M85': 'J', 'M81': 'B', 'M74': 'A', 'M82': 'I', 'M77': 'G', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'B', 'E', 'H', 'I', 'J', 'K', 'L']): {'M79': 'E', 'M85': 'J', 'M81': 'B', 'M74': 'A', 'M82': 'I', 'M77': 'H', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'B', 'F', 'G', 'H', 'I', 'J', 'K']): {'M79': 'H', 'M85': 'J', 'M81': 'B', 'M74': 'F', 'M82': 'A', 'M77': 'G', 'M87': 'I', 'M80': 'K'},
    frozenset(['A', 'B', 'F', 'G', 'H', 'I', 'J', 'L']): {'M79': 'H', 'M85': 'J', 'M81': 'B', 'M74': 'F', 'M82': 'A', 'M77': 'G', 'M87': 'L', 'M80': 'I'},
    frozenset(['A', 'B', 'F', 'G', 'H', 'I', 'K', 'L']): {'M79': 'H', 'M85': 'G', 'M81': 'B', 'M74': 'A', 'M82': 'I', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'B', 'F', 'G', 'H', 'J', 'K', 'L']): {'M79': 'H', 'M85': 'J', 'M81': 'B', 'M74': 'F', 'M82': 'A', 'M77': 'G', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'B', 'F', 'G', 'I', 'J', 'K', 'L']): {'M79': 'I', 'M85': 'J', 'M81': 'B', 'M74': 'F', 'M82': 'A', 'M77': 'G', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'B', 'F', 'H', 'I', 'J', 'K', 'L']): {'M79': 'H', 'M85': 'J', 'M81': 'B', 'M74': 'A', 'M82': 'I', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'B', 'G', 'H', 'I', 'J', 'K', 'L']): {'M79': 'H', 'M85': 'J', 'M81': 'B', 'M74': 'A', 'M82': 'I', 'M77': 'G', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'C', 'D', 'E', 'F', 'G', 'H', 'I']): {'M79': 'H', 'M85': 'G', 'M81': 'E', 'M74': 'C', 'M82': 'A', 'M77': 'F', 'M87': 'D', 'M80': 'I'},
    frozenset(['A', 'C', 'D', 'E', 'F', 'G', 'H', 'J']): {'M79': 'H', 'M85': 'G', 'M81': 'J', 'M74': 'C', 'M82': 'A', 'M77': 'F', 'M87': 'D', 'M80': 'E'},
    frozenset(['A', 'C', 'D', 'E', 'F', 'G', 'H', 'K']): {'M79': 'H', 'M85': 'G', 'M81': 'E', 'M74': 'C', 'M82': 'A', 'M77': 'F', 'M87': 'D', 'M80': 'K'},
    frozenset(['A', 'C', 'D', 'E', 'F', 'G', 'H', 'L']): {'M79': 'H', 'M85': 'G', 'M81': 'F', 'M74': 'C', 'M82': 'A', 'M77': 'D', 'M87': 'L', 'M80': 'E'},
    frozenset(['A', 'C', 'D', 'E', 'F', 'G', 'I', 'J']): {'M79': 'C', 'M85': 'G', 'M81': 'J', 'M74': 'D', 'M82': 'A', 'M77': 'F', 'M87': 'E', 'M80': 'I'},
    frozenset(['A', 'C', 'D', 'E', 'F', 'G', 'I', 'K']): {'M79': 'C', 'M85': 'G', 'M81': 'E', 'M74': 'D', 'M82': 'A', 'M77': 'F', 'M87': 'I', 'M80': 'K'},
    frozenset(['A', 'C', 'D', 'E', 'F', 'G', 'I', 'L']): {'M79': 'C', 'M85': 'G', 'M81': 'E', 'M74': 'D', 'M82': 'A', 'M77': 'F', 'M87': 'L', 'M80': 'I'},
    frozenset(['A', 'C', 'D', 'E', 'F', 'G', 'J', 'K']): {'M79': 'C', 'M85': 'G', 'M81': 'J', 'M74': 'D', 'M82': 'A', 'M77': 'F', 'M87': 'E', 'M80': 'K'},
    frozenset(['A', 'C', 'D', 'E', 'F', 'G', 'J', 'L']): {'M79': 'C', 'M85': 'G', 'M81': 'J', 'M74': 'D', 'M82': 'A', 'M77': 'F', 'M87': 'L', 'M80': 'E'},
    frozenset(['A', 'C', 'D', 'E', 'F', 'G', 'K', 'L']): {'M79': 'C', 'M85': 'G', 'M81': 'E', 'M74': 'D', 'M82': 'A', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'C', 'D', 'E', 'F', 'H', 'I', 'J']): {'M79': 'H', 'M85': 'J', 'M81': 'E', 'M74': 'C', 'M82': 'A', 'M77': 'F', 'M87': 'D', 'M80': 'I'},
    frozenset(['A', 'C', 'D', 'E', 'F', 'H', 'I', 'K']): {'M79': 'H', 'M85': 'E', 'M81': 'F', 'M74': 'C', 'M82': 'A', 'M77': 'D', 'M87': 'I', 'M80': 'K'},
    frozenset(['A', 'C', 'D', 'E', 'F', 'H', 'I', 'L']): {'M79': 'H', 'M85': 'E', 'M81': 'F', 'M74': 'C', 'M82': 'A', 'M77': 'D', 'M87': 'L', 'M80': 'I'},
    frozenset(['A', 'C', 'D', 'E', 'F', 'H', 'J', 'K']): {'M79': 'H', 'M85': 'J', 'M81': 'E', 'M74': 'C', 'M82': 'A', 'M77': 'F', 'M87': 'D', 'M80': 'K'},
    frozenset(['A', 'C', 'D', 'E', 'F', 'H', 'J', 'L']): {'M79': 'H', 'M85': 'J', 'M81': 'F', 'M74': 'C', 'M82': 'A', 'M77': 'D', 'M87': 'L', 'M80': 'E'},
    frozenset(['A', 'C', 'D', 'E', 'F', 'H', 'K', 'L']): {'M79': 'H', 'M85': 'E', 'M81': 'F', 'M74': 'C', 'M82': 'A', 'M77': 'D', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'C', 'D', 'E', 'F', 'I', 'J', 'K']): {'M79': 'C', 'M85': 'J', 'M81': 'E', 'M74': 'D', 'M82': 'A', 'M77': 'F', 'M87': 'I', 'M80': 'K'},
    frozenset(['A', 'C', 'D', 'E', 'F', 'I', 'J', 'L']): {'M79': 'C', 'M85': 'J', 'M81': 'E', 'M74': 'D', 'M82': 'A', 'M77': 'F', 'M87': 'L', 'M80': 'I'},
    frozenset(['A', 'C', 'D', 'E', 'F', 'I', 'K', 'L']): {'M79': 'C', 'M85': 'E', 'M81': 'I', 'M74': 'D', 'M82': 'A', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'C', 'D', 'E', 'F', 'J', 'K', 'L']): {'M79': 'C', 'M85': 'J', 'M81': 'E', 'M74': 'D', 'M82': 'A', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'C', 'D', 'E', 'G', 'H', 'I', 'J']): {'M79': 'H', 'M85': 'G', 'M81': 'J', 'M74': 'C', 'M82': 'A', 'M77': 'D', 'M87': 'E', 'M80': 'I'},
    frozenset(['A', 'C', 'D', 'E', 'G', 'H', 'I', 'K']): {'M79': 'H', 'M85': 'G', 'M81': 'E', 'M74': 'C', 'M82': 'A', 'M77': 'D', 'M87': 'I', 'M80': 'K'},
    frozenset(['A', 'C', 'D', 'E', 'G', 'H', 'I', 'L']): {'M79': 'H', 'M85': 'G', 'M81': 'E', 'M74': 'C', 'M82': 'A', 'M77': 'D', 'M87': 'L', 'M80': 'I'},
    frozenset(['A', 'C', 'D', 'E', 'G', 'H', 'J', 'K']): {'M79': 'H', 'M85': 'G', 'M81': 'J', 'M74': 'C', 'M82': 'A', 'M77': 'D', 'M87': 'E', 'M80': 'K'},
    frozenset(['A', 'C', 'D', 'E', 'G', 'H', 'J', 'L']): {'M79': 'H', 'M85': 'G', 'M81': 'J', 'M74': 'C', 'M82': 'A', 'M77': 'D', 'M87': 'L', 'M80': 'E'},
    frozenset(['A', 'C', 'D', 'E', 'G', 'H', 'K', 'L']): {'M79': 'H', 'M85': 'G', 'M81': 'E', 'M74': 'C', 'M82': 'A', 'M77': 'D', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'C', 'D', 'E', 'G', 'I', 'J', 'K']): {'M79': 'E', 'M85': 'G', 'M81': 'J', 'M74': 'C', 'M82': 'A', 'M77': 'D', 'M87': 'I', 'M80': 'K'},
    frozenset(['A', 'C', 'D', 'E', 'G', 'I', 'J', 'L']): {'M79': 'E', 'M85': 'G', 'M81': 'J', 'M74': 'C', 'M82': 'A', 'M77': 'D', 'M87': 'L', 'M80': 'I'},
    frozenset(['A', 'C', 'D', 'E', 'G', 'I', 'K', 'L']): {'M79': 'E', 'M85': 'G', 'M81': 'I', 'M74': 'C', 'M82': 'A', 'M77': 'D', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'C', 'D', 'E', 'G', 'J', 'K', 'L']): {'M79': 'E', 'M85': 'G', 'M81': 'J', 'M74': 'C', 'M82': 'A', 'M77': 'D', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'C', 'D', 'E', 'H', 'I', 'J', 'K']): {'M79': 'H', 'M85': 'J', 'M81': 'E', 'M74': 'C', 'M82': 'A', 'M77': 'D', 'M87': 'I', 'M80': 'K'},
    frozenset(['A', 'C', 'D', 'E', 'H', 'I', 'J', 'L']): {'M79': 'H', 'M85': 'J', 'M81': 'E', 'M74': 'C', 'M82': 'A', 'M77': 'D', 'M87': 'L', 'M80': 'I'},
    frozenset(['A', 'C', 'D', 'E', 'H', 'I', 'K', 'L']): {'M79': 'H', 'M85': 'E', 'M81': 'I', 'M74': 'C', 'M82': 'A', 'M77': 'D', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'C', 'D', 'E', 'H', 'J', 'K', 'L']): {'M79': 'H', 'M85': 'J', 'M81': 'E', 'M74': 'C', 'M82': 'A', 'M77': 'D', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'C', 'D', 'E', 'I', 'J', 'K', 'L']): {'M79': 'E', 'M85': 'J', 'M81': 'I', 'M74': 'C', 'M82': 'A', 'M77': 'D', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'C', 'D', 'F', 'G', 'H', 'I', 'J']): {'M79': 'H', 'M85': 'G', 'M81': 'J', 'M74': 'C', 'M82': 'A', 'M77': 'F', 'M87': 'D', 'M80': 'I'},
    frozenset(['A', 'C', 'D', 'F', 'G', 'H', 'I', 'K']): {'M79': 'H', 'M85': 'G', 'M81': 'F', 'M74': 'C', 'M82': 'A', 'M77': 'D', 'M87': 'I', 'M80': 'K'},
    frozenset(['A', 'C', 'D', 'F', 'G', 'H', 'I', 'L']): {'M79': 'H', 'M85': 'G', 'M81': 'F', 'M74': 'C', 'M82': 'A', 'M77': 'D', 'M87': 'L', 'M80': 'I'},
    frozenset(['A', 'C', 'D', 'F', 'G', 'H', 'J', 'K']): {'M79': 'H', 'M85': 'G', 'M81': 'J', 'M74': 'C', 'M82': 'A', 'M77': 'F', 'M87': 'D', 'M80': 'K'},
    frozenset(['A', 'C', 'D', 'F', 'G', 'H', 'J', 'L']): {'M79': 'C', 'M85': 'G', 'M81': 'J', 'M74': 'D', 'M82': 'A', 'M77': 'F', 'M87': 'L', 'M80': 'H'},
    frozenset(['A', 'C', 'D', 'F', 'G', 'H', 'K', 'L']): {'M79': 'H', 'M85': 'G', 'M81': 'F', 'M74': 'C', 'M82': 'A', 'M77': 'D', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'C', 'D', 'F', 'G', 'I', 'J', 'K']): {'M79': 'C', 'M85': 'G', 'M81': 'J', 'M74': 'D', 'M82': 'A', 'M77': 'F', 'M87': 'I', 'M80': 'K'},
    frozenset(['A', 'C', 'D', 'F', 'G', 'I', 'J', 'L']): {'M79': 'C', 'M85': 'G', 'M81': 'J', 'M74': 'D', 'M82': 'A', 'M77': 'F', 'M87': 'L', 'M80': 'I'},
    frozenset(['A', 'C', 'D', 'F', 'G', 'I', 'K', 'L']): {'M79': 'C', 'M85': 'G', 'M81': 'I', 'M74': 'D', 'M82': 'A', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'C', 'D', 'F', 'G', 'J', 'K', 'L']): {'M79': 'C', 'M85': 'G', 'M81': 'J', 'M74': 'D', 'M82': 'A', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'C', 'D', 'F', 'H', 'I', 'J', 'K']): {'M79': 'H', 'M85': 'J', 'M81': 'F', 'M74': 'C', 'M82': 'A', 'M77': 'D', 'M87': 'I', 'M80': 'K'},
    frozenset(['A', 'C', 'D', 'F', 'H', 'I', 'J', 'L']): {'M79': 'H', 'M85': 'J', 'M81': 'F', 'M74': 'C', 'M82': 'A', 'M77': 'D', 'M87': 'L', 'M80': 'I'},
    frozenset(['A', 'C', 'D', 'F', 'H', 'I', 'K', 'L']): {'M79': 'H', 'M85': 'F', 'M81': 'I', 'M74': 'C', 'M82': 'A', 'M77': 'D', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'C', 'D', 'F', 'H', 'J', 'K', 'L']): {'M79': 'H', 'M85': 'J', 'M81': 'F', 'M74': 'C', 'M82': 'A', 'M77': 'D', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'C', 'D', 'F', 'I', 'J', 'K', 'L']): {'M79': 'C', 'M85': 'J', 'M81': 'I', 'M74': 'D', 'M82': 'A', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'C', 'D', 'G', 'H', 'I', 'J', 'K']): {'M79': 'H', 'M85': 'G', 'M81': 'J', 'M74': 'C', 'M82': 'A', 'M77': 'D', 'M87': 'I', 'M80': 'K'},
    frozenset(['A', 'C', 'D', 'G', 'H', 'I', 'J', 'L']): {'M79': 'H', 'M85': 'G', 'M81': 'J', 'M74': 'C', 'M82': 'A', 'M77': 'D', 'M87': 'L', 'M80': 'I'},
    frozenset(['A', 'C', 'D', 'G', 'H', 'I', 'K', 'L']): {'M79': 'H', 'M85': 'G', 'M81': 'I', 'M74': 'C', 'M82': 'A', 'M77': 'D', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'C', 'D', 'G', 'H', 'J', 'K', 'L']): {'M79': 'H', 'M85': 'G', 'M81': 'J', 'M74': 'C', 'M82': 'A', 'M77': 'D', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'C', 'D', 'G', 'I', 'J', 'K', 'L']): {'M79': 'I', 'M85': 'G', 'M81': 'J', 'M74': 'C', 'M82': 'A', 'M77': 'D', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'C', 'D', 'H', 'I', 'J', 'K', 'L']): {'M79': 'H', 'M85': 'J', 'M81': 'I', 'M74': 'C', 'M82': 'A', 'M77': 'D', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'C', 'E', 'F', 'G', 'H', 'I', 'J']): {'M79': 'H', 'M85': 'G', 'M81': 'J', 'M74': 'C', 'M82': 'A', 'M77': 'F', 'M87': 'E', 'M80': 'I'},
    frozenset(['A', 'C', 'E', 'F', 'G', 'H', 'I', 'K']): {'M79': 'H', 'M85': 'G', 'M81': 'E', 'M74': 'C', 'M82': 'A', 'M77': 'F', 'M87': 'I', 'M80': 'K'},
    frozenset(['A', 'C', 'E', 'F', 'G', 'H', 'I', 'L']): {'M79': 'H', 'M85': 'G', 'M81': 'E', 'M74': 'C', 'M82': 'A', 'M77': 'F', 'M87': 'L', 'M80': 'I'},
    frozenset(['A', 'C', 'E', 'F', 'G', 'H', 'J', 'K']): {'M79': 'H', 'M85': 'G', 'M81': 'J', 'M74': 'C', 'M82': 'A', 'M77': 'F', 'M87': 'E', 'M80': 'K'},
    frozenset(['A', 'C', 'E', 'F', 'G', 'H', 'J', 'L']): {'M79': 'H', 'M85': 'G', 'M81': 'J', 'M74': 'C', 'M82': 'A', 'M77': 'F', 'M87': 'L', 'M80': 'E'},
    frozenset(['A', 'C', 'E', 'F', 'G', 'H', 'K', 'L']): {'M79': 'H', 'M85': 'G', 'M81': 'E', 'M74': 'C', 'M82': 'A', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'C', 'E', 'F', 'G', 'I', 'J', 'K']): {'M79': 'E', 'M85': 'G', 'M81': 'J', 'M74': 'C', 'M82': 'A', 'M77': 'F', 'M87': 'I', 'M80': 'K'},
    frozenset(['A', 'C', 'E', 'F', 'G', 'I', 'J', 'L']): {'M79': 'E', 'M85': 'G', 'M81': 'J', 'M74': 'C', 'M82': 'A', 'M77': 'F', 'M87': 'L', 'M80': 'I'},
    frozenset(['A', 'C', 'E', 'F', 'G', 'I', 'K', 'L']): {'M79': 'E', 'M85': 'G', 'M81': 'I', 'M74': 'C', 'M82': 'A', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'C', 'E', 'F', 'G', 'J', 'K', 'L']): {'M79': 'E', 'M85': 'G', 'M81': 'J', 'M74': 'C', 'M82': 'A', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'C', 'E', 'F', 'H', 'I', 'J', 'K']): {'M79': 'H', 'M85': 'J', 'M81': 'E', 'M74': 'C', 'M82': 'A', 'M77': 'F', 'M87': 'I', 'M80': 'K'},
    frozenset(['A', 'C', 'E', 'F', 'H', 'I', 'J', 'L']): {'M79': 'H', 'M85': 'J', 'M81': 'E', 'M74': 'C', 'M82': 'A', 'M77': 'F', 'M87': 'L', 'M80': 'I'},
    frozenset(['A', 'C', 'E', 'F', 'H', 'I', 'K', 'L']): {'M79': 'H', 'M85': 'E', 'M81': 'I', 'M74': 'C', 'M82': 'A', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'C', 'E', 'F', 'H', 'J', 'K', 'L']): {'M79': 'H', 'M85': 'J', 'M81': 'E', 'M74': 'C', 'M82': 'A', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'C', 'E', 'F', 'I', 'J', 'K', 'L']): {'M79': 'E', 'M85': 'J', 'M81': 'I', 'M74': 'C', 'M82': 'A', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'C', 'E', 'G', 'H', 'I', 'J', 'K']): {'M79': 'E', 'M85': 'G', 'M81': 'J', 'M74': 'C', 'M82': 'A', 'M77': 'H', 'M87': 'I', 'M80': 'K'},
    frozenset(['A', 'C', 'E', 'G', 'H', 'I', 'J', 'L']): {'M79': 'E', 'M85': 'G', 'M81': 'J', 'M74': 'C', 'M82': 'A', 'M77': 'H', 'M87': 'L', 'M80': 'I'},
    frozenset(['A', 'C', 'E', 'G', 'H', 'I', 'K', 'L']): {'M79': 'E', 'M85': 'G', 'M81': 'I', 'M74': 'C', 'M82': 'A', 'M77': 'H', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'C', 'E', 'G', 'H', 'J', 'K', 'L']): {'M79': 'E', 'M85': 'G', 'M81': 'J', 'M74': 'C', 'M82': 'A', 'M77': 'H', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'C', 'E', 'G', 'I', 'J', 'K', 'L']): {'M79': 'E', 'M85': 'J', 'M81': 'I', 'M74': 'C', 'M82': 'A', 'M77': 'G', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'C', 'E', 'H', 'I', 'J', 'K', 'L']): {'M79': 'E', 'M85': 'J', 'M81': 'I', 'M74': 'C', 'M82': 'A', 'M77': 'H', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'C', 'F', 'G', 'H', 'I', 'J', 'K']): {'M79': 'H', 'M85': 'G', 'M81': 'J', 'M74': 'C', 'M82': 'A', 'M77': 'F', 'M87': 'I', 'M80': 'K'},
    frozenset(['A', 'C', 'F', 'G', 'H', 'I', 'J', 'L']): {'M79': 'H', 'M85': 'G', 'M81': 'J', 'M74': 'C', 'M82': 'A', 'M77': 'F', 'M87': 'L', 'M80': 'I'},
    frozenset(['A', 'C', 'F', 'G', 'H', 'I', 'K', 'L']): {'M79': 'H', 'M85': 'G', 'M81': 'I', 'M74': 'C', 'M82': 'A', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'C', 'F', 'G', 'H', 'J', 'K', 'L']): {'M79': 'H', 'M85': 'G', 'M81': 'J', 'M74': 'C', 'M82': 'A', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'C', 'F', 'G', 'I', 'J', 'K', 'L']): {'M79': 'I', 'M85': 'G', 'M81': 'J', 'M74': 'C', 'M82': 'A', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'C', 'F', 'H', 'I', 'J', 'K', 'L']): {'M79': 'H', 'M85': 'J', 'M81': 'I', 'M74': 'C', 'M82': 'A', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'C', 'G', 'H', 'I', 'J', 'K', 'L']): {'M79': 'H', 'M85': 'J', 'M81': 'I', 'M74': 'C', 'M82': 'A', 'M77': 'G', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'D', 'E', 'F', 'G', 'H', 'I', 'J']): {'M79': 'H', 'M85': 'G', 'M81': 'J', 'M74': 'D', 'M82': 'A', 'M77': 'F', 'M87': 'E', 'M80': 'I'},
    frozenset(['A', 'D', 'E', 'F', 'G', 'H', 'I', 'K']): {'M79': 'H', 'M85': 'G', 'M81': 'E', 'M74': 'D', 'M82': 'A', 'M77': 'F', 'M87': 'I', 'M80': 'K'},
    frozenset(['A', 'D', 'E', 'F', 'G', 'H', 'I', 'L']): {'M79': 'H', 'M85': 'G', 'M81': 'E', 'M74': 'D', 'M82': 'A', 'M77': 'F', 'M87': 'L', 'M80': 'I'},
    frozenset(['A', 'D', 'E', 'F', 'G', 'H', 'J', 'K']): {'M79': 'H', 'M85': 'G', 'M81': 'J', 'M74': 'D', 'M82': 'A', 'M77': 'F', 'M87': 'E', 'M80': 'K'},
    frozenset(['A', 'D', 'E', 'F', 'G', 'H', 'J', 'L']): {'M79': 'H', 'M85': 'G', 'M81': 'J', 'M74': 'D', 'M82': 'A', 'M77': 'F', 'M87': 'L', 'M80': 'E'},
    frozenset(['A', 'D', 'E', 'F', 'G', 'H', 'K', 'L']): {'M79': 'H', 'M85': 'G', 'M81': 'E', 'M74': 'D', 'M82': 'A', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'D', 'E', 'F', 'G', 'I', 'J', 'K']): {'M79': 'E', 'M85': 'G', 'M81': 'J', 'M74': 'D', 'M82': 'A', 'M77': 'F', 'M87': 'I', 'M80': 'K'},
    frozenset(['A', 'D', 'E', 'F', 'G', 'I', 'J', 'L']): {'M79': 'E', 'M85': 'G', 'M81': 'J', 'M74': 'D', 'M82': 'A', 'M77': 'F', 'M87': 'L', 'M80': 'I'},
    frozenset(['A', 'D', 'E', 'F', 'G', 'I', 'K', 'L']): {'M79': 'E', 'M85': 'G', 'M81': 'I', 'M74': 'D', 'M82': 'A', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'D', 'E', 'F', 'G', 'J', 'K', 'L']): {'M79': 'E', 'M85': 'G', 'M81': 'J', 'M74': 'D', 'M82': 'A', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'D', 'E', 'F', 'H', 'I', 'J', 'K']): {'M79': 'H', 'M85': 'J', 'M81': 'E', 'M74': 'D', 'M82': 'A', 'M77': 'F', 'M87': 'I', 'M80': 'K'},
    frozenset(['A', 'D', 'E', 'F', 'H', 'I', 'J', 'L']): {'M79': 'H', 'M85': 'J', 'M81': 'E', 'M74': 'D', 'M82': 'A', 'M77': 'F', 'M87': 'L', 'M80': 'I'},
    frozenset(['A', 'D', 'E', 'F', 'H', 'I', 'K', 'L']): {'M79': 'H', 'M85': 'E', 'M81': 'I', 'M74': 'D', 'M82': 'A', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'D', 'E', 'F', 'H', 'J', 'K', 'L']): {'M79': 'H', 'M85': 'J', 'M81': 'E', 'M74': 'D', 'M82': 'A', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'D', 'E', 'F', 'I', 'J', 'K', 'L']): {'M79': 'E', 'M85': 'J', 'M81': 'I', 'M74': 'D', 'M82': 'A', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'D', 'E', 'G', 'H', 'I', 'J', 'K']): {'M79': 'E', 'M85': 'G', 'M81': 'J', 'M74': 'D', 'M82': 'A', 'M77': 'H', 'M87': 'I', 'M80': 'K'},
    frozenset(['A', 'D', 'E', 'G', 'H', 'I', 'J', 'L']): {'M79': 'E', 'M85': 'G', 'M81': 'J', 'M74': 'D', 'M82': 'A', 'M77': 'H', 'M87': 'L', 'M80': 'I'},
    frozenset(['A', 'D', 'E', 'G', 'H', 'I', 'K', 'L']): {'M79': 'E', 'M85': 'G', 'M81': 'I', 'M74': 'D', 'M82': 'A', 'M77': 'H', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'D', 'E', 'G', 'H', 'J', 'K', 'L']): {'M79': 'E', 'M85': 'G', 'M81': 'J', 'M74': 'D', 'M82': 'A', 'M77': 'H', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'D', 'E', 'G', 'I', 'J', 'K', 'L']): {'M79': 'E', 'M85': 'J', 'M81': 'I', 'M74': 'D', 'M82': 'A', 'M77': 'G', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'D', 'E', 'H', 'I', 'J', 'K', 'L']): {'M79': 'E', 'M85': 'J', 'M81': 'I', 'M74': 'D', 'M82': 'A', 'M77': 'H', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'D', 'F', 'G', 'H', 'I', 'J', 'K']): {'M79': 'H', 'M85': 'G', 'M81': 'J', 'M74': 'D', 'M82': 'A', 'M77': 'F', 'M87': 'I', 'M80': 'K'},
    frozenset(['A', 'D', 'F', 'G', 'H', 'I', 'J', 'L']): {'M79': 'H', 'M85': 'G', 'M81': 'J', 'M74': 'D', 'M82': 'A', 'M77': 'F', 'M87': 'L', 'M80': 'I'},
    frozenset(['A', 'D', 'F', 'G', 'H', 'I', 'K', 'L']): {'M79': 'H', 'M85': 'G', 'M81': 'I', 'M74': 'D', 'M82': 'A', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'D', 'F', 'G', 'H', 'J', 'K', 'L']): {'M79': 'H', 'M85': 'G', 'M81': 'J', 'M74': 'D', 'M82': 'A', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'D', 'F', 'G', 'I', 'J', 'K', 'L']): {'M79': 'I', 'M85': 'G', 'M81': 'J', 'M74': 'D', 'M82': 'A', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'D', 'F', 'H', 'I', 'J', 'K', 'L']): {'M79': 'H', 'M85': 'J', 'M81': 'I', 'M74': 'D', 'M82': 'A', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'D', 'G', 'H', 'I', 'J', 'K', 'L']): {'M79': 'H', 'M85': 'J', 'M81': 'I', 'M74': 'D', 'M82': 'A', 'M77': 'G', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'E', 'F', 'G', 'H', 'I', 'J', 'K']): {'M79': 'E', 'M85': 'G', 'M81': 'J', 'M74': 'F', 'M82': 'A', 'M77': 'H', 'M87': 'I', 'M80': 'K'},
    frozenset(['A', 'E', 'F', 'G', 'H', 'I', 'J', 'L']): {'M79': 'E', 'M85': 'G', 'M81': 'J', 'M74': 'F', 'M82': 'A', 'M77': 'H', 'M87': 'L', 'M80': 'I'},
    frozenset(['A', 'E', 'F', 'G', 'H', 'I', 'K', 'L']): {'M79': 'E', 'M85': 'G', 'M81': 'I', 'M74': 'F', 'M82': 'A', 'M77': 'H', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'E', 'F', 'G', 'H', 'J', 'K', 'L']): {'M79': 'E', 'M85': 'G', 'M81': 'J', 'M74': 'F', 'M82': 'A', 'M77': 'H', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'E', 'F', 'G', 'I', 'J', 'K', 'L']): {'M79': 'E', 'M85': 'J', 'M81': 'I', 'M74': 'F', 'M82': 'A', 'M77': 'G', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'E', 'F', 'H', 'I', 'J', 'K', 'L']): {'M79': 'E', 'M85': 'J', 'M81': 'I', 'M74': 'F', 'M82': 'A', 'M77': 'H', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'E', 'G', 'H', 'I', 'J', 'K', 'L']): {'M79': 'E', 'M85': 'J', 'M81': 'I', 'M74': 'A', 'M82': 'H', 'M77': 'G', 'M87': 'L', 'M80': 'K'},
    frozenset(['A', 'F', 'G', 'H', 'I', 'J', 'K', 'L']): {'M79': 'H', 'M85': 'J', 'M81': 'I', 'M74': 'F', 'M82': 'A', 'M77': 'G', 'M87': 'L', 'M80': 'K'},
    frozenset(['B', 'C', 'D', 'E', 'F', 'G', 'H', 'I']): {'M79': 'C', 'M85': 'G', 'M81': 'B', 'M74': 'D', 'M82': 'H', 'M77': 'F', 'M87': 'E', 'M80': 'I'},
    frozenset(['B', 'C', 'D', 'E', 'F', 'G', 'H', 'J']): {'M79': 'H', 'M85': 'G', 'M81': 'B', 'M74': 'C', 'M82': 'J', 'M77': 'F', 'M87': 'D', 'M80': 'E'},
    frozenset(['B', 'C', 'D', 'E', 'F', 'G', 'H', 'K']): {'M79': 'C', 'M85': 'G', 'M81': 'B', 'M74': 'D', 'M82': 'H', 'M77': 'F', 'M87': 'E', 'M80': 'K'},
    frozenset(['B', 'C', 'D', 'E', 'F', 'G', 'H', 'L']): {'M79': 'C', 'M85': 'G', 'M81': 'B', 'M74': 'D', 'M82': 'H', 'M77': 'F', 'M87': 'L', 'M80': 'E'},
    frozenset(['B', 'C', 'D', 'E', 'F', 'G', 'I', 'J']): {'M79': 'C', 'M85': 'G', 'M81': 'B', 'M74': 'D', 'M82': 'J', 'M77': 'F', 'M87': 'E', 'M80': 'I'},
    frozenset(['B', 'C', 'D', 'E', 'F', 'G', 'I', 'K']): {'M79': 'C', 'M85': 'G', 'M81': 'B', 'M74': 'D', 'M82': 'E', 'M77': 'F', 'M87': 'I', 'M80': 'K'},
    frozenset(['B', 'C', 'D', 'E', 'F', 'G', 'I', 'L']): {'M79': 'C', 'M85': 'G', 'M81': 'B', 'M74': 'D', 'M82': 'E', 'M77': 'F', 'M87': 'L', 'M80': 'I'},
    frozenset(['B', 'C', 'D', 'E', 'F', 'G', 'J', 'K']): {'M79': 'C', 'M85': 'G', 'M81': 'B', 'M74': 'D', 'M82': 'J', 'M77': 'F', 'M87': 'E', 'M80': 'K'},
    frozenset(['B', 'C', 'D', 'E', 'F', 'G', 'J', 'L']): {'M79': 'C', 'M85': 'G', 'M81': 'B', 'M74': 'D', 'M82': 'J', 'M77': 'F', 'M87': 'L', 'M80': 'E'},
    frozenset(['B', 'C', 'D', 'E', 'F', 'G', 'K', 'L']): {'M79': 'C', 'M85': 'G', 'M81': 'B', 'M74': 'D', 'M82': 'E', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['B', 'C', 'D', 'E', 'F', 'H', 'I', 'J']): {'M79': 'C', 'M85': 'J', 'M81': 'B', 'M74': 'D', 'M82': 'H', 'M77': 'F', 'M87': 'E', 'M80': 'I'},
    frozenset(['B', 'C', 'D', 'E', 'F', 'H', 'I', 'K']): {'M79': 'C', 'M85': 'E', 'M81': 'B', 'M74': 'D', 'M82': 'H', 'M77': 'F', 'M87': 'I', 'M80': 'K'},
    frozenset(['B', 'C', 'D', 'E', 'F', 'H', 'I', 'L']): {'M79': 'C', 'M85': 'E', 'M81': 'B', 'M74': 'D', 'M82': 'H', 'M77': 'F', 'M87': 'L', 'M80': 'I'},
    frozenset(['B', 'C', 'D', 'E', 'F', 'H', 'J', 'K']): {'M79': 'C', 'M85': 'J', 'M81': 'B', 'M74': 'D', 'M82': 'H', 'M77': 'F', 'M87': 'E', 'M80': 'K'},
    frozenset(['B', 'C', 'D', 'E', 'F', 'H', 'J', 'L']): {'M79': 'C', 'M85': 'J', 'M81': 'B', 'M74': 'D', 'M82': 'H', 'M77': 'F', 'M87': 'L', 'M80': 'E'},
    frozenset(['B', 'C', 'D', 'E', 'F', 'H', 'K', 'L']): {'M79': 'C', 'M85': 'E', 'M81': 'B', 'M74': 'D', 'M82': 'H', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['B', 'C', 'D', 'E', 'F', 'I', 'J', 'K']): {'M79': 'C', 'M85': 'J', 'M81': 'B', 'M74': 'D', 'M82': 'E', 'M77': 'F', 'M87': 'I', 'M80': 'K'},
    frozenset(['B', 'C', 'D', 'E', 'F', 'I', 'J', 'L']): {'M79': 'C', 'M85': 'J', 'M81': 'B', 'M74': 'D', 'M82': 'E', 'M77': 'F', 'M87': 'L', 'M80': 'I'},
    frozenset(['B', 'C', 'D', 'E', 'F', 'I', 'K', 'L']): {'M79': 'C', 'M85': 'E', 'M81': 'B', 'M74': 'D', 'M82': 'I', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['B', 'C', 'D', 'E', 'F', 'J', 'K', 'L']): {'M79': 'C', 'M85': 'J', 'M81': 'B', 'M74': 'D', 'M82': 'E', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['B', 'C', 'D', 'E', 'G', 'H', 'I', 'J']): {'M79': 'H', 'M85': 'G', 'M81': 'B', 'M74': 'C', 'M82': 'J', 'M77': 'D', 'M87': 'E', 'M80': 'I'},
    frozenset(['B', 'C', 'D', 'E', 'G', 'H', 'I', 'K']): {'M79': 'E', 'M85': 'G', 'M81': 'B', 'M74': 'C', 'M82': 'H', 'M77': 'D', 'M87': 'I', 'M80': 'K'},
    frozenset(['B', 'C', 'D', 'E', 'G', 'H', 'I', 'L']): {'M79': 'E', 'M85': 'G', 'M81': 'B', 'M74': 'C', 'M82': 'H', 'M77': 'D', 'M87': 'L', 'M80': 'I'},
    frozenset(['B', 'C', 'D', 'E', 'G', 'H', 'J', 'K']): {'M79': 'H', 'M85': 'G', 'M81': 'B', 'M74': 'C', 'M82': 'J', 'M77': 'D', 'M87': 'E', 'M80': 'K'},
    frozenset(['B', 'C', 'D', 'E', 'G', 'H', 'J', 'L']): {'M79': 'H', 'M85': 'G', 'M81': 'B', 'M74': 'C', 'M82': 'J', 'M77': 'D', 'M87': 'L', 'M80': 'E'},
    frozenset(['B', 'C', 'D', 'E', 'G', 'H', 'K', 'L']): {'M79': 'E', 'M85': 'G', 'M81': 'B', 'M74': 'C', 'M82': 'H', 'M77': 'D', 'M87': 'L', 'M80': 'K'},
    frozenset(['B', 'C', 'D', 'E', 'G', 'I', 'J', 'K']): {'M79': 'E', 'M85': 'G', 'M81': 'B', 'M74': 'C', 'M82': 'J', 'M77': 'D', 'M87': 'I', 'M80': 'K'},
    frozenset(['B', 'C', 'D', 'E', 'G', 'I', 'J', 'L']): {'M79': 'E', 'M85': 'G', 'M81': 'B', 'M74': 'C', 'M82': 'J', 'M77': 'D', 'M87': 'L', 'M80': 'I'},
    frozenset(['B', 'C', 'D', 'E', 'G', 'I', 'K', 'L']): {'M79': 'E', 'M85': 'G', 'M81': 'B', 'M74': 'C', 'M82': 'I', 'M77': 'D', 'M87': 'L', 'M80': 'K'},
    frozenset(['B', 'C', 'D', 'E', 'G', 'J', 'K', 'L']): {'M79': 'E', 'M85': 'G', 'M81': 'B', 'M74': 'C', 'M82': 'J', 'M77': 'D', 'M87': 'L', 'M80': 'K'},
    frozenset(['B', 'C', 'D', 'E', 'H', 'I', 'J', 'K']): {'M79': 'E', 'M85': 'J', 'M81': 'B', 'M74': 'C', 'M82': 'H', 'M77': 'D', 'M87': 'I', 'M80': 'K'},
    frozenset(['B', 'C', 'D', 'E', 'H', 'I', 'J', 'L']): {'M79': 'E', 'M85': 'J', 'M81': 'B', 'M74': 'C', 'M82': 'H', 'M77': 'D', 'M87': 'L', 'M80': 'I'},
    frozenset(['B', 'C', 'D', 'E', 'H', 'I', 'K', 'L']): {'M79': 'E', 'M85': 'I', 'M81': 'B', 'M74': 'C', 'M82': 'H', 'M77': 'D', 'M87': 'L', 'M80': 'K'},
    frozenset(['B', 'C', 'D', 'E', 'H', 'J', 'K', 'L']): {'M79': 'E', 'M85': 'J', 'M81': 'B', 'M74': 'C', 'M82': 'H', 'M77': 'D', 'M87': 'L', 'M80': 'K'},
    frozenset(['B', 'C', 'D', 'E', 'I', 'J', 'K', 'L']): {'M79': 'E', 'M85': 'J', 'M81': 'B', 'M74': 'C', 'M82': 'I', 'M77': 'D', 'M87': 'L', 'M80': 'K'},
    frozenset(['B', 'C', 'D', 'F', 'G', 'H', 'I', 'J']): {'M79': 'H', 'M85': 'G', 'M81': 'B', 'M74': 'C', 'M82': 'J', 'M77': 'F', 'M87': 'D', 'M80': 'I'},
    frozenset(['B', 'C', 'D', 'F', 'G', 'H', 'I', 'K']): {'M79': 'C', 'M85': 'G', 'M81': 'B', 'M74': 'D', 'M82': 'H', 'M77': 'F', 'M87': 'I', 'M80': 'K'},
    frozenset(['B', 'C', 'D', 'F', 'G', 'H', 'I', 'L']): {'M79': 'C', 'M85': 'G', 'M81': 'B', 'M74': 'D', 'M82': 'H', 'M77': 'F', 'M87': 'L', 'M80': 'I'},
    frozenset(['B', 'C', 'D', 'F', 'G', 'H', 'J', 'K']): {'M79': 'H', 'M85': 'G', 'M81': 'B', 'M74': 'C', 'M82': 'J', 'M77': 'F', 'M87': 'D', 'M80': 'K'},
    frozenset(['B', 'C', 'D', 'F', 'G', 'H', 'J', 'L']): {'M79': 'C', 'M85': 'G', 'M81': 'B', 'M74': 'D', 'M82': 'H', 'M77': 'F', 'M87': 'L', 'M80': 'J'},
    frozenset(['B', 'C', 'D', 'F', 'G', 'H', 'K', 'L']): {'M79': 'C', 'M85': 'G', 'M81': 'B', 'M74': 'D', 'M82': 'H', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['B', 'C', 'D', 'F', 'G', 'I', 'J', 'K']): {'M79': 'C', 'M85': 'G', 'M81': 'B', 'M74': 'D', 'M82': 'J', 'M77': 'F', 'M87': 'I', 'M80': 'K'},
    frozenset(['B', 'C', 'D', 'F', 'G', 'I', 'J', 'L']): {'M79': 'C', 'M85': 'G', 'M81': 'B', 'M74': 'D', 'M82': 'J', 'M77': 'F', 'M87': 'L', 'M80': 'I'},
    frozenset(['B', 'C', 'D', 'F', 'G', 'I', 'K', 'L']): {'M79': 'C', 'M85': 'G', 'M81': 'B', 'M74': 'D', 'M82': 'I', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['B', 'C', 'D', 'F', 'G', 'J', 'K', 'L']): {'M79': 'C', 'M85': 'G', 'M81': 'B', 'M74': 'D', 'M82': 'J', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['B', 'C', 'D', 'F', 'H', 'I', 'J', 'K']): {'M79': 'C', 'M85': 'J', 'M81': 'B', 'M74': 'D', 'M82': 'H', 'M77': 'F', 'M87': 'I', 'M80': 'K'},
    frozenset(['B', 'C', 'D', 'F', 'H', 'I', 'J', 'L']): {'M79': 'C', 'M85': 'J', 'M81': 'B', 'M74': 'D', 'M82': 'H', 'M77': 'F', 'M87': 'L', 'M80': 'I'},
    frozenset(['B', 'C', 'D', 'F', 'H', 'I', 'K', 'L']): {'M79': 'C', 'M85': 'I', 'M81': 'B', 'M74': 'D', 'M82': 'H', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['B', 'C', 'D', 'F', 'H', 'J', 'K', 'L']): {'M79': 'C', 'M85': 'J', 'M81': 'B', 'M74': 'D', 'M82': 'H', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['B', 'C', 'D', 'F', 'I', 'J', 'K', 'L']): {'M79': 'C', 'M85': 'J', 'M81': 'B', 'M74': 'D', 'M82': 'I', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['B', 'C', 'D', 'G', 'H', 'I', 'J', 'K']): {'M79': 'H', 'M85': 'G', 'M81': 'B', 'M74': 'C', 'M82': 'J', 'M77': 'D', 'M87': 'I', 'M80': 'K'},
    frozenset(['B', 'C', 'D', 'G', 'H', 'I', 'J', 'L']): {'M79': 'H', 'M85': 'G', 'M81': 'B', 'M74': 'C', 'M82': 'J', 'M77': 'D', 'M87': 'L', 'M80': 'I'},
    frozenset(['B', 'C', 'D', 'G', 'H', 'I', 'K', 'L']): {'M79': 'H', 'M85': 'G', 'M81': 'B', 'M74': 'C', 'M82': 'I', 'M77': 'D', 'M87': 'L', 'M80': 'K'},
    frozenset(['B', 'C', 'D', 'G', 'H', 'J', 'K', 'L']): {'M79': 'H', 'M85': 'G', 'M81': 'B', 'M74': 'C', 'M82': 'J', 'M77': 'D', 'M87': 'L', 'M80': 'K'},
    frozenset(['B', 'C', 'D', 'G', 'I', 'J', 'K', 'L']): {'M79': 'I', 'M85': 'G', 'M81': 'B', 'M74': 'C', 'M82': 'J', 'M77': 'D', 'M87': 'L', 'M80': 'K'},
    frozenset(['B', 'C', 'D', 'H', 'I', 'J', 'K', 'L']): {'M79': 'H', 'M85': 'J', 'M81': 'B', 'M74': 'C', 'M82': 'I', 'M77': 'D', 'M87': 'L', 'M80': 'K'},
    frozenset(['B', 'C', 'E', 'F', 'G', 'H', 'I', 'J']): {'M79': 'H', 'M85': 'G', 'M81': 'B', 'M74': 'C', 'M82': 'J', 'M77': 'F', 'M87': 'E', 'M80': 'I'},
    frozenset(['B', 'C', 'E', 'F', 'G', 'H', 'I', 'K']): {'M79': 'E', 'M85': 'G', 'M81': 'B', 'M74': 'C', 'M82': 'H', 'M77': 'F', 'M87': 'I', 'M80': 'K'},
    frozenset(['B', 'C', 'E', 'F', 'G', 'H', 'I', 'L']): {'M79': 'E', 'M85': 'G', 'M81': 'B', 'M74': 'C', 'M82': 'H', 'M77': 'F', 'M87': 'L', 'M80': 'I'},
    frozenset(['B', 'C', 'E', 'F', 'G', 'H', 'J', 'K']): {'M79': 'H', 'M85': 'G', 'M81': 'B', 'M74': 'C', 'M82': 'J', 'M77': 'F', 'M87': 'E', 'M80': 'K'},
    frozenset(['B', 'C', 'E', 'F', 'G', 'H', 'J', 'L']): {'M79': 'H', 'M85': 'G', 'M81': 'B', 'M74': 'C', 'M82': 'J', 'M77': 'F', 'M87': 'L', 'M80': 'E'},
    frozenset(['B', 'C', 'E', 'F', 'G', 'H', 'K', 'L']): {'M79': 'E', 'M85': 'G', 'M81': 'B', 'M74': 'C', 'M82': 'H', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['B', 'C', 'E', 'F', 'G', 'I', 'J', 'K']): {'M79': 'E', 'M85': 'G', 'M81': 'B', 'M74': 'C', 'M82': 'J', 'M77': 'F', 'M87': 'I', 'M80': 'K'},
    frozenset(['B', 'C', 'E', 'F', 'G', 'I', 'J', 'L']): {'M79': 'E', 'M85': 'G', 'M81': 'B', 'M74': 'C', 'M82': 'J', 'M77': 'F', 'M87': 'L', 'M80': 'I'},
    frozenset(['B', 'C', 'E', 'F', 'G', 'I', 'K', 'L']): {'M79': 'E', 'M85': 'G', 'M81': 'B', 'M74': 'C', 'M82': 'I', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['B', 'C', 'E', 'F', 'G', 'J', 'K', 'L']): {'M79': 'E', 'M85': 'G', 'M81': 'B', 'M74': 'C', 'M82': 'J', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['B', 'C', 'E', 'F', 'H', 'I', 'J', 'K']): {'M79': 'E', 'M85': 'J', 'M81': 'B', 'M74': 'C', 'M82': 'H', 'M77': 'F', 'M87': 'I', 'M80': 'K'},
    frozenset(['B', 'C', 'E', 'F', 'H', 'I', 'J', 'L']): {'M79': 'E', 'M85': 'J', 'M81': 'B', 'M74': 'C', 'M82': 'H', 'M77': 'F', 'M87': 'L', 'M80': 'I'},
    frozenset(['B', 'C', 'E', 'F', 'H', 'I', 'K', 'L']): {'M79': 'E', 'M85': 'I', 'M81': 'B', 'M74': 'C', 'M82': 'H', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['B', 'C', 'E', 'F', 'H', 'J', 'K', 'L']): {'M79': 'E', 'M85': 'J', 'M81': 'B', 'M74': 'C', 'M82': 'H', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['B', 'C', 'E', 'F', 'I', 'J', 'K', 'L']): {'M79': 'E', 'M85': 'J', 'M81': 'B', 'M74': 'C', 'M82': 'I', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['B', 'C', 'E', 'G', 'H', 'I', 'J', 'K']): {'M79': 'E', 'M85': 'J', 'M81': 'B', 'M74': 'C', 'M82': 'H', 'M77': 'G', 'M87': 'I', 'M80': 'K'},
    frozenset(['B', 'C', 'E', 'G', 'H', 'I', 'J', 'L']): {'M79': 'E', 'M85': 'J', 'M81': 'B', 'M74': 'C', 'M82': 'H', 'M77': 'G', 'M87': 'L', 'M80': 'I'},
    frozenset(['B', 'C', 'E', 'G', 'H', 'I', 'K', 'L']): {'M79': 'E', 'M85': 'G', 'M81': 'B', 'M74': 'C', 'M82': 'I', 'M77': 'H', 'M87': 'L', 'M80': 'K'},
    frozenset(['B', 'C', 'E', 'G', 'H', 'J', 'K', 'L']): {'M79': 'E', 'M85': 'J', 'M81': 'B', 'M74': 'C', 'M82': 'H', 'M77': 'G', 'M87': 'L', 'M80': 'K'},
    frozenset(['B', 'C', 'E', 'G', 'I', 'J', 'K', 'L']): {'M79': 'E', 'M85': 'J', 'M81': 'B', 'M74': 'C', 'M82': 'I', 'M77': 'G', 'M87': 'L', 'M80': 'K'},
    frozenset(['B', 'C', 'E', 'H', 'I', 'J', 'K', 'L']): {'M79': 'E', 'M85': 'J', 'M81': 'B', 'M74': 'C', 'M82': 'I', 'M77': 'H', 'M87': 'L', 'M80': 'K'},
    frozenset(['B', 'C', 'F', 'G', 'H', 'I', 'J', 'K']): {'M79': 'H', 'M85': 'G', 'M81': 'B', 'M74': 'C', 'M82': 'J', 'M77': 'F', 'M87': 'I', 'M80': 'K'},
    frozenset(['B', 'C', 'F', 'G', 'H', 'I', 'J', 'L']): {'M79': 'H', 'M85': 'G', 'M81': 'B', 'M74': 'C', 'M82': 'J', 'M77': 'F', 'M87': 'L', 'M80': 'I'},
    frozenset(['B', 'C', 'F', 'G', 'H', 'I', 'K', 'L']): {'M79': 'H', 'M85': 'G', 'M81': 'B', 'M74': 'C', 'M82': 'I', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['B', 'C', 'F', 'G', 'H', 'J', 'K', 'L']): {'M79': 'H', 'M85': 'G', 'M81': 'B', 'M74': 'C', 'M82': 'J', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['B', 'C', 'F', 'G', 'I', 'J', 'K', 'L']): {'M79': 'I', 'M85': 'G', 'M81': 'B', 'M74': 'C', 'M82': 'J', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['B', 'C', 'F', 'H', 'I', 'J', 'K', 'L']): {'M79': 'H', 'M85': 'J', 'M81': 'B', 'M74': 'C', 'M82': 'I', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['B', 'C', 'G', 'H', 'I', 'J', 'K', 'L']): {'M79': 'H', 'M85': 'J', 'M81': 'B', 'M74': 'C', 'M82': 'I', 'M77': 'G', 'M87': 'L', 'M80': 'K'},
    frozenset(['B', 'D', 'E', 'F', 'G', 'H', 'I', 'J']): {'M79': 'H', 'M85': 'G', 'M81': 'B', 'M74': 'D', 'M82': 'J', 'M77': 'F', 'M87': 'E', 'M80': 'I'},
    frozenset(['B', 'D', 'E', 'F', 'G', 'H', 'I', 'K']): {'M79': 'E', 'M85': 'G', 'M81': 'B', 'M74': 'D', 'M82': 'H', 'M77': 'F', 'M87': 'I', 'M80': 'K'},
    frozenset(['B', 'D', 'E', 'F', 'G', 'H', 'I', 'L']): {'M79': 'E', 'M85': 'G', 'M81': 'B', 'M74': 'D', 'M82': 'H', 'M77': 'F', 'M87': 'L', 'M80': 'I'},
    frozenset(['B', 'D', 'E', 'F', 'G', 'H', 'J', 'K']): {'M79': 'H', 'M85': 'G', 'M81': 'B', 'M74': 'D', 'M82': 'J', 'M77': 'F', 'M87': 'E', 'M80': 'K'},
    frozenset(['B', 'D', 'E', 'F', 'G', 'H', 'J', 'L']): {'M79': 'H', 'M85': 'G', 'M81': 'B', 'M74': 'D', 'M82': 'J', 'M77': 'F', 'M87': 'L', 'M80': 'E'},
    frozenset(['B', 'D', 'E', 'F', 'G', 'H', 'K', 'L']): {'M79': 'E', 'M85': 'G', 'M81': 'B', 'M74': 'D', 'M82': 'H', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['B', 'D', 'E', 'F', 'G', 'I', 'J', 'K']): {'M79': 'E', 'M85': 'G', 'M81': 'B', 'M74': 'D', 'M82': 'J', 'M77': 'F', 'M87': 'I', 'M80': 'K'},
    frozenset(['B', 'D', 'E', 'F', 'G', 'I', 'J', 'L']): {'M79': 'E', 'M85': 'G', 'M81': 'B', 'M74': 'D', 'M82': 'J', 'M77': 'F', 'M87': 'L', 'M80': 'I'},
    frozenset(['B', 'D', 'E', 'F', 'G', 'I', 'K', 'L']): {'M79': 'E', 'M85': 'G', 'M81': 'B', 'M74': 'D', 'M82': 'I', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['B', 'D', 'E', 'F', 'G', 'J', 'K', 'L']): {'M79': 'E', 'M85': 'G', 'M81': 'B', 'M74': 'D', 'M82': 'J', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['B', 'D', 'E', 'F', 'H', 'I', 'J', 'K']): {'M79': 'E', 'M85': 'J', 'M81': 'B', 'M74': 'D', 'M82': 'H', 'M77': 'F', 'M87': 'I', 'M80': 'K'},
    frozenset(['B', 'D', 'E', 'F', 'H', 'I', 'J', 'L']): {'M79': 'E', 'M85': 'J', 'M81': 'B', 'M74': 'D', 'M82': 'H', 'M77': 'F', 'M87': 'L', 'M80': 'I'},
    frozenset(['B', 'D', 'E', 'F', 'H', 'I', 'K', 'L']): {'M79': 'E', 'M85': 'I', 'M81': 'B', 'M74': 'D', 'M82': 'H', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['B', 'D', 'E', 'F', 'H', 'J', 'K', 'L']): {'M79': 'E', 'M85': 'J', 'M81': 'B', 'M74': 'D', 'M82': 'H', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['B', 'D', 'E', 'F', 'I', 'J', 'K', 'L']): {'M79': 'E', 'M85': 'J', 'M81': 'B', 'M74': 'D', 'M82': 'I', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['B', 'D', 'E', 'G', 'H', 'I', 'J', 'K']): {'M79': 'E', 'M85': 'J', 'M81': 'B', 'M74': 'D', 'M82': 'H', 'M77': 'G', 'M87': 'I', 'M80': 'K'},
    frozenset(['B', 'D', 'E', 'G', 'H', 'I', 'J', 'L']): {'M79': 'E', 'M85': 'J', 'M81': 'B', 'M74': 'D', 'M82': 'H', 'M77': 'G', 'M87': 'L', 'M80': 'I'},
    frozenset(['B', 'D', 'E', 'G', 'H', 'I', 'K', 'L']): {'M79': 'E', 'M85': 'G', 'M81': 'B', 'M74': 'D', 'M82': 'I', 'M77': 'H', 'M87': 'L', 'M80': 'K'},
    frozenset(['B', 'D', 'E', 'G', 'H', 'J', 'K', 'L']): {'M79': 'E', 'M85': 'J', 'M81': 'B', 'M74': 'D', 'M82': 'H', 'M77': 'G', 'M87': 'L', 'M80': 'K'},
    frozenset(['B', 'D', 'E', 'G', 'I', 'J', 'K', 'L']): {'M79': 'E', 'M85': 'J', 'M81': 'B', 'M74': 'D', 'M82': 'I', 'M77': 'G', 'M87': 'L', 'M80': 'K'},
    frozenset(['B', 'D', 'E', 'H', 'I', 'J', 'K', 'L']): {'M79': 'E', 'M85': 'J', 'M81': 'B', 'M74': 'D', 'M82': 'I', 'M77': 'H', 'M87': 'L', 'M80': 'K'},
    frozenset(['B', 'D', 'F', 'G', 'H', 'I', 'J', 'K']): {'M79': 'H', 'M85': 'G', 'M81': 'B', 'M74': 'D', 'M82': 'J', 'M77': 'F', 'M87': 'I', 'M80': 'K'},
    frozenset(['B', 'D', 'F', 'G', 'H', 'I', 'J', 'L']): {'M79': 'H', 'M85': 'G', 'M81': 'B', 'M74': 'D', 'M82': 'J', 'M77': 'F', 'M87': 'L', 'M80': 'I'},
    frozenset(['B', 'D', 'F', 'G', 'H', 'I', 'K', 'L']): {'M79': 'H', 'M85': 'G', 'M81': 'B', 'M74': 'D', 'M82': 'I', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['B', 'D', 'F', 'G', 'H', 'J', 'K', 'L']): {'M79': 'H', 'M85': 'G', 'M81': 'B', 'M74': 'D', 'M82': 'J', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['B', 'D', 'F', 'G', 'I', 'J', 'K', 'L']): {'M79': 'I', 'M85': 'G', 'M81': 'B', 'M74': 'D', 'M82': 'J', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['B', 'D', 'F', 'H', 'I', 'J', 'K', 'L']): {'M79': 'H', 'M85': 'J', 'M81': 'B', 'M74': 'D', 'M82': 'I', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['B', 'D', 'G', 'H', 'I', 'J', 'K', 'L']): {'M79': 'H', 'M85': 'J', 'M81': 'B', 'M74': 'D', 'M82': 'I', 'M77': 'G', 'M87': 'L', 'M80': 'K'},
    frozenset(['B', 'E', 'F', 'G', 'H', 'I', 'J', 'K']): {'M79': 'E', 'M85': 'J', 'M81': 'B', 'M74': 'F', 'M82': 'H', 'M77': 'G', 'M87': 'I', 'M80': 'K'},
    frozenset(['B', 'E', 'F', 'G', 'H', 'I', 'J', 'L']): {'M79': 'E', 'M85': 'J', 'M81': 'B', 'M74': 'F', 'M82': 'H', 'M77': 'G', 'M87': 'L', 'M80': 'I'},
    frozenset(['B', 'E', 'F', 'G', 'H', 'I', 'K', 'L']): {'M79': 'E', 'M85': 'G', 'M81': 'B', 'M74': 'F', 'M82': 'I', 'M77': 'H', 'M87': 'L', 'M80': 'K'},
    frozenset(['B', 'E', 'F', 'G', 'H', 'J', 'K', 'L']): {'M79': 'E', 'M85': 'J', 'M81': 'B', 'M74': 'F', 'M82': 'H', 'M77': 'G', 'M87': 'L', 'M80': 'K'},
    frozenset(['B', 'E', 'F', 'G', 'I', 'J', 'K', 'L']): {'M79': 'E', 'M85': 'J', 'M81': 'B', 'M74': 'F', 'M82': 'I', 'M77': 'G', 'M87': 'L', 'M80': 'K'},
    frozenset(['B', 'E', 'F', 'H', 'I', 'J', 'K', 'L']): {'M79': 'E', 'M85': 'J', 'M81': 'B', 'M74': 'F', 'M82': 'I', 'M77': 'H', 'M87': 'L', 'M80': 'K'},
    frozenset(['B', 'E', 'G', 'H', 'I', 'J', 'K', 'L']): {'M79': 'E', 'M85': 'J', 'M81': 'I', 'M74': 'B', 'M82': 'H', 'M77': 'G', 'M87': 'L', 'M80': 'K'},
    frozenset(['B', 'F', 'G', 'H', 'I', 'J', 'K', 'L']): {'M79': 'H', 'M85': 'J', 'M81': 'B', 'M74': 'F', 'M82': 'I', 'M77': 'G', 'M87': 'L', 'M80': 'K'},
    frozenset(['C', 'D', 'E', 'F', 'G', 'H', 'I', 'J']): {'M79': 'C', 'M85': 'G', 'M81': 'J', 'M74': 'D', 'M82': 'H', 'M77': 'F', 'M87': 'E', 'M80': 'I'},
    frozenset(['C', 'D', 'E', 'F', 'G', 'H', 'I', 'K']): {'M79': 'C', 'M85': 'G', 'M81': 'E', 'M74': 'D', 'M82': 'H', 'M77': 'F', 'M87': 'I', 'M80': 'K'},
    frozenset(['C', 'D', 'E', 'F', 'G', 'H', 'I', 'L']): {'M79': 'C', 'M85': 'G', 'M81': 'E', 'M74': 'D', 'M82': 'H', 'M77': 'F', 'M87': 'L', 'M80': 'I'},
    frozenset(['C', 'D', 'E', 'F', 'G', 'H', 'J', 'K']): {'M79': 'C', 'M85': 'G', 'M81': 'J', 'M74': 'D', 'M82': 'H', 'M77': 'F', 'M87': 'E', 'M80': 'K'},
    frozenset(['C', 'D', 'E', 'F', 'G', 'H', 'J', 'L']): {'M79': 'C', 'M85': 'G', 'M81': 'J', 'M74': 'D', 'M82': 'H', 'M77': 'F', 'M87': 'L', 'M80': 'E'},
    frozenset(['C', 'D', 'E', 'F', 'G', 'H', 'K', 'L']): {'M79': 'C', 'M85': 'G', 'M81': 'E', 'M74': 'D', 'M82': 'H', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['C', 'D', 'E', 'F', 'G', 'I', 'J', 'K']): {'M79': 'C', 'M85': 'G', 'M81': 'E', 'M74': 'D', 'M82': 'J', 'M77': 'F', 'M87': 'I', 'M80': 'K'},
    frozenset(['C', 'D', 'E', 'F', 'G', 'I', 'J', 'L']): {'M79': 'C', 'M85': 'G', 'M81': 'E', 'M74': 'D', 'M82': 'J', 'M77': 'F', 'M87': 'L', 'M80': 'I'},
    frozenset(['C', 'D', 'E', 'F', 'G', 'I', 'K', 'L']): {'M79': 'C', 'M85': 'G', 'M81': 'E', 'M74': 'D', 'M82': 'I', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['C', 'D', 'E', 'F', 'G', 'J', 'K', 'L']): {'M79': 'C', 'M85': 'G', 'M81': 'E', 'M74': 'D', 'M82': 'J', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['C', 'D', 'E', 'F', 'H', 'I', 'J', 'K']): {'M79': 'C', 'M85': 'J', 'M81': 'E', 'M74': 'D', 'M82': 'H', 'M77': 'F', 'M87': 'I', 'M80': 'K'},
    frozenset(['C', 'D', 'E', 'F', 'H', 'I', 'J', 'L']): {'M79': 'C', 'M85': 'J', 'M81': 'E', 'M74': 'D', 'M82': 'H', 'M77': 'F', 'M87': 'L', 'M80': 'I'},
    frozenset(['C', 'D', 'E', 'F', 'H', 'I', 'K', 'L']): {'M79': 'C', 'M85': 'E', 'M81': 'I', 'M74': 'D', 'M82': 'H', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['C', 'D', 'E', 'F', 'H', 'J', 'K', 'L']): {'M79': 'C', 'M85': 'J', 'M81': 'E', 'M74': 'D', 'M82': 'H', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['C', 'D', 'E', 'F', 'I', 'J', 'K', 'L']): {'M79': 'C', 'M85': 'J', 'M81': 'E', 'M74': 'D', 'M82': 'I', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['C', 'D', 'E', 'G', 'H', 'I', 'J', 'K']): {'M79': 'E', 'M85': 'G', 'M81': 'J', 'M74': 'C', 'M82': 'H', 'M77': 'D', 'M87': 'I', 'M80': 'K'},
    frozenset(['C', 'D', 'E', 'G', 'H', 'I', 'J', 'L']): {'M79': 'E', 'M85': 'G', 'M81': 'J', 'M74': 'C', 'M82': 'H', 'M77': 'D', 'M87': 'L', 'M80': 'I'},
    frozenset(['C', 'D', 'E', 'G', 'H', 'I', 'K', 'L']): {'M79': 'E', 'M85': 'G', 'M81': 'I', 'M74': 'C', 'M82': 'H', 'M77': 'D', 'M87': 'L', 'M80': 'K'},
    frozenset(['C', 'D', 'E', 'G', 'H', 'J', 'K', 'L']): {'M79': 'E', 'M85': 'G', 'M81': 'J', 'M74': 'C', 'M82': 'H', 'M77': 'D', 'M87': 'L', 'M80': 'K'},
    frozenset(['C', 'D', 'E', 'G', 'I', 'J', 'K', 'L']): {'M79': 'E', 'M85': 'G', 'M81': 'I', 'M74': 'C', 'M82': 'J', 'M77': 'D', 'M87': 'L', 'M80': 'K'},
    frozenset(['C', 'D', 'E', 'H', 'I', 'J', 'K', 'L']): {'M79': 'E', 'M85': 'J', 'M81': 'I', 'M74': 'C', 'M82': 'H', 'M77': 'D', 'M87': 'L', 'M80': 'K'},
    frozenset(['C', 'D', 'F', 'G', 'H', 'I', 'J', 'K']): {'M79': 'C', 'M85': 'G', 'M81': 'J', 'M74': 'D', 'M82': 'H', 'M77': 'F', 'M87': 'I', 'M80': 'K'},
    frozenset(['C', 'D', 'F', 'G', 'H', 'I', 'J', 'L']): {'M79': 'C', 'M85': 'G', 'M81': 'J', 'M74': 'D', 'M82': 'H', 'M77': 'F', 'M87': 'L', 'M80': 'I'},
    frozenset(['C', 'D', 'F', 'G', 'H', 'I', 'K', 'L']): {'M79': 'C', 'M85': 'G', 'M81': 'I', 'M74': 'D', 'M82': 'H', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['C', 'D', 'F', 'G', 'H', 'J', 'K', 'L']): {'M79': 'C', 'M85': 'G', 'M81': 'J', 'M74': 'D', 'M82': 'H', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['C', 'D', 'F', 'G', 'I', 'J', 'K', 'L']): {'M79': 'C', 'M85': 'G', 'M81': 'I', 'M74': 'D', 'M82': 'J', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['C', 'D', 'F', 'H', 'I', 'J', 'K', 'L']): {'M79': 'C', 'M85': 'J', 'M81': 'I', 'M74': 'D', 'M82': 'H', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['C', 'D', 'G', 'H', 'I', 'J', 'K', 'L']): {'M79': 'H', 'M85': 'G', 'M81': 'I', 'M74': 'C', 'M82': 'J', 'M77': 'D', 'M87': 'L', 'M80': 'K'},
    frozenset(['C', 'E', 'F', 'G', 'H', 'I', 'J', 'K']): {'M79': 'E', 'M85': 'G', 'M81': 'J', 'M74': 'C', 'M82': 'H', 'M77': 'F', 'M87': 'I', 'M80': 'K'},
    frozenset(['C', 'E', 'F', 'G', 'H', 'I', 'J', 'L']): {'M79': 'E', 'M85': 'G', 'M81': 'J', 'M74': 'C', 'M82': 'H', 'M77': 'F', 'M87': 'L', 'M80': 'I'},
    frozenset(['C', 'E', 'F', 'G', 'H', 'I', 'K', 'L']): {'M79': 'E', 'M85': 'G', 'M81': 'I', 'M74': 'C', 'M82': 'H', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['C', 'E', 'F', 'G', 'H', 'J', 'K', 'L']): {'M79': 'E', 'M85': 'G', 'M81': 'J', 'M74': 'C', 'M82': 'H', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['C', 'E', 'F', 'G', 'I', 'J', 'K', 'L']): {'M79': 'E', 'M85': 'G', 'M81': 'I', 'M74': 'C', 'M82': 'J', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['C', 'E', 'F', 'H', 'I', 'J', 'K', 'L']): {'M79': 'E', 'M85': 'J', 'M81': 'I', 'M74': 'C', 'M82': 'H', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['C', 'E', 'G', 'H', 'I', 'J', 'K', 'L']): {'M79': 'E', 'M85': 'J', 'M81': 'I', 'M74': 'C', 'M82': 'H', 'M77': 'G', 'M87': 'L', 'M80': 'K'},
    frozenset(['C', 'F', 'G', 'H', 'I', 'J', 'K', 'L']): {'M79': 'H', 'M85': 'G', 'M81': 'I', 'M74': 'C', 'M82': 'J', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['D', 'E', 'F', 'G', 'H', 'I', 'J', 'K']): {'M79': 'E', 'M85': 'G', 'M81': 'J', 'M74': 'D', 'M82': 'H', 'M77': 'F', 'M87': 'I', 'M80': 'K'},
    frozenset(['D', 'E', 'F', 'G', 'H', 'I', 'J', 'L']): {'M79': 'E', 'M85': 'G', 'M81': 'J', 'M74': 'D', 'M82': 'H', 'M77': 'F', 'M87': 'L', 'M80': 'I'},
    frozenset(['D', 'E', 'F', 'G', 'H', 'I', 'K', 'L']): {'M79': 'E', 'M85': 'G', 'M81': 'I', 'M74': 'D', 'M82': 'H', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['D', 'E', 'F', 'G', 'H', 'J', 'K', 'L']): {'M79': 'E', 'M85': 'G', 'M81': 'J', 'M74': 'D', 'M82': 'H', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['D', 'E', 'F', 'G', 'I', 'J', 'K', 'L']): {'M79': 'E', 'M85': 'G', 'M81': 'I', 'M74': 'D', 'M82': 'J', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['D', 'E', 'F', 'H', 'I', 'J', 'K', 'L']): {'M79': 'E', 'M85': 'J', 'M81': 'I', 'M74': 'D', 'M82': 'H', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['D', 'E', 'G', 'H', 'I', 'J', 'K', 'L']): {'M79': 'E', 'M85': 'J', 'M81': 'I', 'M74': 'D', 'M82': 'H', 'M77': 'G', 'M87': 'L', 'M80': 'K'},
    frozenset(['D', 'F', 'G', 'H', 'I', 'J', 'K', 'L']): {'M79': 'H', 'M85': 'G', 'M81': 'I', 'M74': 'D', 'M82': 'J', 'M77': 'F', 'M87': 'L', 'M80': 'K'},
    frozenset(['E', 'F', 'G', 'H', 'I', 'J', 'K', 'L']): {'M79': 'E', 'M85': 'J', 'M81': 'I', 'M74': 'F', 'M82': 'H', 'M77': 'G', 'M87': 'L', 'M80': 'K'},
}


def _precompute_match_cache(db_path: str = DB_PATH) -> dict:
    """Precompute Poisson predictions for every ordered WC2026 team pair (48×47=2256).
    Uses np.outer for vectorised PMF — ~100x faster than the scalar score_matrix loop.
    Returns {(ta, tb): (p_a_win, p_draw, p_b_win, mu_a, mu_b)}.
    """
    ratings, _, intercept = _load_ratings(db_path)
    baseline = math.exp(intercept)
    teams = sorted(WC2026_TEAMS & set(ratings.keys()))
    k = np.arange(11)
    rho = DIXON_COLES_RHO
    cache: dict = {}
    for ta in teams:
        ar_a, dr_a = ratings[ta]
        for tb in teams:
            if ta == tb:
                continue
            ar_b, dr_b = ratings[tb]
            mu_a = ar_a * dr_b / baseline
            mu_b = ar_b * dr_a / baseline
            pa = poisson.pmf(k, mu_a)
            pb = poisson.pmf(k, mu_b)
            mat = np.outer(pa, pb)
            # Inlined Dixon-Coles correction for performance (avoids function call overhead
            # in the hot simulation loop). Must be kept in sync with dixon_coles_correction()
            # above if DIXON_COLES_RHO or the correction formula ever changes.
            mat[0, 0] *= (1 - mu_a * mu_b * rho)
            mat[1, 0] *= (1 + mu_b * rho)
            mat[0, 1] *= (1 + mu_a * rho)
            mat[1, 1] *= (1 - rho)
            mat /= mat.sum()
            a_win = float(np.tril(mat, -1).sum())
            draw  = float(np.trace(mat))
            b_win = float(np.triu(mat, 1).sum())
            cache[(ta, tb)] = (a_win, draw, b_win, mu_a, mu_b)
    return cache


def _sim_group(teams: list, matchups: list, cache: dict, fixed_results=None) -> list:
    """Simulate one group. Returns [(team, pts, gd), ...] best-to-worst.

    Tiebreaker order (FIFA 2026): H2H pts → H2H GD → H2H GF →
    overall GD → overall GF → random.
    """
    pts:  dict = {t: 0 for t in teams}
    gd:   dict = {t: 0 for t in teams}
    gf:   dict = {t: 0 for t in teams}
    game_results: dict = {}  # (ta, tb) -> (goals_ta, goals_tb)

    for ta, tb in matchups:
        if fixed_results and (ta, tb) in fixed_results:
            fr = fixed_results[(ta, tb)]
            if isinstance(fr, tuple):
                ga, gb = int(fr[0]), int(fr[1])
            else:
                _, _, _, mu_a, mu_b = cache[(ta, tb)]
                while True:
                    ga = int(np.random.poisson(mu_a))
                    gb = int(np.random.poisson(mu_b))
                    if fr == 'home_win' and ga > gb:
                        break
                    if fr == 'draw' and ga == gb:
                        break
                    if fr == 'away_win' and gb > ga:
                        break
        else:
            _, _, _, mu_a, mu_b = cache[(ta, tb)]
            ga = int(np.random.poisson(mu_a))
            gb = int(np.random.poisson(mu_b))

        game_results[(ta, tb)] = (ga, gb)
        d = ga - gb
        gd[ta] += d
        gd[tb] -= d
        gf[ta] += ga
        gf[tb] += gb
        if ga > gb:
            pts[ta] += 3
        elif gb > ga:
            pts[tb] += 3
        else:
            pts[ta] += 1
            pts[tb] += 1

    rand_tb = {t: np.random.random() for t in teams}

    def h2h_stats(team, tied_set):
        h_pts = h_gd = h_gf = 0
        for opp in tied_set:
            if opp == team:
                continue
            if (team, opp) in game_results:
                ga, gb = game_results[(team, opp)]
            else:
                gb, ga = game_results[(opp, team)]
            h_gf += ga
            h_gd += ga - gb
            if ga > gb:
                h_pts += 3
            elif ga == gb:
                h_pts += 1
        return h_pts, h_gd, h_gf

    by_pts: dict = {}
    for t in teams:
        by_pts.setdefault(pts[t], []).append(t)

    ranked = []
    for p in sorted(by_pts.keys(), reverse=True):
        tied = by_pts[p]
        if len(tied) == 1:
            ranked.extend(tied)
        else:
            tied_set = set(tied)
            ranked.extend(sorted(
                tied,
                key=lambda t, ts=tied_set: (
                    *(-x for x in h2h_stats(t, ts)),
                    -gd[t], -gf[t], rand_tb[t]
                ),
            ))

    return [(t, pts[t], gd[t]) for t in ranked]


def _sim_ko(ta: str, tb: str, cache: dict) -> str:
    """Simulate one knockout match; draw → 50/50 penalties."""
    a_win, draw, _, _, _ = cache[(ta, tb)]
    return ta if np.random.random() < a_win + draw * 0.5 else tb


# R32 bracket is built inline in run_full_tournament_simulation().


def run_full_tournament_simulation(n: int = 10000, db_path: str = DB_PATH,
                                    fixed_result=None, _cache=None,
                                    _save_to_db: bool = True, _verbose: bool = True,
                                    advancement_only: bool = False) -> dict:
    """Monte Carlo simulation of the full FIFA 2026 World Cup (n iterations).

    Group stage: 12 groups × 6 games.  Best-8 third-place advance using ANNEX_C.
    Knockout: R32 (16 matches) → R16 (8) → QF (4) → SF (2) → Final (1).
    Stage column semantics:
      p_group_advance = P(qualified for knockout stage)
      p_r16           = P(advanced through R32, in R16)
      p_qf            = P(advanced through R16, in QF)
      p_sf            = P(advanced through QF, in SF)
      p_final         = P(advanced through SF, in Final)
      p_champion      = P(won the Final)
    """
    t0 = time.time()

    if _verbose:
        print("Phase 3 — Full Tournament Monte Carlo (official FIFA 2026 bracket)")

    if _cache is not None:
        cache = _cache
    else:
        if _verbose:
            print("  Precomputing all WC2026 match predictions...")
        cache = _precompute_match_cache(db_path)
        if _verbose:
            print(f"  {len(cache)} ordered matchup predictions cached in {time.time() - t0:.1f}s")

    # Auto-load completed WC2026 results when no fixed_result is provided
    if fixed_result is None:
        _combo_order: dict = {
            frozenset({ta, tb}): (ta, tb)
            for grp, teams in WC2026_GROUPS.items()
            for ta, tb in _combinations(teams, 2)
        }
        _fixed: dict = {}
        for _m in _load_completed_wc2026_matches():
            _canonical = _combo_order.get(frozenset({_m["home"], _m["away"]}))
            if _canonical:
                _ta, _tb = _canonical
                _fixed[_canonical] = (
                    (_m["home_score"], _m["away_score"]) if _ta == _m["home"]
                    else (_m["away_score"], _m["home_score"])
                )
        if _fixed:
            fixed_result = _fixed
            if _verbose:
                print(f"  {len(_fixed)} completed WC2026 games fixed at actual scorelines.")

    grp_matchups = {
        grp: list(_combinations(teams, 2))
        for grp, teams in WC2026_GROUPS.items()
    }

    # counts[team] = [group_adv, r32_win, r16_win, qf_win, sf_win, champion]
    counts: dict = {t: [0, 0, 0, 0, 0, 0] for t in WC2026_TEAMS}

    if _verbose:
        print(f"  Running {n:,} simulations...")
    t_sim_start = time.time()
    for _ in range(n):
        # ── Group stage ───────────────────────────────────────────────────────
        w_map: dict = {}
        r_map: dict = {}
        all_thirds: list = []   # (pts, gd, rand, grp, team)

        for grp, teams in WC2026_GROUPS.items():
            st = _sim_group(teams, grp_matchups[grp], cache, fixed_results=fixed_result)
            w_map[grp] = st[0][0]
            r_map[grp] = st[1][0]
            all_thirds.append((st[2][1], st[2][2], float(np.random.random()), grp, st[2][0]))

        # Best 8 third-place by pts → gd → random
        all_thirds.sort(key=lambda x: (x[0], x[1], x[2]), reverse=True)
        best8 = all_thirds[:8]  # (pts, gd, rand, grp, team)
        third_teams = {x[3]: x[4] for x in best8}  # {group: team}

        # Mark all 32 qualifiers
        for t in list(w_map.values()) + list(r_map.values()) + [x[4] for x in best8]:
            counts[t][0] += 1

        if advancement_only:
            continue

        # ── Build R32 bracket via Annex C ─────────────────────────────────────
        adv_groups = frozenset(third_teams.keys())
        bracket_map = ANNEX_C.get(adv_groups)
        if bracket_map is None:
            raise KeyError(
                f"ANNEX_C missing combination: {sorted(adv_groups)}. "
                f"Add this frozenset to the lookup table."
            )
        annex_row = bracket_map

        def t3(grp: str) -> str:
            return third_teams[grp]

        # 16 R32 matchups (flat list)
        r32_pairs = [
            (r_map["A"], r_map["B"]),          # M73
            (w_map["E"], t3(annex_row["M74"])),# M74
            (w_map["F"], r_map["C"]),          # M75
            (w_map["C"], r_map["F"]),          # M76
            (w_map["I"], t3(annex_row["M77"])),# M77
            (r_map["E"], r_map["I"]),          # M78
            (w_map["A"], t3(annex_row["M79"])),# M79
            (w_map["L"], t3(annex_row["M80"])),# M80
            (w_map["D"], t3(annex_row["M81"])),# M81
            (w_map["G"], t3(annex_row["M82"])),# M82
            (r_map["K"], r_map["L"]),          # M83
            (w_map["H"], r_map["J"]),          # M84
            (w_map["B"], t3(annex_row["M85"])),# M85
            (w_map["J"], r_map["H"]),          # M86
            (w_map["K"], t3(annex_row["M87"])),# M87
            (r_map["D"], r_map["G"]),          # M88
        ]

        # R32: simulate → 16 winners
        r32_w = [_sim_ko(ta, tb, cache) for ta, tb in r32_pairs]
        for t in r32_w:
            counts[t][1] += 1   # r32_win → p_r16

        # R16 bracket pairs: (M73,M75) (M74,M77) (M76,M78) (M79,M80)
        #                    (M83,M84) (M81,M82) (M86,M88) (M85,M87)
        # Indices into r32_w:  (0,2) (1,4) (3,5) (6,7) (10,11) (8,9) (13,15) (12,14)
        # R16 bracket: ordered so adjacent pairs produce the correct QF matchups.
        # M97=W89vW90, M98=W93vW94, M99=W91vW92, M100=W95vW96
        # SF: M101=W97vW98, M102=W99vW100
        r16_pairs = [
            (r32_w[0],  r32_w[2]),   # M89: W73 vs W75  →feeds M97
            (r32_w[1],  r32_w[4]),   # M90: W74 vs W77  →feeds M97
            (r32_w[10], r32_w[11]),  # M93: W83 vs W84  →feeds M98
            (r32_w[8],  r32_w[9]),   # M94: W81 vs W82  →feeds M98
            (r32_w[3],  r32_w[5]),   # M91: W76 vs W78  →feeds M99
            (r32_w[6],  r32_w[7]),   # M92: W79 vs W80  →feeds M99
            (r32_w[13], r32_w[15]),  # M95: W86 vs W88  →feeds M100
            (r32_w[12], r32_w[14]),  # M96: W85 vs W87  →feeds M100
        ]

        # R16 → QF → SF → Final: simulate each round in bracket order
        survivors = r16_pairs
        for stage_col in (2, 3, 4):  # r16_win, qf_win, sf_win
            winners = [_sim_ko(ta, tb, cache) for ta, tb in survivors]
            for t in winners:
                counts[t][stage_col] += 1
            survivors = [(winners[i], winners[i + 1]) for i in range(0, len(winners), 2)]

        # survivors is now 1 Final matchup
        finalist_a, finalist_b = survivors[0]
        champ = _sim_ko(finalist_a, finalist_b, cache)
        counts[champ][5] += 1

    if _verbose:
        print(f"  Simulations complete in {time.time() - t_sim_start:.1f}s")

    probs = {
        t: {
            "p_group_advance": counts[t][0] / n,
            "p_r16":           counts[t][1] / n,
            "p_qf":            counts[t][2] / n,
            "p_sf":            counts[t][3] / n,
            "p_final":         counts[t][4] / n,
            "p_champion":      counts[t][5] / n,
        }
        for t in WC2026_TEAMS
    }

    if _save_to_db:
        generated_at = datetime.now(timezone.utc).isoformat()
        conn = sqlite3.connect(db_path)
        conn.execute("DROP TABLE IF EXISTS tournament_probs")
        conn.execute("""
            CREATE TABLE tournament_probs (
                team            TEXT PRIMARY KEY,
                p_group_advance REAL,
                p_r16           REAL,
                p_qf            REAL,
                p_sf            REAL,
                p_final         REAL,
                p_champion      REAL,
                generated_at    TEXT
            )
        """)
        conn.executemany(
            "INSERT INTO tournament_probs VALUES (?,?,?,?,?,?,?,?)",
            [(t,
              round(p["p_group_advance"], 4), round(p["p_r16"], 4),
              round(p["p_qf"], 4),            round(p["p_sf"], 4),
              round(p["p_final"], 4),          round(p["p_champion"], 4),
              generated_at)
             for t, p in probs.items()],
        )
        conn.commit()
        conn.close()
        if _verbose:
            print(f"  Saved {len(probs)} teams → tournament_probs in {db_path}")

    if _verbose:
        _print_tournament_results(probs)
        print(f"\n  Total Phase 3 runtime: {time.time() - t0:.1f}s")
    return probs


def _print_tournament_results(probs: dict) -> None:
    """Print simulation results."""
    by_champ = sorted(probs.items(), key=lambda x: -x[1]["p_champion"])
    W = 100

    print(f"\n{'='*W}")
    print("  Phase 3 — Tournament Simulation Results")
    print(f"{'='*W}")

    print(f"\n  Top 15 P(champion):")
    print(f"  {'Team':<22} {'Advance':>8} {'R32▸R16':>8} {'R16▸QF':>7} {'QF▸SF':>6} {'SF▸F':>6} {'Champ':>6}")
    print(f"  {'-'*W}")
    for team, p in by_champ[:15]:
        print(
            f"  {team:<22}"
            f"  {p['p_group_advance']*100:6.1f}%"
            f"  {p['p_r16']*100:6.1f}%"
            f"  {p['p_qf']*100:5.1f}%"
            f"  {p['p_sf']*100:5.1f}%"
            f"  {p['p_final']*100:5.1f}%"
            f"  {p['p_champion']*100:5.1f}%"
        )

    print(f"\n  Bottom 10 P(champion):")
    print(f"  {'Team':<22} {'Advance':>8} {'Champ':>7}")
    print(f"  {'-'*52}")
    for team, p in by_champ[-10:]:
        print(
            f"  {team:<22}"
            f"  {p['p_group_advance']*100:6.1f}%"
            f"  {p['p_champion']*100:5.2f}%"
        )

    by_adv = sorted(probs.items(), key=lambda x: -x[1]["p_group_advance"])
    print(f"\n  P(group advance) — all 48 teams:")
    print(f"  {'Team':<22} {'Advance':>8}    {'Team':<22} {'Advance':>8}")
    print(f"  {'-'*W}")
    half = (len(by_adv) + 1) // 2
    for left, right in zip(by_adv[:half], by_adv[half:]):
        lt, lp = left; rt, rp = right
        print(
            f"  {lt:<22}  {lp['p_group_advance']*100:6.1f}%    "
            f"{rt:<22}  {rp['p_group_advance']*100:6.1f}%"
        )
    print(f"\n{'='*W}")


def compute_all_leverage(n_baseline: int = 5000, n_conditional: int = 5000, db_path: str = DB_PATH) -> list:
    """Compute leverage scores for all 72 group stage games.

    Leverage = expected total shift in championship probability across all 48
    teams, weighted by the probability of each outcome.  Writes results to the
    game_leverage table in spi_ratings.db.
    """
    t0 = time.time()
    W = 74

    print(f"\n{'='*W}")
    print("  Game Leverage — WC2026 Group Stage  (all 72 games)")
    print(f"{'='*W}")

    # Canonical combination order: frozenset({ta, tb}) -> (ta, tb)
    # Matches the ordering used by _sim_group so fixed_results keys align.
    combo_order: dict = {}
    for grp, teams in WC2026_GROUPS.items():
        for ta, tb in _combinations(teams, 2):
            combo_order[frozenset({ta, tb})] = (ta, tb)

    # Load completed WC2026 results from odds.db — fix at actual scorelines
    completed_fixed: dict = {}
    for m in _load_completed_wc2026_matches():
        canonical = combo_order.get(frozenset({m["home"], m["away"]}))
        if canonical:
            ta, tb = canonical
            # Store scores in combination order (ta_score, tb_score)
            completed_fixed[canonical] = (
                (m["home_score"], m["away_score"]) if ta == m["home"]
                else (m["away_score"], m["home_score"])
            )

    completed_set: set = set(completed_fixed.keys())
    print(f"  {len(completed_fixed)} completed WC2026 games fixed at actual scorelines.")

    # Precompute all match predictions once (reused across all simulations)
    print("  Precomputing all WC2026 match predictions...")
    cache = _precompute_match_cache(db_path)
    print(f"  {len(cache)} predictions cached in {time.time() - t0:.1f}s")

    # Baseline: full tournament sim with completed games fixed
    print(f"\n  Step 1 — Baseline simulation (n={n_baseline:,})...")
    t1 = time.time()
    baseline_probs = run_full_tournament_simulation(
        n=n_baseline, db_path=db_path,
        fixed_result=completed_fixed, _cache=cache,
        _save_to_db=False, _verbose=False,
        advancement_only=True,
    )
    print(f"  Baseline done in {time.time() - t1:.1f}s")

    # Build the 72-game schedule in combination order
    schedule = [
        {"home": ta, "away": tb, "grp": grp}
        for grp, teams in WC2026_GROUPS.items()
        for ta, tb in _combinations(teams, 2)
    ]

    total_sims = len([g for g in schedule if (g["home"], g["away"]) not in completed_set]) * 3
    print(f"\n  Step 2 — Conditional simulations "
          f"({total_sims:,} runs @ n={n_conditional:,} each)...")

    leverage_rows: list = []

    for i, game in enumerate(schedule):
        home, away = game["home"], game["away"]
        key = (home, away)

        if key in completed_set:
            leverage_rows.append({
                "home": home, "away": away,
                "leverage_score": 0.0,
                "leverage_home_win": 0.0,
                "leverage_draw": 0.0,
                "leverage_away_win": 0.0,
                "completed": True,
            })
            continue

        # SPI probabilities for this match
        p_hw, p_d, p_aw, _, _ = cache.get(key, (1/3, 1/3, 1/3, 1.5, 1.5))

        # 3 conditional simulations — one per possible outcome
        delta: dict = {}
        for outcome in ("home_win", "draw", "away_win"):
            fr = {**completed_fixed, key: outcome}
            cond = run_full_tournament_simulation(
                n=n_conditional, db_path=db_path,
                fixed_result=fr, _cache=cache,
                _save_to_db=False, _verbose=False,
                advancement_only=True,
            )
            delta[outcome] = sum(
                abs(cond[t]["p_group_advance"] - baseline_probs[t]["p_group_advance"])
                for t in WC2026_TEAMS
            )

        leverage = p_hw * delta["home_win"] + p_d * delta["draw"] + p_aw * delta["away_win"]

        leverage_rows.append({
            "home": home, "away": away,
            "leverage_score": leverage,
            "leverage_home_win": delta["home_win"],
            "leverage_draw": delta["draw"],
            "leverage_away_win": delta["away_win"],
            "completed": False,
        })

        if (i + 1) % 10 == 0:
            elapsed = time.time() - t0
            print(f"  [{i+1:2}/72] {home:<22} vs {away:<22}  "
                  f"leverage={leverage:.4f}  ({elapsed:.0f}s elapsed)")

    # Save to DB
    generated_at = datetime.now(timezone.utc).isoformat()
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS game_leverage (
            home_team         TEXT,
            away_team         TEXT,
            leverage_score    REAL,
            leverage_home_win REAL,
            leverage_draw     REAL,
            leverage_away_win REAL,
            generated_at      TEXT,
            PRIMARY KEY (home_team, away_team)
        )
    """)
    conn.execute("DELETE FROM game_leverage")
    conn.executemany(
        "INSERT INTO game_leverage VALUES (?,?,?,?,?,?,?)",
        [
            (
                r["home"], r["away"],
                round(r["leverage_score"], 6),
                round(r["leverage_home_win"], 6),
                round(r["leverage_draw"], 6),
                round(r["leverage_away_win"], 6),
                generated_at,
            )
            for r in leverage_rows
        ],
    )
    conn.commit()
    conn.close()
    print(f"\n  Saved {len(leverage_rows)} rows → game_leverage in {db_path}")

    # ── Print results ──────────────────────────────────────────────────────────
    sorted_rows = sorted(leverage_rows, key=lambda x: -x["leverage_score"])
    row_index = {id(r): i + 1 for i, r in enumerate(sorted_rows)}

    print(f"\n{'='*W}")
    print("  Top 15 highest leverage games:")
    print(f"  {'Rk':<4} {'Home':<22} {'Away':<22} {'Leverage':>9}  "
          f"{'HW-Δ':>7}  {'D-Δ':>7}  {'AW-Δ':>7}")
    print(f"  {'-'*W}")
    for rank, r in enumerate(sorted_rows[:15], 1):
        tag = "  [DONE]" if r["completed"] else ""
        print(
            f"  {rank:<4} {r['home']:<22} {r['away']:<22}"
            f"  {r['leverage_score']:8.4f}"
            f"  {r['leverage_home_win']:6.4f}"
            f"  {r['leverage_draw']:6.4f}"
            f"  {r['leverage_away_win']:6.4f}"
            f"{tag}"
        )

    print(f"\n  Bottom 10 lowest leverage games:")
    print(f"  {'Rk':<4} {'Home':<22} {'Away':<22} {'Leverage':>9}")
    print(f"  {'-'*W}")
    for rank, r in enumerate(sorted_rows[-10:], len(sorted_rows) - 9):
        tag = "  [DONE]" if r["completed"] else ""
        print(f"  {rank:<4} {r['home']:<22} {r['away']:<22}  "
              f"{r['leverage_score']:8.4f}{tag}")

    # Sanity checks
    print(f"\n  Sanity checks:")
    for team in ["Spain", "France", "Argentina", "England"]:
        team_games = [r for r in leverage_rows
                      if r["home"] == team or r["away"] == team]
        avg_lev = (sum(r["leverage_score"] for r in team_games) / len(team_games)
                   if team_games else 0.0)
        ranks = sorted(row_index[id(r)] for r in team_games)
        print(f"    {team:<12}  avg leverage = {avg_lev:.4f}  "
              f"(game ranks: {ranks})")

    for h, a in [("Haiti", "Scotland"), ("Curacao", "Ivory Coast")]:
        r = next((x for x in leverage_rows if x["home"] == h and x["away"] == a), None)
        if r:
            print(f"    {h} vs {a}: leverage = {r['leverage_score']:.4f}  "
                  f"(rank {row_index[id(r)]}/72)")

    total_time = time.time() - t0
    print(f"\n  Total runtime: {total_time:.1f}s")
    print(f"{'='*W}\n")
    return leverage_rows


if __name__ == "__main__":
    import sys
    if "--init" in sys.argv:
        seed_historical()
    elif "--predict" in sys.argv:
        validate_predictions()
    elif "--simulate" in sys.argv:
        run_full_tournament_simulation()
    elif "--leverage" in sys.argv:
        compute_all_leverage()
    else:
        main()
        validate_predictions()
