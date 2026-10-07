"""Blender / Blosm / game-engine export manifest. No mesh generation."""

from __future__ import annotations

from typing import Any, Sequence

from catmod.config import Settings, get_settings
from catmod.flood.buildings import all_buildings
from catmod.flood.service import footprints_for_points
from catmod.spatial.presets import STOREY_HEIGHT_M, resolve_preset


def _ring(feature: dict[str, Any]) -> list[list[float]]:
    geom = feature.get("geometry") or {}
    if geom.get("type") == "Polygon":
        coords = geom.get("coordinates") or []
        return list(coords[0]) if coords else []
    return []


def _building_from_feature(
    feature: dict[str, Any],
    *,
    storey_height_m: float,
    water_surface_m: float,
) -> dict[str, Any]:
    props = feature.get("properties") or {}
    storeys = int(props.get("estimated_storeys") or 1)
    height_m = storeys * storey_height_m
    lat = float(props.get("centroid_lat") or 0.0)
    lng = float(props.get("centroid_lng") or 0.0)
    ground = float(props.get("ground_elevation_m") or props.get("elevation") or 2.0)
    ffe = float(props.get("first_floor_elevation_m") or ground)
    depth = float(props.get("inundation_depth_m") or max(0.0, water_surface_m - ffe))
    ring = _ring(feature)
    return {
        "asset_id": props.get("asset_id"),
        "centroid": {"latitude": lat, "longitude": lng, "elevation_m": ground},
        "footprint_lonlat": ring,
        "area_m2": props.get("area_m2"),
        "storeys": storeys,
        "height_m": round(height_m, 3),
        "predicted_material": props.get("roof_wall_material") or "Unknown",
        "occupancy_type": props.get("occupancy_type") or props.get("occupancy"),
        "first_floor_clearance": props.get("ground_clearance_elevation") or "Unknown",
        "first_floor_elevation_m": ffe,
        "vulnerability_score": props.get("vulnerability_score"),
        "risk_level": props.get("risk_level"),
        "inundation_depth_m": depth,
        "extrude_from_m": ground,
        "extrude_to_m": round(ground + height_m, 3),
    }


def _bbox_from_buildings(buildings: Sequence[dict[str, Any]]) -> dict[str, float]:
    lats, lngs, elevs = [], [], []
    for b in buildings:
        c = b.get("centroid") or {}
        if c.get("latitude") is not None:
            lats.append(float(c["latitude"]))
            lngs.append(float(c["longitude"]))
        elevs.append(float(c.get("elevation_m") or 0.0))
        for lon, lat in b.get("footprint_lonlat") or []:
            lngs.append(float(lon))
            lats.append(float(lat))
        elevs.append(float(b.get("extrude_to_m") or 0.0))
    if not lats:
        return {
            "south": -1.32,
            "west": 36.78,
            "north": -1.26,
            "east": 36.86,
            "min_elevation_m": 0.0,
            "max_elevation_m": 30.0,
        }
    return {
        "south": min(lats),
        "west": min(lngs),
        "north": max(lats),
        "east": max(lngs),
        "min_elevation_m": min(elevs) if elevs else 0.0,
        "max_elevation_m": max(elevs) if elevs else 0.0,
    }


def points_from_job(job: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not job:
        return []
    points: list[dict[str, Any]] = []
    for claim in job.get("claims") or []:
        points.append(
            {
                "asset_id": claim.get("asset_id"),
                "latitude": claim.get("latitude"),
                "longitude": claim.get("longitude"),
                "elevation": claim.get("elevation"),
                "occupancy": claim.get("occupancy") or claim.get("occupancy_raw"),
            }
        )
    return points


def points_from_open_buildings() -> list[dict[str, Any]]:
    points = []
    for i, feat in enumerate(all_buildings(), start=1):
        props = feat.get("properties") or {}
        points.append(
            {
                "asset_id": props.get("asset_id") or f"OB-{i:03d}",
                "latitude": props.get("centroid_lat"),
                "longitude": props.get("centroid_lng"),
                "elevation": 2.0,
                "occupancy": "unknown",
            }
        )
    return points


def build_blender_manifest(
    *,
    job: dict[str, Any] | None = None,
    shader_preset: str = "PHOTOREAL_DEFAULT",
    storey_height_m: float = STOREY_HEIGHT_M,
    settings: Settings | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    preset = resolve_preset(shader_preset)
    water_surface_m = float(settings.flood_wse_m)
    points = points_from_job(job) or points_from_open_buildings()
    collection = footprints_for_points(points, settings)
    buildings = [
        _building_from_feature(
            feat,
            storey_height_m=storey_height_m,
            water_surface_m=water_surface_m,
        )
        for feat in collection.get("features") or []
    ]
    bbox = _bbox_from_buildings(buildings)
    depths = [float(b.get("inundation_depth_m") or 0.0) for b in buildings]
    terrain: dict[str, Any] = {
        "elevation_endpoint": "/api/spatial/elevation",
        "vertical_exaggeration": 1.0,
    }
    try:
        from catmod.spatial.elevation import elevation_from_bbox

        terrain["grid"] = elevation_from_bbox(
            float(bbox["west"]),
            float(bbox["south"]),
            float(bbox["east"]),
            float(bbox["north"]),
            rows=4,
            cols=4,
            settings=settings,
        )
        terrain["provider"] = terrain["grid"].get("provider")
    except Exception as exc:
        terrain["fallback"] = True
        terrain["note"] = str(exc)
    photoreal = {
        "session_endpoint": "/api/spatial/3d-tiles-session",
        "load_in_leaflet": False,
        "fallback_buildings": "osm_open_buildings",
    }
    return {
        "format": "catmod.blender_manifest.v1",
        "importer": "blosm",
        "event_id": (job or {}).get("event_id"),
        "shader_preset": preset["id"],
        "shader": preset,
        "bounding_box": bbox,
        "buildings": buildings,
        "water_levels": {
            "absolute_water_surface_m": water_surface_m,
            "plane_offset_from_min_terrain_m": round(
                water_surface_m - float(bbox["min_elevation_m"]), 3
            ),
            "max_inundation_depth_m": max(depths) if depths else 0.0,
            "mean_inundation_depth_m": (sum(depths) / len(depths)) if depths else 0.0,
            "material": preset["water_plane"],
        },
        "terrain": terrain,
        "photoreal_tiles": photoreal,
        "blender_hints": {
            "storey_height_m": storey_height_m,
            "extrude_buildings": True,
            "create_water_volume": True,
            **(preset.get("blender") or {}),
        },
        "building_count": len(buildings),
    }
