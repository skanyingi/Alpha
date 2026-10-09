import json as jsonlib

import httpx
from fastapi.testclient import TestClient

from catmod.config import Settings
from catmod.nlp.gemini_rag import (
    build_dataset_context,
    parse_csv_text,
    query_dataset_rag,
    summarize_dataset,
)


NAIROBI = """asset_id,policy_id,latitude,longitude,elevation,occupancy,tiv,ground_up_loss,deductible,policy_limit,coinsurance,loss_date
N-001,KN-100,-1.2921,36.8219,1660,informal iron sheet,2500000,0,50000,2500000,1.0,2026-04-12
N-002,KN-101,-1.2864,36.8290,1685,permanent masonry,8000000,0,100000,8000000,1.0,2026-04-12
N-003,KN-102,-1.2755,36.8148,1705,concrete rcc,15000000,0,250000,15000000,1.0,2026-04-12
N-004,KN-103,-1.3012,36.7890,1680,mabati,900000,0,20000,900000,1.0,2026-04-12
"""


def _settings() -> Settings:
    return Settings.model_construct(gemini_api_key="", gemini_model="gemini-2.0-flash")


def _context() -> dict:
    rows = parse_csv_text(NAIROBI)
    return build_dataset_context(rows, name="uploaded.csv")


def test_keyword_fallback_finds_informal_iron_sheet():
    result = query_dataset_rag(
        "Which properties are informal iron sheet in Nairobi?",
        _context(),
        _settings(),
    )
    assert result["matched_asset_ids"] == ["N-001"]
    assert "N-001" in result["answer"]
    assert result["source"] == "local-keyword"
    assert 0.0 <= result["confidence"] <= 1.0
    assert "allocated_reinsurer_payout" not in result["summary_stats"]
    assert result["summary_stats"]["total_tiv"] == 2_500_000


def test_starter_kit_columns_and_greeting():
    text = (
        "loc_id,lat,lon,housing_class,tiv_kes\n"
        "NBO-0000,-1.314897,36.935883,semi_permanent,5170000\n"
        "NBO-0001,-1.286,36.82,informal_iron_sheet,900000\n"
    )
    context = build_dataset_context(
        parse_csv_text(text), name="exposure_nairobi_synthetic.csv"
    )
    summary = query_dataset_rag("hello", context, _settings())
    assert summary["source"] == "local-keyword"
    assert "2 rows" in summary["answer"]
    assert "6,070,000.00 Kenyan shillings" in summary["answer"]
    assert "semi_permanent" in summary["answer"]
    assert "NBO-0000" in summary["answer"]
    assert "No rows" not in summary["answer"]


def test_blank_gemini_key_does_not_call_network(monkeypatch):
    def explode(*_args, **_kwargs):
        raise AssertionError("Gemini should not be called without a key")

    monkeypatch.setattr("catmod.nlp.gemini_rag.httpx.Client", explode)
    result = query_dataset_rag("Summarize the total TIV", _context(), _settings())
    assert result["source"] == "local-keyword"
    assert result["summary_stats"]["total_tiv"] == 26_400_000
    assert result["answer"]


def test_gemini_failure_falls_back(monkeypatch):
    class Broken:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def post(self, *_args, **_kwargs):
            raise RuntimeError("upstream down")

    monkeypatch.setattr(
        "catmod.nlp.gemini_rag.httpx.Client", lambda timeout=45.0: Broken()
    )
    settings = Settings.model_construct(
        gemini_api_key="present", gemini_model="gemini-2.0-flash"
    )
    result = query_dataset_rag(
        "Which properties are informal iron sheet in Nairobi?",
        _context(),
        settings,
    )
    assert result["matched_asset_ids"] == ["N-001"]
    assert result["source"] == "local-keyword"


def test_nlp_endpoint_reads_uploaded_csv(tmp_path, monkeypatch):
    import catmod.api as api

    settings = Settings.model_construct(
        gemini_api_key="",
        gemini_model="gemini-2.0-flash",
        jobs_dir=str(tmp_path / "jobs"),
        jobs_keep=4,
        audit_dir=str(tmp_path / "audit"),
    )
    monkeypatch.setattr(api, "get_settings", lambda: settings)
    api._STORE = None
    client = TestClient(api.app)
    response = client.post(
        "/api/v1/nlp/query",
        json={
            "query": "Which properties are informal iron sheet in Nairobi?",
            "csv_text": NAIROBI,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert "N-001" in body["matched_asset_ids"]
    assert body["tab"] == "answer"
    assert "reinsurer_payout" not in body
    audit = (tmp_path / "audit" / "NLP-SESSION.jsonl").read_text(encoding="utf-8")
    assert body["dataset_name"] == "uploaded-session.csv"
    assert "gemini_nlp_rag_queried" in audit


def test_nlp_endpoint_refuses_without_an_upload(tmp_path, monkeypatch):
    import catmod.api as api

    settings = Settings.model_construct(
        gemini_api_key="",
        gemini_model="gemini-2.0-flash",
        jobs_dir=str(tmp_path / "jobs"),
        jobs_keep=4,
        audit_dir=str(tmp_path / "audit"),
    )
    monkeypatch.setattr(api, "get_settings", lambda: settings)
    api._STORE = None
    client = TestClient(api.app)
    response = client.post(
        "/api/v1/nlp/query",
        json={"query": "Which properties are informal iron sheet in Nairobi?"},
    )
    assert response.status_code == 400
    assert "Upload" in response.json()["detail"]


def test_summary_uses_gemini_nlp_not_jev(monkeypatch):
    def explode(*_args, **_kwargs):
        raise AssertionError("Gemini should not be called without a key")

    monkeypatch.setattr("catmod.nlp.gemini_rag.httpx.Client", explode)
    result = summarize_dataset(_context(), _settings())
    assert result["source"] == "local-keyword"
    assert "rows" in result["answer"].lower()
    assert "jev" not in result["source"]


def test_summary_endpoint_reads_uploaded_csv(tmp_path, monkeypatch):
    import catmod.api as api

    settings = Settings.model_construct(
        gemini_api_key="",
        gemini_model="gemini-2.0-flash",
        jobs_dir=str(tmp_path / "jobs"),
        jobs_keep=4,
        audit_dir=str(tmp_path / "audit"),
    )
    monkeypatch.setattr(api, "get_settings", lambda: settings)
    api._STORE = None
    client = TestClient(api.app)
    response = client.post("/api/v1/nlp/summary", json={"csv_text": NAIROBI})
    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "local-keyword"
    assert "rows" in body["answer"].lower()
    assert body["dataset_name"] == "uploaded-session.csv"


class _FakeResponse:
    def __init__(self, body):
        self._body = body
        self.status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return self._body


class _FakeClient:
    """Answers both Gemini and OpenRouter shapes, recording every URL."""

    def __init__(self, calls, answer="Both providers answer.", matched=None):
        self._calls = calls
        self._answer = answer
        self._matched = matched or ["N-001"]

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def _content(self):
        return jsonlib.dumps(
            {
                "answer": self._answer,
                "matched_asset_ids": self._matched,
                "summary_stats": {"row_count": 4},
                "confidence": 0.8,
            }
        )

    def post(self, url, params=None, headers=None, json=None):
        self._calls.append({"url": url, "headers": headers or {}})
        if "openrouter" in url:
            return _FakeResponse(
                {"choices": [{"message": {"content": self._content()}}]}
            )
        return _FakeResponse(
            {"candidates": [{"content": {"parts": [{"text": self._content()}]}}]}
        )


class _BrokenClient:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def post(self, *_args, **_kwargs):
        raise RuntimeError("upstream down")


class _OpenRouterDownClient:
    """OpenRouter returns 429 on every model; Gemini answers."""

    def __init__(self, calls):
        self._calls = calls

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def post(self, url, params=None, headers=None, json=None):
        self._calls.append(url)
        if "openrouter" in url:
            request = httpx.Request("POST", url)
            raise httpx.HTTPStatusError(
                "429", request=request, response=httpx.Response(429, request=request)
            )
        content = jsonlib.dumps(
            {
                "answer": "Gemini covers the OpenRouter outage.",
                "matched_asset_ids": ["N-001"],
                "summary_stats": {"row_count": 4},
                "confidence": 0.9,
            }
        )
        return _FakeResponse(
            {"candidates": [{"content": {"parts": [{"text": content}]}}]}
        )


def test_gemini_covers_openrouter_failure(monkeypatch):
    calls = []
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(
        "catmod.nlp.gemini_rag.httpx.Client",
        lambda **kwargs: _OpenRouterDownClient(calls),
    )
    settings = Settings.model_construct(
        gemini_api_key="gem-present",
        gemini_model="gemini-2.0-flash",
        openrouter_api_key="or-present",
        openrouter_model="qwen/qwen3.8-flash",
        openrouter_base_url="https://openrouter.ai/api/v1",
        openrouter_timeout_s=45.0,
    )
    result = query_dataset_rag("tell me the risk of the data", _context(), settings)
    assert result["source"] == "gemini:gemini-2.0-flash"
    assert result["answer"] == "Gemini covers the OpenRouter outage."
    assert any("openrouter.ai" in url for url in calls)
    assert any("generativelanguage.googleapis.com" in url for url in calls)


def test_openrouter_used_when_gemini_key_absent(monkeypatch):
    calls = []
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(
        "catmod.nlp.gemini_rag.httpx.Client", lambda **kwargs: _FakeClient(calls)
    )
    settings = Settings.model_construct(
        gemini_api_key="",
        gemini_model="gemini-2.0-flash",
        openrouter_api_key="or-present",
        openrouter_model="qwen/qwen3.8-flash",
        openrouter_base_url="https://openrouter.ai/api/v1",
        openrouter_timeout_s=45.0,
    )
    result = query_dataset_rag(
        "Which properties are informal iron sheet in Nairobi?",
        _context(),
        settings,
    )
    assert result["source"] == "openrouter:qwen/qwen3.8-flash"
    assert result["matched_asset_ids"] == ["N-001"]
    assert result["answer"] == "Both providers answer."
    assert any("openrouter.ai/api/v1/chat/completions" in c["url"] for c in calls)
    assert calls[0]["headers"].get("Authorization") == "Bearer or-present"


def test_openrouter_primary_when_both_keys_set(monkeypatch):
    calls = []
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(
        "catmod.nlp.gemini_rag.httpx.Client", lambda **kwargs: _FakeClient(calls)
    )
    settings = Settings.model_construct(
        gemini_api_key="gem-present",
        gemini_model="gemini-2.0-flash",
        openrouter_api_key="or-present",
        openrouter_model="qwen/qwen3.8-flash",
        openrouter_base_url="https://openrouter.ai/api/v1",
        openrouter_timeout_s=45.0,
    )
    result = query_dataset_rag("Summarize the total TIV", _context(), settings)
    assert result["source"] == "openrouter:qwen/qwen3.8-flash"
    assert all("generativelanguage" not in c["url"] for c in calls)
    assert any("openrouter.ai" in c["url"] for c in calls)


def test_openrouter_failure_falls_back_to_local(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(
        "catmod.nlp.gemini_rag.httpx.Client", lambda **kwargs: _BrokenClient()
    )
    settings = Settings.model_construct(
        gemini_api_key="",
        gemini_model="gemini-2.0-flash",
        openrouter_api_key="or-present",
        openrouter_model="qwen/qwen3.8-flash",
        openrouter_base_url="https://openrouter.ai/api/v1",
        openrouter_timeout_s=45.0,
    )
    result = query_dataset_rag(
        "Which properties are informal iron sheet in Nairobi?",
        _context(),
        settings,
    )
    assert result["source"] == "local-keyword"
    assert result["matched_asset_ids"] == ["N-001"]


def test_blank_provider_keys_do_not_call_network(monkeypatch):
    def explode(*_args, **_kwargs):
        raise AssertionError("No provider should be called without a key")

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr("catmod.nlp.gemini_rag.httpx.Client", explode)
    settings = Settings.model_construct(
        gemini_api_key="",
        gemini_model="gemini-2.0-flash",
        openrouter_api_key="",
        openrouter_model="qwen/qwen3.8-flash",
        openrouter_base_url="https://openrouter.ai/api/v1",
        openrouter_timeout_s=45.0,
    )
    result = query_dataset_rag("Summarize the total TIV", _context(), settings)
    assert result["source"] == "local-keyword"


def test_openrouter_chain_reads_configured_fallbacks():
    from catmod.nlp.gemini_rag import _openrouter_chain

    settings = Settings.model_construct(
        openrouter_model="primary/model",
        openrouter_fallbacks="a/one, b/two ,, c/three",
    )
    chain = _openrouter_chain(settings)
    assert chain[:4] == ["primary/model", "a/one", "b/two", "c/three"]


class _OpenRouterFailoverClient:
    def __init__(self, calls):
        self._calls = calls

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def post(self, url, params=None, headers=None, json=None):
        model = (json or {}).get("model")
        self._calls.append(model)
        if model == "primary/model":
            request = httpx.Request("POST", url)
            raise httpx.HTTPStatusError(
                "429", request=request, response=httpx.Response(429, request=request)
            )
        content = jsonlib.dumps(
            {
                "answer": "The fallback model answered.",
                "matched_asset_ids": ["N-001"],
                "summary_stats": {"row_count": 4},
                "confidence": 0.9,
            }
        )
        return _FakeResponse({"choices": [{"message": {"content": content}}]})


def test_openrouter_failover_to_configured_model(monkeypatch):
    calls = []
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(
        "catmod.nlp.gemini_rag.httpx.Client",
        lambda **kwargs: _OpenRouterFailoverClient(calls),
    )
    settings = Settings.model_construct(
        gemini_api_key="",
        gemini_model="gemini-2.0-flash",
        openrouter_api_key="or-present",
        openrouter_model="primary/model",
        openrouter_fallbacks="fallback/model",
        openrouter_base_url="https://openrouter.ai/api/v1",
        openrouter_timeout_s=45.0,
    )
    result = query_dataset_rag("tell me the risk of the data", _context(), settings)
    assert result["source"] == "openrouter:fallback/model"
    assert result["answer"] == "The fallback model answered."
    assert calls == ["primary/model", "fallback/model"]
