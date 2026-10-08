"""On-demand Gemini answers. Never called from the payout path."""

from __future__ import annotations

import time
from typing import Any

from catmod.agents.base import AgentResult, AgentRole, BaseSubAgent
from catmod.nlp.gemini_rag import build_dataset_context, parse_csv_text, query_dataset_rag


class GeminiRAGAgent(BaseSubAgent):
    role = AgentRole.GEMINI_RAG
    audit_layer = 1

    async def execute(self, payload: dict[str, Any]) -> AgentResult:
        started = time.perf_counter()
        query = str(payload.get("query") or "").strip()
        if not query:
            return AgentResult(
                agent_role=self.role,
                status="skipped",
                latency_ms=(time.perf_counter() - started) * 1000.0,
                outputs={"reason": "AI Mode only. Not part of the payout path."},
                audit_layer=self.audit_layer,
            )
        rows = parse_csv_text(str(payload.get("csv_text") or ""))
        context = build_dataset_context(rows, name=str(payload.get("dataset_name") or "uploaded.csv"))
        answer = query_dataset_rag(query, context)
        return AgentResult(
            agent_role=self.role,
            status="ok",
            latency_ms=(time.perf_counter() - started) * 1000.0,
            outputs={
                "answer": answer.get("answer"),
                "matched_asset_ids": answer.get("matched_asset_ids") or [],
                "calculates_payout": False,
            },
            audit_layer=self.audit_layer,
        )
