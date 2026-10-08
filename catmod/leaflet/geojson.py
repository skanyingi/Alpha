"""Leaflet-ready GeoJSON. Color by loss intensity, never by model prose."""

from __future__ import annotations

from typing import Any, Sequence

LOW_LOSS_USD = 250_000.0


def marker_color(*, gul: float, reinsured: float, flagged: bool) -> str:
    if flagged:
        return "#7B1E3A"
    if reinsured > 0:
        return "#C1121F"
    if gul > LOW_LOSS_USD:
        return "#E07A3D"
    return "#2A9D4A"


def generate_leaflet_geojson(claims_data: Sequence[dict[str, Any]]) -> dict[str, Any]:
    features = []
    for c in claims_data:
        flagged = bool(c.get("is_flagged") or c.get("fraud_flag"))
        gul = float(c.get("gul") or c.get("ground_up_loss") or 0.0)
        payout = float(c.get("payout") or c.get("reinsured_payout") or 0.0)
        color = c.get("marker-color") or marker_color(gul=gul, reinsured=payout, flagged=flagged)
        lon = float(c["longitude"])
        lat = float(c["latitude"])
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": {
                    "asset_id": c.get("id") or c.get("asset_id"),
                    "occupancy": c.get("occupancy"),
                    "tiv": float(c.get("tiv") or 0.0),
                    "ground_up_loss": gul,
                    "reinsured_payout": payout,
                    "cedant_retention": float(c.get("cedant_retention") or 0.0),
                    "hdc_interpolation_score": float(c.get("hdc_interpolation_score") or 0.0),
                    "fraud_flag": flagged,
                    "marker-color": color,
                    "flood_depth_m": c.get("flood_depth_m"),
                    "damage_ratio": c.get("damage_ratio"),
                    "synthetic": bool(c.get("synthetic", False)),
                    "badge": c.get("badge") or ("synthetic" if c.get("synthetic") else ""),
                    "hazard_anomaly": c.get("hazard_anomaly"),
                    "loss_basis": c.get("loss_basis"),
                    "style": {
                        "color": color,
                        "fillColor": color,
                        "fillOpacity": 0.85,
                        "radius": 8 if not flagged else 11,
                    },
                },
            }
        )
    return {"type": "FeatureCollection", "features": features}


def hazard_polygon_feature(
    coordinates: list[list[float]],
    *,
    event_id: str,
    properties: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ring = list(coordinates)
    if ring and ring[0] != ring[-1]:
        ring = ring + [ring[0]]
    props = {
        "overlay": "hazard_footprint",
        "event_id": event_id,
        "style": {
            "color": "#1D4E89",
            "fillColor": "#4C8DDE",
            "fillOpacity": 0.18,
            "weight": 2,
        },
    }
    if properties:
        props.update(properties)
    return {
        "type": "Feature",
        "geometry": {"type": "Polygon", "coordinates": [ring]},
        "properties": props,
    }


def build_export(
    *,
    event_id: str,
    claims: Sequence[dict[str, Any]],
    hazard_polygon: list[list[float]] | None = None,
    extra_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    collection = generate_leaflet_geojson(claims)
    if hazard_polygon:
        collection["features"].append(hazard_polygon_feature(hazard_polygon, event_id=event_id))
    collection["metadata"] = {
        "event_id": event_id,
        "legend": {
            "#2A9D4A": "low loss (cedant retained, small)",
            "#E07A3D": "retained loss",
            "#C1121F": "reinsured XL payout",
            "#7B1E3A": "fraud / spatial discrepancy flag",
        },
    }
    if extra_metadata:
        collection["metadata"].update(extra_metadata)
    return collection
