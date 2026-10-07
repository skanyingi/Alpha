"""Geospatial hazard evaluation. Synthetic atlases are explicitly tagged."""

from catmod.hazard.raster import (
    IS_OUT_OF_BOUNDS,
    NULL_ISLAND,
    HazardFormatError,
    HazardHit,
    HazardRaster,
    load_hazard_file,
)
from catmod.hazard.service import (
    STANDARD_RETURN_PERIODS,
    HazardService,
    default_hazard_service,
    lookup_hazard,
)
from catmod.hazard.stochastic import HazardFootprint, StochasticEvent, StochasticHazardGenerator

__all__ = [
    "IS_OUT_OF_BOUNDS",
    "NULL_ISLAND",
    "STANDARD_RETURN_PERIODS",
    "HazardFormatError",
    "HazardHit",
    "HazardRaster",
    "HazardFootprint",
    "HazardService",
    "StochasticEvent",
    "StochasticHazardGenerator",
    "default_hazard_service",
    "load_hazard_file",
    "lookup_hazard",
]
