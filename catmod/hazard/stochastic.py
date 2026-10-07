"""Synthetic stochastic event sets and flood-intensity footprints.

This module mirrors an Oasis-style event catalog: each event has a rate and a
spatial intensity grid. It does not apply deductibles, limits, or treaty terms.
Every product is tagged ``synthetic`` and ``stochastic``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from decimal import ROUND_HALF_EVEN, Decimal

import numpy as np

from catmod.hazard.service import STANDARD_RETURN_PERIODS

DEPTH_QUANTUM = Decimal("0.01")
MAX_DEPTH_M = Decimal("10")
INTENSITY_BINS: tuple[Decimal, ...] = (
    Decimal("0"),
    Decimal("0.25"),
    Decimal("0.5"),
    Decimal("1"),
    Decimal("1.5"),
    Decimal("2"),
    Decimal("3"),
    Decimal("4"),
    Decimal("6"),
)
_GRID = 8


@dataclass(frozen=True)
class _Region:
    name: str
    peril: str
    west: float
    south: float
    east: float
    north: float
    gumbel_location: float
    gumbel_scale: float
    lengthscale_deg: float


REGIONS: dict[str, _Region] = {
    "nairobi": _Region("nairobi", "flood_pluvial", 36.66, -1.45, 37.10, -1.15, 0.30, 0.70, 0.08),
    "nzoia": _Region("nzoia", "flood_fluvial", 33.95, 0.05, 34.85, 0.85, 0.45, 0.85, 0.12),
}


@dataclass(frozen=True)
class StochasticEvent:
    event_id: str
    return_period: int
    rate: Decimal
    intensity_matrix: np.ndarray = field(repr=False)
    peril: str
    region: str
    magnitude_m: Decimal
    seed: int
    synthetic: bool = True
    stochastic: bool = True

    def as_dict(self) -> dict[str, object]:
        return {
            "event_id": self.event_id,
            "return_period": self.return_period,
            "rate": format(self.rate, "f"),
            "peril": self.peril,
            "region": self.region,
            "magnitude_m": format(self.magnitude_m, "f"),
            "mean_intensity_m": float(self.intensity_matrix.mean()),
            "seed": self.seed,
            "synthetic": self.synthetic,
            "stochastic": self.stochastic,
        }


@dataclass(frozen=True)
class HazardFootprint:
    event_id: str
    location_id: str
    latitude: float
    longitude: float
    depth_m: Decimal
    intensity_bin: int
    synthetic: bool = True
    stochastic: bool = True

    def as_dict(self) -> dict[str, object]:
        return {
            "event_id": self.event_id,
            "location_id": self.location_id,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "depth_m": format(self.depth_m, "f"),
            "intensity_bin": self.intensity_bin,
            "synthetic": self.synthetic,
            "stochastic": self.stochastic,
        }


def gumbel_quantile(return_period: int, location: float, scale: float) -> float:
    """Gumbel quantile at annual exceedance ``1 / return_period``."""
    if return_period <= 1:
        raise ValueError("return_period must be > 1")
    if scale <= 0:
        raise ValueError("Gumbel scale must be positive")
    probability = 1.0 - 1.0 / float(return_period)
    return float(location - scale * math.log(-math.log(probability)))


def rbf_covariance(lat: np.ndarray, lon: np.ndarray, lengthscale: float) -> np.ndarray:
    """Symmetric RBF kernel on latitude/longitude, in degrees."""
    if lengthscale <= 0:
        raise ValueError("lengthscale must be positive")
    flat_lat = np.asarray(lat, dtype=np.float64).ravel()
    flat_lon = np.asarray(lon, dtype=np.float64).ravel()
    dlat = flat_lat[:, None] - flat_lat[None, :]
    dlon = flat_lon[:, None] - flat_lon[None, :]
    kernel = np.exp(-(dlat * dlat + dlon * dlon) / (2.0 * lengthscale * lengthscale))
    kernel = 0.5 * (kernel + kernel.T)
    kernel.flat[:: kernel.shape[0] + 1] += 1e-6
    return kernel


def intensity_bin(depth_m: Decimal) -> int:
    """Largest standard bin whose threshold is still <= ``depth_m``."""
    chosen = 0
    for index, edge in enumerate(INTENSITY_BINS):
        if depth_m >= edge:
            chosen = index
    return chosen


def quantize_depth(value: float) -> Decimal:
    depth = Decimal(f"{value:.6f}").quantize(DEPTH_QUANTUM, rounding=ROUND_HALF_EVEN)
    if depth < 0:
        return Decimal("0.00")
    if depth > MAX_DEPTH_M:
        return MAX_DEPTH_M
    return depth


class StochasticHazardGenerator:
    """Regional flood catalog. Rates in a return-period bin sum to ``1 / RP``."""

    def __init__(self, *, grid: int = _GRID) -> None:
        if grid < 2:
            raise ValueError("grid must be at least 2")
        self.grid = grid

    def generate_event_set(
        self,
        region: str,
        num_events: int = 10_000,
        seed: int = 42,
    ) -> list[StochasticEvent]:
        spec = _region(region)
        periods = list(STANDARD_RETURN_PERIODS)
        if num_events < len(periods):
            raise ValueError(f"num_events must be at least {len(periods)} so every return period is represented")
        counts = _split(num_events, len(periods))
        lats, lons = _nodes(spec, self.grid)
        covariance = rbf_covariance(lats, lons, spec.lengthscale_deg)
        cholesky = np.linalg.cholesky(covariance)
        rng = np.random.default_rng(seed)
        events: list[StochasticEvent] = []
        for period, count in zip(periods, counts):
            magnitude = gumbel_quantile(period, spec.gumbel_location, spec.gumbel_scale)
            magnitude_m = quantize_depth(magnitude)
            bin_rate = Decimal(1) / Decimal(period)
            share = bin_rate / Decimal(count)
            white = rng.standard_normal((count, self.grid * self.grid))
            field = white @ cholesky.T
            multiplier = np.clip(1.0 + 0.15 * field, 0.25, 1.75)
            grids = (magnitude * multiplier).reshape(count, self.grid, self.grid)
            assigned = Decimal(0)
            for index in range(count):
                rate = bin_rate - assigned if index == count - 1 else share
                assigned += rate
                events.append(
                    StochasticEvent(
                        event_id=f"{spec.name}-rp{period}-{index:05d}",
                        return_period=period,
                        rate=rate,
                        intensity_matrix=grids[index],
                        peril=spec.peril,
                        region=spec.name,
                        magnitude_m=magnitude_m,
                        seed=seed,
                    )
                )
        return events

    def get_footprint(
        self,
        event: StochasticEvent,
        locations: list[tuple[float, float]],
    ) -> list[HazardFootprint]:
        spec = _region(event.region)
        footprints: list[HazardFootprint] = []
        for index, (latitude, longitude) in enumerate(locations):
            sampled = _bilinear(event.intensity_matrix, spec, latitude, longitude)
            depth = quantize_depth(sampled)
            footprints.append(
                HazardFootprint(
                    event_id=event.event_id,
                    location_id=f"loc-{index}",
                    latitude=float(latitude),
                    longitude=float(longitude),
                    depth_m=depth,
                    intensity_bin=intensity_bin(depth),
                )
            )
        return footprints


def _region(name: str) -> _Region:
    key = (name or "").strip().lower()
    spec = REGIONS.get(key)
    if spec is None:
        known = ", ".join(sorted(REGIONS))
        raise ValueError(f"unknown stochastic region {name!r}; known regions: {known}")
    return spec


def _split(total: int, bins: int) -> list[int]:
    base, remainder = divmod(total, bins)
    return [base + (1 if index < remainder else 0) for index in range(bins)]


def _nodes(spec: _Region, grid: int) -> tuple[np.ndarray, np.ndarray]:
    lats = np.linspace(spec.north, spec.south, grid)
    lons = np.linspace(spec.west, spec.east, grid)
    yy, xx = np.meshgrid(lats, lons, indexing="ij")
    return yy, xx


def _bilinear(matrix: np.ndarray, spec: _Region, latitude: float, longitude: float) -> float:
    rows, cols = matrix.shape
    x_span = spec.east - spec.west
    y_span = spec.north - spec.south
    x = 0.0 if x_span == 0 else (longitude - spec.west) / x_span * (cols - 1)
    y = 0.0 if y_span == 0 else (spec.north - latitude) / y_span * (rows - 1)
    x = float(np.clip(x, 0.0, cols - 1))
    y = float(np.clip(y, 0.0, rows - 1))
    x0 = int(math.floor(x))
    y0 = int(math.floor(y))
    x1 = min(x0 + 1, cols - 1)
    y1 = min(y0 + 1, rows - 1)
    tx = x - x0
    ty = y - y0
    return float(
        matrix[y0, x0] * (1 - tx) * (1 - ty)
        + matrix[y0, x1] * tx * (1 - ty)
        + matrix[y1, x0] * (1 - tx) * ty
        + matrix[y1, x1] * tx * ty
    )
