"""Exceedance probabilities fall as the return period rises."""

from decimal import Decimal
import inspect

from catmod.analytics.ep_curve import build_ep_curve, portfolio_ep_curve


def test_exceedance_probability_strictly_decreases_with_return_period():
    curve = build_ep_curve(
        {
            10: Decimal("1000000"),
            25: Decimal("1800000"),
            50: Decimal("2600000"),
            100: Decimal("3400000"),
            250: Decimal("4100000"),
            500: Decimal("4800000"),
        }
    )
    points = curve["curve"]
    periods = [point["return_period"] for point in points]
    probabilities = [Decimal(point["exceedance_probability"]) for point in points]
    losses = [Decimal(point["loss"]) for point in points]
    assert periods == sorted(periods)
    assert all(earlier > later for earlier, later in zip(probabilities, probabilities[1:]))
    assert all(later >= earlier for earlier, later in zip(losses, losses[1:]))
    assert curve["synthetic"] is True
    assert curve["monotonic_exceedance"] is True
    assert all(point["synthetic"] is True for point in points)


def test_eal_trapezoid_for_a_single_scenario():
    # From P=1, L=0 to P=0.1, L=100, then flat to P=0: 45 + 10 = 55.
    curve = build_ep_curve({10: Decimal("100")})
    assert curve["eal"] == "55.00"
    assert Decimal(curve["tvar"]["0.99"]) >= Decimal(curve["pml"]["10"])


def test_tvar_is_at_least_pml_at_the_same_tail():
    curve = build_ep_curve(
        {
            10: Decimal("100"),
            25: Decimal("250"),
            50: Decimal("400"),
            100: Decimal("700"),
            250: Decimal("900"),
            500: Decimal("1200"),
        }
    )
    assert Decimal(curve["tvar"]["0.99"]) >= Decimal(curve["pml"]["100"])
    assert Decimal(curve["tvar"]["0.995"]) >= Decimal(curve["pml"]["250"])
    assert Decimal(curve["eal"]) > 0
    assert Decimal(curve["eal"]) < Decimal(curve["pml"]["500"])


def test_decreasing_catalog_is_rejected():
    try:
        build_ep_curve({10: Decimal("500"), 100: Decimal("100")})
    except ValueError as exc:
        assert "non-decreasing" in str(exc)
    else:
        raise AssertionError("expected a non-decreasing catalog")


def test_portfolio_ep_curve_is_synthetic_and_monotone():
    curve = portfolio_ep_curve(
        [
            {
                "latitude": 25.77,
                "longitude": -80.19,
                "tiv": 1_000_000,
                "occupancy": "RES_SF",
            },
            {
                "latitude": -1.2921,
                "longitude": 36.8219,
                "tiv": 2_000_000,
                "occupancy": "informal_iron_sheet",
            },
        ]
    )
    probabilities = [Decimal(point["exceedance_probability"]) for point in curve["curve"]]
    losses = [Decimal(point["loss"]) for point in curve["curve"]]
    assert all(earlier > later for earlier, later in zip(probabilities, probabilities[1:]))
    assert all(later >= earlier for earlier, later in zip(losses, losses[1:]))
    assert curve["synthetic"] is True
    assert Decimal(curve["eal"]) > 0
    assert losses[-1] > losses[0]


def test_ep_module_does_not_import_vectors_or_ml():
    import catmod.analytics.ep_curve as ep
    import catmod.finance.waterfall as waterfall

    for module in (ep, waterfall):
        source = inspect.getsource(module)
        assert "torch" not in source
        assert "hdc" not in source
        assert "numpy" not in source
