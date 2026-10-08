from catmod.studio import build_studio_preview


def test_studio_preview_matches_apps_script_shapes():
    job = {
        "event_id": "EVT-1",
        "client_email": "desk@catmod.local",
        "client_name": "Catastrophe desk",
        "filename": "nairobi-book.csv",
        "client_index_id": "CID-1",
        "total_gross_claim": 1000.0,
        "reinsurer_payout": 0.0,
        "cedant_retained_loss": 1000.0,
        "modeled_ground_up_loss": "1200.00",
        "flagged_count": 2,
        "hazard_region": "nairobi",
        "treaty_label": "$100M xs $40M",
        "treaty": {"label": "$100M xs $40M"},
        "ep_curve": {
            "eal": 250.0,
            "curve": [{"return_period": 100, "loss": 400.0}, {"return_period": 250, "loss": 900.0}],
        },
        "synthetic": {"hazard": False, "vulnerability_curves": True, "exposure_portfolio": False},
        "placeholders": {
            "CLIENT_NAME": "Catastrophe desk",
            "EVENT_ID": "EVT-1",
            "GROUND_UP_LOSS": 1000.0,
            "REINSURER_PAYOUT": 0.0,
            "CEDANT_RETENTION": 1000.0,
            "FRAUD_FLAG_COUNT": 2,
            "MODELED_GROUND_UP_LOSS": "1200.00",
            "EXPECTED_ANNUAL_LOSS": 250.0,
            "HAZARD_REGION": "nairobi",
            "SYNTHETIC_HAZARD": "false",
            "SYNTHETIC_VULNERABILITY": "true",
            "SYNTHETIC_EXPOSURE": "false",
        },
        "claims": [
            {"occupancy": "RES_SF"},
            {"occupancy": "RES_SF"},
            {"occupancy": "COM_WHSE"},
            {"occupancy": "informal_iron_sheet", "tiv": 100, "modeled_ground_up_loss": 40, "flood_depth_m": 1.2},
            {"occupancy": "concrete_rcc", "tiv": 300, "modeled_ground_up_loss": 20, "flood_depth_m": 0.4},
        ],
        "audit": {"started_at": "2026-10-08T08:10:00+00:00"},
    }
    pack = build_studio_preview(job)
    assert pack["ready"] is True
    assert pack["report_title"] == "Reinsurance Audit Report - EVT-1"
    assert pack["email"]["to"] == "desk@catmod.local"
    assert "Catastrophe analysis is complete for event EVT-1." in pack["email"]["body"]
    assert pack["email"]["subject"].startswith("Catastrophe analysis complete")
    assert any(task["title"].startswith("[AUDIT REQUIRED]") for task in pack["tasks"])
    assert pack["charts"]["ep"]["labels"] == ["RP 100", "RP 250"]
    assert pack["charts"]["occupancy"]["points"] == [2, 1, 1, 1]
    radar = pack["charts"]["radar"]
    assert radar["spokes"][0] == "Buildings"
    assert len(radar["spokes"]) == 8
    informal = radar["series"][0]
    concrete = radar["series"][3]
    assert informal["label"] == "Informal iron sheet"
    assert informal["values"][0] == 50
    assert informal["values"][1] == 25
    assert concrete["values"][6] == 45
    assert pack["sheet"]["headers"][5] == "EventId"
    assert build_studio_preview(None) == {"ready": False}
