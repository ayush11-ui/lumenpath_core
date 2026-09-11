"""HTTP endpoints for LumenPath.

API surface
-----------
  GET  /                     →  renders the single-page map UI (index.html)
  GET  /api/routes/          →  "safest" + "fastest" routes for start/end coords
  GET  /api/safe-zones/      →  all safety landmark pins
  GET  /api/incidents/       →  reported incident markers
  POST /api/incidents/       →  report a new incident (used by the map UI)
  POST /api/sessions/        →  start a live-share TrackingSession
  GET  /api/sessions/<uuid>/ →  poll a live-share TrackingSession
"""

import json
import math
import random
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST
from .models import StreetSegment, SafeZone, Incident, TrackingSession
from .utils import resolve_route


# ---------------------------------------------------------------------------
# HTML page
# ---------------------------------------------------------------------------
@require_GET
def index(request):
    """Render the mobile-first map shell (Tailwind + Leaflet)."""
    return render(request, "index.html")


# ---------------------------------------------------------------------------
# Routing API
# ---------------------------------------------------------------------------
@require_GET
def routes_api(request):
    """Return both routing profiles for a start/end coordinate pair.

    Query params: start_lat, start_lng, end_lat, end_lng

    Response shape (on success):
        {
          "status": "ok",
          "safest":  {profile, path, distance_meters, duration_minutes, safety_index, ...},
          "fastest": {profile, path, distance_meters, duration_minutes, safety_index, ...}
        }
    """
    try:
        start_lat = float(request.GET.get("start_lat"))
        start_lng = float(request.GET.get("start_lng"))
        end_lat = float(request.GET.get("end_lat"))
        end_lng = float(request.GET.get("end_lng"))
    except (TypeError, ValueError):
        return JsonResponse(
            {
                "status": "error",
                "message": "Provide numeric start_lat, start_lng, end_lat, end_lng query params.",
            },
            status=400,
        )

    # Validate coordinate ranges (lat in [-90, 90], lng in [-180, 180]).
    for label, value in (("start_lat", start_lat), ("end_lat", end_lat)):
        if not -90 <= value <= 90:
            return JsonResponse(
                {"status": "error", "message": f"{label} out of range."}, status=400
            )
    for label, value in (("start_lng", start_lng), ("end_lng", end_lng)):
        if not -180 <= value <= 180:
            return JsonResponse(
                {"status": "error", "message": f"{label} out of range."}, status=400
            )

    safest = resolve_route(start_lat, start_lng, end_lat, end_lng, profile="safest")
    fastest = resolve_route(start_lat, start_lng, end_lat, end_lng, profile="fastest")

    if "error" in safest and "error" in fastest:
        return JsonResponse({"status": "error", "message": safest["error"]}, status=500)

    return JsonResponse({"status": "ok", "safest": safest, "fastest": fastest})


# ---------------------------------------------------------------------------
# Safe zones
# ---------------------------------------------------------------------------
@require_GET
def safe_zones_api(request):
    """Return safe-zone pins (Police / Hospital / 24/7 Store)."""
    zones = SafeZone.objects.all().values("id", "name", "zone_type", "lat", "lng")
    return JsonResponse({"status": "ok", "safe_zones": list(zones)})


# ---------------------------------------------------------------------------
# Street segments (drives the client-side safety heatmap)
# ---------------------------------------------------------------------------
@require_GET
def segments_api(request):
    """Return all street segments with the safety attributes the frontend uses.

    This is the only extra dataset endpoint beyond the spec (besides incidents
    and sessions); it powers the "Safety Heatmap" dock toggle with real data.
    """
    segments = StreetSegment.objects.all().values(
        "id",
        "name",
        "start_lat",
        "start_lng",
        "end_lat",
        "end_lng",
        "lighting_score",
        "crime_rate",
        "distance_meters",
    )
    return JsonResponse({"status": "ok", "segments": list(segments)})


# ---------------------------------------------------------------------------
# Incidents
# ---------------------------------------------------------------------------
@require_GET
def incidents_api(request):
    """Return reported incident markers."""
    incidents = Incident.objects.all().values(
        "id", "type", "severity", "description", "lat", "lng", "reported_at"
    )
    return JsonResponse({"status": "ok", "incidents": list(incidents)})


@csrf_exempt
@require_POST
def report_incident(request):
    """Create a new incident (body: JSON {type, severity, lat, lng, description})."""
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"status": "error", "message": "Invalid JSON body."}, status=400)

    try:
        incident = Incident.objects.create(
            type=payload.get("type", "Reported"),
            severity=payload.get("severity", "Medium"),
            lat=float(payload["lat"]),
            lng=float(payload["lng"]),
            description=payload.get("description", "")[:500],
        )
    except (KeyError, TypeError, ValueError):
        return JsonResponse(
            {"status": "error", "message": "Provide numeric 'lat' and 'lng'."}, status=400
        )

    return JsonResponse(
        {
            "status": "ok",
            "incident": {
                "id": incident.id,
                "type": incident.type,
                "severity": incident.severity,
                "lat": incident.lat,
                "lng": incident.lng,
            },
        },
        status=201,
    )


# ---------------------------------------------------------------------------
# Live tracking sessions ("Share Live Track")
# ---------------------------------------------------------------------------
@csrf_exempt
@require_POST
def create_session(request):
    """Start a TrackingSession for the live-track share feature."""
    try:
        payload = json.loads(request.body.decode("utf-8"))
        session = TrackingSession.objects.create(
            current_lat=float(payload.get("current_lat")),
            current_lng=float(payload.get("current_lng")),
            destination_lat=float(payload["destination_lat"]),
            destination_lng=float(payload["destination_lng"]),
        )
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return JsonResponse(
            {"status": "error", "message": "Provide destination_lat/destination_lng."},
            status=400,
        )

    return JsonResponse(
        {
            "status": "ok",
            "session_token": str(session.session_token),
            "url": f"/api/sessions/{session.session_token}/",
        },
        status=201,
    )


@require_GET
def get_session(request, token):
    """Poll a TrackingSession's current position."""
    try:
        session = TrackingSession.objects.get(session_token=token)
    except TrackingSession.DoesNotExist:
        return JsonResponse({"status": "error", "message": "Session not found."}, status=404)

    return JsonResponse(
        {
            "status": "ok",
            "active": session.active,
            "current_lat": session.current_lat,
            "current_lng": session.current_lng,
            "destination_lat": session.destination_lat,
            "destination_lng": session.destination_lng,
        }
    )


# ---------------------------------------------------------------------------
# Dynamic safety heatmap
# ---------------------------------------------------------------------------
@require_GET
def dynamic_heatmap_api(request):
    """Generate ~30 randomized safety probes around the requested center.

    Query params: lat, lng, radius_m (optional, default 500).

    Each probe carries a ``safety_level``:
        1 = Safe (green) · 2 = Moderate (yellow) · 3 = Unsafe (red)

    The live overlay simulates a crowd-sourced "night-risk" field for the
    presentation demo; a production build would source this from real reports.
    """
    try:
        center_lat = float(request.GET.get("lat"))
        center_lng = float(request.GET.get("lng"))
    except (TypeError, ValueError):
        return JsonResponse(
            {"status": "error", "message": "Provide numeric 'lat' and 'lng'."},
            status=400,
        )

    try:
        radius_m = float(request.GET.get("radius_m", 500))
    except (TypeError, ValueError):
        radius_m = 500.0

    point_count = 30
    probes = []

    for _ in range(point_count):
        # Uniform random offset inside a circle around the center.
        distance = random.uniform(0.0, radius_m)
        bearing = random.uniform(0, 2 * math.pi)

        # Approximate meters → degrees (valid for small distances).
        d_lat = (distance * math.cos(bearing)) / 111320.0
        d_lng = (distance * math.sin(bearing)) / (
            111320.0 * math.cos(math.radians(center_lat))
        )

        # Weighted draw so the demo looks organic (mostly safe/moderate).
        roll = random.random()
        if roll < 0.45:
            safety_level = 1
        elif roll < 0.80:
            safety_level = 2
        else:
            safety_level = 3

        probes.append(
            {
                "lat": round(center_lat + d_lat, 6),
                "lng": round(center_lng + d_lng, 6),
                "safety_level": safety_level,
            }
        )

    return JsonResponse(
        {
            "status": "ok",
            "center": {"lat": center_lat, "lng": center_lng},
            "count": point_count,
            "probes": probes,
        }
    )