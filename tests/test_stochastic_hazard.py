"""Stochastic flood catalogs: rates, spatial kernel, and return-period order."""

from decimal import Decimal
from pathlib import Path

from catmod.hazard.service import STANDARD_RETURN_PERIODS
from catmod.hazard.stochastic import (
    StochasticHazardGenerator,
    gumbel_quantile,
    rbf_covariance,
)
import numpy as np


def test_event_rates_in_each_return_period_integrate_to_one_over_rp():
    events = StochasticHazardGenerator().generate_event_set("nairobi", num_events=18, seed=42)
    totals: dict[int, Decimal] = {period: Decimal("0") for period in STANDARD_RETURN_PERIODS}
    for event in events:
        assert event.synthetic is True
        assert event.stochastic is True
        assert event.peril == "flood_pluvial"
        totals[event.return_period] += event.rate
    for period, total in totals.items():
        assert total == Decimal(1) / Decimal(period)


def test_spatial_covariance_is_symmetric():
    lat = np.linspace(-1.40, -1.20, 6)
    lon = np.linspace(36.70, 36.95, 6)
    yy, xx = np.meshgrid(lat, lon, indexing="ij")
    kernel = rbf_covariance(yy, xx, 0.08)
    assert kernel.shape == (36, 36)
    assert np.allclose(kernel, kernel.T)
    assert np.all(np.linalg.eigvalsh(kernel) > 0)


def test_return_period_intensity_is_monotonic():
    periods = list(STANDARD_RETURN_PERIODS)
    quantiles = [gumbel_quantile(period, 0.30, 0.70) for period in periods]
    assert quantiles == sorted(quantiles)
    assert all(later > earlier for earlier, later in zip(quantiles, quantiles[1:]))

    events = StochasticHazardGenerator().generate_event_set("nzoia", num_events=120, seed=7)
    means: dict[int, list[float]] = {period: [] for period in periods}
    magnitudes: dict[int, Decimal] = {}
    for event in events:
        means[event.return_period].append(float(event.intensity_matrix.mean()))
        magnitudes[event.return_period] = event.magnitude_m
    ordered = [sum(means[period]) / len(means[period]) for period in periods]
    assert all(later > earlier for earlier, later in zip(ordered, ordered[1:]))
    assert all(magnitudes[later] >= magnitudes[earlier] for earlier, later in zip(periods, periods[1:]))


def test_footprints_use_decimal_depths_and_intensity_bins():
    generator = StochasticHazardGenerator()
    event = generator.generate_event_set("nairobi", num_events=6, seed=3)[-1]
    points = generator.get_footprint(event, [(-1.2921, 36.8219), (-1.2864, 36.8290)])
    assert len(points) == 2
    for point in points:
        assert point.synthetic is True
        assert point.stochastic is True
        assert point.depth_m == point.depth_m.quantize(Decimal("0.01"))
        assert Decimal("0") <= point.depth_m <= Decimal("10")
        assert 0 <= point.intensity_bin <= 8


def test_hazard_module_does_not_import_finance_or_vulnerability():
    source = Path("catmod/hazard/stochastic.py").read_text(encoding="utf-8")
    assert "catmod.finance" not in source
    assert "catmod.vulnerability" not in source
