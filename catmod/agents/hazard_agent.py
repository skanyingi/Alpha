"""Surface lookup and damage ratios for Nairobi and Nzoia only."""

from __future__ import annotations

import time
from decimal import Decimal
from typing import Any

from catmod.agents.base import AgentResult, AgentRole, BaseSubAgent
from catmod.hazard.service import default_hazard_service
from catmod.vulnerability.engine import assess

REGIONS = ("nairobi", "nzoia")


class HazardVulnerabilityAgent(BaseSubAgent):
    role = AgentRole.HAZARD_VULNERABILITY
    audit_layer = 8

    async def execute(self, payload: dict[str, Any]) -> AgentResult:
        started = time.perf_counter()
        region = str(payload.get("region") or "nairobi")
        if region not in REGIONS:
            raise ValueError("hazard region must be nairobi or nzoia")
        latitude = float(payload.get("latitude"))
        longitude = float(payload.get("longitude"))
        occupancy = str(payload.get("occupancy") or "UNK")
        tiv = Decimal(str(payload.get("tiv") or "0"))
        hit = default_hazard_service().lookup(
            latitude,
            longitude,
            return_period=int(payload.get("return_period") or 100),
            region=region,
        )
        depth = hit.depth_m if hit.depth_m is not None else Decimal("0")
        vuln = assess(occupancy, depth, tiv)
        return AgentResult(
            agent_role=self.role,
            status="ok",
            latency_ms=(time.perf_counter() - started) * 1000.0,
            outputs={
                "region": region,
                "depth_m": None if hit.depth_m is None else float(hit.depth_m),
                "damage_ratio": float(vuln.damage_ratio),
                "modeled_ground_up_loss": format(vuln.ground_up_loss, "f"),
                "synthetic": bool(hit.synthetic or vuln.synthetic),
            },
            audit_layer=self.audit_layer,
        )
