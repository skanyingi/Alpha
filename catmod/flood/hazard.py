"""Flood exposure scoring and GeoJSON styling.

Risk is an underwriting annotation. It does not alter Layer 4 treaty payouts.
"""

from __future__ import annotations

from typing import Any, Sequence

RISK_GREEN = "#2A9D4A"
RISK_YELLOW = "#E0B825"
RISK_RED = "#C1121F"

FFE_OFFSET_M = {
    "Ground level": 0.15,
    "Raised steps": 0.75,
    "Stilts/Piles": 2.40,
    "Unknown": 0.30,
}


def first_floor_elevation_m(ground_elevation_m: float, clearance: str) -> float:
    return float(ground_elevation_m) + FFE_OFFSET_M.get(clearance, 0.30)


def inundation_depth_m(water_surface_m: float, ffe_m: float) -> float:
    return max(0.0, float(water_surface_m) - float(ffe_m))


def risk_score(
    *,
    vulnerability: int,
    depth_m: float,
    storeys: int,
    occupancy_type: str,
) -> int:
    """Blend Gemini vulnerability with physical inundation. Integer 1-10."""
    depth_term = min(4.0, depth_m * 1.6)
    occ = occupancy_type.lower()
    occ_term = 1.2 if occ in {"residential", "agricultural"} else 0.4 if occ == "industrial" else 0.7
    storey_term = 0.8 if storeys <= 1 and depth_m > 0.2 else 0.0
    combined = 0.55 * float(vulnerability) + depth_term + occ_term + storey_term
    return int(max(1, min(10, round(combined))))


def risk_level(score: int) -> str:
    if score >= 7:
        return "High"
    if score >= 4:
        return "Moderate"
    return "Low"


def risk_color(score: int) -> str:
    level = risk_level(score)
    if level == "High":
        return RISK_RED
    if level == "Moderate":
        return RISK_YELLOW
    return RISK_GREEN


def score_asset(
    *,
    ground_elevation_m: float,
    water_surface_m: float,
    gemini: dict[str, Any],
) -> dict[str, Any]:
    clearance = str(gemini.get("ground_clearance_elevation") or "Unknown")
    ffe = first_floor_elevation_m(ground_elevation_m, clearance)
    depth = inundation_depth_m(water_surface_m, ffe)
    score = risk_score(
        vulnerability=int(gemini.get("vulnerability_score") or 5),
        depth_m=depth,
        storeys=int(gemini.get("estimated_storeys") or 1),
        occupancy_type=str(gemini.get("occupancy_type") or "Unknown"),
    )
    level = risk_level(score)
    return {
        "water_surface_elevation_m": round(float(water_surface_m), 3),
        "ground_elevation_m": round(float(ground_elevation_m), 3),
        "first_floor_elevation_m": round(ffe, 3),
        "inundation_depth_m": round(depth, 3),
        "risk_score": score,
        "risk_level": level,
        "badge": f"{level.upper()} RISK",
        "marker-color": risk_color(score),
    }


def style_for_score(score: int) -> dict[str, Any]:
    color = risk_color(score)
    return {
        "color": color,
        "fillColor": color,
        "fillOpacity": 0.45,
        "weight": 2,
    }


def flood_legend() -> dict[str, str]:
    return {
        RISK_GREEN: "low flood exposure",
        RISK_YELLOW: "moderate flood exposure",
        RISK_RED: "high flood exposure",
        "#1D4E89": "flood hazard extent",
    }


def hazard_polygon_collection(
    rings: Sequence[list[list[float]]],
    *,
    water_surface_m: float,
    name: str = "flood_hazard_extent",
) -> dict[str, Any]:
    features = []
    for ring in rings:
        closed = list(ring)
        if closed and closed[0] != closed[-1]:
            closed = closed + [closed[0]]
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [closed]},
                "properties": {
                    "overlay": "flood_hazard_extent",
                    "name": name,
                    "water_surface_elevation_m": water_surface_m,
                    "style": {
                        "color": "#1D4E89",
                        "fillColor": "#4C8DDE",
                        "fillOpacity": 0.18,
                        "weight": 2,
                    },
                },
            }
        )
    return {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {"legend": flood_legend(), "overlay": "flood_hazard"},
    }
