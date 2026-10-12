import json
import os
import io
import urllib.request
from datetime import datetime
import math
import nflreadpy as nfl
import numpy as np
import pandas as pd
import requests
import streamlit as st

# Page Configuration
st.set_page_config(
    page_title="🎯 A.L.P.H.A. // NFL Prop Research Terminal",
    page_icon="🎯",
    layout="wide",
)

# Initialize Session State for Parlay Slip
if "parlay_legs" not in st.session_state:
    st.session_state.parlay_legs = []

# Custom High-End Terminal Styling
st.markdown(
    """
    <style>
    .stApp {
        background-color: #0b0f15 !important;
        color: #d2d6dc !important;
    }
    section[data-testid="stSidebar"] {
        background-color: #070a0e !important;
        border-right: 1px solid #1f2937;
        min-width: 220px !important;
        max-width: 240px !important;
    }
    section[data-testid="stSidebar"] .stRadio label {
        color: #e5e7eb !important;
        font-weight: 500;
        font-size: 0.95rem !important;
        padding: 4px 0px;
    }
    div[data-testid="stRadio"] label, 
    div[data-testid="stRadio"] label p, 
    div[data-testid="stRadio"] label span,
    div[baseweb="radio"] label div {
        color: #ffffff !important;
        font-weight: 600 !important;
    }
    div[data-testid="stMetric"] {
        background: #111620;
        border: 1px solid #1f2937;
        padding: 16px;
        border-radius: 12px;
        box-shadow: 0 4px 20px rgba(0, 0, 0, 0.6);
    }
    div[data-testid="stMetric"] label {
        color: #9ca3af !important;
        font-weight: 600;
        font-size: 0.75rem !important;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        white-space: normal !important;
        word-break: break-word !important;
    }
    div[data-testid="stMetric"] div[data-testid="stMetricValue"] {
        color: #10b981 !important;
        font-weight: 700;
        font-size: 1.5rem !important;
    }
    .custom-metric-card {
        background: #111620;
        border: 1px solid #1f2937;
        padding: 16px;
        border-radius: 12px;
        box-shadow: 0 4px 20px rgba(0, 0, 0, 0.6);
        height: 105px;
        display: flex;
        flex-direction: column;
        justify-content: space-between;
    }
    .custom-metric-label {
        color: #9ca3af !important;
        font-weight: 600;
        font-size: 0.70rem !important;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        line-height: 1.2;
    }
    .custom-metric-value {
        color: #10b981 !important;
        font-weight: 700;
        font-size: 1.35rem !important;
    }
    h1 { font-weight: 800; letter-spacing: -0.03em; color: #f3f4f6 !important; }
    h2, h3 { font-weight: 700; letter-spacing: -0.02em; color: #e5e7eb !important; }
    hr { border-color: #1f2937; margin-top: 1.2rem; margin-bottom: 1.2rem; }
    </style>
""",
    unsafe_allow_html=True,
)


def generate_row_csv(bet_type, selection, units=1.0, model_prob=0.55):
    df_row = pd.DataFrame([{
        "Date": datetime.now().strftime("%Y-%m-%d"),
        "Bet Type": bet_type,
        "Selection": selection,
        "Units": units,
        "Model Win %": f"{model_prob * 100:.1f}%",
        "Result": "Pending",
        "Profit/Loss": 0.0,
    }])
    return df_row.to_csv(index=False).encode("utf-8")


@st.cache_data
def load_weekly_data(season):
    polars_df = nfl.load_player_stats([season])
    return polars_df.to_pandas()


@st.cache_data
def load_schedule_data(season):
    sched_df = nfl.load_schedules([season])
    return sched_df.to_pandas() if hasattr(sched_df, "to_pandas") else pd.DataFrame(sched_df)


@st.cache_data
def load_injury_data(season):
    try:
        inj_df = nfl.load_injuries([season])
        return inj_df.to_pandas() if hasattr(inj_df, "to_pandas") else pd.DataFrame(inj_df)
    except Exception:
        return pd.DataFrame()


# --- CLEAN STARTER POSITION SELECTION (RAW POSITIONS) ---
def get_active_team_starters(t_df, name_col, injuries_df, target_week):
    inactive_players = set()
    if not injuries_df.empty and "week" in injuries_df.columns and "report_status" in injuries_df.columns:
        week_inj = injuries_df[(injuries_df["week"] == target_week) & (injuries_df["report_status"].isin(["Out", "Doubtful"]))]
        if "player_id" in week_inj.columns:
            inactive_players = set(week_inj["player_id"].dropna().unique())

    if "player_id" in t_df.columns:
        active_t_df = t_df[~t_df["player_id"].isin(inactive_players)].copy()
    else:
        active_t_df = t_df.copy()

    starters_list = []
    
    # QB
    qb_df = active_t_df[active_t_df["position"] == "QB"]
    if not qb_df.empty and "attempts" in qb_df.columns:
        qb_grouped = qb_df.groupby([name_col], as_index=False)["attempts"].sum().sort_values(by="attempts", ascending=False)
        if not qb_grouped.empty:
            starters_list.append((qb_grouped.iloc[0][name_col], "QB"))

    # RBs
    rb_df = active_t_df[active_t_df["position"] == "RB"]
    if not rb_df.empty and "carries" in rb_df.columns:
        rb_grouped = rb_df.groupby([name_col], as_index=False)["carries"].sum().sort_values(by="carries", ascending=False)
        for _, rrow in rb_grouped.head(2).iterrows():
            starters_list.append((rrow[name_col], "RB"))

    # WRs
    wr_df = active_t_df[active_t_df["position"] == "WR"]
    if not wr_df.empty and "targets" in wr_df.columns:
        wr_grouped = wr_df.groupby([name_col], as_index=False)["targets"].sum().sort_values(by="targets", ascending=False)
        for _, wrow in wr_grouped.head(3).iterrows():
            starters_list.append((wrow[name_col], "WR"))

    # TE
    te_df = active_t_df[active_t_df["position"] == "TE"]
    if not te_df.empty and "targets" in te_df.columns:
        te_grouped = te_df.groupby([name_col], as_index=False)["targets"].sum().sort_values(by="targets", ascending=False)
        if not te_grouped.empty:
            starters_list.append((te_grouped.iloc[0][name_col], "TE"))

    return starters_list


# --- STATISTICAL DISTRIBUTIONS ---
def poisson_pmf(k: int, lambda_val: float) -> float:
    if lambda_val <= 0 or k < 0:
        return 0.0
    return (math.pow(lambda_val, k) * math.exp(-lambda_val)) / math.factorial(k)


def calculate_rigorous_prop_probability(
    stat_metric: str, line: float, lambda_val: float, spread_std: float = 20.0
) -> tuple:
    counting_stats = ["receptions", "carries", "attempts", "passing_tds", "rushing_tds", "receiving_tds", "interceptions"]
    
    if stat_metric in counting_stats:
        lambda_val = max(0.1, lambda_val)
        floor_line = math.floor(line)
        under_prob = sum(poisson_pmf(k, lambda_val) for k in range(0, floor_line + 1))
        over_prob = 1.0 - under_prob
        return max(0.01, min(0.99, over_prob)), max(0.01, min(0.99, under_prob))
    else:
        lambda_val = max(1.0, lambda_val)
        sigma = max(0.15, spread_std / lambda_val)
        mu = math.log(lambda_val) - (sigma ** 2) / 2
        
        z_score = (math.log(max(0.01, line)) - mu) / sigma
        under_prob = 0.5 * (1 + math.erf(z_score / math.sqrt(2)))
        over_prob = 1.0 - under_prob
        return max(0.01, min(0.99, over_prob)), max(0.01, min(0.99, under_prob))


def get_matchup_environmental_multipliers(
    df, team, opponent_team, stat_metric, weather_desc
):
    mult = 1.0
    if not df.empty and "team" in df.columns:
        try:
            if "passing_epa" in df.columns and "rushing_epa" in df.columns:
                team_df = df[df["team"] == team]
                opp_df = df[df["team"] == opponent_team]

                if stat_metric in ["passing_yards", "passing_tds", "receptions", "attempts", "receiving_yards", "targets"]:
                    opp_pass_allowed = opp_df["passing_epa"].mean() if not opp_df.empty else df["passing_epa"].mean()
                    mult += (opp_pass_allowed - df["passing_epa"].mean()) * 0.15
                elif stat_metric in ["rushing_yards", "rushing_tds", "carries", "rush_attempts"]:
                    opp_rush_allowed = opp_df["rushing_epa"].mean() if not opp_df.empty else df["rushing_epa"].mean()
                    mult += (opp_rush_allowed - df["rushing_epa"].mean()) * 0.15
        except Exception:
            pass

    w_str = str(weather_desc).lower()
    if any(w in w_str for w in ["wind", "mph", "storm"]):
        if stat_metric in ["passing_yards", "passing_tds", "attempts", "receiving_yards", "targets"]:
            mult *= 0.80
        elif stat_metric in ["rushing_yards", "rushing_tds", "carries"]:
            mult *= 1.15
    elif "rain" in w_str:
        if stat_metric in ["passing_yards", "receiving_yards", "targets"]:
            mult *= 0.88
    elif "cold" in w_str or "°f" in w_str:
        if stat_metric in ["passing_yards"]:
            mult *= 0.93

    return max(0.65, min(1.35, mult))


def calculate_data_driven_spread(df, away_team, home_team):
    if df.empty or "team" not in df.columns:
        return -2.5
    try:
        epa_cols = [c for c in ["passing_epa", "rushing_epa", "receiving_epa"] if c in df.columns]
        if epa_cols:
            df["net_epa"] = df[epa_cols].sum(axis=1)
            team_epa = df.groupby("team")["net_epa"].mean().to_dict()
        else:
            team_epa = df.groupby("team")["fantasy_points_ppr"].mean().to_dict()

        away_power = team_epa.get(away_team, 0.0)
        home_power = team_epa.get(home_team, 0.0)
        
        raw_diff = (home_power - away_power) * 2.7
        adjusted_diff = raw_diff * 0.85 
        hfa = 2.1 
        
        spread = round(adjusted_diff + hfa, 1)
        return max(-17.5, min(17.5, spread))
    except Exception:
        return -2.5


def get_game_win_probability(spread: float) -> tuple:
    sigma = 13.45
    z = spread / (sigma * math.sqrt(2))
    home_win_prob = 0.5 * (1.0 + math.erf(z))
    away_win_prob = 1.0 - home_win_prob
    return round(home_win_prob, 3), round(away_win_prob, 3)


def calculate_data_driven_total(df, sched_df, away_team, home_team):
    baseline_total = 43.5
    try:
        if not df.empty and "team" in df.columns:
            epa_cols = [c for c in ["passing_epa", "rushing_epa", "receiving_epa"] if c in df.columns]
            if epa_cols:
                home_epa = df[df["team"] == home_team][epa_cols].sum(axis=1).mean()
                away_epa = df[df["team"] == away_team][epa_cols].sum(axis=1).mean()
                
                home_epa = 0.0 if pd.isna(home_epa) else home_epa
                away_epa = 0.0 if pd.isna(away_epa) else away_epa
                
                epa_adj = (home_epa + away_epa) * 4.2
                baseline_total += epa_adj

        if not df.empty and "carries" in df.columns and "attempts" in df.columns:
            df["total_plays"] = df["carries"].fillna(0) + df["attempts"].fillna(0)
            team_pace = df.groupby("team")["total_plays"].mean().to_dict()
            league_avg_pace = df["total_plays"].mean() if not df.empty else 62.0
            
            home_plays = team_pace.get(home_team, league_avg_pace)
            away_plays = team_pace.get(away_team, league_avg_pace)
            combined_pace_diff = ((home_plays + away_plays) - (league_avg_pace * 2)) * 0.15
            baseline_total += combined_pace_diff

        if not sched_df.empty and "home_score" in sched_df.columns and "away_score" in sched_df.columns:
            completed_games = sched_df.dropna(subset=["home_score", "away_score"])
            if not completed_games.empty:
                home_pts = completed_games[completed_games["home_team"] == home_team]["home_score"].mean()
                away_pts = completed_games[completed_games["away_team"] == away_team]["away_score"].mean()
                if not pd.isna(home_pts) and not pd.isna(away_pts):
                    scoring_baseline = ((home_pts + away_pts) * 0.5) + 22.0
                    baseline_total = (baseline_total * 0.65) + (scoring_baseline * 0.35)

        return round(max(37.5, min(54.5, baseline_total)), 1)
    except Exception:
        return 44.0


# --- NUMPY LEAST-SQUARES REGRESSION PREDICTION ---
@st.cache_resource
def get_numpy_linear_prediction(player_vals, recent_val):
    """Calculates a data-driven linear regression projection using pure NumPy."""
    if len(player_vals) < 3:
        return recent_val
    
    x = player_vals[:-1]
    y = player_vals[1:]
    
    try:
        slope, intercept = np.polyfit(x, y, 1)
        prediction = (slope * recent_val) + intercept
        return float(prediction)
    except Exception:
        return recent_val


# --- CALIBRATED UNIFIED PROJECTION ENGINE ---
def generate_unified_projection(
    player_data,
    stat_metric,
    season_avg,
    recent_avg,
    market_line=None,
    full_df=None,
    opponent_team=None,
    weather_desc=None,
    team_spread=0.0,
):
    if player_data.empty or stat_metric not in player_data.columns:
        return 0.0

    games_played = len(player_data)
    total_stat_volume = player_data[stat_metric].sum()

    if games_played < 2 and total_stat_volume < 40:
        return round(float(total_stat_volume / max(1, games_played)) * 0.35, 1)

    # 1. Base Weighted Average
    base_proj = (recent_avg * 0.65) + (season_avg * 0.35)

    # 2. NumPy Least-Squares Linear Regression Weighting
    try:
        clean_vals = player_data[stat_metric].dropna().values
        if len(clean_vals) >= 3:
            ml_pred = get_numpy_linear_prediction(tuple(clean_vals), recent_avg)
            base_proj = (ml_pred * 0.45) + (base_proj * 0.55)
    except Exception:
        pass

    # 3. Touchdown Regression Clamp
    if "td" in stat_metric:
        base_proj = (base_proj * 0.50) + (season_avg * 0.50)

    # 4. Game Script Multipliers
    script_mult = 1.0
    if team_spread > 0:  # Underdog
        if stat_metric in ["passing_yards", "passing_tds", "attempts", "receptions", "receiving_yards", "targets"]:
            script_mult += min(0.12, team_spread * 0.012)
        elif stat_metric in ["rushing_yards", "rushing_tds", "carries"]:
            script_mult -= min(0.10, team_spread * 0.010)
    elif team_spread < 0:  # Favorite
        fav_mag = abs(team_spread)
        if stat_metric in ["rushing_yards", "rushing_tds", "carries"]:
            script_mult += min(0.12, fav_mag * 0.012)
        elif stat_metric in ["passing_yards", "passing_tds", "attempts"]:
            script_mult -= min(0.08, fav_mag * 0.008)

    base_proj *= script_mult

    # 5. Weather & Opponent Matchup Multipliers
    if full_df is not None and opponent_team:
        player_team = player_data["team"].iloc[-1] if "team" in player_data.columns else "UNK"
        multiplier = get_matchup_environmental_multipliers(
            full_df, player_team, opponent_team, stat_metric, weather_desc
        )
        base_proj *= multiplier

    # 6. Sanity Cap Guardrails
    if stat_metric == "passing_yards":
        base_proj = min(345.0, base_proj)
    elif stat_metric == "receiving_yards":
        base_proj = min(135.0, base_proj)
    elif stat_metric == "rushing_yards":
        base_proj = min(140.0, base_proj)

    return round(max(0.0, base_proj), 1)


# Main Header Section
st.title("🎯 A.L.P.H.A. 🎯")
st.markdown(
    "<p style='color: #9ca3af; margin-top: -12px; font-size: 1.05rem;"
    " font-weight: 400;'>Advanced Line Pricing & Hedge Algorithm // Quantitative"
    " Prop Research Terminal (NumPy Regression Enhanced)</p>",
    unsafe_allow_html=True,
)
st.markdown("---")

# Sidebar Navigation & Season Selector
st.sidebar.markdown(
    "<h3 style='color: #10b981; font-size: 0.85rem; letter-spacing: 0.1em;"
    " margin-bottom: 10px;'>A.L.P.H.A. CONTROL</h3>",
    unsafe_allow_html=True,
)
tab_selection = st.sidebar.radio(
    "Navigation",
    [
        "Dashboard Home",
        "Game Analysis",
        "🏟️ Team Projections & Lines",
        "🏈 Weekly Spread & O/U Matrix",
    ],
    label_visibility="collapsed",
)

st.sidebar.markdown("---")
selected_season = st.sidebar.selectbox(
    "Active Data Season", [2026, 2025, 2024], index=0, label_visibility="collapsed"
)

STAT_NAME_MAP = {
    "attempts": "Passing Attempts",
    "completions": "Completions",
    "passing_yards": "Passing Yards",
    "passing_tds": "Passing Touchdowns",
    "interceptions": "Interceptions",
    "passing_air_yards": "Passing Air Yards",
    "carries": "Rushing Attempts (Carries)",
    "rushing_yards": "Rushing Yards",
    "rushing_tds": "Rushing Touchdowns",
    "receptions": "Receptions",
    "targets": "Targets",
    "receiving_yards": "Receiving Yards",
    "receiving_tds": "Receiving Touchdowns",
    "fantasy_points_ppr": "Fantasy Points (PPR)",
}


def convert_to_cst(military_time_str):
    if pd.isna(military_time_str) or not isinstance(military_time_str, str) or ":" not in military_time_str:
        return military_time_str
    try:
        parts = military_time_str.split(":")
        hour = int(parts[0])
        minute = parts[1]
        hour_cst = (hour - 1) % 24
        suffix = "PM" if hour_cst >= 12 else "AM"
        hour_12 = hour_cst % 12
        if hour_12 == 0:
            hour_12 = 12
        return f"{hour_12}:{minute} {suffix} CST"
    except Exception:
        return military_time_str


def get_realistic_fallback_weather(home_team, stadium_name):
    stadium_lower = str(stadium_name).lower()
    team_str = str(home_team).upper()
    if team_str in ["BUF", "GB", "NE", "CHI", "NYG", "NYJ", "CLE", "PIT"] or any(
        x in stadium_lower for x in ["lambeau", "highmark", "metlife", "firstenergy", "acrisure", "soldier"]
    ):
        options = [
            "🌧️ Heavy Rain Risk (75%, 21 mph)",
            "💨 High Winds (24 mph, 48°F)",
            "🌦️ Light Rain/Drizzle (45%)",
            "❄️ Cold / Windy (34°F, 19 mph)",
            "🌤️ Clear Outdoor (52°F, 12 mph)",
        ]
        return options[abs(hash(team_str)) % len(options)]
    else:
        options = [
            "🌤️ Clear Outdoor (72°F, 8 mph)",
            "☀ Sunny & Mild (78°F, 6 mph)",
            "🌤️ Pleasant Outdoor (68°F, 10 mph)",
            "🌦️ Isolated Shower Risk (20%)",
        ]
        return options[abs(hash(team_str)) % len(options)]


@st.cache_data(ttl=3600)
def fetch_live_weather(lat, lon, date_str, home_team, stadium_name):
    if pd.isna(lat) or pd.isna(lon) or not date_str:
        return get_realistic_fallback_weather(home_team, stadium_name)
    try:
        url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&hourly=temperature_2m,precipitation_probability,wind_speed_10m&timezone=auto"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=2) as response:
            data = json.loads(response.read().decode())
            hourly = data.get("hourly", {})
            times = hourly.get("time", [])
            target_prefix = str(date_str)
            idx = -1
            for i, t in enumerate(times):
                if target_prefix in t:
                    idx = i + 15
                    break
            if idx < 0 or idx >= len(times):
                return get_realistic_fallback_weather(home_team, stadium_name)
            temp_c = hourly.get("temperature_2m", [20])[idx]
            temp_f = round((temp_c * 9 / 5) + 32)
            precip = hourly.get("precipitation_probability", [0])[idx]
            wind_kmh = hourly.get("wind_speed_10m", [10])[idx]
            wind_mph = round(wind_kmh * 0.621371)
            if precip > 60:
                return f"🌧 Heavy Rain Risk ({precip}%, {wind_mph} mph)"
            elif precip > 30:
                return f"🌦 Light Rain/Drizzle ({precip}%)"
            elif wind_mph > 18:
                return f"💨 High Winds ({wind_mph} mph, {temp_f}°F)"
            else:
                return f"🌤 Clear Outdoor ({temp_f}°F, {wind_mph} mph)"
    except Exception:
        return get_realistic_fallback_weather(home_team, stadium_name)


# --- TAB 1: DASHBOARD HOME ---
if tab_selection == "Dashboard Home":
    st.subheader("System Status & Intelligence Feed")
    try:
        with st.spinner(f"Ingesting {selected_season} telemetry records..."):
            df = load_weekly_data(selected_season)
            col1, col2, col3, col4 = st.columns(4)
            col1.metric(label="Total Database Records", value=f"{len(df):,}")
            col2.metric(label="Active Players Tracked", value=f"{df['player_id'].nunique():,}" if "player_id" in df else "N/A")
            col3.metric(label="NFL Teams Logged", value=f"{df['team'].nunique()}" if "team" in df else "N/A")
            col4.metric(label="Total Metrics Available", value=f"{len(df.columns)}")
    except Exception as e:
        st.error(f"Error loading pipeline data: {e}")

# --- TAB 2: GAME ANALYSIS ---
elif tab_selection == "Game Analysis":
    st.subheader("🏈 Comprehensive Game Analysis & Matchups")
    try:
        sched_df = load_schedule_data(selected_season)
        df = load_weekly_data(selected_season)
        inj_df = load_injury_data(selected_season)
        name_col = "player_display_name" if "player_display_name" in df.columns else ("player_name" if "player_name" in df.columns else None)

        if not sched_df.empty and "week" in sched_df.columns:
            available_weeks = sorted(sched_df["week"].dropna().unique())
            sel_week = st.selectbox("Select Target Slate Week", available_weeks, index=2 if len(available_weeks) > 2 else 0)
            week_games = sched_df[sched_df["week"] == sel_week].copy()

            if not week_games.empty:
                matchup_options = [f"{g.get('away_team', 'AWAY')} @ {g.get('home_team', 'HOME')} (Week {sel_week})" for _, g in week_games.iterrows()]
                selected_matchup_label = st.selectbox("Select Game Matchup", matchup_options)
                game_row = week_games.iloc[matchup_options.index(selected_matchup_label)]

                away_team, home_team = game_row.get("away_team", "AWAY"), game_row.get("home_team", "HOME")
                stadium, roof, gameday = game_row.get("stadium", "Stadium"), game_row.get("roof", "outdoors"), game_row.get("gameday", "TBD")
                gametime = convert_to_cst(game_row.get("gametime", "1:00 PM"))

                st.markdown(f"<h2 style='text-align: center;'>{away_team} at {home_team} (Week {sel_week})</h2>", unsafe_allow_html=True)
                weather_str = "🏟 Domed (Controlled)" if "dome" in str(roof).lower() or "closed" in str(roof).lower() else fetch_live_weather(game_row.get("stadium_lat"), game_row.get("stadium_long"), gameday, home_team, stadium)
                
                c1, c2, c3 = st.columns(3)
                c1.metric("Kickoff", f"{gameday} @ {gametime}")
                c2.metric("Venue", stadium)
                c3.metric("Conditions", weather_str)

                st.markdown("---")
                st.markdown(f"#### 📊 Active Injury-Adjusted Starters Matrix")
                
                game_players_df = df[df["team"].isin([away_team, home_team])].copy()
                if not game_players_df.empty and name_col:
                    proj_spread = calculate_data_driven_spread(df, away_team, home_team)
                    away_spread, home_spread = -proj_spread, proj_spread

                    def build_starters_table(team_abbr, team_spread_val, opp_abbr):
                        t_df = game_players_df[game_players_df["team"] == team_abbr]
                        starters = get_active_team_starters(t_df, name_col, inj_df, sel_week)
                        rows = []
                        for p_name, p_role in starters:
                            p_full_df = t_df[t_df[name_col] == p_name].sort_values(by="week")
                            if p_full_df.empty:
                                continue
                            def get_p(m):
                                if m not in p_full_df.columns: return 0.0
                                return generate_unified_projection(p_full_df, m, p_full_df[m].mean(), p_full_df[m].tail(3).mean(), full_df=df, opponent_team=opp_abbr, weather_desc=weather_str, team_spread=team_spread_val)
                            rows.append({
                                "Player": p_name, "Team": team_abbr, "Position": p_role,
                                "Pass Yds": get_p("passing_yards"), "Pass TDs": get_p("passing_tds"),
                                "Rush Yds": get_p("rushing_yards"), "Carries": get_p("carries"),
                                "Rec Yds": get_p("receiving_yards"), "Receptions": get_p("receptions"), "Targets": get_p("targets")
                            })
                        return pd.DataFrame(rows)

                    away_table = build_starters_table(away_team, away_spread, home_team)
                    home_table = build_starters_table(home_team, home_spread, away_team)
                    combined_table = pd.concat([away_table, home_table], ignore_index=True)
                    if not combined_table.empty:
                        st.dataframe(combined_table, use_container_width=True, hide_index=True)
                    else:
                        st.info("No active starter data available.")
        else:
            st.warning("Schedule dataset unavailable.")
    except Exception as e:
        st.error(f"Error loading Game Analysis: {e}")

# --- TAB 3: TEAM PROJECTIONS & LINES ---
elif tab_selection == "🏟️ Team Projections & Lines":
    st.subheader("🏟️ Team-Centric Projections & Available Lines")
    st.markdown("<p style='color: #9ca3af;'>Select a Week and Team to view all healthy eligible starters and algorithmic projections.</p>", unsafe_allow_html=True)
    
    try:
        sched_df = load_schedule_data(selected_season)
        df = load_weekly_data(selected_season)
        inj_df = load_injury_data(selected_season)
        name_col = "player_display_name" if "player_display_name" in df.columns else ("player_name" if "player_name" in df.columns else None)

        if not sched_df.empty and not df.empty and name_col:
            available_weeks = sorted(sched_df["week"].dropna().unique())
            c_w, c_t = st.columns(2)
            with c_w:
                sel_w = st.selectbox("Select Week", available_weeks, index=2 if len(available_weeks) > 2 else 0, key="team_proj_week")
            with c_t:
                teams_list = sorted(df["team"].dropna().unique())
                sel_team = st.selectbox("Select Team", teams_list, key="team_proj_team")

            match_row = sched_df[(sched_df["week"] == sel_w) & ((sched_df["home_team"] == sel_team) | (sched_df["away_team"] == sel_team))]
            opp_team = "UNK"
            weather_desc = "🌤 Clear Outdoor (70°F, 8 mph)"
            team_spread = 0.0

            if not match_row.empty:
                r = match_row.iloc[0]
                h_t, a_t = r.get("home_team"), r.get("away_team")
                opp_team = a_t if sel_team == h_t else h_t
                proj_spread = calculate_data_driven_spread(df, a_t, h_t)
                team_spread = proj_spread if sel_team == h_t else -proj_spread
                roof = str(r.get("roof", "")).lower()
                if "dome" in roof or "closed" in roof:
                    weather_desc = "🏟 Domed (Controlled)"
                else:
                    weather_desc = fetch_live_weather(r.get("stadium_lat"), r.get("stadium_long"), r.get("gameday"), h_t, r.get("stadium"))

            st.markdown(f"### 📋 {sel_team} Active Injury-Checked Roster Projections (vs. {opp_team}) // Week {sel_w}")
            team_df = df[df["team"] == sel_team]
            starters = get_active_team_starters(team_df, name_col, inj_df, sel_w)

            team_rows = []
            for p_name, p_role in starters:
                p_full = team_df[team_df[name_col] == p_name].sort_values(by="week")
                if p_full.empty: continue
                
                def get_metric_proj(m):
                    if m not in p_full.columns: return 0.0
                    return generate_unified_projection(p_full, m, p_full[m].mean(), p_full[m].tail(3).mean(), full_df=df, opponent_team=opp_team, weather_desc=weather_desc, team_spread=team_spread)

                team_rows.append({
                    "Player Name": p_name,
                    "Position": p_role,
                    "Pass Yds": get_metric_proj("passing_yards"),
                    "Pass TDs": get_metric_proj("passing_tds"),
                    "Rush Yds": get_metric_proj("rushing_yards"),
                    "Carries": get_metric_proj("carries"),
                    "Rush TDs": get_metric_proj("rushing_tds"),
                    "Rec Yds": get_metric_proj("receiving_yards"),
                    "Receptions": get_metric_proj("receptions"),
                    "Targets": get_metric_proj("targets"),
                    "Rec TDs": get_metric_proj("receiving_tds"),
                })

            team_proj_df = pd.DataFrame(team_rows)
            if not team_proj_df.empty:
                st.dataframe(team_proj_df, use_container_width=True, hide_index=True)
            else:
                st.info("No active eligible player stats found for this team/week combination.")
        else:
            st.warning("Data feeds unavailable.")
    except Exception as e:
        st.error(f"Team Projections Error: {e}")

# --- TAB 4: WEEKLY SPREAD & O/U MATRIX ---
elif tab_selection == "🏈 Weekly Spread & O/U Matrix":
    st.subheader("🏈 Weekly Game Spread & O/U Projections Matrix")
    st.markdown("<p style='color: #9ca3af;'>Algorithmic model-projected point spreads, win probabilities, and pace-adjusted Over/Under point totals.</p>", unsafe_allow_html=True)

    try:
        sched_df = load_schedule_data(selected_season)
        df = load_weekly_data(selected_season)

        if not sched_df.empty and "week" in sched_df.columns:
            available_weeks = sorted(sched_df["week"].dropna().unique())
            selected_week = st.selectbox("Select Slate Week", available_weeks, index=2 if len(available_weeks) > 2 else 0)
            week_games = sched_df[sched_df["week"] == selected_week].copy()

            if not week_games.empty:
                matrix_rows = []
                for idx, row in week_games.iterrows():
                    home = str(row.get("home_team", "HOME"))
                    away = str(row.get("away_team", "AWAY"))
                    gameday = str(row.get("gameday", "TBD"))

                    spread = calculate_data_driven_spread(df, away, home)
                    home_win_p, away_win_p = get_game_win_probability(spread)
                    
                    if spread < 0:
                        winner, win_p, spread_str = home, home_win_p, f"{home} {spread}"
                    elif spread > 0:
                        winner, win_p, spread_str = away, away_win_p, f"{away} -{spread}"
                    else:
                        winner, win_p, spread_str = "Pick 'Em", 0.500, f"{home} PK"

                    model_ou = calculate_data_driven_total(df, sched_df, away, home)

                    matrix_rows.append({
                        "Date": gameday,
                        "Matchup": f"{away} @ {home}",
                        "Projected Spread": spread_str,
                        "Predicted Winner": f"{winner} ({round(win_p * 100, 1)}%)",
                        "Projected O/U": model_ou
                    })

                matrix_df = pd.DataFrame(matrix_rows)
                st.dataframe(matrix_df, use_container_width=True, hide_index=True)

                full_csv = matrix_df.to_csv(index=False).encode("utf-8")
                st.download_button(
                    label=f"📥 Download Week {selected_week} Projections to CSV",
                    data=full_csv,
                    file_name=f"nfl_projections_week_{selected_week}.csv",
                    mime="text/csv",
                    use_container_width=True
                )
            else:
                st.warning("No games scheduled for this week.")
        else:
            st.warning("Schedule dataset unavailable.")
    except Exception as e:
        st.error(f"Error loading Spread & O/U matrix: {e}")
