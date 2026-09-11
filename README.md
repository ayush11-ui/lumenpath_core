# LumenPath — Night-Safety Urban Pedestrian Routing Engine

A full-stack Django MVP for a **night-safety urban pedestrian routing engine** that recommends both the fastest and safest walking routes through a city at night.

Built with Django 5.2, Leaflet.js, Tailwind CSS, and a custom Dijkstra pathfinding engine.

---

## Features

- **Dual Routing Engine** — Custom Dijkstra solver with two cost profiles:
  - *Fastest Route*: pure distance minimization
  - *Safest Route*: penalized by lighting score and crime rate to favour well-lit, low-crime streets
- **Interactive Map UI** — Full-screen Leaflet.js map with CartoDB Positron tiles, pulsing start/end markers, and glowing polyline routes
- **Safety Heatmap Overlay** — Real-time heatmap built from segment-level lighting and crime data
- **Safe Zone Pins** — Toggle Police stations, Hospitals, and 24/7 Stores on/off
- **Report Incidents** — Click the map to report streetlight outages, suspicious activity, or poor pavement
- **Live Navigation Simulation** — "Start Safe Navigation" animates a user dot walking the safest path
- **Share Live Track** — Create a shareable tracking session via UUID endpoint
- **Expandable Bottom Sheet** — Safest/Fastest tab switcher with safety index meter, ETA, distance, and block count

---

## Quick Start

```bash
# 1. Clone the repo
git clone https://github.com/ayush11-ui/lumenpath_core.git
cd lumenpath_core

# 2. Create virtual environment and install Django
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install django

# 3. Run migrations and seed demo data
python manage.py migrate
python manage.py seed_data

# 4. Start the dev server
python manage.py runserver 8099

# 5. Open in browser
# http://127.0.0.1:8099/
```

---

## Project Structure

```
lumenpath_core/
├── lumenpath_core/        # Django project settings
│   ├── settings.py
│   ├── urls.py
│   └── wsgi.py
├── routing/               # Main application
│   ├── models.py          # StreetSegment, SafeZone, Incident, TrackingSession
│   ├── utils.py           # Dijkstra pathfinding engine
│   ├── views.py           # JSON API endpoints + HTML view
│   ├── urls.py            # API route wiring
│   ├── templates/
│   │   └── index.html     # Full Tailwind + Leaflet SPA
│   ├── management/
│   │   └── commands/
│   │       └── seed_data.py   # Populates 127 segments, 5 zones, 3 incidents
│   └── static/
├── db.sqlite3             # Pre-seeded SQLite database
├── manage.py
└── requirements.txt
```

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/` | Map UI (single-page app) |
| `GET` | `/api/routes/?start_lat=&start_lng=&end_lat=&end_lng=` | Returns both safest and fastest routes with polylines, distance, ETA, safety index |
| `GET` | `/api/safe-zones/` | All safety landmark pins (Police, Hospital, 24/7 Store) |
| `GET` | `/api/segments/` | All street segments with lighting/crime scores (drives heatmap) |
| `GET` | `/api/incidents/` | Reported incident markers |
| `POST` | `/api/incidents/report/` | Report a new incident (JSON body: type, severity, lat, lng) |
| `POST` | `/api/sessions/` | Create a live-share tracking session |
| `GET` | `/api/sessions/<uuid>/` | Poll a tracking session's current position |

---

## Routing Engine

The core routing engine in `routing/utils.py` implements Dijkstra's algorithm over a graph built from `StreetSegment` records. The graph is treated as **undirected** (pedestrians can walk both directions).

### Cost Functions

**Fastest Route:**
```
weight = distance_meters
```

**Safest Route:**
```
weight = distance_meters * (1 + (10 - lighting_score) * 0.4 + crime_rate * 0.3)
```

This penalises dark streets (low `lighting_score`) and high-crime streets (high `crime_rate`), causing the solver to route through better-lit, safer corridors even if the path is slightly longer.

### Safety Index

A 0–100 score combining normalised lighting and crime averages along the chosen route:
```
safety_index = (lighting_norm * 0.55 + crime_norm * 0.45) * 100
```

---

## Demo Data

The `seed_data` command creates an 8×8 block grid (127 connected street segments) centred on Buenos Aires coordinates, with:
- Randomly distributed lighting (1–10) and crime (1–10) scores
- Deterministic hazard clustering so some blocks are noticeably darker/riskier
- 5 safe zones (2 Hospitals, 1 Police station, 2 24/7 Stores)
- 3 seeded incident markers

---

## Tech Stack

- **Backend**: Django 5.2 + SQLite3 (zero config)
- **Frontend**: Tailwind CSS (CDN) + Leaflet.js (CDN)
- **Tiles**: CartoDB Positron (light basemap)
- **Algorithm**: Custom Dijkstra with heapq priority queue

---

## License

MIT
