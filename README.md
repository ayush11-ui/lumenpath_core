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
- **Google Sign-In** — django-allauth based OAuth login with a profile drawer (avatar, name, email)
- **Profile Drawer** — Mom auto-share toggle, CCTV priority toggle, "avoid unlit alleys" toggle, and one-tap SOS
- **Dynamic Safety Heatmap** — Live heatmap rendered from a probe-level API (`/api/dynamic-heatmap/`)
- **Expandable Bottom Sheet** — Safest/Fastest tab switcher with safety index meter, ETA, distance, and block count

---

## Quick Start

```bash
# 1. Clone the repo
git clone https://github.com/ayush11-ui/lumenpath_core.git
cd lumenpath_core

# 2. Create virtual environment and install dependencies
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt

# 3. Run migrations and seed demo data
python manage.py migrate
python manage.py seed_data

# 4. Start the dev server
python manage.py runserver 8099

# 5. Open in browser
# http://127.0.0.1:8099/
```

> **Google login setup (env vars):** Copy `.env.example` to `.env` and set `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` (Authorized redirect URI: `http://127.0.0.1:8099/accounts/google/login/callback/`). The provider is configured directly from environment variables, so no Django admin setup is required. Alternatively, you can still register the app in Django admin at `/admin/socialaccount/socialapp/` (SITE: `example.com`).

### Environment Variables

All runtime configuration is read from `.env` (loaded automatically, no extra dependency):

| Variable | Default | Purpose |
|----------|---------|---------|
| `SECRET_KEY` | (dev fallback) | Django secret key |
| `DEBUG` | `True` | Django debug mode (`0/1/true/false`) |
| `ALLOWED_HOSTS` | `*` | Comma-separated allowed hosts |
| `GOOGLE_CLIENT_ID` | *(empty)* | Google OAuth client ID |
| `GOOGLE_CLIENT_SECRET` | *(empty)* | Google OAuth client secret |

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
| `GET` | `/api/routes/?start_lat=&start_lng=&end_lat=&end_lng=` | Both safest and fastest routes. Optional `avoid_unlit=1` and `cctv=1` preferences |
| `GET` | `/api/safe-zones/` | All safety landmark pins (Police, Hospital, 24/7 Store) |
| `GET` | `/api/segments/` | All street segments with lighting/crime scores (drives heatmap) |
| `GET` | `/api/dynamic-heatmap/?lat=&lng=&zoom=` | Segment-probe safety heatmap (level 1 safe / 2 moderate / 3 unsafe) |
| `GET` | `/api/incidents/` | Reported incident markers |
| `POST` | `/api/incidents/report/` | Report a new incident (JSON body: type, severity, lat, lng) |
| `POST` | `/api/sessions/` | Create a live-share tracking session |
| `GET` | `/api/sessions/<token>/` | Poll a tracking session's current position (UUID or string token) |
| `POST` | `/api/sessions/<token>/update/` | Update a tracking session's current position (JSON body: lat, lng) |

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

User preferences adjust the safest profile:
- `avoid_unlit=1` — adds a ×6 distance penalty to dark segments (lighting score below 4) + 4.0 SURROUNDING penalty
- `cctv=1` — ×0.82 discount on all segments with CCTV coverage

### Safety Index

A 0–100 score combining normalised lighting and crime averages along the chosen route, clamped to the 0–100 range:
```
safety_index = (lighting_norm * 0.55 + (1 - crime_norm) * 0.45) * 100
```

Walking pace is assumed at 80 m/min for the ETA (reported as `duration_minutes`).

---

## Demo Data

The `seed_data` command creates an 8×8 block grid (127 connected street segments) centred on Buenos Aires coordinates, with:
- Randomly distributed lighting (0–10) and crime (1–10) scores
- Deterministic hazard clustering so some blocks are noticeably darker/riskier
- ~45% of segments flagged with CCTV coverage (`has_cctv`)
- 5 safe zones (2 Hospitals, 1 Police station, 2 24/7 Stores)
- 3 seeded incident markers

The `seed_data` command is idempotent in the sense that re-running wipes the existing demo rows and rebuilds the same deterministic dataset (note: incidents reported through the UI are also reset).

---

## Tech Stack

- **Backend**: Django 5.2 + SQLite3 (zero config)
- **Auth**: django-allauth (Google OAuth)
- **Frontend**: Tailwind CSS (CDN) + Leaflet.js + Leaflet.heat (CDN)
- **Tiles**: CartoDB Positron (light) tiles with proper attribution (OSM + CARTO)
- **Algorithm**: Custom Dijkstra with heapq priority queue

---

## License

MIT
