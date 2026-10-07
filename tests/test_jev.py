import time

from catmod.jev.occupancy import classify_occupancy
from catmod.jev.harness import JevHarness, local_triage
from catmod.schemas import RawClaim


def test_occupancy_aliases_warehouse_family():
    for raw in ("whse", "steel-shed", "storage", "WHSE / Distro Center"):
        ans = classify_occupancy(raw)
        assert ans.choice == "COM_WHSE", raw
        assert ans.confidence > 0.5


def test_occupancy_office_and_sfd():
    assert classify_occupancy("office tower").choice == "COM_OFF"
    assert classify_occupancy("sfd").choice == "RES_SF"


def test_clean_warehouse_routes_to_finance():
    claim = RawClaim(
        asset_id="A-1",
        latitude=-1.2921,
        longitude=36.8219,
        occupancy_raw="whse",
        tiv=5_000_000,
        ground_up_loss=1_000_000,
        deductible=100_000,
        policy_limit=5_000_000,
    )
    triage = local_triage(claim, 0.95)
    assert triage.standardized_occupancy == "COM_WHSE"
    assert triage.route == "finance"
    assert triage.occupancy.confidence > 0.95


def test_null_island_routes_to_hdc():
    claim = RawClaim(
        asset_id="A-bad",
        latitude=0.0,
        longitude=0.0,
        occupancy_raw="res",
        tiv=1_000_000,
        ground_up_loss=950_000,
    )
    triage = local_triage(claim, 0.95)
    assert triage.route == "hdc_physics"
    assert triage.fraud_or_discrepancy.noul > 0.9


def test_batch_under_500ms():
    claims = [
        RawClaim(
            asset_id=f"A-{i}",
            latitude=-1.2921 + i * 0.001,
            longitude=36.8219,
            occupancy_raw=raw,
            tiv=1_000_000,
            ground_up_loss=100_000,
        )
        for i, raw in enumerate(["whse", "storage", "sfd", "office", "steel-shed"] * 40)
    ]
    harness = JevHarness()
    t0 = time.perf_counter()
    results = harness.triage_batch(claims)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    assert len(results) == 200
    assert elapsed_ms < 500, elapsed_ms
