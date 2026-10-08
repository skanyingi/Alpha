from fastapi.testclient import TestClient

from catmod.jobs import JobStore


def _job(event_id: str, gross: float = 10.0) -> dict:
    return {
        "event_id": event_id,
        "client_index_id": "desk",
        "total_gross_claim": gross,
        "reinsurer_payout": 1.0,
        "flagged_count": 0,
        "claims": [],
        "geojson": {"type": "FeatureCollection", "features": []},
        "audit": {"event_id": event_id, "entries": []},
    }


def test_jobs_reload_from_disk(tmp_path):
    first = JobStore(tmp_path, keep=4)
    first.remember(_job("EVT-ONE", 12))
    first.remember(_job("EVT-TWO", 20))

    second = JobStore(tmp_path, keep=4)
    assert [job["event_id"] for job in second.values()] == ["EVT-ONE", "EVT-TWO"]
    assert second.get("EVT-TWO")["total_gross_claim"] == 20
    assert second.latest()["event_id"] == "EVT-TWO"


def test_jobs_keep_drops_oldest_file(tmp_path):
    store = JobStore(tmp_path, keep=1)
    store.remember(_job("EVT-OLD"))
    store.remember(_job("EVT-NEW"))
    assert list(tmp_path.glob("*.json")) == [tmp_path / "EVT-NEW.json"]

    reloaded = JobStore(tmp_path, keep=1)
    assert reloaded.get("EVT-OLD") is None
    assert reloaded.get("EVT-NEW")["event_id"] == "EVT-NEW"


def test_events_endpoint_reads_saved_jobs(tmp_path, monkeypatch):
    import catmod.api as api
    from catmod.config import get_settings

    monkeypatch.setenv("CATMOD_JOBS_DIR", str(tmp_path))
    get_settings.cache_clear()
    previous = api._STORE
    api._STORE = None
    try:
        api.job_store().remember(_job("EVT-KEEP", 42))
        api._STORE = None
        client = TestClient(api.app)
        body = client.get("/api/v1/events").json()
        assert body["events"][0]["event_id"] == "EVT-KEEP"
        assert body["events"][0]["total_gross_claim"] == 42
        audit = client.get("/api/v1/audit/EVT-KEEP")
        assert audit.status_code == 200
        assert audit.json()["event_id"] == "EVT-KEEP"
    finally:
        api._STORE = previous
        get_settings.cache_clear()
