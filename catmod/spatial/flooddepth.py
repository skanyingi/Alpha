"""Flood depth grid for one diorama cell.

Samples the hazard atlas already used by the loss engine. Values are metres
of water above local ground (susceptibility × 4 m for Nairobi, then the
return-period scale, clipped to 10 m). They are not AMSL elevations.
"""

from __future__ import annotations

from typing import Any

from catmod.hazard.service import STANDARD_RETURN_PERIODS, default_hazard_service


def flood_depth_grid(
    west: float,
    south: float,
    east: float,
    north: float,
    *,
    rows: int = 32,
    cols: int = 32,
    return_period: int = 100,
    region: str = "nairobi",
) -> dict[str, Any]:
    rows = max(2, min(int(rows), 64))
    cols = max(2, min(int(cols), 64))
    if return_period not in STANDARD_RETURN_PERIODS:
        known = ", ".join(str(rp) for rp in STANDARD_RETURN_PERIODS)
        raise ValueError(f"return_period must be one of {known}")
    if east == west:
        east = west + 1e-4
    if north == south:
        north = south + 1e-4

    service = default_hazard_service()
    depth: list[list[float]] = []
    synthetic = True
    proxy = True
    source = ""
    for r in range(rows):
        lat = south + (north - south) * r / (rows - 1)
        line: list[float] = []
        for c in range(cols):
            lon = west + (east - west) * c / (cols - 1)
            hit = service.lookup(lat, lon, return_period=return_period, region=region)
            metres = float(hit.depth_m or 0.0)
            line.append(round(max(0.0, min(10.0, metres)), 4))
            if hit.in_bounds:
                synthetic = bool(hit.synthetic)
                proxy = bool(hit.proxy)
                source = hit.source or source
        depth.append(line)

    flat = [value for line in depth for value in line]
    return {
        "crs": "EPSG:4326",
        "vertical_meaning": "metres_above_local_ground",
        "region": region,
        "return_period": return_period,
        "rows": rows,
        "cols": cols,
        "bbox": {"west": west, "south": south, "east": east, "north": north},
        "depth_m": depth,
        "min_depth_m": min(flat) if flat else 0.0,
        "max_depth_m": max(flat) if flat else 0.0,
        "synthetic": synthetic,
        "proxy": proxy,
        "source": source,
        "note": (
            "Drape as terrain elevation + depth_m. "
            "flood_wse_m is not an AMSL plane over Nairobi."
        ),
    }
