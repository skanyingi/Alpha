"""Parse a bordereau and assign the client and event ids."""

from __future__ import annotations

import time
from typing import Any

from catmod.agents.base import AgentResult, AgentRole, BaseSubAgent
from catmod.ingestion.indexing import assign_client_index_id, assign_event_id
from catmod.ingestion.parser import decode_payload_bytes, parse_attachment


class IngestionAgent(BaseSubAgent):
    role = AgentRole.INGESTION
    audit_layer = 1

    async def execute(self, payload: dict[str, Any]) -> AgentResult:
        started = time.perf_counter()
        filename = str(payload.get("filename") or "bordereau.csv")
        text = payload.get("data")
        blob = decode_payload_bytes(payload.get("data_base64"))
        claims = parse_attachment(
            filename=filename,
            text=None if text is None else str(text),
            blob=blob,
            content_type=payload.get("content_type"),
        )
        client_index_id = payload.get("client_index_id") or assign_client_index_id(
            str(payload.get("client_email") or ""),
            filename,
            str(text or payload.get("data_base64") or ""),
        )
        event_id = payload.get("event_id") or assign_event_id(str(client_index_id), filename)
        return AgentResult(
            agent_role=self.role,
            status="ok",
            latency_ms=(time.perf_counter() - started) * 1000.0,
            outputs={
                "claim_count": len(claims),
                "client_index_id": client_index_id,
                "event_id": event_id,
                "asset_ids": [claim.asset_id for claim in claims],
            },
            audit_layer=self.audit_layer,
        )
