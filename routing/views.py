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
from django.http import JsonResponse
from django.shortcuts import render
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST
from .models import StreetSegment, SafeZone, Incident, TrackingSession
from .utils import resolve_route


def _exempt(view):
    """Decorator shorthand — applies CSRF exemption to a plain-function view."""
    return csrf_exempt(view)


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