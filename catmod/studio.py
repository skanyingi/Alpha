"""Studio previews filled the same way Apps Script fills Docs, Slides, Sheets, Tasks, and Gmail."""

from __future__ import annotations

from collections import Counter
from typing import Any

HIGH_LAYER_PAYOUT = 10_000_000

SHEET_HEADERS = [
    "Timestamp",
    "ClientIndexId",
    "Sender",
    "Subject",
    "Filename",
    "EventId",
    "Status",
    "GrossClaim",
    "ReinsurerPayout",
    "CedantRetention",
    "FraudFlags",
    "ExpectedAnnualLoss",
    "DriveFolderUrl",
    "DocReportUrl",
    "SlidesDeckUrl",
]


def _money(value: Any) -> str:
    try:
        return f"${float(value):,.2f}"
    except (TypeError, ValueError):
        return "n/a"


def _number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def build_studio_preview(job: dict[str, Any] | None) -> dict[str, Any]:
    if not job:
        return {"ready": False}
    placeholders = job.get("placeholders") or {}
    ep = job.get("ep_curve") or {}
    treaty = job.get("treaty") or {}
    synthetic = job.get("synthetic") or {}
    client_name = str(placeholders.get("CLIENT_NAME") or job.get("client_name") or job.get("client_email") or "Client")
    client_email = str(job.get("client_email") or "")
    event_id = str(placeholders.get("EVENT_ID") or job.get("event_id") or "")
    gross = _money(placeholders.get("GROUND_UP_LOSS", job.get("total_gross_claim")))
    payout = _money(placeholders.get("REINSURER_PAYOUT", job.get("reinsurer_payout")))
    retention = _money(placeholders.get("CEDANT_RETENTION", job.get("cedant_retained_loss")))
    modeled = _money(placeholders.get("MODELED_GROUND_UP_LOSS", job.get("modeled_ground_up_loss")))
    eal = _money(placeholders.get("EXPECTED_ANNUAL_LOSS", ep.get("eal")))
    flags = int(_number(placeholders.get("FRAUD_FLAG_COUNT", job.get("flagged_count"))))
    region = str(placeholders.get("HAZARD_REGION") or job.get("hazard_region") or "")
    treaty_label = str(treaty.get("label") or job.get("treaty_label") or "")
    report_lines = [
        ["Client", client_name],
        ["Event ID", event_id],
        ["Ground-Up / Gross Claim", gross],
        ["Reinsurer Payout", payout],
        ["Cedant Retention", retention],
        ["Flagged Fraud / Discrepancy Count", str(flags)],
        ["Modeled ground-up loss", modeled],
        ["Expected annual loss", eal],
        ["Hazard region", region],
        ["Synthetic hazard", str(placeholders.get("SYNTHETIC_HAZARD") or synthetic.get("hazard") or "")],
        ["Synthetic vulnerability curves", str(placeholders.get("SYNTHETIC_VULNERABILITY") or synthetic.get("vulnerability_curves") or "")],
        ["Synthetic exposure portfolio", str(placeholders.get("SYNTHETIC_EXPOSURE") or synthetic.get("exposure_portfolio") or "")],
    ]
    email_rows = [
        f"Client: {client_name}",
        f"Event: {event_id}",
        f"Gross claim: {gross}",
        f"Reinsurer payout: {payout}",
        f"Cedant retention: {retention}",
        f"Fraud / discrepancy flags: {flags}",
        f"Expected annual loss: {eal}",
    ]
    closing = (
        "The PDF audit report is attached. Treaty amounts are produced by the deterministic financial engine. "
        "Spatial interpolation is not used to alter contractual amounts."
    )
    body = "\n".join(
        [f"Catastrophe analysis is complete for event {event_id}.", ""]
        + email_rows
        + ["", "Drive archive: unavailable", "Executive presentation: unavailable", "Audit document: unavailable", "", closing, "", "Regards,", "Catastrophe Analytics Desk"]
    )
    curve = list(ep.get("curve") or [])
    ep_labels = [f"RP {point.get('return_period')}" for point in curve]
    ep_points = [
        _number(point.get("loss_float") if point.get("loss_float") is not None else point.get("loss"))
        for point in curve
    ]
    occupancy: Counter[str] = Counter()
    for claim in job.get("claims") or []:
        if isinstance(claim, dict):
            occupancy[str(claim.get("occupancy") or "Unknown")] += 1
    tasks = []
    if flags > 0:
        tasks.append({
            "title": f"[AUDIT REQUIRED] Review {flags} fraud/spatial flags for Event {event_id}",
            "notes": "Due in 24 hours. Review the audit report before the client reply.",
        })
    if _number(job.get("reinsurer_payout")) > HIGH_LAYER_PAYOUT:
        tasks.append({
            "title": f"[HIGH LAYER EXPOSURE] Review {payout} Reinsurer Payout for Event {event_id}",
            "notes": "Check Excess-of-Loss attachment points and reinstatement terms."
            + (f" Treaty: {treaty_label}" if treaty_label else ""),
        })
    tasks.append({
        "title": f"[CLIENT FOLLOW-UP] Send formal catastrophe audit response to {client_name}"
        + (f" ({client_email})" if client_email else ""),
        "notes": "Attach the Apps Script PDF and the executive deck.",
    })
    started = str((job.get("audit") or {}).get("started_at") or "")
    return {
        "ready": True,
        "event_id": event_id,
        "report_title": f"Reinsurance Audit Report - {event_id}",
        "report_lines": report_lines,
        "email": {
            "to": client_email,
            "subject": f"Catastrophe analysis complete — {event_id}",
            "body": body,
        },
        "slides": [
            {"title": "Catastrophe analytics", "lines": [client_name, f"Event {event_id}", treaty_label or "Excess-of-Loss executive briefing"]},
            {"title": "Financial waterfall", "lines": [f"Gross claim {gross}", f"Reinsurer payout {payout}", f"Cedant retention {retention}"]},
            {"title": "Risk analytics and EP curve", "lines": [f"Expected annual loss {eal}", f"Modeled ground-up loss {modeled}"]},
            {
                "title": "Triage and anomaly summary",
                "lines": [f"Flagged fraud / spatial count: {flags}"] + ([f"Hazard region {region}"] if region else []),
            },
        ],
        "sheet": {
            "headers": SHEET_HEADERS,
            "row": [
                started,
                str(job.get("client_index_id") or ""),
                client_email,
                f"Bordereau {job.get('filename') or ''}",
                str(job.get("filename") or ""),
                event_id,
                "processed",
                gross,
                payout,
                retention,
                str(flags),
                eal,
                "",
                "",
                "",
            ],
        },
        "tasks": tasks,
        "charts": {
            "ep": {"labels": ep_labels, "points": ep_points},
            "occupancy": {"labels": list(occupancy.keys()), "points": list(occupancy.values())},
        },
    }
