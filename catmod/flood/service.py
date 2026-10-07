"""Orchestrate geocode → footprint → imagery → Gemini → flood score. Not finance."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from catmod.config import Settings, get_settings
from catmod.flood.buildings import bbox_query, match_footprint
from catmod.flood.gemini import extract_vulnerability, gemini_configured
from catmod.flood.hazard import (
    flood_legend,
    hazard_polygon_collection,
    score_asset,
    style_for_score,
)
from catmod.flood.maps import (
    fetch_aerial,
    fetch_street_view,
    geocode_address,
    normalize_geocode,
    reverse_geocode,
)


def _hazard_path() -> Path:
    return Path(__file__).resolve().parents[2] / "data" / "flood_hazard" / "nairobi_pluvial.geojson"


def heuristic_gemini(occupancy_hint: str = "", elevation_m: float = 0.0) -> dict[str, Any]:
    hint = (occupancy_hint or "").lower()
    if any(k in hint for k in ("whse", "warehouse", "storage", "shed", "industrial")):
        occ, mat, storeys, score = "Industrial", "Corrugated Metal", 1, 6
    elif any(k in hint for k in ("office", "retail", "hotel", "commercial")):
        occ, mat, storeys, score = "Commercial", "Reinforced Concrete", 4, 4
    elif any(k in hint for k in ("sfd", "res", "house", "dwelling", "home")):
        occ, mat, storeys, score = "Residential", "Masonry", 1, 7
    elif any(k in hint for k in ("farm", "agr", "barn")):
        occ, mat, storeys, score = "Agricultural", "Timber", 1, 7
    else:
        occ, mat, storeys, score = "Unknown", "Unknown", 1, 5
    clearance = "Raised steps" if elevation_m >= 4 else "Ground level"
    return {
        "occupancy_type": occ,
        "estimated_storeys": storeys,
        "roof_wall_material": mat,
        "ground_clearance_elevation": clearance,
        "vulnerability_score": score,
        "justification": "Heuristic from occupancy/elevation because imagery analysis was not used.",
        "source": "heuristic",
    }


def evaluate_asset(
    *,
    address: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    occupancy_hint: str = "",
    ground_elevation_m: float | None = None,
    asset_id: str | None = None,
    settings: Settings | None = None,
    fetch_imagery: bool = True,
    use_gemini: bool = True,
) -> dict[str, Any]:
    settings = settings or get_settings()
    geocode: dict[str, Any]
    if address and not (latitude is not None and longitude is not None):
        geocode = geocode_address(address, settings)
        latitude = float(geocode["latitude"])
        longitude = float(geocode["longitude"])
    else:
        if latitude is None or longitude is None:
            raise ValueError("Provide address or latitude and longitude")
        if fetch_imagery:
            geocode = reverse_geocode(float(latitude), float(longitude), settings)
            latitude = float(geocode["latitude"])
            longitude = float(geocode["longitude"])
        else:
            geocode = normalize_geocode(
                {
                    "latitude": float(latitude),
                    "longitude": float(longitude),
                    "formatted_address": address or f"{float(latitude):.5f}, {float(longitude):.5f}",
                    "place_id": None,
                    "types": [],
                    "provider": "supplied",
                    "status": "skipped_bulk",
                }
            )

    lat = float(latitude)
    lon = float(longitude)
    wse = float(settings.flood_wse_m)
    if ground_elevation_m is None:
        try:
            from catmod.spatial.elevation import lookup_elevation_m

            elev = float(lookup_elevation_m(lat, lon, settings))
        except Exception:
            elev = 2.0
    else:
        elev = float(ground_elevation_m)

    footprint = match_footprint(lat, lon, settings=settings)
    centroid_lat = float(footprint["properties"].get("centroid_lat") or lat)
    centroid_lng = float(footprint["properties"].get("centroid_lng") or lon)

    aerial_bytes = street_bytes = None
    aerial_mime = street_mime = "image/jpeg"
    depth_hint = max(0.0, wse - elev)
    if fetch_imagery:
        try:
            aerial_bytes, aerial_mime = fetch_aerial(centroid_lat, centroid_lng, settings)
        except Exception:
            aerial_bytes = None
        try:
            street_bytes, street_mime = fetch_street_view(
                centroid_lat, centroid_lng, settings, depth_m=depth_hint
            )
        except Exception:
            street_bytes = None

    context = (
        f"asset_id={asset_id or ''} address={geocode.get('formatted_address')} "
        f"lat={centroid_lat:.6f} lng={centroid_lng:.6f} occupancy_hint={occupancy_hint} "
        f"ground_elevation_m={elev} footprint_area_m2={footprint['properties'].get('area_m2')}"
    )
    if use_gemini and gemini_configured(settings) and (aerial_bytes or occupancy_hint):
        vision = extract_vulnerability(
            aerial_bytes=aerial_bytes,
            aerial_mime=aerial_mime,
            street_bytes=None if street_mime == "image/svg+xml" else street_bytes,
            street_mime=street_mime,
            context=context,
            settings=settings,
        )
    else:
        vision = heuristic_gemini(occupancy_hint, elev)
        if use_gemini and not gemini_configured(settings):
            vision["justification"] = (
                "GEMINI_API_KEY not set; occupancy heuristic used instead of vision."
            )

    flood = score_asset(ground_elevation_m=elev, water_surface_m=wse, gemini=vision)
    color = flood["marker-color"]
    style = style_for_score(int(flood["risk_score"]))

    props = dict(footprint["properties"])
    props.update(
        {
            "asset_id": asset_id,
            "address": geocode.get("formatted_address"),
            "occupancy_type": vision["occupancy_type"],
            "estimated_storeys": vision["estimated_storeys"],
            "roof_wall_material": vision["roof_wall_material"],
            "ground_clearance_elevation": vision["ground_clearance_elevation"],
            "vulnerability_score": vision["vulnerability_score"],
            "justification": vision["justification"],
            "gemini_source": vision.get("source"),
            "aerial_url": f"/api/v1/flood/imagery/aerial?lat={centroid_lat}&lng={centroid_lng}",
            "street_url": f"/api/v1/flood/imagery/street?lat={centroid_lat}&lng={centroid_lng}",
            "street_fallback": street_mime == "image/svg+xml" or street_bytes is None,
            "marker-color": color,
            "style": style,
            **flood,
        }
    )
    feature = {
        "type": "Feature",
        "geometry": footprint["geometry"],
        "properties": props,
    }
    return {
        "asset_id": asset_id,
        "latitude": centroid_lat,
        "longitude": centroid_lng,
        "address": geocode.get("formatted_address"),
        "geocode": geocode,
        "footprint": {
            "area_m2": props.get("area_m2"),
            "centroid_lat": centroid_lat,
            "centroid_lng": centroid_lng,
            "source": props.get("source"),
            "match": props.get("match"),
        },
        "imagery": {
            "aerial_url": props["aerial_url"],
            "street_url": props["street_url"],
            "aerial_fetched": aerial_bytes is not None,
            "street_fetched": street_bytes is not None,
            "street_fallback": bool(props.get("street_fallback")),
            "ground_elevation_m": elev,
        },
        "gemini": vision,
        "flood": flood,
        "geojson": feature,
    }


def footprints_for_points(
    points: list[dict[str, Any]],
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Match Open Buildings polygons to claim/asset points without calling Gemini."""
    settings = settings or get_settings()
    features: list[dict[str, Any]] = []
    for pt in points:
        lat = float(pt.get("latitude") or 0.0)
        lon = float(pt.get("longitude") or 0.0)
        if abs(lat) < 1e-6 and abs(lon) < 1e-6:
            continue
        result = evaluate_asset(
            latitude=lat,
            longitude=lon,
            occupancy_hint=str(pt.get("occupancy") or pt.get("occupancy_raw") or ""),
            ground_elevation_m=float(pt.get("elevation") or 2.0),
            asset_id=str(pt.get("asset_id") or pt.get("id") or ""),
            settings=settings,
            fetch_imagery=False,
            use_gemini=False,
        )
        features.append(result["geojson"])
    return {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "legend": flood_legend(),
            "layer": "flood_building_footprints",
        },
    }


def hazard_collection(settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    path = _hazard_path()
    if path.is_file():
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw.setdefault("metadata", {})
        raw["metadata"]["legend"] = flood_legend()
        return raw
    ring = [
        [36.78, -1.32],
        [36.86, -1.32],
        [36.86, -1.26],
        [36.78, -1.26],
        [36.78, -1.32],
    ]
    return hazard_polygon_collection([ring], water_surface_m=settings.flood_wse_m)


def buildings_in_viewport(
    west: float,
    south: float,
    east: float,
    north: float,
    settings: Settings | None = None,
) -> dict[str, Any]:
    feats = bbox_query(west, south, east, north, settings)
    return {
        "type": "FeatureCollection",
        "features": feats,
        "metadata": {"layer": "open_buildings_bbox", "count": len(feats)},
    }
