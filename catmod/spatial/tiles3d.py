"""Google Photorealistic 3D Tiles + Map Tiles session bootstrap.

Returns session tokens and root URLs for Cesium / Three.js / Blosm. Does not
download or render tile meshes. On billing/auth failure, returns a procedural
Open-Meteo DEM + OSM footprint session instead of raising.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx

from catmod.config import Settings, get_settings
from catmod.flood.maps import MapsError, _key, maps_configured
from catmod.geo.fallback import fetch_with_fallback, google_status_reason

TILES_ROOT = "https://tile.googleapis.com/v1/3dtiles/root.json"
CREATE_SESSION = "https://tile.googleapis.com/v1/createSession"
_SESSION_RE = re.compile(r"[?&]session=([^&]+)")


def _extract_session(node: Any) -> str | None:
    if isinstance(node, str):
        match = _SESSION_RE.search(node)
        if match:
            return match.group(1)
        parsed = urlparse(node)
        qs = parse_qs(parsed.query)
        if "session" in qs and qs["session"]:
            return qs["session"][0]
        return None
    if isinstance(node, dict):
        for value in node.values():
            found = _extract_session(value)
            if found:
                return found
    if isinstance(node, list):
        for value in node:
            found = _extract_session(value)
            if found:
                return found
    return None


def _extract_bounding_volume(node: Any) -> dict[str, Any] | None:
    if isinstance(node, dict):
        if "boundingVolume" in node and isinstance(node["boundingVolume"], dict):
            return node["boundingVolume"]
        for value in node.values():
            found = _extract_bounding_volume(value)
            if found:
                return found
    if isinstance(node, list):
        for value in node:
            found = _extract_bounding_volume(value)
            if found:
                return found
    return None


def create_map_tiles_session(
    settings: Settings | None = None,
    *,
    map_type: str = "satellite",
    language: str = "en-US",
    region: str = "US",
) -> dict[str, Any]:
    key = _key(settings)
    payload = {
        "mapType": map_type,
        "language": language,
        "region": region,
        "imageFormat": "png",
        "highDpi": True,
    }
    with httpx.Client(timeout=8.0) as client:
        response = client.post(CREATE_SESSION, params={"key": key}, json=payload)
        if response.status_code in {400, 401, 403, 429}:
            raise MapsError(f"Map Tiles session HTTP {response.status_code}")
        response.raise_for_status()
        body = response.json()
    if "error" in body:
        raise MapsError(str(body["error"]))
    deny = google_status_reason(body)
    if deny:
        raise MapsError(deny)
    return {
        "session": body.get("session"),
        "expiry": body.get("expiry") or body.get("expireTime"),
        "tileWidth": body.get("tileWidth"),
        "tileHeight": body.get("tileHeight"),
        "mapType": map_type,
        "imageFormat": body.get("imageFormat") or "png",
        "provider": "google",
    }


def fetch_3d_tiles_root(settings: Settings | None = None) -> dict[str, Any]:
    with httpx.Client(timeout=8.0) as client:
        response = client.get(TILES_ROOT, params={"key": key})
        if response.status_code in {400, 401, 403, 429}:
            raise MapsError(f"3D Tiles root HTTP {response.status_code}")
        response.raise_for_status()
        body = response.json()
    deny = google_status_reason(body)
    if deny:
        raise MapsError(deny)
    return body


def procedural_3d_fallback(
    *,
    west: float | None,
    south: float | None,
    east: float | None,
    north: float | None,
    renderer: str,
    reason: str = "Google Photorealistic 3D Tiles unavailable",
) -> dict[str, Any]:
    bbox = None
    terrain = None
    if None not in (west, south, east, north):
        bbox = {"west": west, "south": south, "east": east, "north": north}
        try:
            from catmod.spatial.elevation import elevation_from_bbox

            terrain = elevation_from_bbox(float(west), float(south), float(east), float(north), rows=4, cols=4)
        except Exception as exc:
            terrain = {"provider": "open_meteo", "error": str(exc)}
    return {
        "provider": "open_stack_procedural",
        "fallback": True,
        "fallback_reason": reason,
        "root_url": None,
        "tileset_root_proxy": "/api/spatial/3d-tiles-session",
        "session": None,
        "bounding_volume": None,
        "bounding_box": bbox,
        "terrain": terrain,
        "buildings_source": "osm_open_buildings",
        "map_tiles_session": None,
        "renderer": renderer,
        "renderer_hints": {
            "cesium": {
                "fromUrl": None,
                "note": "Use OSM buildings + Open-Meteo DEM; Google Photorealistic 3D Tiles unavailable.",
                "session": None,
            },
            "threejs": {
                "tilesRendererRoot": None,
                "session": None,
            },
            "blosm": {
                "provider": "osm-buildings",
                "session": None,
                "bbox": bbox,
            },
        },
        "load_meshes": False,
        "note": "Fallback procedural terrain + OSM footprints. Do not stream 3D tile meshes into the Leaflet view.",
    }


def create_3d_tiles_session(
    *,
    west: float | None = None,
    south: float | None = None,
    east: float | None = None,
    north: float | None = None,
    renderer: str = "cesium",
    settings: Settings | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()

    def primary() -> dict[str, Any]:
        if not maps_configured(settings):
            raise MapsError("GOOGLE_MAPS_API_KEY is not configured")

        tileset = fetch_3d_tiles_root(settings)
        session = _extract_session(tileset)
        bounding = _extract_bounding_volume(tileset)
        try:
            map_session = create_map_tiles_session(settings)
        except Exception as exc:
            map_session = {"error": str(exc), "provider": "google"}

        bbox = None
        if None not in (west, south, east, north):
            bbox = {
                "west": west,
                "south": south,
                "east": east,
                "north": north,
            }

        return {
            "provider": "google_photorealistic_3d_tiles",
            "fallback": False,
            "root_url": TILES_ROOT,
            "tileset_root_proxy": "/api/spatial/3d-tiles-session",
            "session": session,
            "bounding_volume": bounding,
            "bounding_box": bbox,
            "map_tiles_session": map_session,
            "renderer": renderer,
            "renderer_hints": {
                "cesium": {
                    "fromUrl": TILES_ROOT,
                    "note": "Append key server-side or reuse session query param from root.json",
                    "session": session,
                },
                "threejs": {
                    "tilesRendererRoot": TILES_ROOT,
                    "session": session,
                },
                "blosm": {
                    "provider": "google-3d-tiles",
                    "session": session,
                    "bbox": bbox,
                },
            },
            "load_meshes": False,
            "note": "Session bootstrap only. Do not stream 3D tile meshes into the Leaflet view.",
        }

    return fetch_with_fallback(
        service="Photorealistic 3D Tiles",
        primary=primary,
        fallback=lambda: procedural_3d_fallback(
            west=west, south=south, east=east, north=north, renderer=renderer
        ),
        fallback_name="procedural terrain + OSM building footprints",
    )
