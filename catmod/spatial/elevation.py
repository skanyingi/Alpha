"""Google Maps Elevation API → Open-Meteo free elevation fallback.

Heightmap grid is used for 3D flood displacement and local inundation heuristics.
"""

from __future__ import annotations

from typing import Any, Sequence

import httpx

from catmod.config import Settings, get_settings
from catmod.flood.maps import MapsError, _key, maps_configured
from catmod.geo.fallback import fetch_with_fallback, google_status_reason

ELEVATION_URL = "https://maps.googleapis.com/maps/api/elevation/json"
OPEN_METEO_ELEVATION = "https://api.open-meteo.com/v1/elevation"
MAX_POINTS = 512
OPEN_METEO_MAX = 100


def _chunks(items: list[tuple[float, float]], size: int = MAX_POINTS):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def sample_grid(
    west: float,
    south: float,
    east: float,
    north: float,
    rows: int,
    cols: int,
) -> list[tuple[float, float]]:
    rows = max(2, min(int(rows), 64))
    cols = max(2, min(int(cols), 64))
    if east == west:
        east = west + 1e-4
    if north == south:
        north = south + 1e-4
    points: list[tuple[float, float]] = []
    for r in range(rows):
        lat = south + (north - south) * r / (rows - 1)
        for c in range(cols):
            lon = west + (east - west) * c / (cols - 1)
            points.append((lat, lon))
    return points


def polygon_bbox(ring: Sequence[Sequence[float]]) -> tuple[float, float, float, float]:
    lons = [float(p[0]) for p in ring]
    lats = [float(p[1]) for p in ring]
    return min(lons), min(lats), max(lons), max(lats)


def fetch_elevation_google(
    locations: Sequence[tuple[float, float]],
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    if not locations:
        return []
    key = _key(settings)
    out: list[dict[str, Any]] = []
    with httpx.Client(timeout=8.0) as client:
        for chunk in _chunks(list(locations)):
            loc = "|".join(f"{lat:.7f},{lon:.7f}" for lat, lon in chunk)
            response = client.get(ELEVATION_URL, params={"locations": loc, "key": key})
            if response.status_code in {400, 401, 403, 429}:
                raise MapsError(f"Elevation HTTP {response.status_code}")
            response.raise_for_status()
            body = response.json()
            deny = google_status_reason(body)
            status = body.get("status")
            if status != "OK":
                raise MapsError(deny or f"Elevation API failed: {status}")
            for row in body.get("results") or []:
                locn = row.get("location") or {}
                out.append(
                    {
                        "lat": float(locn.get("lat", 0.0)),
                        "lng": float(locn.get("lng", 0.0)),
                        "elevation_m": float(row.get("elevation", 0.0)),
                        "resolution_m": float(row.get("resolution") or 0.0),
                        "provider": "google",
                    }
                )
    return out


def fetch_elevation_open_meteo(locations: Sequence[tuple[float, float]]) -> list[dict[str, Any]]:
    if not locations:
        return []
    out: list[dict[str, Any]] = []
    with httpx.Client(timeout=15.0) as client:
        for chunk in _chunks(list(locations), OPEN_METEO_MAX):
            lats = ",".join(f"{lat:.7f}" for lat, _lon in chunk)
            lons = ",".join(f"{lon:.7f}" for _lat, lon in chunk)
            response = client.get(
                OPEN_METEO_ELEVATION,
                params={"latitude": lats, "longitude": lons},
            )
            response.raise_for_status()
            body = response.json()
            elevs = body.get("elevation") or []
            if len(elevs) != len(chunk):
                raise MapsError("Open-Meteo elevation length mismatch")
            for (lat, lon), elev in zip(chunk, elevs):
                out.append(
                    {
                        "lat": float(lat),
                        "lng": float(lon),
                        "elevation_m": float(elev if elev is not None else 0.0),
                        "resolution_m": 30.0,
                        "provider": "open_meteo",
                    }
                )
    return out


def _heuristic_elevation(locations: Sequence[tuple[float, float]]) -> list[dict[str, Any]]:
    return [
        {
            "lat": float(lat),
            "lng": float(lon),
            "elevation_m": 2.0,
            "resolution_m": 0.0,
            "provider": "heuristic",
        }
        for lat, lon in locations
    ]


def fetch_elevation_points(
    locations: Sequence[tuple[float, float]],
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    if not locations:
        return []

    def primary() -> list[dict[str, Any]]:
        if not maps_configured(settings):
            raise MapsError("GOOGLE_MAPS_API_KEY is not configured")
        return fetch_elevation_google(locations, settings)

    try:
        return fetch_with_fallback(
            service="Elevation",
            primary=primary,
            fallback=lambda: fetch_elevation_open_meteo(locations),
            fallback_name="Open-Meteo Free Elevation API",
        )
    except Exception as exc:
        from catmod.geo.fallback import log_fallback

        log_fallback("Elevation", str(exc), "flat heuristic grid")
        return _heuristic_elevation(locations)


def assemble_heightmap(
    samples: Sequence[dict[str, Any]],
    *,
    west: float,
    south: float,
    east: float,
    north: float,
    rows: int,
    cols: int,
) -> dict[str, Any]:
    elevations = [float(s["elevation_m"]) for s in samples] or [0.0]
    baseline = min(elevations)
    heightmap: list[list[float]] = []
    flat = list(samples)
    idx = 0
    for _r in range(rows):
        line: list[float] = []
        for _c in range(cols):
            if idx < len(flat):
                line.append(float(flat[idx]["elevation_m"]))
            else:
                line.append(baseline)
            idx += 1
        heightmap.append(line)
    provider = next((s.get("provider") for s in samples if s.get("provider")), "google")
    return {
        "crs": "EPSG:4326",
        "vertical_unit": "meters",
        "provider": provider,
        "bbox": {
            "west": west,
            "south": south,
            "east": east,
            "north": north,
            "min_elevation_m": baseline,
            "max_elevation_m": max(elevations),
        },
        "rows": rows,
        "cols": cols,
        "cell_size_deg": {
            "lat": (north - south) / max(rows - 1, 1),
            "lng": (east - west) / max(cols - 1, 1),
        },
        "baseline_elevation_m": baseline,
        "mean_elevation_m": sum(elevations) / len(elevations),
        "grid": list(samples),
        "heightmap": heightmap,
        "usage": "3d_flood_displacement_plane",
    }


def elevation_from_locations(
    locations: Sequence[tuple[float, float]],
    settings: Settings | None = None,
) -> dict[str, Any]:
    samples = fetch_elevation_points(locations, settings)
    lats = [s["lat"] for s in samples]
    lngs = [s["lng"] for s in samples]
    west, east = (min(lngs), max(lngs)) if lngs else (0.0, 0.0)
    south, north = (min(lats), max(lats)) if lats else (0.0, 0.0)
    n = len(samples)
    cols = max(1, int(round(n**0.5)))
    rows = max(1, (n + cols - 1) // cols)
    return assemble_heightmap(samples, west=west, south=south, east=east, north=north, rows=rows, cols=cols)


def elevation_from_bbox(
    west: float,
    south: float,
    east: float,
    north: float,
    *,
    rows: int = 12,
    cols: int = 12,
    settings: Settings | None = None,
) -> dict[str, Any]:
    points = sample_grid(west, south, east, north, rows, cols)
    samples = fetch_elevation_points(points, settings)
    return assemble_heightmap(
        samples,
        west=west,
        south=south,
        east=east,
        north=north,
        rows=max(2, min(int(rows), 64)),
        cols=max(2, min(int(cols), 64)),
    )


def lookup_elevation_m(
    latitude: float,
    longitude: float,
    settings: Settings | None = None,
) -> float:
    payload = elevation_from_locations([(float(latitude), float(longitude))], settings)
    grid = payload.get("grid") or []
    if grid:
        return float(grid[0]["elevation_m"])
    return float(payload.get("mean_elevation_m") or 0.0)


def build_elevation_payload(
    *,
    locations: Sequence[tuple[float, float]] | None = None,
    bbox: tuple[float, float, float, float] | None = None,
    polygon: Sequence[Sequence[float]] | None = None,
    rows: int = 12,
    cols: int = 12,
    settings: Settings | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    if locations:
        return elevation_from_locations(locations, settings)
    if polygon:
        west, south, east, north = polygon_bbox(polygon)
        return elevation_from_bbox(west, south, east, north, rows=rows, cols=cols, settings=settings)
    if bbox:
        west, south, east, north = bbox
        return elevation_from_bbox(west, south, east, north, rows=rows, cols=cols, settings=settings)
    raise ValueError("Provide locations, bbox [west,south,east,north], or a polygon ring.")
