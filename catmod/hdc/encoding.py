"""Continuous key-value encoding of geospatial and financial scalars."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

import catmod.hdc.fhrr as fhrr
from catmod.hdc.fhrr import Array


def _norm_lat(lat: float) -> float:
    return float(np.clip(lat, -90.0, 90.0)) / 90.0


def _norm_lon(lon: float) -> float:
    return float(np.clip(lon, -180.0, 180.0)) / 180.0


def _norm_lat_fine(lat: float) -> float:
    """~2 km phase cycle so neighboring assets do not look identical."""
    return float(np.clip(lat, -90.0, 90.0)) / 0.02


def _norm_lon_fine(lon: float) -> float:
    return float(np.clip(lon, -180.0, 180.0)) / 0.02


def _norm_elev(elev: float) -> float:
    return float(np.clip(elev, -500.0, 9000.0)) / 9000.0


def _norm_time(t: float) -> float:
    return float(t)


def _norm_cost(cost: float) -> float:
    if cost <= 0:
        return 0.0
    return float(np.log1p(cost) / np.log1p(1.0e9))


def _norm_damage(damage_ratio: float) -> float:
    return float(np.clip(damage_ratio, 0.0, 1.0))


@dataclass
class ItemMemory:
    dim: int = fhrr.DIM
    seed: int = 42
    rng: np.random.Generator = field(init=False, repr=False)
    keys: dict[str, Array] = field(default_factory=dict)
    occupancy: dict[str, Array] = field(default_factory=dict)
    bases: dict[str, Array] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.rng = np.random.default_rng(self.seed)
        for name in ("lat", "lon", "elev", "time", "cost", "occ", "id", "lat_fine", "lon_fine", "damage"):
            self.keys[name] = fhrr.random_hypervector(self.dim, self.rng)
            self.bases[name] = fhrr.random_hypervector(self.dim, self.rng)

    def occupancy_vector(self, code: str) -> Array:
        if code not in self.occupancy:
            self.occupancy[code] = fhrr.random_hypervector(self.dim, self.rng)
        return self.occupancy[code]

    def encode_scalar(self, name: str, value: float, normalizer) -> Array:
        return fhrr.exponentiate(self.bases[name], normalizer(value))

    def encode_lat(self, latitude: float) -> Array:
        coarse = self.encode_scalar("lat", latitude, _norm_lat)
        fine = self.encode_scalar("lat_fine", latitude, _norm_lat_fine)
        return fhrr.bind(coarse, fine)

    def encode_lon(self, longitude: float) -> Array:
        coarse = self.encode_scalar("lon", longitude, _norm_lon)
        fine = self.encode_scalar("lon_fine", longitude, _norm_lon_fine)
        return fhrr.bind(coarse, fine)

    def encode_claim(
        self,
        *,
        latitude: float,
        longitude: float,
        elevation: float,
        time_t: float,
        cost: float,
        occupancy: str,
        damage_ratio: float = 0.0,
    ) -> Array:
        """Location, occupancy, and physical damage ratio, superposed into one claim vector."""
        v_lat = self.encode_lat(latitude)
        v_lon = self.encode_lon(longitude)
        v_elev = self.encode_scalar("elev", elevation, _norm_elev)
        v_time = self.encode_scalar("time", time_t, _norm_time)
        v_cost = self.encode_scalar("cost", cost, _norm_cost)
        v_damage = self.encode_scalar("damage", damage_ratio, _norm_damage)
        v_occ = self.occupancy_vector(occupancy)
        parts = [
            fhrr.bind(self.keys["lat"], v_lat),
            fhrr.bind(self.keys["lon"], v_lon),
            fhrr.bind(self.keys["elev"], v_elev),
            fhrr.bind(self.keys["time"], v_time),
            fhrr.bind(self.keys["cost"], v_cost),
            fhrr.bind(self.keys["occ"], v_occ),
            fhrr.bind(self.keys["damage"], v_damage),
            fhrr.bind(self.keys["id"], fhrr.bind(fhrr.bind(v_lat, v_lon), v_cost)),
        ]
        return fhrr.superpose(parts)
