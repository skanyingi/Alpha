"""Append one audit step for each sub-agent handoff."""

from __future__ import annotations

from catmod.audit import AuditLog

_STEPS = (
    (1, "agent_ingestion", "INGESTION"),
    (2, "agent_jev_router", "JEV_ROUTER"),
    (8, "agent_hazard_vulnerability", "HAZARD_VULNERABILITY"),
    (3, "agent_hdc_memory", "HDC_MEMORY"),
    (4, "agent_finance_executor", "FINANCE_EXECUTOR"),
    (5, "agent_analytics_geojson", "ANALYTICS_GEOJSON"),
)


def record_agent_trail(
    audit: AuditLog,
    *,
    elapsed_ms: float,
    jev_ms: float,
    finance_routes: int,
    hdc_routes: int,
    claim_count: int,
) -> None:
    detail = {
        "claim_count": claim_count,
        "route_finance": finance_routes,
        "route_hdc_physics": hdc_routes,
        "pipeline_ms": round(elapsed_ms, 3),
        "finance_engine": "decimal_cents_half_even",
        "llm_used": False,
    }
    for layer, name, role in _STEPS:
        latency = jev_ms if role == "JEV_ROUTER" else None
        audit.record(
            layer=layer,
            name=name,
            status="ok",
            latency_ms=latency,
            detail={**detail, "agent_role": role},
        )
