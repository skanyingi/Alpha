from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from catmod.pipeline import run_pipeline
from catmod.schemas import BordereauWebhook

REQUIRED_STEPS = {
    1: "bordereau_parsed",
    2: "jev_triage_complete",
    3: "hdc_portfolio_encoded",
    4: "financial_waterfall_complete",
    5: "leaflet_geojson_emitted",
    8: "hazard_lookup_complete",
    9: "vulnerability_complete",
    10: "ep_curve_complete",
}


def main() -> None:
    sample = ROOT / "data" / "sample_nairobi_bordereau.csv"
    result = run_pipeline(
        BordereauWebhook(
            client_email="desk@nairobi.example",
            client_name="Nairobi County Mutual",
            filename="sample_nairobi_bordereau.csv",
            data=sample.read_text(encoding="utf-8"),
            loss_basis="modeled",
            hazard_region="nairobi",
            hazard_polygon=[
                [36.75, -1.33],
                [36.90, -1.33],
                [36.90, -1.24],
                [36.75, -1.24],
            ],
        )
    )
    steps = {(entry["layer"], entry["step"]) for entry in result["audit"]["entries"]}
    missing = [f"L{layer}:{name}" for layer, name in REQUIRED_STEPS.items() if (layer, name) not in steps]
    if missing:
        raise SystemExit("missing audit steps: " + ", ".join(missing))
    summary = {
        "event_id": result["event_id"],
        "hazard_region": result["hazard_region"],
        "loss_basis": result["loss_basis"],
        "total_gross_claim": result["total_gross_claim"],
        "reinsurer_payout": result["reinsurer_payout"],
        "cedant_retained_loss": result["cedant_retained_loss"],
        "reinstatement_premium_due": result["reinstatement_premium_due"],
        "modeled_ground_up_loss": result["modeled_ground_up_loss"],
        "synthetic": result["synthetic"],
        "center": result["geojson"]["metadata"]["center"],
        "flagged_count": result["flagged_count"],
        "audit_layers_present": sorted({entry["layer"] for entry in result["audit"]["entries"]}),
        "audit_log": result["audit"]["log_path"],
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
