"""Google Open Buildings — footprint match by bounding box / nearest centroid.

Loads local GeoJSON tiles (and an optional remote FeatureCollection). When no polygon
intersects the query point, a rectangular estimate is synthesized from a typical area
so the map always has a building footprint to click.
"""

from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Any

import httpx

from catmod.config import Settings, get_settings

EARTH_M = 6371000.0
DEFAULT_AREA_M2 = 400.0


def _data_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "data" / "open_buildings"


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    h = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * EARTH_M * math.asin(min(1.0, math.sqrt(h)))


def ring_centroid(ring: list[list[float]]) -> tuple[float, float]:
    if not ring:
        return 0.0, 0.0
    lons = [p[0] for p in ring[:-1] or ring]
    lats = [p[1] for p in ring[:-1] or ring]
    if not lons:
        return 0.0, 0.0
    return sum(lats) / len(lats), sum(lons) / len(lons)


def ring_area_m2(ring: list[list[float]]) -> float:
    """Shoelace on a local equirectangular plane."""
    if len(ring) < 4:
        return 0.0
    lat0 = ring[0][1]
    lon0 = ring[0][0]
    meters_per_deg_lat = 111_320.0
    meters_per_deg_lon = 111_320.0 * math.cos(math.radians(lat0))
    xs, ys = [], []
    for lon, lat in ring:
        xs.append((lon - lon0) * meters_per_deg_lon)
        ys.append((lat - lat0) * meters_per_deg_lat)
    acc = 0.0
    for i in range(len(xs) - 1):
        acc += xs[i] * ys[i + 1] - xs[i + 1] * ys[i]
    return abs(acc) / 2.0


def _point_on_segment(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> bool:
    cross = (px - ax) * (by - ay) - (py - ay) * (bx - ax)
    if abs(cross) > 1e-12:
        return False
    dot = (px - ax) * (bx - ax) + (py - ay) * (by - ay)
    if dot < 0:
        return False
    return dot <= (bx - ax) ** 2 + (by - ay) ** 2


def point_in_ring(lat: float, lon: float, ring: list[list[float]]) -> bool:
    """Ray casting; coordinates are [lon, lat] as in GeoJSON."""
    inside = False
    n = len(ring)
    if n < 4:
        return False
    for i in range(n - 1):
        x1, y1 = ring[i][0], ring[i][1]
        x2, y2 = ring[i + 1][0], ring[i + 1][1]
        if _point_on_segment(lon, lat, x1, y1, x2, y2):
            return True
        intersect = ((y1 > lat) != (y2 > lat)) and (
            lon < (x2 - x1) * (lat - y1) / ((y2 - y1) or 1e-18) + x1
        )
        if intersect:
            inside = not inside
    return inside


def estimate_rectangle(lat: float, lon: float, area_m2: float = DEFAULT_AREA_M2) -> list[list[float]]:
    side = math.sqrt(max(area_m2, 25.0))
    dlat = (side / 2.0) / 111_320.0
    dlon = (side / 2.0) / (111_320.0 * max(0.2, math.cos(math.radians(lat))))
    ring = [
        [lon - dlon, lat - dlat],
        [lon + dlon, lat - dlat],
        [lon + dlon, lat + dlat],
        [lon - dlon, lat + dlat],
        [lon - dlon, lat - dlat],
    ]
    return ring


def _feature_from_polygon(
    ring: list[list[float]],
    *,
    properties: dict[str, Any],
) -> dict[str, Any]:
    lat_c, lon_c = ring_centroid(ring)
    area = float(properties.get("area_m2") or ring_area_m2(ring))
    props = dict(properties)
    props["area_m2"] = round(area, 2)
    props["centroid_lat"] = lat_c
    props["centroid_lng"] = lon_c
    return {
        "type": "Feature",
        "geometry": {"type": "Polygon", "coordinates": [ring]},
        "properties": props,
    }


def _iter_polygons(feature: dict[str, Any]) -> list[list[list[float]]]:
    geom = feature.get("geometry") or {}
    gtype = geom.get("type")
    coords = geom.get("coordinates") or []
    if gtype == "Polygon":
        return [coords[0]] if coords else []
    if gtype == "MultiPolygon":
        rings = []
        for poly in coords:
            if poly:
                rings.append(poly[0])
        return rings
    return []


def _normalize_collection(raw: dict[str, Any], source: str) -> list[dict[str, Any]]:
    features = raw.get("features") if raw.get("type") == "FeatureCollection" else [raw]
    out: list[dict[str, Any]] = []
    for feat in features or []:
        if not isinstance(feat, dict):
            continue
        for ring in _iter_polygons(feat):
            if len(ring) < 4:
                continue
            props = dict(feat.get("properties") or {})
            props.setdefault("source", source)
            props.setdefault("area_m2", props.get("area_in_meters") or ring_area_m2(ring))
            out.append(_feature_from_polygon(ring, properties=props))
    return out


def _load_geojson_file(path: Path) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return _normalize_collection(raw, source=f"open_buildings:{path.name}")


@lru_cache(maxsize=1)
def load_local_buildings() -> tuple[dict[str, Any], ...]:
    folder = _data_dir()
    loaded: list[dict[str, Any]] = []
    if folder.is_dir():
        for path in sorted(folder.glob("*.geojson")):
            loaded.extend(_load_geojson_file(path))
    settings = get_settings()
    extra = (settings.open_buildings_path or "").strip()
    if extra:
        extra_path = Path(extra)
        if extra_path.is_file():
            loaded.extend(_load_geojson_file(extra_path))
        elif extra_path.is_dir():
            for path in sorted(extra_path.glob("*.geojson")):
                loaded.extend(_load_geojson_file(path))
    return tuple(loaded)


def fetch_remote_buildings(url: str) -> list[dict[str, Any]]:
    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        response = client.get(url)
        response.raise_for_status()
        raw = response.json()
    return _normalize_collection(raw, source=f"open_buildings_remote:{url}")


def all_buildings(settings: Settings | None = None) -> list[dict[str, Any]]:
    settings = settings or get_settings()
    buildings = list(load_local_buildings())
    url = (settings.open_buildings_url or "").strip()
    if url:
        try:
            buildings.extend(fetch_remote_buildings(url))
        except Exception:
            pass
    return buildings


def bbox_query(
    west: float,
    south: float,
    east: float,
    north: float,
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    hits = []
    for feat in all_buildings(settings):
        lat = feat["properties"]["centroid_lat"]
        lon = feat["properties"]["centroid_lng"]
        if south <= lat <= north and west <= lon <= east:
            hits.append(feat)
    return hits


def match_footprint(
    latitude: float,
    longitude: float,
    *,
    max_distance_m: float = 75.0,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Return the Open Buildings polygon covering the point, else nearest, else an estimate."""
    best: dict[str, Any] | None = None
    best_d = float("inf")
    containing: dict[str, Any] | None = None
    for feat in all_buildings(settings):
        ring = feat["geometry"]["coordinates"][0]
        if point_in_ring(latitude, longitude, ring):
            containing = feat
            break
        d = haversine_m(
            latitude,
            longitude,
            feat["properties"]["centroid_lat"],
            feat["properties"]["centroid_lng"],
        )
        if d < best_d:
            best_d = d
            best = feat
    if containing is not None:
        props = dict(containing["properties"])
        props["match"] = "contains"
        props["match_distance_m"] = 0.0
        return {**containing, "properties": props}
    if best is not None and best_d <= max_distance_m:
        props = dict(best["properties"])
        props["match"] = "nearest"
        props["match_distance_m"] = round(best_d, 2)
        return {**best, "properties": props}
    ring = estimate_rectangle(latitude, longitude)
    return _feature_from_polygon(
        ring,
        properties={
            "source": "estimated_rectangle",
            "match": "estimated",
            "match_distance_m": None,
            "confidence": 0.2,
        },
    )
