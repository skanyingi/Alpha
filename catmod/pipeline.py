"""End-to-end job: ingest -> Jev -> hazard -> vulnerability -> HDC -> finance -> EP/Leaflet.

Reported bordereau ground-up losses stay the contractual Layer 4 input when
``loss_basis`` is ``auto`` or ``reported``. A zero ground-up loss, or
``loss_basis="modeled"``, sends the vulnerability module's Decimal cents into
the same waterfall. The modeled waterfall and the EP curve always run, and
every synthetic grid or proxy curve is tagged.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from catmod.analytics.ep_curve import catalog_ep_curve, portfolio_ep_curve
from catmod.audit import AuditLog
from catmod.config import Settings, get_settings
from catmod.finance.metrics import portfolio_tail_metrics
from catmod.finance.treaty import XLTreaty
from catmod.finance.waterfall import calculate_reinsurance_waterfall
from catmod.hazard.provenance import exposure_portfolio_synthetic
from catmod.hazard.raster import HazardHit
from catmod.hazard.service import STANDARD_RETURN_PERIODS, HazardService, default_hazard_service, service_with_file
from catmod.hazard.stochastic import StochasticHazardGenerator
from catmod.hdc.encoding import ItemMemory
from catmod.hdc.memory import PortfolioMemory
from catmod.hdc.physics import physics_validate
from catmod.ingestion.indexing import assign_client_index_id, assign_event_id
from catmod.ingestion.parser import decode_payload_bytes, parse_attachment
from catmod.jev.harness import JevHarness
from catmod.leaflet.geojson import build_export
from catmod.schemas import BordereauWebhook, EnrichedClaim
from catmod.vulnerability.engine import VulnerabilityResult, assess
from catmod.vulnerability.stochastic_engine import evaluate_vulnerability_sample


def _loss_epoch_days(loss_date: str) -> float:
    if not loss_date:
        return 0.0
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%Y%m%d"):
        try:
            dt = datetime.strptime(loss_date[:10], fmt).replace(tzinfo=timezone.utc)
            return (dt - datetime(2020, 1, 1, tzinfo=timezone.utc)).days / 365.25
        except ValueError:
            continue
    return 0.0


def _loss_basis_for(mode: str, reported_ground_up_loss: float) -> str:
    if mode == "modeled":
        return "modeled"
    if mode == "reported":
        return "reported"
    return "reported" if reported_ground_up_loss > 0 else "modeled"


def _waterfall_summary(waterfall: dict[str, Any], *, synthetic: bool) -> dict[str, Any]:
    summary = {key: value for key, value in waterfall.items() if not isinstance(value, list)}
    summary["synthetic"] = synthetic
    summary["llm_used"] = False
    summary["vector_approximation_used"] = False
    summary["engine"] = "decimal_cents_half_even"
    return summary


def _hazard_service(payload: BordereauWebhook) -> HazardService:
    if payload.hazard_raster_path:
        return service_with_file(payload.hazard_raster_path)
    return default_hazard_service()


def _hazard_is_synthetic(evaluations: list[tuple[HazardHit, VulnerabilityResult, str]]) -> bool:
    in_bounds = [hit for hit, _vuln, _basis in evaluations if hit.in_bounds]
    if not in_bounds:
        return True
    return any(hit.synthetic for hit in in_bounds)


def _stochastic_catalog(
    claims,
    triages,
    treaty: XLTreaty,
    *,
    region: str,
    event_count: int,
    sample_count: int,
    seed: int,
) -> dict[str, Any]:
    """Event catalog, Beta ground-up samples, and one Decimal waterfall per event.

    The returned losses are the financial view. Hypervector encoding is left to
    the caller so this function never touches FHRR memory.
    """
    generator = StochasticHazardGenerator()
    events = generator.generate_event_set(region, num_events=event_count, seed=seed)
    locations = [(claim.latitude, claim.longitude) for claim in claims]
    deductibles = [claim.deductible for claim in claims]
    policy_limits = [claim.policy_limit for claim in claims]
    coinsurance = [claim.coinsurance for claim in claims]
    occupancies = [triage.standardized_occupancy for triage in triages]
    gross_losses: list[Decimal] = []
    reinsurer_losses: list[Decimal] = []
    rates: list[Decimal] = []
    mean_ratios: list[Decimal] = []
    std_ratios: list[Decimal] = []
    draws = 0
    footprints: list[dict[str, float | str]] = []
    for event_index, event in enumerate(events):
        points = generator.get_footprint(event, locations)
        event_guls: list[Decimal] = []
        damage_values: list[float] = []
        for loc_index, (claim, occupancy, point) in enumerate(zip(claims, occupancies, points)):
            sampled = evaluate_vulnerability_sample(
                occupancy,
                point.depth_m,
                claim.tiv,
                num_samples=sample_count,
                seed=seed + event_index * 10007 + loc_index,
            )
            event_guls.append(sampled.mean_ground_up_loss)
            mean_ratios.append(sampled.mean_damage_ratio)
            std_ratios.append(sampled.stddev_damage_ratio)
            damage_values.append(float(sampled.mean_damage_ratio))
            draws += sample_count
        waterfall = calculate_reinsurance_waterfall(
            event_guls,
            deductibles,
            policy_limits,
            treaty,
            coinsurance,
        )
        gross_losses.append(Decimal(str(waterfall["total_gross_claim"])))
        reinsurer_losses.append(Decimal(str(waterfall["reinsurer_payout"])))
        rates.append(event.rate)
        if event_index < 48:
                footprints.append(
                    {
                        "latitude": sum(claim.latitude for claim in claims) / len(claims),
                        "longitude": sum(claim.longitude for claim in claims) / len(claims),
                        "damage_ratio": sum(damage_values) / len(damage_values),
                        "cost": float(sum(event_guls, Decimal("0"))),
                        "occupancy": occupancies[0],
                        "event_id": event.event_id,
                    }
                )
    curve = catalog_ep_curve(gross_losses, rates, years=2_000, seed=seed)
    mean_dr = sum(mean_ratios, Decimal("0")) / Decimal(len(mean_ratios))
    mean_sigma = sum(std_ratios, Decimal("0")) / Decimal(len(std_ratios))
    weighted_reinsurer = sum(
        (rate * loss for rate, loss in zip(rates, reinsurer_losses)),
        Decimal("0"),
    )
    return {
        "synthetic": True,
        "stochastic": True,
        "secondary_uncertainty": True,
        "region": region,
        "seed": seed,
        "event_count": len(events),
        "beta_samples": draws,
        "mean_damage_ratio": format(mean_dr, "f"),
        "stddev_damage_ratio": format(mean_sigma, "f"),
        "rate_weighted_reinsurer_payout": format(weighted_reinsurer, "f"),
        "ep_curve": curve,
        "footprints": footprints,
    }


def default_treaty(settings: Settings, incoming: BordereauWebhook) -> XLTreaty:
    if incoming.treaty is not None:
        t = incoming.treaty
        return XLTreaty(
            attachment_point=t.attachment_point,
            limit=t.limit,
            co_participation=t.co_participation,
            reinstatement_cost=t.reinstatement_cost,
            reinstatements=t.reinstatements,
            original_premium=t.original_premium or settings.default_layer_premium,
        )
    return XLTreaty(
        attachment_point=settings.default_attachment,
        limit=settings.default_limit,
        co_participation=settings.default_copart,
        reinstatement_cost=settings.default_reinstatement_rate,
        reinstatements=settings.default_reinstatements,
        original_premium=settings.default_layer_premium,
    )


def run_pipeline(payload: BordereauWebhook, settings: Settings | None = None) -> dict[str, Any]:
    started = time.perf_counter()
    settings = settings or get_settings()
    hazard_region = payload.hazard_region or settings.default_hazard_region
    exposure_synthetic = exposure_portfolio_synthetic(payload.filename)
    if payload.return_period not in STANDARD_RETURN_PERIODS:
        known = ", ".join(str(rp) for rp in STANDARD_RETURN_PERIODS)
        raise ValueError(f"return_period must be one of {known}")
    blob = decode_payload_bytes(payload.data_base64)
    client_index_id = payload.client_index_id or assign_client_index_id(
        payload.client_email, payload.filename, payload.data or payload.data_base64 or ""
    )
    event_id = payload.event_id or assign_event_id(client_index_id, payload.filename)
    audit = AuditLog(event_id, settings.audit_dir)

    audit.record(
        layer=1,
        name="apps_script_webhook_received",
        status="ok",
        detail={
            "client_email": payload.client_email,
            "client_name": payload.client_name,
            "filename": payload.filename,
            "client_index_id": client_index_id,
            "underwriter_email": payload.underwriter_email,
            "source_urls": list(payload.source_urls),
        },
    )

    with audit.span(1, "bordereau_parsed"):
        claims = parse_attachment(
            filename=payload.filename,
            text=payload.data,
            blob=blob,
            content_type=payload.content_type,
        )
    audit.record(
        layer=1,
        name="bordereau_parsed",
        status="ok",
        detail={"claim_count": len(claims), "filename": payload.filename},
    )

    harness = JevHarness(settings)
    t0 = time.perf_counter()
    triages = harness.triage_batch(claims)
    jev_ms = (time.perf_counter() - t0) * 1000.0
    finance_routes = sum(1 for t in triages if t.route == "finance")
    hdc_routes = sum(1 for t in triages if t.route == "hdc_physics")
    audit.record(
        layer=2,
        name="jev_triage_complete",
        status="ok" if jev_ms < 500 else "latency_budget_exceeded",
        latency_ms=jev_ms,
        detail={
            "batch_size": len(claims),
            "budget_ms": 500,
            "within_budget": jev_ms < 500,
            "route_finance": finance_routes,
            "route_hdc_physics": hdc_routes,
            "hosted_jev": harness.hosted.enabled,
        },
    )

    hazard = _hazard_service(payload)
    evaluations: list[tuple[HazardHit, VulnerabilityResult, str]] = []
    for claim, triage in zip(claims, triages):
        hit = hazard.lookup(
            claim.latitude,
            claim.longitude,
            return_period=payload.return_period,
            region=hazard_region,
        )
        if hit.anomaly:
            audit.record(
                layer=8,
                name="hazard_anomaly",
                status=hit.anomaly,
                detail=hit.as_dict(),
            )
        depth = hit.depth_m if hit.depth_m is not None else Decimal("0")
        vuln = assess(triage.standardized_occupancy, depth, claim.tiv)
        basis = _loss_basis_for(payload.loss_basis, claim.ground_up_loss)
        evaluations.append((hit, vuln, basis))
    hazard_synthetic = _hazard_is_synthetic(evaluations)
    audit.record(
        layer=8,
        name="hazard_lookup_complete",
        status="ok",
        detail={
            "return_period": payload.return_period,
            "region": hazard_region,
            "locations": len(evaluations),
            "anomalies": sum(1 for hit, _vuln, _basis in evaluations if hit.anomaly),
            "synthetic": hazard_synthetic,
            "proxy": any(hit.proxy for hit, _vuln, _basis in evaluations),
            "value_kinds": sorted({hit.value_kind for hit, _vuln, _basis in evaluations}),
            "sources": sorted({hit.source for hit, _vuln, _basis in evaluations}),
            "conversion": sorted({hit.message for hit, _vuln, _basis in evaluations if hit.message}),
        },
    )
    modeled_total = sum((vuln.ground_up_loss for _hit, vuln, _basis in evaluations), Decimal("0.00"))
    audit.record(
        layer=9,
        name="vulnerability_complete",
        status="ok",
        detail={
            "synthetic": True,
            "proxy": True,
            "curve_family": "jrc_huizinga_proxy",
            "ground_up_loss": format(modeled_total, "f"),
            "engine": "decimal_cents_half_even",
            "occupancies": sorted({vuln.curve_code for _hit, vuln, _basis in evaluations}),
        },
    )

    stochastic_catalog: dict[str, Any] | None = None
    if payload.execution_mode == "stochastic":
        if not claims:
            raise ValueError("stochastic execution requires at least one bordereau line")
        stochastic_treaty = default_treaty(settings, payload)
        stochastic_catalog = _stochastic_catalog(
            claims,
            triages,
            stochastic_treaty,
            region=hazard_region,
            event_count=payload.stochastic_event_count,
            sample_count=payload.stochastic_samples,
            seed=settings.hdc_seed,
        )
        audit.record(
            layer=8,
            name="stochastic_hazard_simulated",
            status="ok",
            detail={
                "num_events": stochastic_catalog["event_count"],
                "spatial_covariance_seed": stochastic_catalog["seed"],
                "region": hazard_region,
                "synthetic": True,
                "stochastic": True,
            },
        )
        audit.record(
            layer=9,
            name="secondary_uncertainty_evaluated",
            status="ok",
            detail={
                "mean_dr": stochastic_catalog["mean_damage_ratio"],
                "stddev_dr": stochastic_catalog["stddev_damage_ratio"],
                "beta_samples": stochastic_catalog["beta_samples"],
                "synthetic": True,
                "proxy": True,
                "secondary_uncertainty": True,
            },
        )

    items = ItemMemory(dim=settings.hdc_dim, seed=settings.hdc_seed)
    memory = PortfolioMemory(items)
    for claim, triage, (_hit, vuln, basis) in zip(claims, triages, evaluations):
        selected_loss = vuln.ground_up_loss if basis == "modeled" else claim.ground_up_loss
        memory.encode_and_add(
            latitude=claim.latitude,
            longitude=claim.longitude,
            elevation=claim.elevation,
            time_t=_loss_epoch_days(claim.loss_date),
            cost=float(selected_loss or claim.tiv),
            occupancy=triage.standardized_occupancy,
            damage_ratio=float(vuln.damage_ratio),
        )
    if stochastic_catalog is not None:
        for index, footprint in enumerate(stochastic_catalog["footprints"]):
            memory.encode_and_add(
                latitude=float(footprint["latitude"]),
                longitude=float(footprint["longitude"]),
                elevation=0.0,
                time_t=float(index),
                cost=float(footprint["cost"]),
                occupancy=str(footprint["occupancy"]),
                damage_ratio=float(footprint["damage_ratio"]),
            )
    audit.record(
        layer=3,
        name="hdc_portfolio_encoded",
        status="ok",
        detail={
            "dimension": settings.hdc_dim,
            "claims_in_superposition": memory.count,
            "representation": "FHRR complex",
            "roles": ["location", "occupancy", "damage_ratio"],
        },
    )

    physics_hits: list[tuple[float, bool]] = []
    for claim, triage in zip(claims, triages):
        if triage.route == "hdc_physics":
            physics_hits.append(physics_validate(claim, triage, memory))
        else:
            physics_hits.append((memory.interpolation_score(claim.latitude, claim.longitude), True))

    lats = [c.latitude for c in claims if not (abs(c.latitude) < 1e-6 and abs(c.longitude) < 1e-6)]
    lons = [c.longitude for c in claims if not (abs(c.latitude) < 1e-6 and abs(c.longitude) < 1e-6)]
    clusters: list[dict[str, float]] = []
    if lats and lons:
        pad_lat = max((max(lats) - min(lats)) * 0.15, 0.05)
        pad_lon = max((max(lons) - min(lons)) * 0.15, 0.05)
        clusters = memory.exposure_clusters(
            (min(lats) - pad_lat, max(lats) + pad_lat),
            (min(lons) - pad_lon, max(lons) + pad_lon),
            steps=5,
        )[:5]
    projected = memory.project_time(1.0 / 365.25)
    audit.record(
        layer=3,
        name="hdc_query_complete",
        status="ok",
        detail={
            "physics_validated": sum(1 for t in triages if t.route == "hdc_physics"),
            "top_clusters": clusters[:3],
            "temporal_projection": "M(t+1d) = M(t) ⊗ P^Δt",
            "projected_norm": float(abs(projected).mean()),
        },
    )

    treaty = default_treaty(settings, payload)
    deductibles = [c.deductible for c in claims]
    policy_limits = [c.policy_limit for c in claims]
    coinsurance = [c.coinsurance for c in claims]
    finance_guls: list[float | Decimal] = [
        vuln.ground_up_loss if basis == "modeled" else claim.ground_up_loss
        for claim, (_hit, vuln, basis) in zip(claims, evaluations)
    ]
    waterfall = calculate_reinsurance_waterfall(
        finance_guls,
        deductibles,
        policy_limits,
        treaty,
        coinsurance,
    )
    modeled_guls = [vuln.ground_up_loss for _hit, vuln, _basis in evaluations]
    modeled_waterfall = calculate_reinsurance_waterfall(
        modeled_guls,
        deductibles,
        policy_limits,
        treaty,
        coinsurance,
    )
    tails = portfolio_tail_metrics(
        waterfall["per_policy_covered"],
        waterfall["total_gross_claim"],
    )
    primary_synthetic = bool(evaluations) and all(basis == "modeled" for _hit, _vuln, basis in evaluations)
    audit.record(
        layer=4,
        name="financial_waterfall_complete",
        status="ok",
        detail={
            "treaty": treaty.layer_label,
            "loss_basis": payload.loss_basis,
            "synthetic": primary_synthetic,
            "total_gross_claim": waterfall["total_gross_claim"],
            "reinsurer_payout": waterfall["reinsurer_payout"],
            "cedant_retained_loss": waterfall["cedant_retained_loss"],
            "reinstatement_premium_due": waterfall["reinstatement_premium_due"],
            "llm_used": False,
            "vector_approximation_used": False,
            "engine": "decimal_cents_half_even",
        },
    )
    audit.record(
        layer=4,
        name="modeled_vulnerability_waterfall",
        status="ok",
        detail={
            "synthetic": True,
            "ground_up_loss": format(modeled_total, "f"),
            "reinsurer_payout": modeled_waterfall["reinsurer_payout"],
            "cedant_retained_loss": modeled_waterfall["cedant_retained_loss"],
            "reinstatement_premium_due": modeled_waterfall["reinstatement_premium_due"],
            "llm_used": False,
            "vector_approximation_used": False,
            "engine": "decimal_cents_half_even",
        },
    )
    exposures = [
        {
            "latitude": claim.latitude,
            "longitude": claim.longitude,
            "tiv": claim.tiv,
            "occupancy": triage.standardized_occupancy,
        }
        for claim, triage in zip(claims, triages)
    ]
    ep_curve = portfolio_ep_curve(exposures, service=hazard, region=hazard_region)
    audit.record(
        layer=10,
        name="ep_curve_complete",
        status="ok",
        detail={
            "synthetic": True,
            "eal": ep_curve["eal"],
            "return_periods": ep_curve["return_periods"],
            "monotonic_exceedance": ep_curve["monotonic_exceedance"],
        },
    )
    if stochastic_catalog is not None:
        stochastic_curve = stochastic_catalog["ep_curve"]
        audit.record(
            layer=10,
            name="stochastic_ep_curve_generated",
            status="ok",
            detail={
                "synthetic": True,
                "stochastic": True,
                "oep": stochastic_curve["oep"]["var"],
                "aep": stochastic_curve["aep"]["var"],
                "eal": stochastic_curve["eal"],
                "tvar_995": stochastic_curve["tvar_995"],
            },
        )

    enriched: list[EnrichedClaim] = []
    leaflet_rows: list[dict[str, Any]] = []
    flagged_count = 0
    for i, (claim, triage, (hit, vuln, basis)) in enumerate(zip(claims, triages, evaluations)):
        interp, physics_ok = physics_hits[i]
        fraud_flag = triage.fraud_or_discrepancy.noul >= 0.5 or not physics_ok
        if fraud_flag:
            flagged_count += 1
        gul_value = float(vuln.ground_up_loss) if basis == "modeled" else claim.ground_up_loss
        row = EnrichedClaim(
            asset_id=claim.asset_id,
            policy_id=claim.policy_id,
            latitude=claim.latitude,
            longitude=claim.longitude,
            elevation=claim.elevation,
            occupancy_raw=claim.occupancy_raw,
            occupancy=triage.standardized_occupancy,
            occupancy_confidence=triage.occupancy.confidence,
            tiv=claim.tiv,
            ground_up_loss=gul_value,
            deductible=claim.deductible,
            policy_limit=claim.policy_limit,
            coinsurance=claim.coinsurance,
            loss_date=claim.loss_date,
            route=triage.route,
            fraud_flag=fraud_flag,
            fraud_noul=triage.fraud_or_discrepancy.noul,
            spatial_severity=triage.spatial_severity.score,
            hdc_interpolation_score=interp,
            hdc_physics_ok=physics_ok,
            covered_loss=waterfall["per_policy_covered"][i],
            allocated_reinsurer_payout=waterfall["allocated_reinsurer_payout"][i],
            allocated_cedant_retention=waterfall["allocated_cedant_retention"][i],
            flood_depth_m=None if hit.depth_m is None else float(hit.depth_m),
            damage_ratio=float(vuln.damage_ratio),
            modeled_ground_up_loss=float(vuln.ground_up_loss),
            reported_ground_up_loss=claim.ground_up_loss,
            hazard_anomaly=hit.anomaly,
            hazard_region=hit.region,
            hazard_synthetic=hit.synthetic,
            synthetic=bool(vuln.synthetic or exposure_synthetic or hit.synthetic or basis == "modeled"),
            loss_basis=basis,
        )
        enriched.append(row)
        leaflet_rows.append(
            {
                "id": row.asset_id,
                "asset_id": row.asset_id,
                "latitude": row.latitude,
                "longitude": row.longitude,
                "occupancy": row.occupancy,
                "gul": row.covered_loss,
                "ground_up_loss": row.ground_up_loss,
                "payout": row.allocated_reinsurer_payout,
                "cedant_retention": row.allocated_cedant_retention,
                "hdc_interpolation_score": row.hdc_interpolation_score,
                "is_flagged": row.fraud_flag,
                "fraud_flag": row.fraud_flag,
                "flood_depth_m": row.flood_depth_m,
                "damage_ratio": row.damage_ratio,
                "synthetic": row.synthetic,
                "badge": "synthetic" if row.synthetic else "",
                "hazard_anomaly": row.hazard_anomaly,
                "loss_basis": row.loss_basis,
                "hazard_source": hit.source,
                "proxy": hit.proxy or vuln.proxy,
            }
        )

    if hazard_region == "nzoia":
        map_center = {"latitude": 0.45, "longitude": 34.22, "zoom": 11}
    else:
        map_center = {
            "latitude": settings.default_map_latitude,
            "longitude": settings.default_map_longitude,
            "zoom": settings.default_map_zoom,
        }
    provenance = {
        "hazard": hazard_synthetic,
        "vulnerability_curves": True,
        "exposure_portfolio": exposure_synthetic,
    }
    geojson = build_export(
        event_id=event_id,
        claims=leaflet_rows,
        hazard_polygon=payload.hazard_polygon,
        extra_metadata={
            "synthetic": True,
            "provenance": provenance,
            "hazard_region": hazard_region,
            "center": map_center,
            "disclaimer": (
                "Vulnerability curves are a JRC/Huizinga proxy (synthetic: true). "
                "Synthetic exposure portfolios are generated for the hackathon. "
                "Mounted nzoia_rp GeoTIFFs are JRC flood depth in metres. "
                "Nairobi pluvial rasters are a susceptibility proxy, depth_m = susceptibility × 4.0 m."
            ),
            "ep_curve": ep_curve,
        },
    )
    audit.record(
        layer=5,
        name="leaflet_geojson_emitted",
        status="ok",
        detail={
            "feature_count": len(geojson["features"]),
            "has_hazard_polygon": bool(payload.hazard_polygon),
            "type": geojson["type"],
            "synthetic": True,
            "ep_curve_embedded": True,
        },
    )
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    audit.record(
        layer=5,
        name="pipeline_sla",
        status="ok" if elapsed_ms < 1000 else "latency_budget_exceeded",
        latency_ms=elapsed_ms,
        detail={"budget_ms": 1000, "within_budget": elapsed_ms < 1000},
    )

    result = {
        "event_id": event_id,
        "client_index_id": client_index_id,
        "client_email": payload.client_email,
        "client_name": payload.client_name or payload.client_email,
        "filename": payload.filename,
        "total_gross_claim": waterfall["total_gross_claim"],
        "reinsurer_payout": waterfall["reinsurer_payout"],
        "cedant_retained_loss": waterfall["cedant_retained_loss"],
        "reinstatement_premium_due": waterfall["reinstatement_premium_due"],
        "layer_loss": waterfall["layer_loss"],
        "exhaustion_ratio": waterfall["exhaustion_ratio"],
        "treaty_label": waterfall["treaty_label"],
        "treaty": {
            "attachment_point": treaty.attachment_point,
            "limit": treaty.limit,
            "co_participation": treaty.co_participation,
            "reinstatements": treaty.reinstatements,
            "original_premium": treaty.original_premium,
            "label": waterfall["treaty_label"],
        },
        "source_urls": list(payload.source_urls),
        "flagged_count": flagged_count,
        "claim_count": len(claims),
        "tvar_pml": tails,
        "loss_basis": payload.loss_basis,
        "execution_mode": payload.execution_mode,
        "return_period": payload.return_period,
        "hazard_region": hazard_region,
        "synthetic": {
            "hazard": hazard_synthetic,
            "vulnerability_curves": True,
            "exposure_portfolio": exposure_synthetic,
            "ep_curve": True,
            "primary_ground_up_loss": primary_synthetic,
        },
        "modeled_ground_up_loss": format(modeled_total, "f"),
        "modeled_waterfall": _waterfall_summary(modeled_waterfall, synthetic=True),
        "ep_curve": ep_curve,
        "stochastic_catalog": None
        if stochastic_catalog is None
        else {key: value for key, value in stochastic_catalog.items() if key != "footprints"},
        "placeholders": {
            "CLIENT_NAME": payload.client_name or payload.client_email,
            "EVENT_ID": event_id,
            "GROUND_UP_LOSS": waterfall["total_gross_claim"],
            "REINSURER_PAYOUT": waterfall["reinsurer_payout"],
            "CEDANT_RETENTION": waterfall["cedant_retained_loss"],
            "FRAUD_FLAG_COUNT": flagged_count,
            "MODELED_GROUND_UP_LOSS": format(modeled_total, "f"),
            "EXPECTED_ANNUAL_LOSS": ep_curve["eal"],
            "SYNTHETIC": True,
            "SYNTHETIC_HAZARD": str(hazard_synthetic).lower(),
            "SYNTHETIC_VULNERABILITY": "true",
            "SYNTHETIC_EXPOSURE": str(exposure_synthetic).lower(),
            "HAZARD_REGION": hazard_region,
        },
        "claims": [e.model_dump() for e in enriched],
        "geojson": geojson,
        "audit": audit.as_dict(),
    }
    return result


def process_bordereau(payload: BordereauWebhook, settings: Settings | None = None) -> dict[str, Any]:
    """Webhook alias for ``run_pipeline``."""
    return run_pipeline(payload, settings)
