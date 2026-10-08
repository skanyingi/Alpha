from decimal import Decimal

from catmod.finance import XLTreaty, calculate_reinsurance_waterfall, ground_up_to_covered, pml, tvar


def test_primary_terms_deductible_limit_coinsurance():
    # min(GUL, limit) - deductible, then coinsurance: (min(5M, 3M) - 1M) * 0.9 = 1.8M
    covered = ground_up_to_covered(5_000_000, 1_000_000, 3_000_000, 0.90)
    assert float(covered) == 1_800_000.00


def test_below_attachment_no_reinsurer_payout():
    treaty = XLTreaty(40_000_000, 100_000_000, 0.90, 1.0, 1, 5_000_000)
    out = calculate_reinsurance_waterfall([10_000_000], [0], [20_000_000], treaty)
    assert out["total_gross_claim"] == 10_000_000
    assert out["reinsurer_payout"] == 0.0
    assert out["cedant_retained_loss"] == 10_000_000
    assert out["reinstatement_premium_due"] == 0.0


def test_xl_100m_xs_40m_90_percent_share():
    treaty = XLTreaty(
        attachment_point=40_000_000,
        limit=100_000_000,
        co_participation=0.90,
        reinstatement_cost=1.0,
        reinstatements=1,
        original_premium=5_000_000,
    )
    # Covered: min(50M,100M)-1M = 49M ; min(30M,25M)-0.5M = 24.5M ; total 73.5M
    out = calculate_reinsurance_waterfall(
        [50_000_000, 30_000_000],
        [1_000_000, 500_000],
        [100_000_000, 25_000_000],
        treaty,
    )
    assert out["total_gross_claim"] == 73_500_000.00
    assert out["layer_loss"] == 33_500_000.00
    assert out["reinsurer_payout"] == 30_150_000.00
    assert out["cedant_retained_loss"] == 43_350_000.00
    assert out["reinstatement_premium_due"] == 1_675_000.00


def test_layer_exhaustion_caps_reinstatement_at_purchased_count():
    treaty = XLTreaty(10_000_000, 5_000_000, 1.0, 1.0, 1, 2_000_000)
    out = calculate_reinsurance_waterfall([20_000_000], [0], [0], treaty)
    assert out["layer_loss"] == 5_000_000
    assert out["exhaustion_ratio"] == 1.0
    assert out["reinstatement_premium_due"] == 2_000_000.00


def test_policy_allocations_sum_to_the_contractual_totals():
    treaty = XLTreaty(10, 1_000, Decimal("0.33"), 1, 1, 0)
    out = calculate_reinsurance_waterfall(
        [100.004, 200.006, 50.002],
        [0, 0, 0],
        [0, 0, 0],
        treaty,
    )
    assert sum(out["allocated_reinsurer_payout"], Decimal("0")) == out["reinsurer_payout"]
    assert sum(out["allocated_cedant_retention"], Decimal("0")) == out["cedant_retained_loss"]
    assert isinstance(out["total_gross_claim"], Decimal)


def test_finance_does_not_import_ml_layers():
    import catmod.finance.waterfall as wf
    import inspect

    source = inspect.getsource(wf)
    assert "torch" not in source
    assert "hdc" not in source
    assert "jev" not in source


def test_tvar_is_mean_of_tail():
    losses = [1, 2, 3, 4, 100]
    value = tvar(losses, 0.80)
    assert value >= 4
    assert pml([10, 20, 30, 40, 50], 5) >= 40
