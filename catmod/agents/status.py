"""Last observed agent latencies for the status endpoint and the Alpha agents page."""

from __future__ import annotations

from typing import Any

from catmod.agents.base import AgentResult

CATALOG: tuple[dict[str, Any], ...] = (
    {
        "role": "INGESTION",
        "title": "Ingestion",
        "layer": 1,
        "summary": "Parses the uploaded CSV and assigns the client and event ids.",
    },
    {
        "role": "JEV_ROUTER",
        "title": "Jev router",
        "layer": 2,
        "summary": "Master orchestrator. Choice, Score, and Noul under 500 ms decide finance or HDC.",
    },
    {
        "role": "HAZARD_VULNERABILITY",
        "title": "Hazard and vulnerability",
        "layer": 8,
        "summary": "Nairobi and Nzoia depth lookup, then the mean damage ratio.",
    },
    {
        "role": "HDC_MEMORY",
        "title": "HDC memory",
        "layer": 3,
        "summary": "Fourier hypervectors for lines Jev flagged. Does not change the payout.",
    },
    {
        "role": "FINANCE_EXECUTOR",
        "title": "Finance executor",
        "layer": 4,
        "summary": "Decimal cents waterfall. $100M xs $40M, 90% share. No model math.",
    },
    {
        "role": "ANALYTICS_GEOJSON",
        "title": "Analytics and map",
        "layer": 10,
        "summary": "Exceedance curve, EAL, and the Leaflet export.",
    },
    {
        "role": "GEMINI_RAG",
        "title": "Gemini RAG",
        "layer": 1,
        "summary": "On demand when AI Mode is on. Answers from the upload. Does not price the treaty.",
    },
)

_last: list[dict[str, Any]] = []
_total_ms: float | None = None


def remember(agents: list[AgentResult], *, total_ms: float) -> None:
    global _last, _total_ms
    _last = [agent.model_dump(mode="json") for agent in agents]
    _total_ms = total_ms


def agent_status() -> dict[str, Any]:
    by_role = {row["agent_role"]: row for row in _last}
    agents = []
    for spec in CATALOG:
        seen = by_role.get(spec["role"])
        agents.append(
            {
                **spec,
                "status": "idle" if seen is None else seen["status"],
                "latency_ms": None if seen is None else seen["latency_ms"],
            }
        )
    return {
        "sla_ms": 1000,
        "jev_budget_ms": 500,
        "finance_isolated": True,
        "last_total_ms": _total_ms,
        "agents": agents,
    }
