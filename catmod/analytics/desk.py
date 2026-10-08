"""Desk analytics that stay on the deterministic finance and vulnerability engines."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from catmod.audit import LAYER_NAMES
from catmod.finance.treaty import XLTreaty
from catmod.finance.waterfall import calculate_reinsurance_waterfall, money
from catmod.vulnerability.curves import CURVE_FAMILY, CURVES

HOUSING_CLASSES: tuple[str, ...] = (
    "informal_iron_sheet",
    "semi_permanent",
    "permanent_masonry",
    "concrete_rcc",
)


def housing_breakdown(claims: list[dict[str, Any]]) -> dict[str, Any]:
    """TIV and modeled ground-up loss by the four Nairobi housing classes."""
    buckets = {
        code: {"tiv": Decimal("0"), "ground_up_loss": Decimal("0"), "count": 0}
        for code in HOUSING_CLASSES
    }
    other = {"tiv": Decimal("0"), "ground_up_loss": Decimal("0"), "count": 0}
    for claim in claims:
        code = str(claim.get("occupancy") or "UNK")
        tiv = Decimal(str(claim.get("tiv") or 0))
        gul_raw = claim.get("modeled_ground_up_loss")
        if gul_raw is None:
            gul_raw = claim.get("ground_up_loss") or 0
        gul = Decimal(str(gul_raw))
        target = buckets.get(code, other)
        target["tiv"] += tiv
        target["ground_up_loss"] += gul
        target["count"] += 1
    classes = [
        {
            "occupancy": code,
            "count": buckets[code]["count"],
            "tiv": format(money(buckets[code]["tiv"]), "f"),
            "ground_up_loss": format(money(buckets[code]["ground_up_loss"]), "f"),
        }
        for code in HOUSING_CLASSES
    ]
    return {
        "classes": classes,
        "other": {
            "count": other["count"],
            "tiv": format(money(other["tiv"]), "f"),
            "ground_up_loss": format(money(other["ground_up_loss"]), "f"),
        },
    }


def vulnerability_curve_payload() -> dict[str, Any]:
    """Depth-damage knots for the housing-class inspector. Ratios stay on the proxy curves."""
    curves = []
    for code in HOUSING_CLASSES:
        knots = [
            {"depth_m": format(depth, "f"), "damage_ratio": format(ratio, "f")}
            for depth, ratio in CURVES[code]
        ]
        curves.append(
            {
                "occupancy": code,
                "synthetic": True,
                "family": CURVE_FAMILY,
                "knots": knots,
            }
        )
    return {"curves": curves, "synthetic": True, "family": CURVE_FAMILY, "depth_axis_m": 10}


def treaty_for_what_if(
    job: dict[str, Any],
    *,
    attachment_point: float,
    limit: float,
    co_participation: float,
    reinstatement_cost: float,
) -> XLTreaty:
    stored = job.get("treaty") or {}
    premium = stored.get("original_premium")
    if premium in (None, ""):
        premium = 0
    reinstatements = stored.get("reinstatements")
    if reinstatements in (None, ""):
        reinstatements = 1
    return XLTreaty(
        attachment_point=attachment_point,
        limit=limit,
        co_participation=co_participation,
        reinstatement_cost=reinstatement_cost,
        reinstatements=int(reinstatements),
        original_premium=premium,
    )


def waterfall_for_claims(claims: list[dict[str, Any]], treaty: XLTreaty) -> dict[str, Any]:
    if not claims:
        gross: list[Any] = [0]
        deductibles: list[Any] = [0]
        limits: list[Any] = [0]
        coins: list[Any] = [1]
    else:
        gross = [claim.get("ground_up_loss") or 0 for claim in claims]
        deductibles = [claim.get("deductible") or 0 for claim in claims]
        limits = [claim.get("policy_limit") or 0 for claim in claims]
        coins = [
            1 if claim.get("coinsurance") is None else claim.get("coinsurance")
            for claim in claims
        ]
    result = calculate_reinsurance_waterfall(gross, deductibles, limits, treaty, coins)
    return {
        "total_gross_claim": format(result["total_gross_claim"], "f"),
        "reinsurer_payout": format(result["reinsurer_payout"], "f"),
        "cedant_retained_loss": format(result["cedant_retained_loss"], "f"),
        "reinstatement_premium_due": format(result["reinstatement_premium_due"], "f"),
        "treaty_label": result["treaty_label"],
    }


def scenario_net_curve(ep_curve: dict[str, Any], treaty: XLTreaty) -> list[dict[str, Any]]:
    """Apply the occurrence XL to each return-period ground-up total."""
    points = []
    for point in ep_curve.get("curve") or []:
        gul = money(point.get("loss") or 0)
        result = calculate_reinsurance_waterfall([gul], [0], [0], treaty, [1])
        points.append(
            {
                "return_period": int(point["return_period"]),
                "gul": format(gul, "f"),
                "net": format(result["cedant_retained_loss"], "f"),
                "reinsurer": format(result["reinsurer_payout"], "f"),
            }
        )
    return points


def audit_trace(job: dict[str, Any]) -> list[dict[str, Any]]:
    entries = ((job.get("audit") or {}).get("entries") or [])
    latest: dict[int, dict[str, Any]] = {}
    for entry in entries:
        try:
            layer = int(entry.get("layer") or 0)
        except (TypeError, ValueError):
            continue
        latest[layer] = entry
    trace = []
    for layer in range(1, 11):
        entry = latest.get(layer) or {}
        trace.append(
            {
                "layer": layer,
                "name": LAYER_NAMES.get(layer, ""),
                "step": entry.get("step") or "",
                "status": entry.get("status") or "not_run",
            }
        )
    return trace
