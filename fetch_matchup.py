"""
fetch_matchup.py
Trae el historial bateador-vs-pitcher directo del endpoint publico de Baseball Savant
(statcast_search), evitando pybaseball y su bug de "boolean value of NA is ambiguous".

Para cada pitcher probable del dia, identifica a los bateadores titulares mas frecuentes
del equipo rival (por plate appearances en la temporada) y trae su historial de
enfrentamientos directos contra ese pitcher.

Salida: data/matchup_data.json
"""

import json
import csv
import io
import time
import urllib.request
import urllib.parse
import urllib.error
import datetime

STATSAPI = "https://statsapi.mlb.com/api/v1"
SAVANT_SEARCH = "https://baseballsavant.mlb.com/statcast_search/csv"
INPUT_PATH = "data/mlb_games.json"
OUTPUT_PATH = "data/matchup_data.json"

MIN_PA_FOR_SIGNAL = 10  # por debajo de esto, la muestra es ruido, no senal
TOP_N_BATTERS = 9


def get_json(url, retries=3, delay=2):
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "DiamondSignal/1.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError) as e:
            print(f"    [warn] fallo request ({attempt+1}/{retries}): {e}")
            time.sleep(delay)
    return None


def get_top_batters(team_id, season, limit=TOP_N_BATTERS):
    """Bateadores del equipo con mas plate appearances en la temporada actual."""
    url = f"{STATSAPI}/teams/{team_id}/roster?rosterType=active"
    roster = get_json(url)
    if not roster:
        return []

    player_ids = [p["person"]["id"] for p in roster.get("roster", [])
                  if p.get("position", {}).get("abbreviation") not in ("P",)]

    batters = []
    for pid in player_ids:
        stat_url = f"{STATSAPI}/people/{pid}/stats?stats=season&group=hitting&season={season}"
        data = get_json(stat_url)
        try:
            stat = data["stats"][0]["splits"][0]["stat"]
            pa = int(stat.get("plateAppearances", 0))
        except (KeyError, IndexError, TypeError):
            pa = 0
        if pa > 0:
            batters.append({"id": pid, "pa_season": pa})
        time.sleep(0.15)

    batters.sort(key=lambda b: b["pa_season"], reverse=True)
    return batters[:limit]


def get_batter_name(batter_id):
    data = get_json(f"{STATSAPI}/people/{batter_id}")
    try:
        return data["people"][0]["fullName"]
    except (KeyError, IndexError, TypeError):
        return f"Player {batter_id}"


def fetch_bvp_csv(batter_id, pitcher_id):
    """Trae el historial completo de enfrentamientos directos via Statcast Search CSV."""
    params = {
        "batters_lookup[]": batter_id,
        "pitchers_lookup[]": pitcher_id,
        "hfGT": "R|",       # solo temporada regular
        "player_type": "batter",
        "type": "details",
    }
    url = SAVANT_SEARCH + "?" + urllib.parse.urlencode(params)

    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "DiamondSignal/1.0"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                text = resp.read().decode("utf-8")
                return list(csv.DictReader(io.StringIO(text)))
        except (urllib.error.URLError, urllib.error.HTTPError) as e:
            print(f"      [warn] fallo Savant ({attempt+1}/3): {e}")
            time.sleep(2)
    return []


def summarize_matchup(rows):
    """Agrega filas pitch-by-pitch de Savant a un resumen bateador-vs-pitcher."""
    if not rows:
        return {"pa": 0, "sample_size_ok": False}

    # cada plate appearance completa termina con un evento (events != vacio)
    pa_events = [r for r in rows if r.get("events")]
    pa_count = len(pa_events)

    hits = sum(1 for r in pa_events if r.get("events") in
               ("single", "double", "triple", "home_run"))
    hr = sum(1 for r in pa_events if r.get("events") == "home_run")
    k = sum(1 for r in pa_events if r.get("events") == "strikeout")
    bb = sum(1 for r in pa_events if r.get("events") == "walk")

    exit_velos = [float(r["launch_speed"]) for r in rows
                  if r.get("launch_speed") not in (None, "", "null")]
    avg_ev = round(sum(exit_velos) / len(exit_velos), 1) if exit_velos else None

    ab = pa_count - bb  # aproximado, no descuenta sac flies/hbp para mantenerlo simple

    return {
        "pa": pa_count,
        "ab_approx": ab,
        "hits": hits,
        "hr": hr,
        "k": k,
        "bb": bb,
        "avg_approx": round(hits / ab, 3) if ab > 0 else None,
        "avg_exit_velo": avg_ev,
        "sample_size_ok": pa_count >= MIN_PA_FOR_SIGNAL,
    }


def main():
    try:
        with open(INPUT_PATH, encoding="utf-8") as f:
            games_data = json.load(f)
    except FileNotFoundError:
        print(f"No existe {INPUT_PATH}. Corre fetch_mlb_data.py primero.")
        return

    season = datetime.date.today().year
    all_matchups = {}

    for g in games_data.get("games", []):
        matchups_for_game = []

        pairs = [
            (g.get("away_team_id"), g.get("away_team"), g.get("home_pitcher_id"), g.get("home_pitcher")),
            (g.get("home_team_id"), g.get("home_team"), g.get("away_pitcher_id"), g.get("away_pitcher")),
        ]

        for team_id, team_name, pitcher_id, pitcher_name in pairs:
            if not pitcher_id or not team_id:
                continue

            print(f"  Matchups: {team_name} bateadores vs {pitcher_name}")
            top_batters = get_top_batters(team_id, season)

            for b in top_batters:
                name = get_batter_name(b["id"])
                rows = fetch_bvp_csv(b["id"], pitcher_id)
                summary = summarize_matchup(rows)
                summary.update({
                    "batter_id": b["id"],
                    "batter_name": name,
                    "pitcher_id": pitcher_id,
                    "pitcher_name": pitcher_name,
                })
                matchups_for_game.append(summary)
                time.sleep(0.5)  # cortesia con Savant, endpoint no oficial

        all_matchups[str(g["game_id"])] = matchups_for_game

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(all_matchups, f, indent=2, ensure_ascii=False)

    print(f"Guardado en {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
