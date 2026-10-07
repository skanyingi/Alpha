"""Occurrence exceedance-probability curve from return-period scenario losses.

Probabilities are ``1 / RP`` and are therefore strictly decreasing in the
return period. Losses must be non-decreasing in the return period. Money is
``Decimal`` cents. This module does not touch hypervectors or treaty floats
until a cents value is already fixed.
"""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal
from typing import Mapping, Sequence

from catmod.hazard.service import STANDARD_RETURN_PERIODS, HazardService, default_hazard_service
from catmod.vulnerability.engine import assess

CENTS = Decimal("0.01")
ZERO = Decimal("0")
ONE = Decimal("1")


def build_ep_curve(losses_by_return_period: Mapping[int, Decimal | str | float]) -> dict[str, object]:
    """Build the OEP curve, EAL, PML, and TVaR for a catalog of scenario totals."""
    if not losses_by_return_period:
        raise ValueError("ep curve requires at least one return-period loss")
    ordered = sorted((int(rp), _cents(loss)) for rp, loss in losses_by_return_period.items())
    for (rp0, loss0), (rp1, loss1) in zip(ordered, ordered[1:]):
        if rp1 <= rp0:
            raise ValueError("return periods must be unique and positive")
        if loss1 < loss0:
            raise ValueError(
                f"scenario loss at RP {rp1} ({loss1}) is below RP {rp0} ({loss0}); "
                "OEP losses must be non-decreasing in return period"
            )
    curve: list[dict[str, object]] = []
    for rp, loss in ordered:
        if rp <= 1:
            raise ValueError("return_period must be > 1")
        probability = ONE / Decimal(rp)
        curve.append(
            {
                "return_period": rp,
                "exceedance_probability": format(probability, "f"),
                "exceedance_probability_float": float(probability),
                "loss": format(loss, "f"),
                "loss_float": float(loss),
                "synthetic": True,
            }
        )
    probabilities = [ONE / Decimal(int(point["return_period"])) for point in curve]
    for earlier, later in zip(probabilities, probabilities[1:]):
        if earlier <= later:
            raise ValueError("exceedance probabilities must be strictly decreasing in return period")
    eal = expected_annual_loss(ordered)
    pml = {str(rp): format(loss, "f") for rp, loss in ordered}
    tvar = {
        "0.95": format(tail_value_at_risk(ordered, Decimal("0.95")), "f"),
        "0.99": format(tail_value_at_risk(ordered, Decimal("0.99")), "f"),
        "0.995": format(tail_value_at_risk(ordered, Decimal("0.995")), "f"),
        "0.998": format(tail_value_at_risk(ordered, Decimal("0.998")), "f"),
    }
    return {
        "synthetic": True,
        "method": "oep_trapezoid",
        "curve_family": "return_period_catalog",
        "return_periods": [rp for rp, _loss in ordered],
        "curve": curve,
        "eal": format(eal, "f"),
        "eal_float": float(eal),
        "pml": pml,
        "tvar": tvar,
        "monotonic_exceedance": True,
    }


def expected_annual_loss(ordered: Sequence[tuple[int, Decimal]]) -> Decimal:
    """Trapezoid of loss versus exceedance probability.

    Anchors: loss 0 at probability 1, and a flat tail from the rarest scenario
    down to probability 0.
    """
    knots = _loss_knots(ordered)
    total = ZERO
    for (p0, loss0), (p1, loss1) in zip(knots, knots[1:]):
        total += (p0 - p1) * (loss0 + loss1) / Decimal(2)
    return _cents(total)


def probable_maximum_loss(ordered: Sequence[tuple[int, Decimal]], return_period: int) -> Decimal:
    """Scenario loss at ``return_period``, linearly interpolated in exceedance space."""
    if return_period <= 1:
        raise ValueError("return_period must be > 1")
    target = ONE / Decimal(return_period)
    knots = [(ONE / Decimal(rp), loss) for rp, loss in sorted(ordered)]
    if target >= knots[0][0]:
        return knots[0][1]
    if target <= knots[-1][0]:
        return knots[-1][1]
    for (p0, loss0), (p1, loss1) in zip(knots, knots[1:]):
        if p1 <= target <= p0:
            if p0 == p1:
                return loss1
            weight = (p0 - target) / (p0 - p1)
            return _cents(loss0 + (loss1 - loss0) * weight)
    return knots[-1][1]


def tail_value_at_risk(ordered: Sequence[tuple[int, Decimal]], alpha: Decimal) -> Decimal:
    """``TVaR_α = 1/(1-α) ∫_α^1 q(u) du`` on the piecewise-linear OEP."""
    if not (ZERO < alpha < ONE):
        raise ValueError("alpha must be in (0, 1)")
    p_star = ONE - alpha
    knots = _loss_knots(ordered)
    tail: list[tuple[Decimal, Decimal]] = [(p_star, _loss_at(knots, p_star))]
    for probability, loss in knots:
        if probability < p_star:
            tail.append((probability, loss))
    tail.sort(key=lambda item: item[0], reverse=True)
    integral = ZERO
    for (p0, loss0), (p1, loss1) in zip(tail, tail[1:]):
        integral += (p0 - p1) * (loss0 + loss1) / Decimal(2)
    return _cents(integral / p_star)


def scenario_losses(
    exposures: Sequence[Mapping[str, object]],
    *,
    service: HazardService | None = None,
    region: str | None = None,
    return_periods: Sequence[int] = STANDARD_RETURN_PERIODS,
) -> dict[int, Decimal]:
    """Sum ``TIV × DR(depth(RP))`` across the portfolio for each return period."""
    hazard = service or default_hazard_service()
    totals: dict[int, Decimal] = {}
    previous = ZERO
    for rp in return_periods:
        total = ZERO
        for exposure in exposures:
            hit = hazard.lookup(
                float(exposure["latitude"]),
                float(exposure["longitude"]),
                return_period=int(rp),
                region=region,
            )
            depth = hit.depth_m if hit.depth_m is not None else ZERO
            total += assess(str(exposure.get("occupancy") or "UNK"), depth, exposure.get("tiv") or 0).ground_up_loss
        if total < previous:
            total = previous
        previous = total
        totals[int(rp)] = total
    return totals


def portfolio_ep_curve(
    exposures: Sequence[Mapping[str, object]],
    *,
    service: HazardService | None = None,
    region: str | None = None,
    return_periods: Sequence[int] = STANDARD_RETURN_PERIODS,
) -> dict[str, object]:
    losses = scenario_losses(exposures, service=service, region=region, return_periods=return_periods)
    curve = build_ep_curve(losses)
    curve["loss_basis"] = "modeled_ground_up"
    curve["scenario_count"] = len(return_periods)
    curve["exposure_count"] = len(exposures)
    return curve


def _loss_knots(ordered: Sequence[tuple[int, Decimal]]) -> list[tuple[Decimal, Decimal]]:
    """Exceedance knots from probability 1 (loss 0) down to probability 0 (max loss)."""
    scenarios = sorted(ordered)
    knots: list[tuple[Decimal, Decimal]] = [(ONE, ZERO)]
    for rp, loss in scenarios:
        knots.append((ONE / Decimal(rp), loss))
    knots.append((ZERO, scenarios[-1][1]))
    knots.sort(key=lambda item: item[0], reverse=True)
    return knots


def _loss_at(knots: Sequence[tuple[Decimal, Decimal]], probability: Decimal) -> Decimal:
    if probability >= knots[0][0]:
        return knots[0][1]
    if probability <= knots[-1][0]:
        return knots[-1][1]
    for (p0, loss0), (p1, loss1) in zip(knots, knots[1:]):
        if p1 <= probability <= p0:
            if p0 == p1:
                return loss1
            weight = (p0 - probability) / (p0 - p1)
            return loss0 + (loss1 - loss0) * weight
    return knots[-1][1]


def _cents(value: Decimal | str | float) -> Decimal:
    return Decimal(str(value)).quantize(CENTS, rounding=ROUND_HALF_EVEN)
