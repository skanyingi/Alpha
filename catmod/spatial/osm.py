"""OpenStreetMap footprints and roads for one diorama cell.

Overpass is called from the server. A failure returns an empty collection and a
note so the terrain view still loads. Queries stay inside one neighborhood.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

OVERPASS_URLS = (
    "https://lz4.overpass-api.de/api/interpreter",
    "https://overpass-api.de/api/interpreter",
)
OSM_HEADERS = {
    "User-Agent": "HypervectorRAG-CAT/1.0 (local flood desk; nominatim fallback)",
    "Accept": "application/json",
}
MAX_SPAN_DEG = 0.08
BUILDING_CAP = 4000
ROAD_CAP = 200
_CACHE: dict[tuple, dict[str, Any]] = {}
_CACHE_LIMIT = 12


def _empty(note: str) -> dict[str, Any]:
    return {
        "type": "FeatureCollection",
        "features": [],
        "metadata": {"count": 0, "note": note, "source": "osm"},
    }


def _bbox_note(west: float, south: float, east: float, north: float) -> str | None:
    if east <= west or north <= south:
        return "bbox is empty"
    if (east - west) > MAX_SPAN_DEG or (north - south) > MAX_SPAN_DEG:
        return "bbox is larger than one neighborhood"
    return None


def _ring_centroid(coords: list[list[float]]) -> tuple[float, float]:
    ring = coords[:-1] if len(coords) > 1 and coords[0] == coords[-1] else coords
    if not ring:
        return 0.0, 0.0
    return (
        sum(point[0] for point in ring) / len(ring),
        sum(point[1] for point in ring) / len(ring),
    )


def ways_to_features(elements: list[dict[str, Any]], *, kind: str, cap: int) -> list[dict[str, Any]]:
    features: list[dict[str, Any]] = []
    minimum = 4 if kind == "building" else 2
    for element in elements:
        if element.get("type") != "way":
            continue
        tags = element.get("tags") or {}
        if kind == "building" and "building" not in tags:
            continue
        if kind == "road" and "highway" not in tags:
            continue
        geometry = element.get("geometry") or []
        coords = [
            [float(point["lon"]), float(point["lat"])]
            for point in geometry
            if "lon" in point and "lat" in point
        ]
        if len(coords) < minimum:
            continue
        if kind == "building":
            if coords[0] != coords[-1]:
                coords.append(coords[0])
            if len(coords) < 4:
                continue
            lon, lat = _ring_centroid(coords)
            geom: dict[str, Any] = {"type": "Polygon", "coordinates": [coords]}
        else:
            lon, lat = coords[0][0], coords[0][1]
            geom = {"type": "LineString", "coordinates": coords}
        features.append(
            {
                "type": "Feature",
                "geometry": geom,
                "properties": {
                    "osm_id": element.get("id"),
                    "name": tags.get("name") or tags.get("name:en") or "",
                    "building": tags.get("building"),
                    "height": tags.get("height"),
                    "building:levels": tags.get("building:levels"),
                    "building:material": tags.get("building:material"),
                    "highway": tags.get("highway"),
                    "centroid_lng": lon,
                    "centroid_lat": lat,
                    "source": "osm",
                },
            }
        )
        if len(features) >= cap:
            break
    return features


def fetch_overpass(query: str) -> list[dict[str, Any]]:
    errors: list[str] = []
    for url in OVERPASS_URLS:
        try:
            return _post_overpass(url, query)
        except Exception as exc:
            errors.append(str(exc))
    time.sleep(3)
    try:
        return _post_overpass(OVERPASS_URLS[0], query)
    except Exception as exc:
        errors.append(str(exc))
    raise RuntimeError(errors[-1] if errors else "Overpass unavailable")


def _post_overpass(url: str, query: str) -> list[dict[str, Any]]:
    with httpx.Client(timeout=32.0, headers=OSM_HEADERS) as client:
        response = client.post(url, data={"data": query})
        response.raise_for_status()
        body = response.json()
    elements = body.get("elements") or []
    if not isinstance(elements, list):
        return []
    return elements


def _cache_key(kind: str, west: float, south: float, east: float, north: float) -> tuple:
    return (kind, round(west, 5), round(south, 5), round(east, 5), round(north, 5))


def _remember(key: tuple, payload: dict[str, Any]) -> dict[str, Any]:
    if len(_CACHE) >= _CACHE_LIMIT:
        _CACHE.pop(next(iter(_CACHE)))
    _CACHE[key] = payload
    return payload


def osm_buildings(west: float, south: float, east: float, north: float) -> dict[str, Any]:
    note = _bbox_note(west, south, east, north)
    if note:
        return _empty(note)
    key = _cache_key("buildings", west, south, east, north)
    cached = _CACHE.get(key)
    if cached is not None:
        return cached
    query = (
        f"[out:json][timeout:25];"
        f'way["building"]({south},{west},{north},{east});'
        f"out geom;"
    )
    try:
        elements = fetch_overpass(query)
    except Exception as exc:
        return _empty(f"Overpass unavailable: {exc}")
    features = ways_to_features(elements, kind="building", cap=BUILDING_CAP)
    capped = len(elements) > BUILDING_CAP
    payload = {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "count": len(features),
            "note": "capped at 4000" if capped else "",
            "source": "osm",
        },
    }
    return _remember(key, payload) if features else payload


def osm_roads(west: float, south: float, east: float, north: float) -> dict[str, Any]:
    note = _bbox_note(west, south, east, north)
    if note:
        return _empty(note)
    key = _cache_key("roads", west, south, east, north)
    cached = _CACHE.get(key)
    if cached is not None:
        return cached
    query = (
        f"[out:json][timeout:25];"
        f'way["highway"~"^(primary|secondary|tertiary|residential)$"]'
        f"({south},{west},{north},{east});"
        f"out geom;"
    )
    try:
        elements = fetch_overpass(query)
    except Exception as exc:
        return _empty(f"Overpass unavailable: {exc}")
    features = ways_to_features(elements, kind="road", cap=ROAD_CAP)
    payload = {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {"count": len(features), "note": "", "source": "osm"},
    }
    return _remember(key, payload) if features else payload
