"""HTTP endpoints for LumenPath.

API surface
-----------
  GET  /                                →  renders the single-page map UI
  GET  /api/routes/                     →  "safest" + "fastest" routes
  GET  /api/dynamic-heatmap/            →  real segment-derived safety probes
  GET  /api/safe-zones/                 →  safety landmark pins
  GET  /api/segments/                   →  all street segments
  GET  /api/incidents/                  →  reported incident markers
  POST /api/incidents/report/           →  report a new incident
  POST /api/sessions/                   →  start a live-share TrackingSession
  POST /api/sessions/<token>/update/    →  update a session's current position
  GET  /api/sessions/<token>/           →  poll a live-share TrackingSession
"""

import json
import math
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.core.exceptions import ValidationError
from django.views.decorators.http import require_GET, require_POST
from .models import StreetSegment, SafeZone, Incident, TrackingSession
from .utils import resolve_route, segment_safety_score


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
_LAT_RANGE = (-90.0, 90.0)
_LNG_RANGE = (-180.0, 180.0)
_ALLOWED_INCIDENT_TYPES = {"streetlight outage", "suspicious activity", "poor pavement"}
_ALLOWED_SEVERITIES = {"Low", "Medium", "High"}


def _valid_lat(v):
    return isinstance(v, float) and _LAT_RANGE[0] <= v <= _LAT_RANGE[1]


def _valid_lng(v):
    return isinstance(v, float) and _LNG_RANGE[0] <= v <= _LNG_RANGE[1]


# ---------------------------------------------------------------------------
# HTML page
# ---------------------------------------------------------------------------
@require_GET
def index(request):
    return render(request, "index.html")


# ---------------------------------------------------------------------------
# Routing API
# ---------------------------------------------------------------------------
@require_GET
def routes_api(request):
    """Return both routing profiles for a start/end coordinate pair.

    Optional query params:
        avoid_unlit=1    → penalise very dark streets (lighting <= 2)
        cctv=1           → favour CCTV-covered streets
    """
    try:
        start_lat = float(request.GET.get("start_lat"))
        start_lng = float(request.GET.get("start_lng"))
        end_lat = float(request.GET.get("end_lat"))
        end_lng = float(request.GET.get("end_lng"))
    except (TypeError, ValueError):
        return JsonResponse(
            {"status": "error",
             "message": "Provide numeric start_lat, start_lng, end_lat, end_lng query params."},
            status=400,
        )

    for label, value in (("start_lat", start_lat), ("end_lat", end_lat)):
        if not _valid_lat(value):
            return JsonResponse({"status": "error", "message": f"{label} out of range."},
                                status=400)
    for label, value in (("start_lng", start_lng), ("end_lng", end_lng)):
        if not _valid_lng(value):
            return JsonResponse({"status": "error", "message": f"{label} out of range."},
                                status=400)

    avoid = request.GET.get("avoid_unlit", "").lower() in ("1", "true", "yes")
    cctv = request.GET.get("cctv", "").lower() in ("1", "true", "yes")

    safest = resolve_route(start_lat, start_lng, end_lat, end_lng,
                           profile="safest", avoid_unlit=avoid, cctv_priority=cctv)
    fastest = resolve_route(start_lat, start_lng, end_lat, end_lng, profile="fastest")

    if "error" in safest and "error" in fastest:
        return JsonResponse({"status": "error", "message": safest["error"]}, status=500)
    if "error" in fastest:
        return JsonResponse({"status": "error",
                             "message": f"Fastest routing failed: {fastest['error']}"},
                            status=500)
    if "error" in safest:
        return JsonResponse({"status": "error",
                             "message": f"Safest routing failed: {safest['error']}"},
                            status=500)

    return JsonResponse({"status": "ok", "safest": safest, "fastest": fastest})


# ---------------------------------------------------------------------------
# Dynamic safety heatmap (segment-derived probes)
# ---------------------------------------------------------------------------
@require_GET
def dynamic_heatmap_api(request):
    """Generate safety probes from actual StreetSegment data near a center point.

    Query params: lat, lng, radius_m (optional, default 500).

    Each probe carries a ``safety_level``:
        1 = Safe (green) · 2 = Moderate (yellow) · 3 = Unsafe (red)
    derived from the segment's real lighting / crime scores.
    """
    try:
        center_lat = float(request.GET.get("lat"))
        center_lng = float(request.GET.get("lng"))
    except (TypeError, ValueError):
        return JsonResponse(
            {"status": "error", "message": "Provide numeric 'lat' and 'lng'."},
            status=400,
        )
    if not _valid_lat(center_lat) or not _valid_lng(center_lng):
        return JsonResponse({"status": "error", "message": "Coordinates out of range."},
                            status=400)

    try:
        radius_m = float(request.GET.get("radius_m", 500))
    except (TypeError, ValueError):
        radius_m = 500.0

    cos_lat = math.cos(math.radians(center_lat))
    probes = []
    for seg in StreetSegment.objects.all():
        mid_lat = (seg.start_lat + seg.end_lat) / 2.0
        mid_lng = (seg.start_lng + seg.end_lng) / 2.0
        dlat = (mid_lat - center_lat) * 111320.0
        dlng = (mid_lng - center_lng) * 111320.0 * cos_lat
        dist = math.sqrt(dlat * dlat + dlng * dlng)
        if dist > radius_m:
            continue

        score = segment_safety_score(seg)
        if score >= 0.70:
            safety_level = 1
        elif score >= 0.40:
            safety_level = 2
        else:
            safety_level = 3

        probes.append({
            "lat": round(mid_lat, 6),
            "lng": round(mid_lng, 6),
            "safety_level": safety_level,
        })

    return JsonResponse({
        "status": "ok",
        "center": {"lat": center_lat, "lng": center_lng},
        "count": len(probes),
        "probes": probes[:60],
    })


# ---------------------------------------------------------------------------
# Safe zones
# ---------------------------------------------------------------------------
@require_GET
def safe_zones_api(request):
    zones = SafeZone.objects.all().values("id", "name", "zone_type", "lat", "lng")
    return JsonResponse({"status": "ok", "safe_zones": list(zones)})


# ---------------------------------------------------------------------------
# Street segments
# ---------------------------------------------------------------------------
@require_GET
def segments_api(request):
    segments = StreetSegment.objects.all().values(
        "id", "name", "start_lat", "start_lng", "end_lat", "end_lng",
        "lighting_score", "crime_rate", "distance_meters", "has_cctv",
    )
    return JsonResponse({"status": "ok", "segments": list(segments)})


# ---------------------------------------------------------------------------
# Incidents
# ---------------------------------------------------------------------------
@require_GET
def incidents_api(request):
    incidents = Incident.objects.all().values(
        "id", "type", "severity", "description", "lat", "lng", "reported_at",
    )
    return JsonResponse({"status": "ok", "incidents": list(incidents)})


@csrf_exempt
@require_POST
def report_incident(request):
    """Create a new incident (body: JSON {type, severity, lat, lng, description?})."""
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"status": "error", "message": "Invalid JSON body."},
                            status=400)

    inc_type = str(payload.get("type", "")).strip().lower()
    severity = str(payload.get("severity", "Medium")).strip().capitalize()
    if inc_type not in _ALLOWED_INCIDENT_TYPES:
        inc_type = "other"
    if severity not in _ALLOWED_SEVERITIES:
        severity = "Medium"

    try:
        lat = float(payload["lat"])
        lng = float(payload["lng"])
    except (KeyError, TypeError, ValueError):
        return JsonResponse(
            {"status": "error", "message": "Provide numeric 'lat' and 'lng'."},
            status=400,
        )
    if not _valid_lat(lat) or not _valid_lng(lng):
        return JsonResponse(
            {"status": "error", "message": "Lat/lng out of range."},
            status=400,
        )

    description = str(payload.get("description", ""))[:500]

    incident = Incident.objects.create(
        type=inc_type.capitalize(),
        severity=severity,
        lat=lat,
        lng=lng,
        description=description,
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
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse(
            {"status": "error",
             "message": "Provide JSON body with destination_lat and destination_lng."},
            status=400,
        )

    try:
        dest_lat = float(payload["destination_lat"])
        dest_lng = float(payload["destination_lng"])
    except (KeyError, TypeError, ValueError):
        return JsonResponse(
            {"status": "error",
             "message": "Provide numeric destination_lat and destination_lng."},
            status=400,
        )

    if not (_valid_lat(dest_lat) and _valid_lng(dest_lng)):
        return JsonResponse(
            {"status": "error", "message": "Coordinates out of range."},
            status=400,
        )

    current_lat = payload.get("current_lat")
    current_lng = payload.get("current_lng")
    try:
        current_lat = float(current_lat) if current_lat is not None else dest_lat
        current_lng = float(current_lng) if current_lng is not None else dest_lng
    except (TypeError, ValueError):
        current_lat, current_lng = dest_lat, dest_lng

    session = TrackingSession.objects.create(
        current_lat=current_lat,
        current_lng=current_lng,
        destination_lat=dest_lat,
        destination_lng=dest_lng,
    )

    return JsonResponse(
        {
            "status": "ok",
            "session_token": str(session.session_token),
            "url": f"/api/sessions/{session.session_token}/",
        },
        status=201,
    )


@csrf_exempt
@require_POST
def update_session(request, token):
    """Update a live-tracking session's current position."""
    try:
        session = TrackingSession.objects.get(session_token=token)
    except (TrackingSession.DoesNotExist, ValueError, TypeError, ValidationError):
        return JsonResponse({"status": "error", "message": "Session not found."},
                            status=404)

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"status": "error", "message": "Invalid JSON body."},
                            status=400)

    try:
        session.current_lat = float(payload["current_lat"])
        session.current_lng = float(payload["current_lng"])
    except (KeyError, TypeError, ValueError):
        pass

    if "active" in payload:
        session.active = bool(payload["active"])

    if not session.active:
        session.save(update_fields=["current_lat", "current_lng", "active"])
    else:
        session.save(update_fields=["current_lat", "current_lng"])

    return JsonResponse({
        "status": "ok",
        "active": session.active,
        "current_lat": session.current_lat,
        "current_lng": session.current_lng,
    })


@require_GET
def get_session(request, token):
    """Poll a TrackingSession's current position. Accepts UUID or plain string."""
    try:
        session = TrackingSession.objects.get(session_token=token)
    except (TrackingSession.DoesNotExist, ValueError, TypeError, ValidationError):
        return JsonResponse({"status": "error", "message": "Session not found."},
                            status=404)

    return JsonResponse({
        "status": "ok",
        "active": session.active,
        "current_lat": session.current_lat,
        "current_lng": session.current_lng,
        "destination_lat": session.destination_lat,
        "destination_lng": session.destination_lng,
    })
