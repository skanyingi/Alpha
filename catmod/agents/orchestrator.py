"""Run the desk job and attach the agent trail. Payouts stay inside run_pipeline."""

from __future__ import annotations

import time
from typing import Any

from catmod.agents.base import AgentResult, AgentRole
from catmod.agents.status import remember
from catmod.config import Settings
from catmod.pipeline import run_pipeline
from catmod.schemas import BordereauWebhook

_ROLE_LAYER = {
    "agent_ingestion": (AgentRole.INGESTION, 1),
    "agent_jev_router": (AgentRole.JEV_ROUTER, 2),
    "agent_hazard_vulnerability": (AgentRole.HAZARD_VULNERABILITY, 8),
    "agent_hdc_memory": (AgentRole.HDC_MEMORY, 3),
    "agent_finance_executor": (AgentRole.FINANCE_EXECUTOR, 4),
    "agent_analytics_geojson": (AgentRole.ANALYTICS_GEOJSON, 5),
}


def execute_workflow(payload: BordereauWebhook, settings: Settings | None = None) -> dict[str, Any]:
    started = time.perf_counter()
    result = run_pipeline(payload, settings)
    elapsed = (time.perf_counter() - started) * 1000.0
    agents: list[AgentResult] = []
    for entry in result["audit"]["entries"]:
        mapped = _ROLE_LAYER.get(entry["step"])
        if mapped is None:
            continue
        role, layer = mapped
        agents.append(
            AgentResult(
                agent_role=role,
                status=entry["status"],
                latency_ms=float(entry["latency_ms"] or 0.0),
                outputs=dict(entry.get("detail") or {}),
                audit_layer=layer,
            )
        )
    remember(agents, total_ms=elapsed)
    packed = dict(result)
    packed["agents"] = [agent.model_dump(mode="json") for agent in agents]
    packed["agent_sla"] = {"budget_ms": 1000, "elapsed_ms": round(elapsed, 3), "within_budget": elapsed < 1000}
    return packed
