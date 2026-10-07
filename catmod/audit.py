"""Structured, append-only audit trail spanning all five layers."""

from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any


LAYER_NAMES = {
    1: "google_workspace_ingestion",
    2: "jev_system_one",
    3: "hdc_fhrr_spatial_memory",
    4: "deterministic_reinsurance_finance",
    5: "leaflet_geojson_export",
    6: "flood_exposure_vulnerability",
    7: "spatial_3d_game_engine_export",
    8: "hazard_raster_lookup",
    9: "vulnerability_damage_function",
    10: "exceedance_probability_analytics",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class AuditLog:
    """In-memory + JSONL audit log for a single event job."""

    def __init__(self, event_id: str, audit_dir: str = "audit_logs") -> None:
        self.event_id = event_id
        self.job_id = f"job-{uuid.uuid4().hex[:12]}"
        self.started_at = utc_now()
        self.audit_dir = audit_dir
        self.entries: list[dict[str, Any]] = []
        os.makedirs(audit_dir, exist_ok=True)
        self._path = os.path.join(audit_dir, f"{event_id}.jsonl")
        self.record(
            layer=1,
            name="job_opened",
            status="ok",
            detail={"job_id": self.job_id, "event_id": event_id},
        )

    def record(
        self,
        *,
        layer: int,
        name: str,
        status: str,
        detail: dict[str, Any] | None = None,
        latency_ms: float | None = None,
    ) -> dict[str, Any]:
        entry = {
            "ts": utc_now(),
            "event_id": self.event_id,
            "job_id": self.job_id,
            "layer": layer,
            "layer_name": LAYER_NAMES.get(layer, "unknown"),
            "step": name,
            "status": status,
            "latency_ms": None if latency_ms is None else round(latency_ms, 3),
            "detail": detail or {},
        }
        self.entries.append(entry)
        with open(self._path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, default=str) + "\n")
        return entry

    def span(self, layer: int, name: str):
        return _AuditSpan(self, layer, name)

    def as_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "job_id": self.job_id,
            "started_at": self.started_at,
            "finished_at": utc_now(),
            "log_path": self._path,
            "entries": self.entries,
            "layer_verification": self.verify_layers(),
        }

    def verify_layers(self) -> dict[str, Any]:
        """Confirm each required layer produced a successful step."""
        required = {
            1: {"apps_script_webhook_received", "bordereau_parsed", "job_opened"},
            2: {"jev_triage_complete"},
            3: {"hdc_portfolio_encoded", "hdc_query_complete"},
            4: {"financial_waterfall_complete"},
            5: {"leaflet_geojson_emitted"},
        }
        seen: dict[int, set[str]] = {i: set() for i in range(1, 6)}
        for e in self.entries:
            if e["status"] == "ok":
                layer = int(e["layer"])
                if layer in seen:
                    seen[layer].add(e["step"])
        return {
            str(layer): {
                "layer_name": LAYER_NAMES[layer],
                "required_any_of": sorted(steps),
                "observed": sorted(seen[layer]),
                "verified": bool(seen[layer] & steps),
            }
            for layer, steps in required.items()
        }


class _AuditSpan:
    def __init__(self, log: AuditLog, layer: int, name: str) -> None:
        self.log = log
        self.layer = layer
        self.name = name
        self.t0 = 0.0

    def __enter__(self) -> "_AuditSpan":
        self.t0 = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        latency = (time.perf_counter() - self.t0) * 1000.0
        if exc_type is None:
            return
        self.log.record(
            layer=self.layer,
            name=self.name,
            status="error",
            latency_ms=latency,
            detail={"error": str(exc), "type": exc_type.__name__},
        )
