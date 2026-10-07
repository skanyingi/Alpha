"""Occurrence exceedance-probability curve from return-period scenario losses.

Probabilities are ``1 / RP`` and are therefore strictly decreasing in the
return period. Losses must be non-decreasing in the return period. Money is
``Decimal`` cents. This module does not touch hypervectors or treaty floats
until a cents value is already fixed.
"""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal
import math
import random
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
    tvar = _tail_block(ordered)
    var = _var_block(ordered)
    aep = _poisson_aep(ordered)
    return {
        "synthetic": True,
        "method": "oep_trapezoid",
        "curve_family": "return_period_catalog",
        "return_periods": [rp for rp, _loss in ordered],
        "curve": curve,
        "oep": curve,
        "aep": aep,
        "eal": format(eal, "f"),
        "eal_float": float(eal),
        "pml": pml,
        "var": var,
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


def value_at_risk(ordered: Sequence[tuple[int, Decimal]], alpha: Decimal) -> Decimal:
    """Loss at exceedance probability ``1 - alpha`` on the piecewise OEP."""
    if not (ZERO < alpha < ONE):
        raise ValueError("alpha must be in (0, 1)")
    return _cents(_loss_at(_loss_knots(ordered), ONE - alpha))


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


_ALPHAS: tuple[Decimal, ...] = (
    Decimal("0.95"),
    Decimal("0.99"),
    Decimal("0.995"),
    Decimal("0.998"),
)


def catalog_ep_curve(
    event_losses: Sequence[Decimal | str | float],
    event_rates: Sequence[Decimal | str | float],
    *,
    years: int = 4_000,
    seed: int = 42,
) -> dict[str, object]:
    """OEP and AEP for a Poisson event catalog.

    Occurrence loss in a year is the largest event that occurs. Aggregate loss
    is the sum of event losses times their Poisson counts. EAL is the exact
    ``Σ rate × loss``; the Monte Carlo sample supplies VaR and TVaR.
    """
    if years < 100:
        raise ValueError("years must be at least 100")
    if len(event_losses) != len(event_rates) or not event_losses:
        raise ValueError("event_losses and event_rates must be the same non-empty length")
    losses = [_cents(loss) for loss in event_losses]
    rates = [Decimal(str(rate)) for rate in event_rates]
    if any(rate < 0 for rate in rates):
        raise ValueError("event rates must be non-negative")
    eal = _cents(sum((rate * loss for rate, loss in zip(rates, losses)), ZERO))
    loss_f = [float(loss) for loss in losses]
    rate_f = [float(rate) for rate in rates]
    rng = random.Random(seed)
    annual_sum: list[float] = []
    annual_max: list[float] = []
    for _ in range(years):
        total = 0.0
        largest = 0.0
        for loss, rate in zip(loss_f, rate_f):
            count = _poisson(rng, rate)
            if count:
                total += count * loss
                if loss > largest:
                    largest = loss
        annual_sum.append(total)
        annual_max.append(largest)
    oep = _empirical_tail(annual_max, "oep")
    aep = _empirical_tail(annual_sum, "aep")
    return {
        "synthetic": True,
        "stochastic": True,
        "method": "poisson_catalog",
        "years": years,
        "event_count": len(losses),
        "eal": format(eal, "f"),
        "oep": oep,
        "aep": aep,
        "var": aep["var"],
        "tvar": aep["tvar"],
        "tvar_995": aep["tvar"]["0.995"],
    }


def _tail_block(ordered: Sequence[tuple[int, Decimal]]) -> dict[str, str]:
    return {format(alpha, "f"): format(tail_value_at_risk(ordered, alpha), "f") for alpha in _ALPHAS}


def _var_block(ordered: Sequence[tuple[int, Decimal]]) -> dict[str, str]:
    return {format(alpha, "f"): format(value_at_risk(ordered, alpha), "f") for alpha in _ALPHAS}


def _poisson_aep(ordered: Sequence[tuple[int, Decimal]]) -> list[dict[str, object]]:
    """Aggregate exceedance ``1 - exp(-1/RP)`` on the same scenario losses."""
    points: list[dict[str, object]] = []
    for rp, loss in ordered:
        frequency = 1.0 / float(rp)
        probability = Decimal(str(1.0 - math.exp(-frequency)))
        points.append(
            {
                "return_period": rp,
                "exceedance_probability": format(probability, "f"),
                "loss": format(loss, "f"),
                "synthetic": True,
            }
        )
    return points


def _poisson(rng: random.Random, lam: float) -> int:
    if lam <= 0:
        return 0
    # Knuth's method. Catalog rates are small, so the inner loop stays short.
    limit = math.exp(-lam)
    product = 1.0
    count = 0
    while product > limit:
        count += 1
        product *= rng.random()
    return count - 1


def _quantile(ordered: list[float], alpha: float) -> float:
    if len(ordered) == 1:
        return ordered[0]
    position = alpha * (len(ordered) - 1)
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    weight = position - low
    return ordered[low] * (1.0 - weight) + ordered[high] * weight


def _empirical_tail(samples: list[float], perspective: str) -> dict[str, object]:
    ordered = sorted(samples)
    eal = _cents(Decimal(str(sum(ordered) / len(ordered))))
    var: dict[str, str] = {}
    tvar: dict[str, str] = {}
    for alpha in _ALPHAS:
        quantile = _quantile(ordered, float(alpha))
        var_loss = _cents(Decimal(str(quantile)))
        tail = [value for value in ordered if value >= float(var_loss)]
        tail_mean = sum(tail) / len(tail) if tail else quantile
        key = format(alpha, "f")
        var[key] = format(var_loss, "f")
        tvar[key] = format(_cents(Decimal(str(tail_mean))), "f")
    return {
        "perspective": perspective,
        "eal": format(eal, "f"),
        "var": var,
        "tvar": tvar,
    }


def _cents(value: Decimal | str | float) -> Decimal:
    return Decimal(str(value)).quantize(CENTS, rounding=ROUND_HALF_EVEN)
