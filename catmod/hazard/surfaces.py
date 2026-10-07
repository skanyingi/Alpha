"""Synthetic and mounted flood atlases.

Nairobi's bundled grid is a susceptibility proxy (``depth = score × 4 m``).
Nzoia's bundled grid is a synthetic depth stand-in. Mounted ``nzoia_rp*.tif``
files replace that stand-in and keep JRC metre depths with ``synthetic: false``.
"""

from __future__ import annotations

from collections.abc import Callable

from catmod.hazard.provenance import (
    NAIROBI_PLUVIAL_SOURCE,
    NAIROBI_SUSCEPTIBILITY_DEPTH_M,
    discover_mounted_hazards,
)
from catmod.hazard.raster import HazardRaster


def _grid(
    *,
    west: float,
    south: float,
    east: float,
    north: float,
    rows: int,
    cols: int,
    sample: Callable[[float, float], float],
) -> list[list[float]]:
    dlat = (north - south) / rows
    dlon = (east - west) / cols
    values: list[list[float]] = []
    for r in range(rows):
        lat = north - (r + 0.5) * dlat
        row: list[float] = []
        for c in range(cols):
            lon = west + (c + 0.5) * dlon
            row.append(round(float(sample(lat, lon)), 5))
        values.append(row)
    return values


def miami_surge_raster() -> HazardRaster:
    """100-year synthetic surge depth (metres), deeper toward the Atlantic."""
    west, south, east, north = -80.32, 25.70, -80.10, 25.86

    def sample(lat: float, lon: float) -> float:
        coastal = (lon - west) / (east - west)
        southness = (north - lat) / (north - south)
        depth = 0.25 + 5.6 * (coastal**1.35) + 0.35 * southness
        return max(0.0, min(8.0, depth))

    return HazardRaster(
        values=_grid(west=west, south=south, east=east, north=north, rows=32, cols=32, sample=sample),
        west=west,
        south=south,
        east=east,
        north=north,
        name="miami",
        source="synthetic:miami_surge_100y",
        synthetic=True,
        proxy=True,
        value_kind="depth_m",
    )


def nairobi_susceptibility_raster() -> HazardRaster:
    """Synthetic pluvial susceptibility for Nairobi. Score in [0, 1]."""
    west, south, east, north = 36.66, -1.45, 37.10, -1.15

    def sample(lat: float, lon: float) -> float:
        # Higher scores toward the southwestern low ground (Kibera / Ngong drainage).
        southness = (north - lat) / (north - south)
        westness = (east - lon) / (east - west)
        score = 0.08 + 0.55 * southness * westness + 0.12 * southness
        return max(0.0, min(1.0, score))

    return HazardRaster(
        values=_grid(west=west, south=south, east=east, north=north, rows=28, cols=28, sample=sample),
        west=west,
        south=south,
        east=east,
        north=north,
        name="nairobi",
        source=NAIROBI_PLUVIAL_SOURCE,
        synthetic=True,
        proxy=True,
        value_kind="susceptibility",
        susceptibility_depth_m=NAIROBI_SUSCEPTIBILITY_DEPTH_M,
    )


def nzoia_depth_raster() -> HazardRaster:
    """Synthetic metre depths for the Nzoia corridor when JRC GeoTIFFs are absent."""
    west, south, east, north = 33.95, 0.05, 34.85, 0.85

    def sample(lat: float, lon: float) -> float:
        river = abs(lon - 34.22)
        corridor = max(0.0, 1.0 - river / 0.28)
        downstream = max(0.0, min(1.0, (0.55 - lat) / 0.50))
        depth = 0.15 + 4.8 * corridor * (0.45 + 0.55 * downstream)
        return max(0.0, min(8.0, depth))

    return HazardRaster(
        values=_grid(west=west, south=south, east=east, north=north, rows=30, cols=30, sample=sample),
        west=west,
        south=south,
        east=east,
        north=north,
        name="nzoia",
        source="Synthetic Nzoia depth stand-in (mount nzoia_rp*.tif for JRC metre depths)",
        synthetic=True,
        proxy=True,
        value_kind="depth_m",
    )


def default_surfaces() -> list[HazardRaster]:
    mounted = discover_mounted_hazards()
    nzoia = [surface for surface in mounted if surface.name == "nzoia"]
    nairobi = [surface for surface in mounted if surface.name == "nairobi"]
    hotspots = [surface for surface in mounted if surface.name == "nairobi_hotspots"]
    surfaces: list[HazardRaster] = []
    surfaces.extend(nzoia or [nzoia_depth_raster()])
    surfaces.extend(nairobi or [nairobi_susceptibility_raster()])
    surfaces.extend(hotspots)
    surfaces.append(miami_surge_raster())
    return surfaces
