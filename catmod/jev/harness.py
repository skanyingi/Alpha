"""System-One harness: parallel Choice / Score / Noul triage under a 500 ms budget."""

from __future__ import annotations

import math
from typing import Any

from catmod.config import Settings, get_settings
from catmod.jev.client import HostedJevClient
from catmod.jev.occupancy import OCCUPANCY_CRITERIA, classify_occupancy
from catmod.jev.primitives import Question, noul_answer, score_answer
from catmod.schemas import RawClaim, TriageResult

TRIAGE_QUESTIONS: dict[str, Question] = {
    "occupancy": {
        "type": "choice",
        "instructions": (
            "Map the occupancy/construction description to the standardized "
            "catastrophe vulnerability occupancy code."
        ),
        "criteria": OCCUPANCY_CRITERIA,  # type: ignore[typeddict-item]
    },
    "fraud_or_discrepancy": {
        "type": "noul",
        "instructions": (
            "This bordereau line contains a fraud indicator or a physical/spatial "
            "discrepancy that should not proceed straight to financial settlement."
        ),
        "criteria": {
            "true": (
                "Null-island coordinates, occupancy-TIV mismatch, claim exceeds TIV, "
                "impossible elevation, or corrupted location."
            ),
            "false": "Location, occupancy, TIV and claim value are internally consistent.",
        },
    },
    "clean_for_finance": {
        "type": "noul",
        "instructions": (
            "This line is clean and may proceed directly to deterministic financial "
            "math without HDC physics validation."
        ),
        "criteria": {
            "true": "Occupancy is standardized with high confidence and no spatial discrepancy.",
            "false": "Needs HDC spatial memory / physics validation before payout math.",
        },
    },
    "spatial_severity": {
        "type": "score",
        "instructions": "Severity of spatial or physical discrepancy on this line.",
        "criteria": [
            "No spatial issue; coordinates and occupancy are consistent.",
            "Minor data quality issue with no physical contradiction.",
            "Moderate discrepancy: occupancy or value is unusual for the coordinates.",
            "Severe discrepancy: location, elevation, or claim conflicts with nearby assets.",
            "Physically impossible: null island, ocean warehouse, or claim far above TIV.",
        ],
    },
}


def _null_island(lat: float, lon: float) -> bool:
    return abs(lat) < 1e-6 and abs(lon) < 1e-6


def _out_of_range(lat: float, lon: float) -> bool:
    return not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0)


def _local_spatial_logits(claim: RawClaim) -> list[float]:
    """Heuristic logits for the 5-level spatial severity Score (low -> impossible)."""
    logits = [2.5, 0.0, -1.0, -2.0, -3.0]
    lat, lon = claim.latitude, claim.longitude
    if _null_island(lat, lon):
        logits = [-4, -3, -1, 2.5, 6.0]
    elif _out_of_range(lat, lon):
        logits = [-4, -3, -1, 3.0, 5.5]
    if claim.elevation < -500 or claim.elevation > 9000:
        logits[3] += 3.0
        logits[4] += 1.5
        logits[0] -= 2.0
    if claim.tiv > 0 and claim.ground_up_loss > claim.tiv * 1.15:
        logits[3] += 2.5
        logits[4] += 1.0
        logits[0] -= 2.0
    if claim.tiv > 0 and claim.occupancy_raw:
        occ = claim.occupancy_raw.lower()
        residentialish = any(k in occ for k in ("sfd", "house", "home", "res", "dwelling"))
        warehouseish = any(k in occ for k in ("whse", "warehouse", "storage", "shed"))
        if residentialish and claim.tiv > 25_000_000:
            logits[2] += 2.0
            logits[0] -= 1.0
        if warehouseish and 0 < claim.tiv < 25_000:
            logits[2] += 2.0
    if not claim.occupancy_raw.strip():
        logits[1] += 1.5
        logits[0] -= 0.5
    return logits


def _local_fraud_noul(claim: RawClaim, spatial_score: float) -> float:
    p = 1.0 / (1.0 + math.exp(-(spatial_score - 2.2) * 1.6))
    if claim.tiv > 0 and claim.ground_up_loss > claim.tiv * 1.5:
        p = max(p, 0.92)
    if _null_island(claim.latitude, claim.longitude) and claim.ground_up_loss > 0:
        p = max(p, 0.97)
    return float(min(0.999, max(0.001, p)))


def local_triage(claim: RawClaim, threshold: float) -> TriageResult:
    occupancy = classify_occupancy(claim.occupancy_raw)
    spatial = score_answer(list(TRIAGE_QUESTIONS["spatial_severity"]["criteria"]), _local_spatial_logits(claim))
    fraud = noul_answer(_local_fraud_noul(claim, spatial.score))
    clean_p = occupancy.confidence * (1.0 - fraud.noul)
    if spatial.score >= 1.5:
        clean_p *= 0.4
    clean_p = max(0.0, min(1.0, clean_p))
    clean = noul_answer(clean_p)
    high_conf_clean = occupancy.confidence > threshold and clean.noul > threshold and fraud.noul < (1.0 - threshold)
    spatial_flagged = spatial.score >= 1.5 or fraud.noul >= 0.5
    if high_conf_clean and not spatial_flagged:
        route: str = "finance"
    else:
        route = "hdc_physics"
    return TriageResult(
        asset_id=claim.asset_id,
        occupancy=occupancy,
        fraud_or_discrepancy=fraud,
        clean_for_finance=clean,
        spatial_severity=spatial,
        route=route,  # type: ignore[arg-type]
        standardized_occupancy=occupancy.choice,
    )


class JevHarness:
    """Evaluate occupancy, fraud Noul, and spatial Score in one non-autoregressive pass."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.hosted = HostedJevClient(self.settings)

    def triage_batch(self, claims: list[RawClaim]) -> list[TriageResult]:
        return [self._triage_one(c) for c in claims]

    def _triage_one(self, claim: RawClaim) -> TriageResult:
        local = local_triage(claim, self.settings.clean_confidence_threshold)
        if (
            self.hosted.enabled
            and local.occupancy.confidence < self.settings.clean_confidence_threshold
            and (claim.extras.get("narrative") or local.standardized_occupancy == "UNK")
        ):
            try:
                return self._hosted_merge(claim, local)
            except Exception:
                return local
        return local

    def _hosted_merge(self, claim: RawClaim, local: TriageResult) -> TriageResult:
        state: dict[str, Any] = {
            "asset_id": claim.asset_id,
            "occupancy_raw": claim.occupancy_raw,
            "latitude": claim.latitude,
            "longitude": claim.longitude,
            "elevation": claim.elevation,
            "tiv": claim.tiv,
            "ground_up_loss": claim.ground_up_loss,
            "narrative": (claim.extras or {}).get("narrative", ""),
        }
        answers = self.hosted.decide(state, TRIAGE_QUESTIONS)
        occupancy = answers.get("occupancy", local.occupancy)
        fraud = answers.get("fraud_or_discrepancy", local.fraud_or_discrepancy)
        clean = answers.get("clean_for_finance", local.clean_for_finance)
        spatial = answers.get("spatial_severity", local.spatial_severity)
        from catmod.schemas import ChoiceAnswer, NoulAnswer, ScoreAnswer

        if not isinstance(occupancy, ChoiceAnswer):
            occupancy = local.occupancy
        if not isinstance(fraud, NoulAnswer):
            fraud = local.fraud_or_discrepancy
        if not isinstance(clean, NoulAnswer):
            clean = local.clean_for_finance
        if not isinstance(spatial, ScoreAnswer):
            spatial = local.spatial_severity
        threshold = self.settings.clean_confidence_threshold
        high_conf_clean = occupancy.confidence > threshold and clean.noul > threshold
        route = "finance" if high_conf_clean and fraud.noul < 0.5 else "hdc_physics"
        return TriageResult(
            asset_id=claim.asset_id,
            occupancy=occupancy,
            fraud_or_discrepancy=fraud,
            clean_for_finance=clean,
            spatial_severity=spatial,
            route=route,  # type: ignore[arg-type]
            standardized_occupancy=occupancy.choice,
        )
