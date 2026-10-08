from fastapi.testclient import TestClient

from catmod.config import Settings
from catmod.nlp.gemini_rag import build_dataset_context, parse_csv_text, query_dataset_rag


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
    return build_dataset_context(rows, name="sample_nairobi_bordereau.csv")


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

    monkeypatch.setattr("catmod.nlp.gemini_rag.httpx.Client", lambda timeout=45.0: Broken())
    settings = Settings.model_construct(gemini_api_key="present", gemini_model="gemini-2.0-flash")
    result = query_dataset_rag(
        "Which properties are informal iron sheet in Nairobi?",
        _context(),
        settings,
    )
    assert result["matched_asset_ids"] == ["N-001"]
    assert result["source"] == "local-keyword"


def test_nlp_endpoint_reads_named_dataset(tmp_path, monkeypatch):
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
            "dataset_name": "sample_nairobi_bordereau",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert "N-001" in body["matched_asset_ids"]
    assert body["tab"] == "answer"
    assert "reinsurer_payout" not in body
    audit = (tmp_path / "audit" / "NLP-SESSION.jsonl").read_text(encoding="utf-8")
    assert "gemini_nlp_rag_queried" in audit
