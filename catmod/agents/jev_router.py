"""Master orchestrator. Jev Choice, Score, and Noul decide the handoff.

A line goes straight to the finance tool when occupancy confidence is above
0.95, fraud Noul is below 0.05, and the spatial score is not flagged.
Everything else is handed to HDC for a physics check. HDC never replaces
the decimal payout.
"""

from __future__ import annotations

import time
from typing import Any

from catmod.agents.base import AgentResult, AgentRole, BaseSubAgent
from catmod.config import get_settings
from catmod.ingestion.parser import parse_attachment
from catmod.jev.harness import JevHarness
from catmod.schemas import TriageResult

OCCUPANCY_DIRECT = 0.95
FRAUD_DIRECT = 0.05
SPATIAL_FLAG = 1.5


def route_decision(triage: TriageResult) -> str:
    """Return finance or hdc_physics. Spatial flags stay on the HDC path."""
    direct = (
        triage.occupancy.confidence > OCCUPANCY_DIRECT
        and triage.fraud_or_discrepancy.noul < FRAUD_DIRECT
        and triage.spatial_severity.score < SPATIAL_FLAG
    )
    if direct:
        return "finance"
    return "hdc_physics"


class JevRouterAgent(BaseSubAgent):
    role = AgentRole.JEV_ROUTER
    audit_layer = 2

    async def execute(self, payload: dict[str, Any]) -> AgentResult:
        started = time.perf_counter()
        claims = payload.get("claims")
        if claims is None:
            claims = parse_attachment(
                filename=str(payload.get("filename") or "bordereau.csv"),
                text=None if payload.get("data") is None else str(payload.get("data")),
                content_type=payload.get("content_type"),
            )
        triages = JevHarness(get_settings()).triage_batch(list(claims))
        routes = []
        for triage in triages:
            decision = route_decision(triage)
            routes.append(
                {
                    "asset_id": triage.asset_id,
                    "route": decision,
                    "harness_route": triage.route,
                    "occupancy_confidence": triage.occupancy.confidence,
                    "fraud_noul": triage.fraud_or_discrepancy.noul,
                    "spatial_severity": triage.spatial_severity.score,
                }
            )
        elapsed = (time.perf_counter() - started) * 1000.0
        return AgentResult(
            agent_role=self.role,
            status="ok" if elapsed < 500 else "latency_budget_exceeded",
            latency_ms=elapsed,
            outputs={
                "budget_ms": 500,
                "within_budget": elapsed < 500,
                "route_finance": sum(1 for row in routes if row["route"] == "finance"),
                "route_hdc_physics": sum(1 for row in routes if row["route"] == "hdc_physics"),
                "routes": routes,
            },
            audit_layer=self.audit_layer,
        )
