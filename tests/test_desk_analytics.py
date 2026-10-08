"""Housing breakdown, vulnerability knots, and what-if waterfall stay on the finance engine."""

from decimal import Decimal

from fastapi.testclient import TestClient

from catmod.analytics.desk import housing_breakdown, scenario_net_curve, vulnerability_curve_payload
from catmod.config import Settings
from catmod.finance.treaty import XLTreaty
from catmod.finance.waterfall import calculate_reinsurance_waterfall


def test_housing_breakdown_keeps_the_four_classes_and_the_residual():
    result = housing_breakdown(
        [
            {"occupancy": "informal_iron_sheet", "tiv": "100.00", "ground_up_loss": "40.00"},
            {"occupancy": "semi_permanent", "tiv": "200.00", "ground_up_loss": "50.00"},
            {"occupancy": "permanent_masonry", "tiv": "300.00", "ground_up_loss": "60.00"},
            {"occupancy": "concrete_rcc", "tiv": "400.00", "ground_up_loss": "70.00"},
            {"occupancy": "UNK", "tiv": "10.00", "ground_up_loss": "1.00"},
        ]
    )
    by_name = {row["occupancy"]: row for row in result["classes"]}
    assert list(by_name) == [
        "informal_iron_sheet",
        "semi_permanent",
        "permanent_masonry",
        "concrete_rcc",
    ]
    assert by_name["concrete_rcc"]["tiv"] == "400.00"
    assert result["other"]["count"] == 1
    assert result["other"]["tiv"] == "10.00"


def test_vulnerability_curves_cover_each_housing_class():
    payload = vulnerability_curve_payload()
    names = [curve["occupancy"] for curve in payload["curves"]]
    assert names == [
        "informal_iron_sheet",
        "semi_permanent",
        "permanent_masonry",
        "concrete_rcc",
    ]
    assert payload["synthetic"] is True
    assert payload["curves"][0]["knots"][0]["depth_m"] == "0"


def test_scenario_net_matches_the_waterfall_on_the_same_total():
    treaty = XLTreaty(
        attachment_point=Decimal("100"),
        limit=Decimal("50"),
        co_participation=Decimal("0.90"),
        reinstatement_cost=Decimal("1"),
        reinstatements=1,
        original_premium=Decimal("0"),
    )
    curve = scenario_net_curve(
        {"curve": [{"return_period": 100, "loss": "1000.00"}]},
        treaty,
    )
    direct = calculate_reinsurance_waterfall([Decimal("1000.00")], [0], [0], treaty, [1])
    assert curve[0]["gul"] == "1000.00"
    assert curve[0]["net"] == format(direct["cedant_retained_loss"], "f")
    assert curve[0]["reinsurer"] == format(direct["reinsurer_payout"], "f")


def test_what_if_endpoint_uses_the_saved_book(tmp_path, monkeypatch):
    import catmod.api as api

    settings = Settings(
        gemini_api_key="",
        gemini_model="gemini-3.8-flash",
        jobs_dir=str(tmp_path / "jobs"),
        jobs_keep=4,
        audit_dir=str(tmp_path / "audit"),
        default_layer_premium=0,
        hdc_dim=256,
        hdc_seed=1,
    )
    monkeypatch.setattr(api, "get_settings", lambda: settings)
    monkeypatch.setattr("catmod.pipeline.get_settings", lambda: settings)
    api._STORE = None
    client = TestClient(api.app)
    csv = (
        "asset_id,latitude,longitude,tiv,occupancy,deductible,policy_limit\n"
        "N-1,-1.2921,36.8219,1000000,informal iron sheet,0,0\n"
    )
    created = client.post(
        "/v1/process-bordereau",
        json={
            "client_email": "desk@catmod.local",
            "filename": "desk.csv",
            "data": csv,
            "content_type": "text/csv",
            "loss_basis": "modeled",
            "hazard_region": "nairobi",
            "return_period": 100,
        },
    )
    assert created.status_code == 200
    event_id = created.json()["event_id"]
    curves = client.get("/v1/vulnerability-curves")
    assert curves.status_code == 200
    assert len(curves.json()["curves"]) == 4
    simulated = client.post("/v1/simulate-ep", json={"event_id": event_id})
    assert simulated.status_code == 200
    body = simulated.json()
    assert body["points"]
    assert body["points"][0]["audit"]
    shifted = client.post(
        "/v1/reinsurance-waterfall",
        json={
            "event_id": event_id,
            "attachment_point": 0,
            "limit": 1_000_000_000,
            "co_participation": 1,
        },
    )
    assert shifted.status_code == 200
    paid = shifted.json()
    assert Decimal(paid["reinsurer_payout"]) >= 0
    assert Decimal(paid["cedant_retained_loss"]) >= 0
    assert abs(
        Decimal(paid["reinsurer_payout"]) + Decimal(paid["cedant_retained_loss"])
        - Decimal(paid["total_gross_claim"])
    ) < Decimal("0.02")
