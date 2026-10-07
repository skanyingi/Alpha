"""Portfolio superposition memory and instantaneous FHRR queries."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

import catmod.hdc.fhrr as fhrr
from catmod.hdc.encoding import ItemMemory, _norm_time
from catmod.hdc.fhrr import Array


@dataclass
class PortfolioMemory:
    items: ItemMemory
    memory: Array = field(init=False)
    count: int = 0

    def __post_init__(self) -> None:
        self.memory = np.zeros(self.items.dim, dtype=np.complex64)

    def add(self, claim_hv: Array) -> None:
        self.memory = self.memory + fhrr._as_hv(claim_hv)
        self.count += 1

    def encode_and_add(self, **kwargs) -> Array:
        hv = self.items.encode_claim(**kwargs)
        self.add(hv)
        return hv

    def project_time(self, delta_t: float) -> Array:
        """M(t + Δt) = M(t) ⊗ P^{Δt}."""
        p_delta = fhrr.exponentiate(self.items.bases["time"], _norm_time(delta_t))
        return fhrr.bind(self.memory, p_delta)

    def location_roles(self, latitude: float, longitude: float) -> tuple[Array, Array]:
        v_lat = self.items.encode_lat(latitude)
        v_lon = self.items.encode_lon(longitude)
        return (
            fhrr.bind(self.items.keys["lat"], v_lat),
            fhrr.bind(self.items.keys["lon"], v_lon),
        )

    def interpolation_score(self, latitude: float, longitude: float) -> float:
        """Mean similarity of (K_lat ⊗ V_lat) and (K_lon ⊗ V_lon) to M.

        Matches the stored role-filler superposition; a 4-way bind would be
        orthogonal to bundled pairs and collapse to noise.
        """
        if self.count == 0:
            return 0.0
        lat_role, lon_role = self.location_roles(latitude, longitude)
        scale = max(self.count, 1)
        memory = self.memory / scale
        return 0.5 * (
            fhrr.similarity(lat_role, memory) + fhrr.similarity(lon_role, memory)
        )

    def interpolate_cost(self, latitude: float, longitude: float) -> float:
        """Unbind the loc-cost association (K_id ⊗ V_lat ⊗ V_lon ⊗ V_cost)."""
        if self.count == 0:
            return 0.0
        v_lat = self.items.encode_lat(latitude)
        v_lon = self.items.encode_lon(longitude)
        assoc = fhrr.unbind(self.memory, self.items.keys["id"])
        cost_hv = fhrr.unbind(fhrr.unbind(assoc, v_lat), v_lon)
        x_hat = fhrr.decode_exponent(fhrr.cleanup(cost_hv), self.items.bases["cost"])
        x_hat = float(np.clip(x_hat, 0.0, 1.5))
        return float(np.expm1(x_hat * np.log1p(1.0e9)))

    def exposure_clusters(
        self,
        lat_range: tuple[float, float],
        lon_range: tuple[float, float],
        steps: int = 12,
    ) -> list[dict[str, float]]:
        """Grid probe of superposition — no vector database, O(D) per cell."""
        lats = np.linspace(lat_range[0], lat_range[1], steps)
        lons = np.linspace(lon_range[0], lon_range[1], steps)
        cells: list[dict[str, float]] = []
        for lat in lats:
            for lon in lons:
                score = self.interpolation_score(float(lat), float(lon))
                cells.append(
                    {
                        "latitude": float(lat),
                        "longitude": float(lon),
                        "exposure_score": float(score),
                    }
                )
        cells.sort(key=lambda c: c["exposure_score"], reverse=True)
        return cells
