import json as jsonlib

from fastapi.testclient import TestClient

from catmod.config import Settings
from catmod.nlp.gemini_rag import brief_job, build_briefing_context


def _job() -> dict:
    return {
        "event_id": "EVT-BRIEF-1",
        "filename": "nairobi-book.csv",
        "claim_count": 3,
        "total_gross_claim": 1000.0,
        "reinsurer_payout": 400.0,
        "cedant_retained_loss": 600.0,
        "reinstatement_premium_due": 0.0,
        "layer_loss": 400.0,
        "exhaustion_ratio": 0.1,
        "modeled_ground_up_loss": "1200.00",
        "flagged_count": 2,
        "hazard_region": "nairobi",
        "treaty_label": "$100M xs $40M",
        "treaty": {
            "label": "$100M xs $40M",
            "attachment_point": 40_000_000.0,
            "limit": 100_000_000.0,
            "co_participation": 0.9,
        },
        "tvar_pml": {"location_var_99": 900.0},
        "ep_curve": {
            "eal": 250.0,
            "curve": [
                {"return_period": 10, "loss": 100.0, "loss_float": 100.0},
                {"return_period": 100, "loss": 400.0, "loss_float": 400.0},
                {"return_period": 500, "loss": 1500.0, "loss_float": 1500.0},
            ],
        },
        "placeholders": {
            "EVENT_ID": "EVT-BRIEF-1",
            "GROUND_UP_LOSS": 1000.0,
            "REINSURER_PAYOUT": 400.0,
            "CEDANT_RETENTION": 600.0,
            "MODELED_GROUND_UP_LOSS": "1200.00",
            "EXPECTED_ANNUAL_LOSS": 250.0,
            "HAZARD_REGION": "nairobi",
        },
        "claims": [
            {
                "asset_id": "N-001",
                "occupancy": "informal_iron_sheet",
                "tiv": 100,
                "modeled_ground_up_loss": 40,
                "flood_depth_m": 1.2,
                "damage_ratio": 0.4,
            },
            {
                "asset_id": "N-002",
                "occupancy": "concrete_rcc",
                "tiv": 300,
                "modeled_ground_up_loss": 90,
                "flood_depth_m": 0.4,
                "damage_ratio": 0.3,
            },
            {
                "asset_id": "N-003",
                "occupancy": "permanent_masonry",
                "tiv": 200,
                "ground_up_loss": 55,
                "flood_depth_m": 0.8,
                "damage_ratio": 0.28,
            },
        ],
        "synthetic": {
            "hazard": False,
            "vulnerability_curves": True,
            "exposure_portfolio": False,
        },
    }


def _settings(**overrides) -> Settings:
    base = {
        "gemini_api_key": "",
        "gemini_model": "gemini-2.0-flash",
        "openrouter_api_key": "",
        "openrouter_model": "openai/gpt-4.1-nano",
        "openrouter_fallbacks": "",
        "openrouter_base_url": "https://openrouter.ai/api/v1",
        "openrouter_timeout_s": 45.0,
    }
    base.update(overrides)
    return Settings.model_construct(**base)


class _FakeResponse:
    def __init__(self, body):
        self._body = body

    def raise_for_status(self):
        return None

    def json(self):
        return self._body


class _OpenRouterClient:
    def __init__(self):
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def post(self, url, params=None, headers=None, json=None):
        self.calls.append(url)
        content = jsonlib.dumps(
            {"answer": "Underwriter briefing text.", "confidence": 0.9}
        )
        return _FakeResponse({"choices": [{"message": {"content": content}}]})


def test_briefing_context_includes_statistics_curve_and_top_losses():
    packet = build_briefing_context(_job())
    stats = packet["statistics"]
    assert stats["total_gross_claim"] == 1000.0
    assert stats["reinsurer_payout"] == 400.0
    assert stats["expected_annual_loss"] == 250.0
    assert stats["treaty"]["label"] == "$100M xs $40M"
    assert stats["tvar_pml"]["location_var_99"] == 900.0
    assert [point["return_period"] for point in packet["ep_curve"]["curve"]] == [
        10,
        100,
        500,
    ]
    losses = packet["largest_losses"]
    assert [row["asset_id"] for row in losses] == ["N-002", "N-003", "N-001"]
    assert losses[0]["loss"] == 90.0
    assert losses[1]["loss"] == 55.0


def test_briefing_fallback_without_keys(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    result = brief_job(_job(), _settings())
    assert result["source"] == "local-briefing"
    briefing = result["briefing"]
    assert "EVT-BRIEF-1" in briefing
    assert "$1,000" in briefing
    assert "$250" in briefing
    assert "500-year" in briefing
    assert "N-002" in briefing


def test_briefing_uses_openrouter(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    client = _OpenRouterClient()
    monkeypatch.setattr("catmod.nlp.gemini_rag.httpx.Client", lambda **kwargs: client)
    result = brief_job(_job(), _settings(openrouter_api_key="or-present"))
    assert result["source"] == "openrouter:openai/gpt-4.1-nano"
    assert result["briefing"] == "Underwriter briefing text."
    assert any("openrouter.ai" in url for url in client.calls)


def test_briefing_endpoint_reads_modeled_job(tmp_path, monkeypatch):
    import catmod.api as api
    from catmod.jobs import JobStore

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    settings = _settings(
        jobs_dir=str(tmp_path / "jobs"),
        jobs_keep=4,
        audit_dir=str(tmp_path / "audit"),
    )
    monkeypatch.setattr(api, "get_settings", lambda: settings)
    store = JobStore(settings.jobs_dir, settings.jobs_keep)
    store.remember(_job())
    monkeypatch.setattr(api, "_STORE", store)
    client = TestClient(api.app)
    response = client.post(
        "/api/v1/nlp/briefing",
        json={"event_id": "EVT-BRIEF-1"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "local-briefing"
    assert body["briefing"]
    assert body["statistics"]["reinsurer_payout"] == 400.0
    assert len(body["ep_curve"]["curve"]) == 3
    assert [row["asset_id"] for row in body["largest_losses"]] == [
        "N-002",
        "N-003",
        "N-001",
    ]
    audit = (tmp_path / "audit" / "EVT-BRIEF-1.jsonl").read_text(encoding="utf-8")
    assert "nlp_risk_briefing" in audit


def test_briefing_endpoint_404_without_jobs(tmp_path, monkeypatch):
    import catmod.api as api
    from catmod.jobs import JobStore

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    settings = _settings(
        jobs_dir=str(tmp_path / "jobs"),
        jobs_keep=4,
        audit_dir=str(tmp_path / "audit"),
    )
    monkeypatch.setattr(api, "get_settings", lambda: settings)
    monkeypatch.setattr(api, "_STORE", JobStore(settings.jobs_dir, settings.jobs_keep))
    client = TestClient(api.app)
    response = client.post("/api/v1/nlp/briefing", json={})
    assert response.status_code == 404
