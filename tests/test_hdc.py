import numpy as np

from catmod.hdc.encoding import ItemMemory
from catmod.hdc.fhrr import bind, exponentiate, random_hypervector, similarity, unbind
from catmod.hdc.memory import PortfolioMemory


def test_bind_unbind_roundtrip():
    rng = np.random.default_rng(0)
    a = random_hypervector(512, rng)
    b = random_hypervector(512, rng)
    recovered = unbind(bind(a, b), b)
    assert similarity(recovered, a) > 0.99


def test_continuous_exponent_recovers_nearby_scalars():
    rng = np.random.default_rng(1)
    basis = random_hypervector(2048, rng)
    v1 = exponentiate(basis, 0.40)
    v2 = exponentiate(basis, 0.41)
    v_far = exponentiate(basis, 0.90)
    assert similarity(v1, v2) > similarity(v1, v_far)


def test_temporal_projection_is_bind_with_phase_power():
    items = ItemMemory(dim=1024, seed=7)
    mem = PortfolioMemory(items)
    mem.encode_and_add(
        latitude=25.76,
        longitude=-80.19,
        elevation=3,
        time_t=0.0,
        cost=1_000_000,
        occupancy="COM_WHSE",
    )
    shifted = mem.project_time(0.01)
    assert shifted.shape == mem.memory.shape
    assert np.isfinite(shifted.real).all()


def test_portfolio_superposition_and_cluster_probe():
    items = ItemMemory(dim=2048, seed=3)
    mem = PortfolioMemory(items)
    for i in range(6):
        mem.encode_and_add(
            latitude=25.76 + i * 0.001,
            longitude=-80.19,
            elevation=2,
            time_t=0.1,
            cost=2_000_000,
            occupancy="COM_WHSE",
        )
    near = mem.interpolation_score(25.762, -80.19)
    far = mem.interpolation_score(51.5, -0.12)
    assert near > far
    clusters = mem.exposure_clusters((25.75, 25.78), (-80.21, -80.17), steps=6)
    assert clusters[0]["exposure_score"] >= clusters[-1]["exposure_score"]
