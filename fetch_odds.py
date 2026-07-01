"""
fetch_odds.py
Trae cuotas moneyline de MLB via TheOddsAPI.
La key se pasa por variable de entorno ODDS_API_KEY (configurada como GitHub Secret).

Salida: data/odds_data.json
"""

import json
import os
import urllib.request
import urllib.parse
import urllib.error

ODDS_API_URL = "https://api.the-odds-api.com/v4/sports/baseball_mlb/odds"
OUTPUT_PATH = "data/odds_data.json"


def american_to_prob(odds):
    """Convierte cuota americana a probabilidad implicita."""
    odds = float(odds)
    if odds > 0:
        return round(100 / (odds + 100), 4)
    return round(-odds / (-odds + 100), 4)


def main():
    api_key = os.environ.get("ODDS_API_KEY")
    if not api_key:
        print("[error] Falta la variable de entorno ODDS_API_KEY.")
        with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
            json.dump({"games": []}, f, indent=2)
        return

    params = {
        "apiKey": api_key,
        "regions": "us",
        "markets": "h2h",
        "oddsFormat": "american",
    }
    url = ODDS_API_URL + "?" + urllib.parse.urlencode(params)

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "DiamondSignal/1.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError) as e:
        print(f"[error] fallo TheOddsAPI: {e}")
        with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
            json.dump({"games": []}, f, indent=2)
        return

    games = []
    for g in raw:
        best_odds = {}
        for book in g.get("bookmakers", []):
            for market in book.get("markets", []):
                if market.get("key") != "h2h":
                    continue
                for outcome in market.get("outcomes", []):
                    name = outcome["name"]
                    price = outcome["price"]
                    if name not in best_odds or price > best_odds[name]:
                        best_odds[name] = price

        games.append({
            "home_team": g.get("home_team"),
            "away_team": g.get("away_team"),
            "commence_time": g.get("commence_time"),
            "odds": {
                team: {
                    "american": price,
                    "implied_prob": american_to_prob(price),
                }
                for team, price in best_odds.items()
            },
        })

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump({"games": games}, f, indent=2, ensure_ascii=False)

    print(f"Guardado en {OUTPUT_PATH} ({len(games)} juegos con cuotas)")


if __name__ == "__main__":
    main()
