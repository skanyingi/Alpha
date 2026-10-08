"""Deterministic reinsurance waterfall. 100% auditable. No LLM. No vectors."""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any, Sequence

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
) -> dict[str, Any]:
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
    share = treaty.co_participation

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
        reinstatement_ratio * treaty.reinstatement_cost * treaty.original_premium
    )

    if total_gross_claim > 0:
        allocated_reinsurer = [
            money(share * layer_loss * covered_loss / total_gross_claim) for covered_loss in covered
        ]
        allocated_reinsurer = _pin_remainder(allocated_reinsurer, reinsurer_payout)
        allocated_cedant = [
            money(covered_loss - allocated) for covered_loss, allocated in zip(covered, allocated_reinsurer)
        ]
        allocated_cedant = _pin_remainder(allocated_cedant, cedant_retained)
    else:
        allocated_reinsurer = [Decimal("0.00")] * n
        allocated_cedant = [Decimal("0.00")] * n

    return {
        "total_gross_claim": total_gross_claim,
        "reinsurer_payout": reinsurer_payout,
        "cedant_retained_loss": cedant_retained,
        "layer_loss": layer_loss,
        "cedant_layer_share": cedant_layer_share,
        "retention_below_attachment": retention_below_attachment,
        "exhaustion_ratio": exhaustion,
        "reinstatement_premium_due": reinstatement_premium,
        "treaty_label": treaty.layer_label,
        "per_policy_covered": covered,
        "allocated_reinsurer_payout": allocated_reinsurer,
        "allocated_cedant_retention": allocated_cedant,
    }


def _pin_remainder(parts: list[Decimal], target: Decimal) -> list[Decimal]:
    """Put the leftover cent on the largest line so the parts sum to the contractual total."""
    if not parts:
        return parts
    drift = money(target - sum(parts, Decimal("0.00")))
    if drift == 0:
        return parts
    index = max(range(len(parts)), key=lambda item: parts[item])
    adjusted = list(parts)
    adjusted[index] = money(adjusted[index] + drift)
    return adjusted
