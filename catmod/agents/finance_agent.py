"""Run the contractual waterfall. Decimal cents only. No model, no vectors."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from catmod.agents.base import AgentResult, AgentRole, BaseSubAgent
from catmod.finance.treaty import XLTreaty
from catmod.finance.waterfall import calculate_reinsurance_waterfall

_FORBIDDEN = ("torch", "numpy", "hdc")


def assert_finance_isolated() -> None:
    source = Path(calculate_reinsurance_waterfall.__code__.co_filename).read_text(encoding="utf-8")
    for token in _FORBIDDEN:
        if token in source:
            raise RuntimeError(f"finance waterfall must not reference {token}")


class FinanceExecutorAgent(BaseSubAgent):
    role = AgentRole.FINANCE_EXECUTOR
    audit_layer = 4

    async def execute(self, payload: dict[str, Any]) -> AgentResult:
        started = time.perf_counter()
        assert_finance_isolated()
        treaty = payload.get("treaty")
        if not isinstance(treaty, XLTreaty):
            treaty = XLTreaty(
                attachment_point=40_000_000.0,
                limit=100_000_000.0,
                co_participation=0.90,
                reinstatement_cost=1.0,
                reinstatements=1,
                original_premium=0.0,
            )
        waterfall = calculate_reinsurance_waterfall(
            payload.get("gross_losses") or [],
            payload.get("deductibles") or [],
            payload.get("policy_limits") or [],
            treaty,
            payload.get("coinsurance"),
        )
        if not isinstance(waterfall["total_gross_claim"], float):
            raise RuntimeError("waterfall must publish float cents from Decimal math")
        return AgentResult(
            agent_role=self.role,
            status="ok",
            latency_ms=(time.perf_counter() - started) * 1000.0,
            outputs={
                "total_gross_claim": waterfall["total_gross_claim"],
                "reinsurer_payout": waterfall["reinsurer_payout"],
                "cedant_retained_loss": waterfall["cedant_retained_loss"],
                "engine": "decimal_cents_half_even",
                "llm_used": False,
                "vector_approximation_used": False,
            },
            audit_layer=self.audit_layer,
        )
