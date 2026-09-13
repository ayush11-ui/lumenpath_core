"""Seed the LumenPath SQLite database with demo data.

Creates:
  * 127 connected street segments forming a connected mock-city grid. Each
    quadrilateral "block" in the grid shares corner nodes with its neighbours,
    so the whole 8x8 block area is one traversable graph.
  * 5 safe zones (Police, Hospital, 24/7 Stores).
  * 3 incident markers.

Run with:
    python manage.py seed_data

Idempotent: every run wipes the existing demo rows and rebuilds them.
"""

import random
from django.core.management.base import BaseCommand
from routing.models import StreetSegment, SafeZone, Incident

random.seed(42)  # deterministic output so the demo always looks the same


# ---------------------------------------------------------------------------
# Grid definition
# ---------------------------------------------------------------------------
# Mock city centred on Buenos Aires (near Gaona / Rivadavia) where most seed
# coordinates feel organic — but any urban coordinates work fine.
BASE_LAT, BASE_LNG = -34.6265, -58.4491

GRID_SIZE = 8           # 8x8 block grid = 7x... actually 8 columns of blocks
BLOCK_LAT, BLOCK_LNG = 0.0035, 0.0045  # ~	385m x 400m per block dims


def node_pos(gx, gy):
    """Return (lat, lng) for grid coordinate (gx, gy)."""
    return BASE_LAT + gy * BLOCK_LAT, BASE_LNG + gx * BLOCK_LNG


def haversine_m(lat1, lng1, lat2, lng2):
    """Straight-line great-circle distance in meters (used as segment length)."""
    import math

    R = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


# ---------------------------------------------------------------------------
# Street segment generator
# ---------------------------------------------------------------------------
def build_segments():
    """Generate every horizontal + vertical block edge in the grid.

    Node (gx, gy) and (gx+1, gy) form a horizontal street; (gx, gy+1) forms a
    vertical street. Consecutive edges share their endpoint nodes, which is what
    makes the whole grid a single connected graph.
    """
    segments = []
    colors = ["Violet", "Indigo", "Amber", "Emerald", "Coral", "Azure", "Slate", "Jade"]
    avenues = ["Gen. Paz", "San Martín", "Rivadavia", "Alberdi", "Gaona"]

    # Horizontal roads (streets running west → east).
    for gy in range(GRID_SIZE):
        name = f"Calle {avenues[gy % len(avenues)]}"
        for gx in range(GRID_SIZE):
            lat1, lng1 = node_pos(gx, gy)
            lat2, lng2 = node_pos(gx + 1, gy)
            segments.append(make_segment(
                name, lat1, lng1, lat2, lng2, colors[(gx + gy) % len(colors)]
            ))

    # Vertical roads (avenues running north → south).
    for gx in range(GRID_SIZE + 1):
        name = f"Avenida {colors[gx % len(colors)]}"
        for gy in range(GRID_SIZE - 1):
            lat1, lng1 = node_pos(gx, gy)
            lat2, lng2 = node_pos(gx, gy + 1)
            segments.append(make_segment(
                name, lat1, lng1, lat2, lng2, colors[(gx + gy) % len(colors)]
            ))

    return segments


def make_segment(name, lat1, lng1, lat2, lng2, color):
    """Draw one StreetSegment with (slightly correlated) random safety values.

    We bias lighting/crime per-road via a simple pseudo-random scheme so the
    'safest' and 'fastest' paths genuinely differ from each other — otherwise
    every route in a plain grid would be identical and the demo would be dull.
    """
    # A deterministic per-seed "neighbourhood hazard" value in [0,1].
    hazard = random.random()
    # Bright, safe roads are rarer; most average, some genuinely dark.
    lighting = max(1, min(10, int(random.gauss(6.5, 1.6))))
    if hazard > 0.85:
        lighting = random.randint(1, 3)     # a few very dark blocks
    if hazard < 0.10:
        lighting = random.randint(9, 10)    # a few well-lit main streets

    crime = max(1, min(10, int(random.gauss(4.5, 1.8))))
    if hazard > 0.85:
        crime = random.randint(8, 10)

    dist = haversine_m(lat1, lng1, lat2, lng2)

    return StreetSegment(
        name=name,
        start_lat=lat1,
        start_lng=lng1,
        end_lat=lat2,
        end_lng=lng2,
        lighting_score=lighting,
        crime_rate=crime,
        distance_meters=dist,
        has_cctv=random.random() < 0.45,  # ~45% of blocks have public CCTV
    )


# ---------------------------------------------------------------------------
# Safe zones & incidents
# ---------------------------------------------------------------------------
SAFE_ZONES = [
    ("Comisaría 4ª", "Police", -34.6190, -58.4470),
    ("Hospital Rivadavia", "Hospital", -34.6220, -58.4600),
    ("Hospital Durand", "Hospital", -34.6340, -58.4485),
    ("Tienda 24 Horas Central", "24/7 Store", -34.6280, -58.4410),
    ("Open 24 – Gaona", "24/7 Store", -34.6320, -58.4550),
]

INCIDENTS = [
    ("Streetlight outage", "High", "3 lamp posts dark for two blocks", -34.6305, -58.4562),
    ("Suspicious activity", "Medium", "Loitering near the plaza entry", -34.6240, -58.4430),
    ("Poor pavement", "Low", "Broken sidewalk, trip hazard at night", -34.6298, -58.4504),
]


class Command(BaseCommand):
    help = "Populate the database with the LumenPath demo grid, safe zones and incidents."

    def handle(self, *args, **options):
        # Idempotent: wipe and re-create so re-running always gives a clean demo.
        StreetSegment.objects.all().delete()
        SafeZone.objects.all().delete()
        Incident.objects.all().delete()

        segments = build_segments()
        for seg in segments:
            seg.save()  # save() computes start_key / end_key correctly

        for name, zone_type, lat, lng in SAFE_ZONES:
            SafeZone.objects.create(name=name, zone_type=zone_type, lat=lat, lng=lng)

        for itype, severity, desc, lat, lng in INCIDENTS:
            Incident.objects.create(
                type=itype,
                severity=severity,
                description=desc,
                lat=lat,
                lng=lng,
            )

        self.stdout.write(self.style.SUCCESS(
            f"Seeded {StreetSegment.objects.count()} street segments, "
            f"{SafeZone.objects.count()} safe zones and "
            f"{Incident.objects.count()} incidents."
        ))