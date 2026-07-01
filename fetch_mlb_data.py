"""
fetch_mlb_data.py
Trae el calendario del dia, pitchers probables, ERA de los ultimos 5 arranques (L5),
IP promedio por arranque, y promedios ofensivos de equipo desde la MLB Stats API oficial.
No requiere API key.

Salida: data/mlb_games.json
"""

import json
import datetime
import time
import urllib.request
import urllib.error

STATSAPI = "https://statsapi.mlb.com/api/v1"
OUTPUT_PATH = "data/mlb_games.json"


def get_json(url, retries=3, delay=2):
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "DiamondSignal/1.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError) as e:
            print(f"  [warn] fallo request ({attempt+1}/{retries}): {e}")
            time.sleep(delay)
    return None


def get_today_schedule(date_str):
    url = f"{STATSAPI}/schedule?sportId=1&date={date_str}&hydrate=probablePitcher,team"
    data = get_json(url)
    if not data:
        return []

    games = []
    for date_block in data.get("dates", []):
        for g in date_block.get("games", []):
            teams = g.get("teams", {})
            home = teams.get("home", {})
            away = teams.get("away", {})
            games.append({
                "game_id": g.get("gamePk"),
                "game_date": g.get("gameDate"),
                "status": g.get("status", {}).get("detailedState"),
                "home_team": home.get("team", {}).get("name"),
                "home_team_id": home.get("team", {}).get("id"),
                "away_team": away.get("team", {}).get("name"),
                "away_team_id": away.get("team", {}).get("id"),
                "home_pitcher": home.get("probablePitcher", {}).get("fullName"),
                "home_pitcher_id": home.get("probablePitcher", {}).get("id"),
                "away_pitcher": away.get("probablePitcher", {}).get("fullName"),
                "away_pitcher_id": away.get("probablePitcher", {}).get("id"),
            })
    return games


def get_pitcher_l5(pitcher_id, season):
    """Ultimos 5 arranques: ERA por arranque, IP por arranque."""
    if not pitcher_id:
        return None
    url = f"{STATSAPI}/people/{pitcher_id}/stats?stats=gameLog&group=pitching&season={season}"
    data = get_json(url)
    if not data:
        return None

    try:
        splits = data["stats"][0]["splits"]
    except (KeyError, IndexError):
        return None

    starts = [s for s in splits if s.get("stat", {}).get("gamesStarted", 0) == "1"
              or s.get("stat", {}).get("gamesStarted", 0) == 1]
    starts = sorted(starts, key=lambda s: s.get("date", ""), reverse=True)[:5]

    if not starts:
        return None

    era_values, ip_values, results = [], [], []
    for s in starts:
        stat = s.get("stat", {})
        er = float(stat.get("earnedRuns", 0))
        ip_str = stat.get("inningsPitched", "0.0")
        ip = _ip_to_float(ip_str)
        era = (er * 9 / ip) if ip > 0 else 0
        era_values.append(round(era, 2))
        ip_values.append(ip)
        results.append({
            "date": s.get("date"),
            "opponent": s.get("opponent", {}).get("name"),
            "ip": ip,
            "er": er,
            "era_game": round(era, 2),
            "so": stat.get("strikeOuts", 0),
            "bb": stat.get("baseOnBalls", 0),
        })

    total_er = sum(float(s.get("stat", {}).get("earnedRuns", 0)) for s in starts)
    total_ip = sum(ip_values)
    era_l5 = round((total_er * 9 / total_ip), 2) if total_ip > 0 else None
    ip_avg = round(total_ip / len(starts), 2) if starts else None

    return {
        "era_l5": era_l5,
        "ip_avg": ip_avg,
        "starts": results,
    }


def _ip_to_float(ip_str):
    """MLB reporta '6.1' como 6 y 1/3 innings (no 6.1 decimal real)."""
    try:
        if "." in str(ip_str):
            whole, frac = str(ip_str).split(".")
            frac_map = {"0": 0.0, "1": 1 / 3, "2": 2 / 3}
            return float(whole) + frac_map.get(frac, 0.0)
        return float(ip_str)
    except (ValueError, TypeError):
        return 0.0


def get_team_offense(team_id, season):
    """Promedios ofensivos de equipo (runs por juego, OPS)."""
    url = f"{STATSAPI}/teams/{team_id}/stats?stats=season&group=hitting&season={season}"
    data = get_json(url)
    if not data:
        return None
    try:
        stat = data["stats"][0]["splits"][0]["stat"]
    except (KeyError, IndexError):
        return None

    games = int(stat.get("gamesPlayed", 1)) or 1
    runs = int(stat.get("runs", 0))
    return {
        "runs_per_game": round(runs / games, 2),
        "avg": stat.get("avg"),
        "ops": stat.get("ops"),
    }


def main():
    today = datetime.date.today().isoformat()
    season = datetime.date.today().year
    print(f"Buscando calendario MLB para {today}...")

    games = get_today_schedule(today)
    print(f"  {len(games)} juego(s) encontrado(s)")

    for g in games:
        print(f"  Procesando: {g['away_team']} @ {g['home_team']}")

        g["home_pitcher_l5"] = get_pitcher_l5(g["home_pitcher_id"], season)
        g["away_pitcher_l5"] = get_pitcher_l5(g["away_pitcher_id"], season)
        g["home_team_offense"] = get_team_offense(g["home_team_id"], season)
        g["away_team_offense"] = get_team_offense(g["away_team_id"], season)

        time.sleep(0.3)  # cortesia con la API

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump({"date": today, "games": games}, f, indent=2, ensure_ascii=False)

    print(f"Guardado en {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
