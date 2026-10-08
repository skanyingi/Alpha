"""Encode a flagged line into FHRR memory. This does not calculate payouts."""

from __future__ import annotations

import time
from typing import Any

from catmod.agents.base import AgentResult, AgentRole, BaseSubAgent
from catmod.config import get_settings
from catmod.hdc.encoding import ItemMemory
from catmod.hdc.memory import PortfolioMemory


class HDCMemoryAgent(BaseSubAgent):
    role = AgentRole.HDC_MEMORY
    audit_layer = 3

    async def execute(self, payload: dict[str, Any]) -> AgentResult:
        started = time.perf_counter()
        settings = get_settings()
        items = ItemMemory(dim=settings.hdc_dim, seed=settings.hdc_seed)
        memory = PortfolioMemory(items)
        asset_id = str(payload.get("asset_id") or "line")
        memory.encode_and_add(
            latitude=float(payload.get("latitude") or -1.2921),
            longitude=float(payload.get("longitude") or 36.8219),
            elevation=float(payload.get("elevation") or 1660),
            time_t=float(payload.get("time_t") or 0),
            cost=float(payload.get("cost") or 0),
            occupancy=str(payload.get("occupancy") or "UNK"),
            damage_ratio=float(payload.get("damage_ratio") or 0),
        )
        return AgentResult(
            agent_role=self.role,
            status="ok",
            latency_ms=(time.perf_counter() - started) * 1000.0,
            outputs={
                "asset_id": asset_id,
                "dimension": settings.hdc_dim,
                "replaces_payout": False,
            },
            audit_layer=self.audit_layer,
        )
