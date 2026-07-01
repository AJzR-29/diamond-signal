# DiamondSignal — MLB Predictive Edge

App de predicción MLB enfocada en datos de jugador (ERA L5 del abridor, ofensiva de
equipo, historial real bateador-vs-pitcher via Statcast). Las cuotas de casas de
apuestas solo se usan al final para medir edge, no para decidir la predicción.

## Fuentes de datos

- **MLB Stats API** (oficial, sin key) — calendario, pitchers probables, ERA L5, ofensiva de equipo
- **Baseball Savant** (Statcast, sin key) — historial bateador-vs-pitcher, acceso directo sin `pybaseball`
- **TheOddsAPI** (requiere key) — cuotas moneyline, solo para calcular edge/EV

## Estructura

```
diamond-signal/
├── index.html              # frontend (dashboard)
├── fetch_mlb_data.py        # calendario + pitchers + ofensiva
├── fetch_matchup.py         # matchup bateador-vs-pitcher (Baseball Savant)
├── fetch_odds.py            # cuotas (TheOddsAPI)
├── build_predictions.py     # combina todo en el modelo final
├── data/
│   └── predictions.json     # lo que consume el frontend (se regenera solo)
└── .github/workflows/
    └── update.yml           # corre todo el pipeline diario
```

## Setup en GitHub

### 1. Crear el repo
Sube esta carpeta completa a un repo nuevo en GitHub (puede ser público o privado,
GitHub Pages funciona con ambos si tienes cuenta Pro/Team, o público si es cuenta free).

### 2. Configurar el secret de la API de cuotas
Ve a **Settings → Secrets and variables → Actions → New repository secret**:
- Name: `ODDS_API_KEY`
- Value: tu key de TheOddsAPI

### 3. Activar GitHub Pages
**Settings → Pages → Source: Deploy from a branch → main → / (root)**

Tu app quedará en `https://tuusuario.github.io/diamond-signal/`

### 4. Correr el Action por primera vez
El Action corre automático todos los días a las 11:00 UTC (~6-7am Panamá), pero
puedes forzar la primera corrida manualmente:
**Actions → Update MLB Predictions → Run workflow**

## Correr localmente (para probar antes de subir)

```bash
pip install --break-system-packages requests  # si decides usar requests en vez de urllib

python fetch_mlb_data.py
python fetch_matchup.py
export ODDS_API_KEY="tu_key_aqui"
python fetch_odds.py
python build_predictions.py
```

Luego abre `index.html` directo en el navegador (o `python -m http.server` para
evitar restricciones de fetch() en `file://`).

## Notas sobre el modelo (v1)

Es un modelo heurístico transparente, no un modelo estadístico entrenado:

- **Pitcher score**: 65% ERA L5, 35% IP promedio por arranque
- **Team offense score**: 50% runs/juego, 50% OPS
- **Matchup adjustment**: hasta ±15%, SOLO si hay ≥10 PA históricos agregados
  entre los bateadores titulares y el pitcher rival (si no, no se aplica —
  evita que muestras chicas metan ruido)
- **Home advantage**: +1.8% fijo al equipo local
- **Edge**: probabilidad del modelo menos probabilidad de mercado (sin vig)

Este modelo va a mejorar en precisión conforme acumules historial real de
resultados — ese es el siguiente paso natural (guardar picks vs. resultados,
por ejemplo en Supabase, para poder calibrar los pesos con datos en vez de
suposiciones).

## Limitaciones conocidas de v1

- `fetch_matchup.py` usa el endpoint público no oficial de Baseball Savant
  (`statcast_search/csv`) — no tiene términos de uso formales, así que trátalo
  con cortesía (ya tiene `time.sleep()` entre requests) y no lo satures.
- El matchup se calcula contra los 9 bateadores con más plate appearances de la
  temporada, no contra el lineup confirmado del día (no está disponible con
  suficiente anticipación para automatizar).
- `TOP_N_BATTERS` y `MIN_PA_FOR_SIGNAL` son ajustables en `fetch_matchup.py` y
  `build_predictions.py` respectivamente.
