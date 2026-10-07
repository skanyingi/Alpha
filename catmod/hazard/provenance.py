"""Filename provenance for hackathon hazard products.

Real JRC depth grids and Nairobi County hotspots stay ``synthetic: false``.
The Nairobi pluvial proxy and generated portfolios stay ``synthetic: true``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from decimal import Decimal
from pathlib import Path

JRC_NZOIA_SOURCE = "European Commission Joint Research Centre (JRC) Global Flood Hazard Maps"
NAIROBI_HOTSPOT_SOURCE = "Nairobi County Government Flood Hotspots Mapping (Geocoded)"
NAIROBI_PLUVIAL_SOURCE = "Copernicus GLO-30 DEM + OSM River Distance Proxy"
SYNTHETIC_PORTFOLIO_SOURCE = "Synthetic Building Portfolio (Generated for Hackathon)"
# Documented Nairobi assumption. Susceptibility is not a measured depth.
NAIROBI_SUSCEPTIBILITY_DEPTH_M = Decimal("4.0")
SUSCEPTIBILITY_CONVERSION = "proxy conversion assumption: depth_m = susceptibility × 4.0 m"

_RP = re.compile(r"rp[_\-]?(\d+)", re.IGNORECASE)


@dataclass(frozen=True)
class HazardProvenance:
    synthetic: bool
    proxy: bool
    source: str
    value_kind: str
    susceptibility_depth_m: Decimal | None = None
    native_return_period: int | None = None
    apply_return_period_scale: bool = True
    name: str | None = None


def return_period_from_name(name: str) -> int | None:
    match = _RP.search(name)
    if match is None:
        return None
    return int(match.group(1))


def infer_provenance(path: str | Path) -> HazardProvenance:
    source = Path(path)
    stem = source.name.lower()
    rp = return_period_from_name(stem)
    if "nzoia_rp" in stem:
        return HazardProvenance(
            synthetic=False,
            proxy=False,
            source=JRC_NZOIA_SOURCE,
            value_kind="depth_m",
            native_return_period=rp,
            apply_return_period_scale=False,
            name="nzoia",
        )
    if "nairobi_hotspots" in stem:
        return HazardProvenance(
            synthetic=False,
            proxy=False,
            source=NAIROBI_HOTSPOT_SOURCE,
            value_kind="susceptibility",
            susceptibility_depth_m=NAIROBI_SUSCEPTIBILITY_DEPTH_M,
            name="nairobi_hotspots",
        )
    if "nairobi_pluvial" in stem or "pluvial_proxy" in stem:
        return HazardProvenance(
            synthetic=True,
            proxy=True,
            source=NAIROBI_PLUVIAL_SOURCE,
            value_kind="susceptibility",
            susceptibility_depth_m=NAIROBI_SUSCEPTIBILITY_DEPTH_M,
            name="nairobi",
        )
    return HazardProvenance(
        synthetic=True,
        proxy=True,
        source=str(source),
        value_kind="depth_m",
        name=None,
    )


def apply_synthetic_override(provenance: HazardProvenance, synthetic: bool | None) -> HazardProvenance:
    if synthetic is None:
        return provenance
    return replace(provenance, synthetic=synthetic)


def exposure_portfolio_synthetic(filename: str) -> bool:
    name = Path(filename).name.lower()
    return "synthetic" in name or name.startswith("sample_")


def discover_mounted_hazards(data_root: Path | None = None) -> list:
    """Load hackathon rasters when they are present under ``data/``."""
    root = data_root or Path(__file__).resolve().parents[2] / "data"
    if not root.is_dir():
        return []
    patterns = (
        "nzoia_rp*.tif",
        "nzoia_rp*.tiff",
        "nairobi_pluvial_proxy_*.tif",
        "nairobi_pluvial_proxy_*.tiff",
        "nairobi_hotspots_geocoded.csv",
    )
    from catmod.hazard.raster import load_hazard_file

    mounted = []
    seen: set[Path] = set()
    for pattern in patterns:
        for path in sorted(root.rglob(pattern)):
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            mounted.append(load_hazard_file(path))
    return mounted
