"""Routing engine for LumenPath.

Implements a custom Dijkstra shortest-path solver over the street graph stored
in `StreetSegment`. Two cost functions are supported:

  * "fastest" — cost is purely `distance_meters`
  * "safest"  — distance is penalised for darkness and crime:

        weight = distance * (1 + (10 - lighting_score) * 0.4 + crime_rate * 0.3)

The graph is built lazily once per request (with a tiny in-process cache keyed
off the row count) and treated as undirected, since pedestrians walk streets in
both directions.
"""

import heapq
from .models import StreetSegment

# Colour-blind-safe priority weights for the "safety index" meter (0..100).
SAFETY_WEIGHTS = {
    "lighting": 0.55,
    "crime": 0.45,
}


class GraphCache:
    """Tiny cache so we don't rebuild the adjacency graph every request."""

    _row_count = None
    _adjacency = None

    @classmethod
    def get_adjacency(cls):
        """Return adjacency dict, rebuilding it if the DB row count changed."""
        count = StreetSegment.objects.count()
        if cls._adjacency is None or cls._row_count != count:
            cls._adjacency = build_adjacency()
            cls._row_count = count
        return cls._adjacency


def node_key(lat, lng, precision=6):
    """Stable string key for a coordinate node (must match StreetSegment)."""
    return f"{round(lat, precision)},{round(lng, precision)}"


def build_adjacency():
    """Build {node_key: [ (neighbor_key, StreetSegment), ... ]} for all edges.

    Keys are always computed from the real coordinates to stay correct even
    when ``bulk_create()`` has skipped the model's ``save()`` override.
    """
    adjacency = {}
    for seg in StreetSegment.objects.all():
        start = node_key(seg.start_lat, seg.start_lng)
        end = node_key(seg.end_lat, seg.end_lng)
        adjacency.setdefault(start, []).append((end, seg))
        adjacency.setdefault(end, []).append((start, seg))
    return adjacency


def cost_fastest(seg):
    """Cost of a segment for the 'fastest' profile."""
    return float(seg.distance_meters)


def _base_cost_safest(seg):
    """Base safety-weighted cost: dark roads and high-crime areas inflate the
    effective distance so the solver trades a little extra travel time for much
    better security.
    """
    return float(seg.distance_meters) * (
        1.0 + (10.0 - float(seg.lighting_score)) * 0.4 + float(seg.crime_rate) * 0.3
    )


def make_cost_safest(avoid_unlit=False, cctv_priority=False):
    """Build a safety cost function honouring the user's routing preferences.

    * avoid_unlit     — very dark blocks (lighting <= 2) get a heavy penalty
    * cctv_priority   — CCTV-covered streets get a mild discount
    """
    def cost(seg):
        c = _base_cost_safest(seg)
        if avoid_unlit and seg.lighting_score <= 2:
            c *= 6.0
        if cctv_priority and bool(seg.has_cctv):
            c *= 0.82
        return c

    return cost


def cost_safest(seg):
    """Default safety cost (no routing preferences)."""
    return make_cost_safest()(seg)


COST_FUNCTIONS = {
    "fastest": cost_fastest,
    "safest": cost_safest,
}


def _nearest_node(adjacency, lat, lng):
    """Snap arbitrary coordinates onto the nearest graph node.

    Falls back to the first node in the graph if the graph is empty (edge
    case that shouldn't happen once seed_data has run).
    """
    target = node_key(lat, lng)
    if target in adjacency:
        return target

    best = None
    best_dist = float("inf")
    for n in adjacency:
        n_lat, n_lng = (float(part) for part in n.split(","))
        d = (n_lat - float(lat)) ** 2 + (n_lng - float(lng)) ** 2
        if d < best_dist:
            best_dist = d
            best = n
    return best


def dijkstra(adjacency, start_key, end_key, cost_fn):
    """Classic Dijkstra using heapq.

    Returns `(total_cost, path_keys)` where `path_keys` is the ordered list of
    node keys from start to end inclusive. Returns `(inf, [])` when no path
    exists.
    """
    if start_key not in adjacency or end_key not in adjacency:
        return float("inf"), []

    dist = {start_key: 0.0}
    prev = {}
    pq = [(0.0, start_key)]
    settled = set()

    while pq:
        current_cost, current = heapq.heappop(pq)
        if current in settled:
            continue
        settled.add(current)

        # Early exit once we finalise the destination.
        if current == end_key:
            break

        for neighbor, seg in adjacency[current]:
            # Skip zero-length micro edges to avoid funky zig-zags.
            if seg.distance_meters <= 0:
                continue
            new_cost = current_cost + cost_fn(seg)
            if new_cost < dist.get(neighbor, float("inf")):
                dist[neighbor] = new_cost
                prev[neighbor] = (current, seg)
                heapq.heappush(pq, (new_cost, neighbor))

    if end_key not in dist:
        return float("inf"), []

    # Reconstruct the node chain backwards.
    path_keys = []
    cursor = end_key
    while cursor != start_key:
        path_keys.append(cursor)
        cursor = prev[cursor][0]
    path_keys.append(start_key)
    path_keys.reverse()
    return dist[end_key], path_keys


def _segment_safety_score(seg):
    """0..1 rating combining lighting + crime using fixed weights.

    Higher = safer. Crime is *inverted* before weighting so more crime lowers
    the score, exactly as the product spec requires.
    """
    lighting_norm = (float(seg.lighting_score) - 1.0) / 9.0   # 1..10 → 0..1
    crime_norm = 1.0 - (float(seg.crime_rate) - 1.0) / 9.0    # inverted 1..10
    return (
        lighting_norm * SAFETY_WEIGHTS["lighting"]
        + crime_norm * SAFETY_WEIGHTS["crime"]
    )


# Public alias so views (e.g. the dynamic heatmap) can reuse the same 0..1 score.
segment_safety_score = _segment_safety_score


def resolve_route(start_lat, start_lng, end_lat, end_lng, profile="safest",
                  avoid_unlit=False, cctv_priority=False):
    """High-level entry point used by the API.

    Returns a fully serialisable route dict containing the walkable coordinate
    polyline, travel distance/time, and a 0-100 safety index — or an error dict
    if snapping or pathfinding fails.
    """
    adjacency = GraphCache.get_adjacency()
    if not adjacency:
        return {"error": "No street segments found. Run `python manage.py seed_data`."}

    start_key = _nearest_node(adjacency, start_lat, start_lng)
    end_key = _nearest_node(adjacency, end_lat, end_lng)
    if start_key is None or end_key is None:
        return {"error": "No street graph available."}

    if profile == "safest":
        cost_fn = make_cost_safest(avoid_unlit=avoid_unlit, cctv_priority=cctv_priority)
    else:
        cost_fn = COST_FUNCTIONS.get(profile, COST_FUNCTIONS["safest"])

    total_cost, path_keys = dijkstra(adjacency, start_key, end_key, cost_fn)
    if not path_keys:
        return {"error": f"No reachable path for profile '{profile}'."}

    # Walk the node chain again to pull the real segment rows (needed for the
    # safety metrics and per-node coordinates).
    coords, segments = _path_details(path_keys, adjacency)
    if not coords:
        return {"error": f"No reachable path for profile '{profile}'."}

    distance = sum(s.distance_meters for s in segments)
    duration_min = distance / 80.0  # average walking pace ~80 m/min (4.8 km/h)
    raw_index = sum(_segment_safety_score(s) for s in segments) / len(segments) * 100
    safety_index = round(min(100.0, max(0.0, raw_index)))

    return {
        "profile": profile,
        "start": {"lat": start_lat, "lng": start_lng},
        "end": {"lat": end_lat, "lng": end_lng},
        "path": [[lat, lng] for lat, lng in coords],
        "distance_meters": round(distance, 1),
        "duration_minutes": round(duration_min, 1),
        "safety_index": safety_index,
        "segments": len(segments),
    }


def _path_details(path_keys, adjacency):
    """Turn an ordered node-key chain into (coords, segments) pairs.

    We traverse consecutive key pairs and locate the actual StreetSegment that
    connects them from the adjacency bookkeeping.
    """
    # Create a reverse lookup: (k1, k2) sorted normalized -> segment.
    edge_lookup = {}
    for node, neighbors in adjacency.items():
        for other, seg in neighbors:
            key = tuple(sorted((node, other)))
            edge_lookup[key] = seg

    coords = []
    segments = []
    for i in range(len(path_keys) - 1):
        a = path_keys[i]
        b = path_keys[i + 1]
        seg = edge_lookup.get(tuple(sorted((a, b))))
        if seg is None:
            return [], []
        a_lat, a_lng = (float(p) for p in a.split(","))
        b_lat, b_lng = (float(p) for p in b.split(","))
        coords.append((a_lat, a_lng))
        segments.append(seg)
    # Append the final destination node.
    f_lat, f_lng = (float(p) for p in path_keys[-1].split(","))
    coords.append((f_lat, f_lng))
    return coords, segments