from decimal import Decimal
from pathlib import Path

from catmod.leaflet.geojson import generate_leaflet_geojson
from catmod.pipeline import run_pipeline
from catmod.schemas import BordereauWebhook
from catmod.vulnerability.engine import assess


SAMPLE = Path(__file__).resolve().parents[1] / "data" / "sample_nairobi_bordereau.csv"


def test_leaflet_feature_collection_schema():
    geo = generate_leaflet_geojson(
        [
            {
                "id": "A-1",
                "latitude": -1.2921,
                "longitude": 36.8219,
                "occupancy": "COM_WHSE",
                "gul": 1000,
                "payout": 0,
                "is_flagged": False,
            }
        ]
    )
    assert geo["type"] == "FeatureCollection"
    feat = geo["features"][0]
    assert feat["geometry"]["coordinates"] == [36.8219, -1.2921]
    assert feat["properties"]["marker-color"].startswith("#")


def test_end_to_end_pipeline_audit_layers():
    payload = BordereauWebhook(
        client_email="uw@cedant.example",
        client_name="Nairobi County Mutual",
        filename="sample_nairobi_bordereau.csv",
        hazard_region="nairobi",
        data=SAMPLE.read_text(encoding="utf-8") + "N-000,KN-0,0,0,0,whse,1000,0,0,1000,1.0,2026-04-12\n",
        hazard_polygon=[
            [36.75, -1.33],
            [36.90, -1.33],
            [36.90, -1.24],
            [36.75, -1.24],
        ],
    )
    result = run_pipeline(payload)
    assert result["event_id"]
    assert result["client_index_id"].startswith("CID-")
    assert result["claim_count"] == 5
    assert result["placeholders"]["CLIENT_NAME"] == "Nairobi County Mutual"
    assert "GROUND_UP_LOSS" in result["placeholders"]
    assert result["total_gross_claim"] > 0
    assert result["geojson"]["type"] == "FeatureCollection"
    assert any(f["geometry"]["type"] == "Polygon" for f in result["geojson"]["features"])
    flagged = [c for c in result["claims"] if c["asset_id"] == "N-000"][0]
    assert flagged["fraud_flag"] is True
    assert flagged["route"] == "hdc_physics"
    sheet = [c for c in result["claims"] if c["asset_id"] == "N-001"][0]
    assert sheet["occupancy"] == "informal_iron_sheet"
    verification = result["audit"]["layer_verification"]
    for layer in ("1", "2", "3", "4", "5"):
        assert verification[layer]["verified"] is True, verification[layer]
    assert result["audit"]["log_path"]
    jev_steps = [e for e in result["audit"]["entries"] if e["step"] == "jev_triage_complete"]
    assert jev_steps and jev_steps[0]["detail"]["within_budget"] is True
    finance = [e for e in result["audit"]["entries"] if e["step"] == "financial_waterfall_complete"][0]
    assert finance["detail"]["llm_used"] is False
    assert finance["detail"]["vector_approximation_used"] is False
    assert finance["detail"]["synthetic"] is True
    assert result["total_gross_claim"] == 7_732_953.6
    assert result["reinsurer_payout"] == 0
    assert result["cedant_retained_loss"] == 7_732_953.6
    assert result["reinstatement_premium_due"] == 0
    assert result["synthetic"]["hazard"] is True
    assert result["synthetic"]["vulnerability_curves"] is True
    assert result["synthetic"]["ep_curve"] is True
    assert result["synthetic"]["primary_ground_up_loss"] is True
    assert result["source_urls"] == []
    assert result["treaty"]["attachment_point"] == 40_000_000
    assert result["treaty"]["limit"] == 100_000_000
    assert result["ep_curve"]["synthetic"] is True
    assert result["geojson"]["metadata"]["synthetic"] is True
    anomalies = [e for e in result["audit"]["entries"] if e["step"] == "hazard_anomaly"]
    assert any(e["status"] == "NULL_ISLAND" and e["detail"]["message"] == "Null Island" for e in anomalies)
    sla = [e for e in result["audit"]["entries"] if e["step"] == "pipeline_sla"][0]
    assert sla["detail"]["within_budget"] is True


def test_modeled_exposure_uses_decimal_vulnerability_loss():
    payload = BordereauWebhook(
        client_email="desk@nairobi.example",
        client_name="Nairobi Mutual",
        filename="exposure.csv",
        loss_basis="modeled",
        data=(
            "asset_id,policy_id,latitude,longitude,elevation,occupancy,tiv,ground_up_loss,"
            "deductible,policy_limit,coinsurance,loss_date\n"
            "K-1,P-1,-1.2921,36.8219,1700,mabati,2000000,0,10000,2000000,1.0,2026-04-01\n"
        ),
    )
    result = run_pipeline(payload)
    claim = result["claims"][0]
    assert claim["occupancy"] == "informal_iron_sheet"
    assert claim["loss_basis"] == "modeled"
    assert claim["synthetic"] is True
    assert claim["hazard_synthetic"] is True
    assert 0 < claim["damage_ratio"] <= 1
    assert claim["ground_up_loss"] == claim["modeled_ground_up_loss"] > 0
    assert result["synthetic"]["primary_ground_up_loss"] is True
    assert result["modeled_waterfall"]["synthetic"] is True
    assert result["modeled_waterfall"]["vector_approximation_used"] is False
    probabilities = [p["exceedance_probability"] for p in result["ep_curve"]["curve"]]
    assert all(float(a) > float(b) for a, b in zip(probabilities, probabilities[1:]))
    finance = [e for e in result["audit"]["entries"] if e["step"] == "financial_waterfall_complete"][0]
    assert finance["detail"]["llm_used"] is False
    assert finance["detail"]["vector_approximation_used"] is False
    assert finance["detail"]["engine"] == "decimal_cents_half_even"


def _modeled_region(filename: str, region: str) -> dict:
    sample = Path(__file__).resolve().parents[1] / "data" / filename
    return run_pipeline(
        BordereauWebhook(
            client_email="desk@kenya.example",
            client_name="Kenya Mutual",
            filename=filename,
            data=sample.read_text(encoding="utf-8"),
            loss_basis="modeled",
            hazard_region=region,
        )
    )


def test_nairobi_and_nzoia_modeled_losses_enter_the_decimal_waterfall():
    for filename, region, value_kind in (
        ("sample_nairobi_bordereau.csv", "nairobi", "susceptibility"),
        ("sample_nzoia_bordereau.csv", "nzoia", "depth_m"),
    ):
        result = _modeled_region(filename, region)
        assert result["hazard_region"] == region
        assert result["loss_basis"] == "modeled"
        assert result["synthetic"]["vulnerability_curves"] is True
        assert result["synthetic"]["exposure_portfolio"] is True
        expected_lat = -1.28 if region == "nairobi" else 0.45
        assert result["geojson"]["metadata"]["center"]["latitude"] == expected_lat
        assert result["geojson"]["metadata"]["provenance"]["vulnerability_curves"] is True
        hazard = [e for e in result["audit"]["entries"] if e["step"] == "hazard_lookup_complete"][0]
        finance = [e for e in result["audit"]["entries"] if e["step"] == "financial_waterfall_complete"][0]
        modeled = [e for e in result["audit"]["entries"] if e["step"] == "modeled_vulnerability_waterfall"][0]
        assert value_kind in hazard["detail"]["value_kinds"]
        assert finance["detail"]["vector_approximation_used"] is False
        assert finance["detail"]["engine"] == "decimal_cents_half_even"
        assert modeled["detail"]["vector_approximation_used"] is False
        assert modeled["detail"]["synthetic"] is True
        for claim in result["claims"]:
            assert claim["loss_basis"] == "modeled"
            assert claim["flood_depth_m"] is not None
            assert claim["synthetic"] is True
            expected = assess(claim["occupancy"], claim["flood_depth_m"], claim["tiv"])
            assert Decimal(str(claim["ground_up_loss"])) == expected.ground_up_loss
            assert claim["ground_up_loss"] == claim["modeled_ground_up_loss"]
        if region == "nairobi":
            assert any("4.0" in note for note in hazard["detail"]["conversion"])
            assert result["synthetic"]["hazard"] is True
            assert all(claim["flood_depth_m"] <= 4.0001 for claim in result["claims"])
        else:
            assert hazard["detail"]["conversion"] == []
            assert result["total_gross_claim"] > 0


def test_stochastic_mode_audits_the_catalog_without_changing_the_contractual_loss():
    data = (
        "asset_id,policy_id,latitude,longitude,elevation,occupancy,tiv,ground_up_loss,"
        "deductible,policy_limit,coinsurance,loss_date\n"
        "K-1,P-1,-1.2921,36.8219,1700,warehouse,5000000,1000000,10000,5000000,1.0,2026-04-01\n"
    )
    base = dict(
        client_email="desk@nairobi.example",
        client_name="Nairobi Mutual",
        filename="one.csv",
        data=data,
        hazard_region="nairobi",
        loss_basis="reported",
    )
    reported = run_pipeline(BordereauWebhook(**base))
    stochastic = run_pipeline(
        BordereauWebhook(
            **base,
            execution_mode="stochastic",
            stochastic_event_count=12,
            stochastic_samples=4,
        )
    )
    assert stochastic["execution_mode"] == "stochastic"
    assert stochastic["total_gross_claim"] == reported["total_gross_claim"]
    assert stochastic["reinsurer_payout"] == reported["reinsurer_payout"]
    catalog = stochastic["stochastic_catalog"]
    assert catalog["synthetic"] is True
    assert catalog["stochastic"] is True
    assert catalog["event_count"] == 12
    assert catalog["beta_samples"] == 48
    assert Decimal(catalog["ep_curve"]["eal"]) >= 0
    steps = {entry["step"] for entry in stochastic["audit"]["entries"]}
    assert "stochastic_hazard_simulated" in steps
    assert "secondary_uncertainty_evaluated" in steps
    assert "stochastic_ep_curve_generated" in steps
    encoded = [entry for entry in stochastic["audit"]["entries"] if entry["step"] == "hdc_portfolio_encoded"][0]
    assert encoded["detail"]["claims_in_superposition"] == 13


def test_bordereau_webhook_keeps_source_urls():
    payload = BordereauWebhook(
        client_email="uw@cedant.example",
        filename="sample.csv",
        data="asset_id\n",
        source_urls=["https://drive.google.com/file/d/abc/view"],
    )
    assert payload.source_urls == ["https://drive.google.com/file/d/abc/view"]
