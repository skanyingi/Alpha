"""Shared Pydantic contracts. Finance never imports this module's optional layers."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from catmod.config import STOCHASTIC_BATCH_SIZE, STOCHASTIC_FULL_CATALOG_SIZE


class XLTreatyIn(BaseModel):
    attachment_point: float = Field(..., ge=0, description="Retention / attachment, e.g. 40e6")
    limit: float = Field(..., gt=0, description="Layer limit, e.g. 100e6 for $100M xs $40M")
    co_participation: float = Field(0.90, ge=0, le=1, description="Reinsurer share of the layer")
    reinstatement_cost: float = Field(1.0, ge=0, description="Reinstatement rate, 1.0 = 100% AP")
    reinstatements: int = Field(1, ge=0, description="Number of reinstatements purchased")
    original_premium: float = Field(0.0, ge=0, description="Layer original premium for RP calc")


class BordereauWebhook(BaseModel):
    client_email: str
    client_name: str | None = None
    filename: str
    data: str | None = None
    data_base64: str | None = None
    content_type: str | None = None
    client_index_id: str | None = None
    event_id: str | None = None
    underwriter_email: str | None = None
    source_urls: list[str] = Field(
        default_factory=list,
        description="Drive or document URLs found in the source email body",
    )
    treaty: XLTreatyIn | None = None
    hazard_polygon: list[list[float]] | None = None
    loss_basis: Literal["auto", "reported", "modeled"] = "auto"
    execution_mode: Literal["deterministic", "stochastic"] = "deterministic"
    stochastic_event_count: int = Field(
        STOCHASTIC_BATCH_SIZE,
        ge=1,
        le=STOCHASTIC_FULL_CATALOG_SIZE,
        description="Number of stochastic events to evaluate per batch",
    )
    stochastic_samples: int = Field(
        24,
        ge=1,
        le=500,
        description="Beta draws per location per event. The vulnerability sampler defaults to 100.",
    )
    return_period: int = 100
    hazard_region: Literal["nairobi", "nzoia"] | None = None
    hazard_raster_path: str | None = None


class FloodEvaluateIn(BaseModel):
    address: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    occupancy_hint: str = ""
    ground_elevation_m: float | None = None
    asset_id: str | None = None


class LatLngIn(BaseModel):
    latitude: float
    longitude: float


class ElevationIn(BaseModel):
    locations: list[LatLngIn] | None = None
    bbox: list[float] | None = Field(
        default=None,
        description="[west, south, east, north] in degrees",
    )
    polygon: list[list[float]] | None = Field(
        default=None,
        description="GeoJSON-style ring of [lon, lat] positions",
    )
    rows: int = Field(12, ge=2, le=64)
    cols: int = Field(12, ge=2, le=64)


class TilesSessionIn(BaseModel):
    west: float | None = None
    south: float | None = None
    east: float | None = None
    north: float | None = None
    renderer: str = "cesium"


class RAGQueryIn(BaseModel):
    query: str = Field(..., min_length=1, max_length=4000)
    event_id: str | None = None
    dataset_name: str | None = None
    csv_text: str | None = Field(
        default=None,
        max_length=400_000,
        description="Optional CSV text from folders held in the browser",
    )


class SummaryIn(BaseModel):
    event_id: str | None = None
    csv_text: str | None = Field(
        default=None,
        max_length=400_000,
        description="Optional CSV text from the open studio tab",
    )


class BlenderManifestIn(BaseModel):
    event_id: str | None = None
    shader_preset: str = "PHOTOREAL_DEFAULT"
    storey_height_m: float = Field(3.5, gt=0, le=10)


class RawClaim(BaseModel):
    asset_id: str
    policy_id: str = ""
    latitude: float = 0.0
    longitude: float = 0.0
    elevation: float = 0.0
    occupancy_raw: str = ""
    tiv: float = 0.0
    ground_up_loss: float = 0.0
    deductible: float = 0.0
    policy_limit: float = 0.0
    coinsurance: float = 1.0
    loss_date: str = ""
    extras: dict[str, Any] = Field(default_factory=dict)


class ChoiceAnswer(BaseModel):
    type: Literal["choice"] = "choice"
    choice: str
    probabilities: dict[str, float]
    confidence: float


class ScoreAnswer(BaseModel):
    type: Literal["score"] = "score"
    score: float
    probabilities: dict[str, float]
    legend: dict[str, str] = Field(default_factory=dict)
    confidence: float


class NoulAnswer(BaseModel):
    type: Literal["noul"] = "noul"
    noul: float


class TriageResult(BaseModel):
    asset_id: str
    occupancy: ChoiceAnswer
    fraud_or_discrepancy: NoulAnswer
    clean_for_finance: NoulAnswer
    spatial_severity: ScoreAnswer
    route: Literal["finance", "hdc_physics"]
    standardized_occupancy: str


class EnrichedClaim(BaseModel):
    asset_id: str
    policy_id: str
    latitude: float
    longitude: float
    elevation: float
    occupancy_raw: str
    occupancy: str
    occupancy_confidence: float
    tiv: float
    ground_up_loss: float
    deductible: float
    policy_limit: float
    coinsurance: float
    loss_date: str
    route: Literal["finance", "hdc_physics"]
    fraud_flag: bool
    fraud_noul: float
    spatial_severity: float
    hdc_interpolation_score: float = 0.0
    hdc_physics_ok: bool = True
    covered_loss: float = 0.0
    allocated_reinsurer_payout: float = 0.0
    allocated_cedant_retention: float = 0.0
    flood_depth_m: float | None = None
    damage_ratio: float = 0.0
    modeled_ground_up_loss: float = 0.0
    reported_ground_up_loss: float = 0.0
    hazard_anomaly: str | None = None
    hazard_region: str = ""
    hazard_synthetic: bool = True
    synthetic: bool = False
    loss_basis: str = "reported"
