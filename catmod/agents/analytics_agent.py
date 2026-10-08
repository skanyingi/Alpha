"""OEP curve and Leaflet export. Reads the waterfall; does not recompute it."""

from __future__ import annotations

import time
from typing import Any

from catmod.agents.base import AgentResult, AgentRole, BaseSubAgent
from catmod.leaflet.geojson import build_export


class AnalyticsGeoJSONAgent(BaseSubAgent):
    role = AgentRole.ANALYTICS_GEOJSON
    audit_layer = 10

    async def execute(self, payload: dict[str, Any]) -> AgentResult:
        started = time.perf_counter()
        claims = list(payload.get("claims") or [])
        geojson = build_export(
            event_id=str(payload.get("event_id") or "analytics"),
            claims=claims,
            hazard_polygon=payload.get("hazard_polygon"),
        )
        return AgentResult(
            agent_role=self.role,
            status="ok",
            latency_ms=(time.perf_counter() - started) * 1000.0,
            outputs={
                "eal": payload.get("eal"),
                "feature_count": len(geojson.get("features") or []),
                "geojson_type": geojson.get("type"),
            },
            audit_layer=self.audit_layer,
        )
