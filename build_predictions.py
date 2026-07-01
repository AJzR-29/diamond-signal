"""
build_predictions.py
Combina mlb_games.json + matchup_data.json + odds_data.json en un modelo de
prediccion simple y transparente, y genera el archivo final que consume el frontend.

Modelo (heuristico, pensado para iterar con datos reales de historial despues):
  - pitcher_score: ERA L5 (peso 65%) + IP promedio por arranque (peso 35%)
  - team_offense_score: runs por juego + OPS del equipo rival
  - matchup_adjustment: ajuste pequeno (max 15%) SOLO si hay muestra >=10 PA
    agregada de los bateadores titulares contra ese pitcher especifico
  - home_advantage: +1.8% al equipo local
  - edge = probabilidad del modelo - probabilidad de mercado (sin vig)

Salida: data/predictions.json
"""

import json
import datetime

GAMES_PATH = "data/mlb_games.json"
MATCHUP_PATH = "data/matchup_data.json"
ODDS_PATH = "data/odds_data.json"
OUTPUT_PATH = "data/predictions.json"

HOME_ADV = 0.018
MATCHUP_MAX_WEIGHT = 0.15
LEAGUE_AVG_BA = 0.248


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"[warn] no existe {path}, usando valores por defecto")
        return default


def pitcher_score(pitcher_l5):
    """Menor ERA = mejor. Mas IP por arranque = mejor (menos carga al bullpen)."""
    if not pitcher_l5 or pitcher_l5.get("era_l5") is None:
        return 0.5  # neutral si no hay datos (ej. pitcher nuevo, poca muestra)

    era = pitcher_l5["era_l5"]
    ip = pitcher_l5.get("ip_avg") or 5.0

    # normalizacion simple: ERA 2.50 -> score alto, ERA 6.00 -> score bajo
    era_component = max(0, min(1, (6.0 - era) / (6.0 - 2.5)))
    ip_component = max(0, min(1, (ip - 3.0) / (7.0 - 3.0)))

    return round(era_component * 0.65 + ip_component * 0.35, 4)


def offense_score(team_offense):
    if not team_offense:
        return 0.5
    rpg = team_offense.get("runs_per_game") or 4.3
    ops = float(team_offense.get("ops") or 0.720)

    rpg_component = max(0, min(1, (rpg - 3.0) / (6.0 - 3.0)))
    ops_component = max(0, min(1, (ops - 0.600) / (0.850 - 0.600)))

    return round(rpg_component * 0.5 + ops_component * 0.5, 4)


def matchup_adjustment(matchups_for_pitcher):
    """Compara el avg agregado de los titulares contra este pitcher vs. el avg de liga.
    Solo cuenta bateadores con muestra suficiente (sample_size_ok)."""
    valid = [m for m in matchups_for_pitcher if m.get("sample_size_ok") and m.get("avg_approx") is not None]
    if not valid:
        return 0.0, False

    avg_vs_pitcher = sum(m["avg_approx"] for m in valid) / len(valid)
    delta = avg_vs_pitcher - LEAGUE_AVG_BA  # positivo = el equipo le batea bien a este pitcher
    # escalamos el delta de AVG (rango tipico +-0.080) a un ajuste de hasta MATCHUP_MAX_WEIGHT
    scaled = max(-1, min(1, delta / 0.080)) * MATCHUP_MAX_WEIGHT
    return round(scaled, 4), True


def devig(prob_a, prob_b):
    total = prob_a + prob_b
    if total == 0:
        return 0.5, 0.5
    return round(prob_a / total, 4), round(prob_b / total, 4)


def american_ev_per_100(model_prob, american_odds):
    if american_odds is None:
        return None
    odds = float(american_odds)
    payout = (odds if odds > 0 else 10000 / abs(odds))  # ganancia neta por cada 100 apostados
    ev = (model_prob * payout) - ((1 - model_prob) * 100)
    return round(ev, 2)


def find_odds_for_game(odds_data, home_team, away_team):
    for g in odds_data.get("games", []):
        if g.get("home_team") == home_team and g.get("away_team") == away_team:
            return g
    return None


def main():
    games_data = load_json(GAMES_PATH, {"date": datetime.date.today().isoformat(), "games": []})
    matchup_data = load_json(MATCHUP_PATH, {})
    odds_data = load_json(ODDS_PATH, {"games": []})

    predictions = []

    for g in games_data.get("games", []):
        game_matchups = matchup_data.get(str(g["game_id"]), [])

        home_pitcher_matchups = [m for m in game_matchups if m.get("pitcher_id") == g.get("home_pitcher_id")]
        away_pitcher_matchups = [m for m in game_matchups if m.get("pitcher_id") == g.get("away_pitcher_id")]

        home_pscore = pitcher_score(g.get("home_pitcher_l5"))
        away_pscore = pitcher_score(g.get("away_pitcher_l5"))

        home_off = offense_score(g.get("home_team_offense"))
        away_off = offense_score(g.get("away_team_offense"))

        # el equipo home gana con: su pitcher fuerte + ofensiva propia + debilidad del pitcher rival
        home_raw = (home_pscore * 0.5) + (home_off * 0.25) + ((1 - away_pscore) * 0.25)
        away_raw = (away_pscore * 0.5) + (away_off * 0.25) + ((1 - home_pscore) * 0.25)

        home_adj, home_matchup_ok = matchup_adjustment(away_pitcher_matchups)  # bateo del AWAY vs pitcher HOME
        away_adj, away_matchup_ok = matchup_adjustment(home_pitcher_matchups)  # bateo del HOME vs pitcher AWAY

        home_raw += home_adj
        away_raw += away_adj

        home_raw += HOME_ADV

        total = home_raw + away_raw
        home_prob = round(home_raw / total, 4) if total > 0 else 0.5
        away_prob = round(1 - home_prob, 4)

        odds_game = find_odds_for_game(odds_data, g["home_team"], g["away_team"])
        home_market, away_market = None, None
        home_edge, away_edge = None, None
        home_ev, away_ev = None, None

        if odds_game:
            odds = odds_game.get("odds", {})
            home_odds_entry = odds.get(g["home_team"])
            away_odds_entry = odds.get(g["away_team"])
            if home_odds_entry and away_odds_entry:
                home_market, away_market = devig(
                    home_odds_entry["implied_prob"], away_odds_entry["implied_prob"]
                )
                home_edge = round(home_prob - home_market, 4)
                away_edge = round(away_prob - away_market, 4)
                home_ev = american_ev_per_100(home_prob, home_odds_entry["american"])
                away_ev = american_ev_per_100(away_prob, away_odds_entry["american"])

        predictions.append({
            "game_id": g["game_id"],
            "game_date": g["game_date"],
            "home_team": g["home_team"],
            "away_team": g["away_team"],
            "home_pitcher": g.get("home_pitcher"),
            "away_pitcher": g.get("away_pitcher"),
            "home_pitcher_era_l5": (g.get("home_pitcher_l5") or {}).get("era_l5"),
            "away_pitcher_era_l5": (g.get("away_pitcher_l5") or {}).get("era_l5"),
            "model_prob_home": home_prob,
            "model_prob_away": away_prob,
            "market_prob_home": home_market,
            "market_prob_away": away_market,
            "edge_home": home_edge,
            "edge_away": away_edge,
            "ev_home": home_ev,
            "ev_away": away_ev,
            "matchup_sample_ok_home": home_matchup_ok,
            "matchup_sample_ok_away": away_matchup_ok,
            "matchup_detail": {
                "home_pitcher_vs_away_batters": away_pitcher_matchups,
                "away_pitcher_vs_home_batters": home_pitcher_matchups,
            },
        })

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump({
            "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
            "date": games_data.get("date"),
            "games": predictions,
        }, f, indent=2, ensure_ascii=False)

    print(f"Guardado en {OUTPUT_PATH} ({len(predictions)} juegos)")


if __name__ == "__main__":
    main()
