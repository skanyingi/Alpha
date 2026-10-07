"""Physics / spatial consistency checks via FHRR interpolation — not financial math."""

from __future__ import annotations

from catmod.hdc.memory import PortfolioMemory
from catmod.schemas import RawClaim, TriageResult


def physics_validate(
    claim: RawClaim,
    triage: TriageResult,
    memory: PortfolioMemory,
    neighborhood_floor: float = 0.02,
) -> tuple[float, bool]:
    """Return (interpolation_score, physically_plausible).

    A claim at null-island or far from any encoded mass is implausible.
    A claim whose GUL wildly exceeds the interpolated neighborhood cost is flagged.
    """
    score = memory.interpolation_score(claim.latitude, claim.longitude)
    plausible = True
    if abs(claim.latitude) < 1e-6 and abs(claim.longitude) < 1e-6:
        plausible = False
    if not (-90.0 <= claim.latitude <= 90.0 and -180.0 <= claim.longitude <= 180.0):
        plausible = False
    if claim.elevation < -500 or claim.elevation > 9000:
        plausible = False
    if memory.count >= 3 and score < neighborhood_floor and triage.route == "hdc_physics":
        # Isolated from the encoded event footprint.
        if triage.spatial_severity.score >= 3.0:
            plausible = False
    if claim.tiv > 0 and claim.ground_up_loss > claim.tiv * 1.5:
        plausible = False
    interpolated = memory.interpolate_cost(claim.latitude, claim.longitude)
    if interpolated > 1.0 and claim.ground_up_loss > interpolated * 25.0 and memory.count >= 4:
        plausible = False
    return float(score), bool(plausible)


def score_all(
    claims: list[RawClaim],
    triages: list[TriageResult],
    memory: PortfolioMemory,
) -> list[tuple[float, bool]]:
    return [physics_validate(c, t, memory) for c, t in zip(claims, triages)]
