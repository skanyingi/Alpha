import asyncio
from decimal import Decimal

from catmod.agents.finance_agent import FinanceExecutorAgent, assert_finance_isolated
from catmod.agents.jev_router import JevRouterAgent
from catmod.agents.orchestrator import execute_workflow
from catmod.finance.treaty import XLTreaty
from catmod.finance.waterfall import calculate_reinsurance_waterfall
from catmod.pipeline import run_pipeline
from catmod.schemas import BordereauWebhook

NAIROBI_CSV = """asset_id,policy_id,latitude,longitude,elevation,occupancy,tiv,ground_up_loss,deductible,policy_limit,coinsurance,loss_date
N-001,KN-100,-1.2921,36.8219,1660,informal iron sheet,2500000,0,50000,2500000,1.0,2026-04-12
N-002,KN-101,-1.2864,36.8290,1685,permanent masonry,8000000,0,100000,8000000,1.0,2026-04-12
N-003,KN-102,-1.2755,36.8148,1705,concrete rcc,15000000,0,250000,15000000,1.0,2026-04-12
N-004,KN-103,-1.3012,36.7890,1680,mabati,900000,0,20000,900000,1.0,2026-04-12
"""


def _book() -> BordereauWebhook:
    return BordereauWebhook(
        client_email="desk@nairobi.example",
        client_name="Nairobi Mutual",
        filename="nairobi-book.csv",
        data=NAIROBI_CSV,
        loss_basis="modeled",
        hazard_region="nairobi",
    )


def test_finance_executor_matches_decimal_cents():
    assert_finance_isolated()
    treaty = XLTreaty(
        attachment_point=40_000_000.0,
        limit=100_000_000.0,
        co_participation=0.90,
        reinstatement_cost=1.0,
        reinstatements=1,
        original_premium=0.0,
    )
    payload = {
        "gross_losses": [1000.005, 2500],
        "deductibles": [100, 0],
        "policy_limits": [5000, 5000],
        "coinsurance": [1, 1],
        "treaty": treaty,
    }
    result = asyncio.run(FinanceExecutorAgent().execute(payload))
    direct = calculate_reinsurance_waterfall(
        payload["gross_losses"],
        payload["deductibles"],
        payload["policy_limits"],
        treaty,
        payload["coinsurance"],
    )
    assert result.outputs["engine"] == "decimal_cents_half_even"
    assert result.outputs["llm_used"] is False
    assert result.outputs["vector_approximation_used"] is False
    assert result.outputs["total_gross_claim"] == direct["total_gross_claim"]
    assert result.outputs["reinsurer_payout"] == direct["reinsurer_payout"]
    cents = Decimal(str(result.outputs["total_gross_claim"])).quantize(Decimal("0.01"))
    assert float(cents) == result.outputs["total_gross_claim"]


def test_jev_router_sends_clean_nairobi_lines_to_finance():
    routed = asyncio.run(JevRouterAgent().execute({"filename": "nairobi-book.csv", "data": NAIROBI_CSV}))
    assert routed.outputs["within_budget"] is True
    assert routed.outputs["route_finance"] == 4
    assert routed.outputs["route_hdc_physics"] == 0
    assert routed.latency_ms < 500


def test_agent_workflow_matches_pipeline_and_sla():
    payload = _book()
    direct = run_pipeline(payload)
    worked = execute_workflow(payload)
    assert worked["total_gross_claim"] == direct["total_gross_claim"]
    assert worked["reinsurer_payout"] == direct["reinsurer_payout"]
    assert worked["cedant_retained_loss"] == direct["cedant_retained_loss"]
    roles = {row["agent_role"] for row in worked["agents"]}
    assert "FINANCE_EXECUTOR" in roles
    assert "JEV_ROUTER" in roles
    finance = [row for row in worked["agents"] if row["agent_role"] == "FINANCE_EXECUTOR"][0]
    assert finance["outputs"]["llm_used"] is False
    assert worked["agent_sla"]["within_budget"] is True
    assert worked["agent_sla"]["elapsed_ms"] < 1000
