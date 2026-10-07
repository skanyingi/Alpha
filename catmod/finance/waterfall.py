"""Deterministic reinsurance waterfall. 100% auditable. No LLM. No vectors."""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal
from typing import Sequence

from catmod.finance.treaty import XLTreaty

CENTS = Decimal("0.01")


def money(value: float | Decimal | str) -> Decimal:
    return Decimal(str(value)).quantize(CENTS, rounding=ROUND_HALF_EVEN)


def ground_up_to_covered(
    ground_up_loss: float | Decimal | str,
    deductible: float | Decimal | str,
    policy_limit: float | Decimal | str,
    coinsurance: float | Decimal | str = 1.0,
) -> Decimal:
    """Primary policy terms: deductible, limit, co-insurance cap.

    covered = max(0, min(GUL, policy_limit) - deductible) * coinsurance
    A policy_limit of 0 is treated as unlimited.
    """
    gul = money(ground_up_loss)
    ded = money(deductible)
    if policy_limit and policy_limit > 0:
        capped = min(gul, money(policy_limit))
    else:
        capped = gul
    after_ded = capped - ded
    if after_ded < 0:
        after_ded = Decimal("0.00")
    share = Decimal(str(coinsurance))
    if share < 0:
        share = Decimal("0")
    if share > 1:
        share = Decimal("1")
    return money(after_ded * share)


def calculate_reinsurance_waterfall(
    gross_losses: Sequence[float | Decimal | str],
    deductibles: Sequence[float | Decimal | str],
    policy_limits: Sequence[float | Decimal | str],
    treaty: XLTreaty,
    coinsurance: Sequence[float | Decimal | str] | None = None,
) -> dict[str, float]:
    """Occurrence XL waterfall on the event aggregate.

    Order:
      1. Ground-up -> primary terms (deductible, limit, coinsurance)
      2. Gross claim aggregation
      3. XL attachment / limit
      4. Co-participation
      5. Reinstatement premium (pro-rata to layer usage, capped by reinstatements)
    """
    n = len(gross_losses)
    if not (len(deductibles) == n and len(policy_limits) == n):
        raise ValueError("gross_losses, deductibles, and policy_limits must be the same length")
    coins = list(coinsurance) if coinsurance is not None else [1.0] * n
    if len(coins) != n:
        raise ValueError("coinsurance must match gross_losses length")

    covered = [
        ground_up_to_covered(g, d, lim, c)
        for g, d, lim, c in zip(gross_losses, deductibles, policy_limits, coins)
    ]
    total_gross_claim = sum(covered, Decimal("0.00"))

    attachment = money(treaty.attachment_point)
    layer_limit = money(treaty.limit)
    share = Decimal(str(treaty.co_participation))

    if total_gross_claim <= attachment:
        layer_loss = Decimal("0.00")
    else:
        layer_loss = min(total_gross_claim - attachment, layer_limit)

    reinsurer_payout = money(layer_loss * share)
    cedant_retained = money(total_gross_claim - reinsurer_payout)
    cedant_layer_share = money(layer_loss * (Decimal("1") - share))
    retention_below_attachment = money(min(total_gross_claim, attachment))

    exhaustion = Decimal("0") if layer_limit == 0 else (layer_loss / layer_limit)
    usable_reinstatements = Decimal(str(treaty.reinstatements))
    reinstatement_ratio = min(exhaustion, usable_reinstatements)
    reinstatement_premium = money(
        reinstatement_ratio * Decimal(str(treaty.reinstatement_cost)) * Decimal(str(treaty.original_premium))
    )

    per_policy_covered = [float(x) for x in covered]
    total_f = float(total_gross_claim)
    if total_f > 0:
        allocated_reinsurer = [float(money(Decimal(str(treaty.co_participation)) * layer_loss * Decimal(str(c)) / total_gross_claim)) for c in covered]
        allocated_cedant = [float(money(Decimal(str(pc)) - Decimal(str(ar)))) for pc, ar in zip(per_policy_covered, allocated_reinsurer)]
    else:
        allocated_reinsurer = [0.0] * n
        allocated_cedant = [0.0] * n

    return {
        "total_gross_claim": float(total_gross_claim),
        "reinsurer_payout": float(reinsurer_payout),
        "cedant_retained_loss": float(cedant_retained),
        "layer_loss": float(layer_loss),
        "cedant_layer_share": float(cedant_layer_share),
        "retention_below_attachment": float(retention_below_attachment),
        "exhaustion_ratio": float(exhaustion),
        "reinstatement_premium_due": float(reinstatement_premium),
        "treaty_label": treaty.layer_label,
        "per_policy_covered": per_policy_covered,
        "allocated_reinsurer_payout": allocated_reinsurer,
        "allocated_cedant_retention": allocated_cedant,
    }
