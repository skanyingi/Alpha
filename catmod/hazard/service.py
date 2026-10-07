"""Hazard evaluation: raster or coordinate lookup, then return-period scaling."""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal
from functools import lru_cache

from catmod.hazard.raster import (
    IS_OUT_OF_BOUNDS,
    MAX_DEPTH_M,
    NULL_ISLAND,
    CoordinateHazardIndex,
    HazardHit,
    HazardRaster,
    is_null_island,
    load_hazard_file,
)
from catmod.hazard.provenance import (
    NAIROBI_SUSCEPTIBILITY_DEPTH_M,
    SUSCEPTIBILITY_CONVERSION,
)
from catmod.hazard.surfaces import default_surfaces

STANDARD_RETURN_PERIODS: tuple[int, ...] = (10, 25, 50, 100, 250, 500)
# Multipliers on the stored 100-year field. Strictly increasing, so a
# non-decreasing damage curve cannot invent a smaller loss at a longer RP.
RETURN_PERIOD_SCALE: dict[int, Decimal] = {
    10: Decimal("0.35"),
    25: Decimal("0.55"),
    50: Decimal("0.78"),
    100: Decimal("1"),
    250: Decimal("1.28"),
    500: Decimal("1.55"),
}
_DEPTH_QUANTUM = Decimal("0.0001")


def scale_for_return_period(return_period: int) -> Decimal:
    if return_period not in RETURN_PERIOD_SCALE:
        known = ", ".join(str(rp) for rp in STANDARD_RETURN_PERIODS)
        raise ValueError(f"return_period must be one of {known}")
    return RETURN_PERIOD_SCALE[return_period]


class HazardService:
    def __init__(self, surfaces: list[HazardRaster | CoordinateHazardIndex] | None = None) -> None:
        self.surfaces = list(surfaces) if surfaces is not None else default_surfaces()

    def lookup(
        self,
        latitude: float,
        longitude: float,
        *,
        return_period: int = 100,
        region: str | None = None,
    ) -> HazardHit:
        scale = scale_for_return_period(return_period)
        if is_null_island(latitude, longitude):
            return self._anomaly(
                latitude,
                longitude,
                anomaly=NULL_ISLAND,
                message="Null Island",
                return_period=return_period,
                synthetic=True,
                proxy=False,
                source="anomaly",
                region="null_island",
            )
        if not (-90.0 <= latitude <= 90.0 and -180.0 <= longitude <= 180.0):
            return self._anomaly(
                latitude,
                longitude,
                anomaly=IS_OUT_OF_BOUNDS,
                message="IS_OUT_OF_BOUNDS",
                return_period=return_period,
                synthetic=True,
                proxy=False,
                source="anomaly",
                region=region or "invalid",
            )
        searched = self._select(region, return_period)
        for surface in searched:
            if surface.covers(latitude, longitude):
                return self._from_surface(surface, latitude, longitude, return_period, scale)
        synthetic = all(surface.synthetic for surface in searched) if searched else True
        return self._anomaly(
            latitude,
            longitude,
            anomaly=IS_OUT_OF_BOUNDS,
            message="IS_OUT_OF_BOUNDS",
            return_period=return_period,
            synthetic=synthetic,
            proxy=any(surface.proxy for surface in searched) if searched else True,
            source="atlas",
            region=region or "unassigned",
        )

    def _select(
        self,
        region: str | None,
        return_period: int,
    ) -> list[HazardRaster | CoordinateHazardIndex]:
        pool = self.surfaces
        if region:
            key = region.strip().lower()
            pool = [surface for surface in self.surfaces if surface.name.lower() == key]
            if not pool:
                known = ", ".join(sorted({surface.name for surface in self.surfaces})) or "(none)"
                raise ValueError(f"unknown hazard region {region!r}; known regions: {known}")
        exact = [surface for surface in pool if surface.native_return_period == return_period]
        if exact:
            return exact
        return [surface for surface in pool if surface.native_return_period is None]

    def _from_surface(
        self,
        surface: HazardRaster | CoordinateHazardIndex,
        latitude: float,
        longitude: float,
        return_period: int,
        scale: Decimal,
    ) -> HazardHit:
        raw = surface.sample_base(latitude, longitude)
        scale_used = scale if surface.apply_return_period_scale else Decimal("1")
        message = ""
        if surface.value_kind == "susceptibility":
            native = _clip(raw, Decimal("0"), Decimal("1"))
            reference = surface.susceptibility_depth_m or NAIROBI_SUSCEPTIBILITY_DEPTH_M
            base_depth = native * reference
            message = SUSCEPTIBILITY_CONVERSION
        else:
            base_depth = _clip(raw, Decimal("0"), MAX_DEPTH_M)
        depth = _q(min(MAX_DEPTH_M, base_depth * scale_used))
        susceptibility = _q(depth / MAX_DEPTH_M)
        return HazardHit(
            latitude=latitude,
            longitude=longitude,
            depth_m=depth,
            base_depth_m=_q(base_depth),
            susceptibility=susceptibility,
            in_bounds=True,
            anomaly=None,
            synthetic=surface.synthetic,
            proxy=surface.proxy,
            source=surface.source,
            region=surface.name,
            return_period=return_period,
            value_kind=surface.value_kind,
            message=message,
        )

    def _anomaly(
        self,
        latitude: float,
        longitude: float,
        *,
        anomaly: str,
        message: str,
        return_period: int,
        synthetic: bool,
        proxy: bool,
        source: str,
        region: str,
    ) -> HazardHit:
        return HazardHit(
            latitude=latitude,
            longitude=longitude,
            depth_m=None,
            base_depth_m=None,
            susceptibility=None,
            in_bounds=False,
            anomaly=anomaly,
            synthetic=synthetic,
            proxy=proxy,
            source=source,
            region=region,
            return_period=return_period,
            value_kind="depth_m",
            message=message,
        )


def _clip(value: Decimal, low: Decimal, high: Decimal) -> Decimal:
    if value < low:
        return low
    if value > high:
        return high
    return value


def _q(value: Decimal) -> Decimal:
    return value.quantize(_DEPTH_QUANTUM, rounding=ROUND_HALF_EVEN)


@lru_cache(maxsize=1)
def default_hazard_service() -> HazardService:
    return HazardService()


def lookup_hazard(
    latitude: float,
    longitude: float,
    *,
    return_period: int = 100,
    region: str | None = None,
) -> HazardHit:
    return default_hazard_service().lookup(
        latitude,
        longitude,
        return_period=return_period,
        region=region,
    )


def service_with_file(path: str, *, synthetic: bool | None = None) -> HazardService:
    """Atlas plus a caller-supplied raster searched first. Provenance follows the filename."""
    loaded = load_hazard_file(path, synthetic=synthetic)
    return HazardService([loaded, *default_surfaces()])
