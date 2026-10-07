"""Fourier Holographic Reduced Representations in complex vector space.

Operations:
  bind(a, b)        Hadamard product  (phase addition)     a ⊗ b
  unbind(a, b)      bind(a, conjugate(b))                  a ⊘ b
  bundle / superpose  superposition sum                    a ⊕ b
  exponentiate(h, x)  H = B^x  continuous scalar encoding
  similarity        mean real part of conj(a)*b
"""

from __future__ import annotations

from typing import Sequence

import numpy as np

Array = np.ndarray

DIM = 10_000


def _as_hv(h: Array) -> Array:
    return np.asarray(h, dtype=np.complex64)


def random_hypervector(dim: int = DIM, rng: np.random.Generator | None = None) -> Array:
    engine = rng if rng is not None else np.random.default_rng()
    angles = (2.0 * np.pi * engine.random(dim)).astype(np.float32)
    return np.exp(1j * angles).astype(np.complex64)


def identity(dim: int = DIM) -> Array:
    return np.ones(dim, dtype=np.complex64)


def bind(h1: Array, h2: Array) -> Array:
    return _as_hv(h1) * _as_hv(h2)


def unbind(h1: Array, h2: Array) -> Array:
    return _as_hv(h1) * np.conjugate(_as_hv(h2))


def bundle(h_list: Sequence[Array]) -> Array:
    stacked = np.stack([_as_hv(h) for h in h_list], axis=0)
    summed = np.sum(stacked, axis=0)
    mag = np.abs(summed)
    mag = np.where(mag == 0, 1.0, mag)
    return (summed / mag).astype(np.complex64)


def superpose(h_list: Sequence[Array]) -> Array:
    """Unnormalized sum. Preserves analog occupancy counts in portfolio memory."""
    stacked = np.stack([_as_hv(h) for h in h_list], axis=0)
    return np.sum(stacked, axis=0).astype(np.complex64)


def cleanup(h: Array) -> Array:
    mag = np.abs(_as_hv(h))
    mag = np.where(mag == 0, 1.0, mag)
    return (_as_hv(h) / mag).astype(np.complex64)


def exponentiate(h: Array, exponent: float) -> Array:
    """Continuous encoding H = B^x via phase scaling. No discrete bins."""
    phases = np.angle(_as_hv(h)) * float(exponent)
    return np.exp(1j * phases).astype(np.complex64)


def similarity(h1: Array, h2: Array) -> float:
    a = _as_hv(h1)
    b = _as_hv(h2)
    return float(np.real(np.mean(np.conjugate(a) * b)))


def permute(h: Array, shift: int = 1) -> Array:
    return np.roll(_as_hv(h), shift)


def decode_exponent(encoded: Array, basis: Array) -> float:
    """Recover scalar x from V ≈ B^x using phase ratios (circular-safe)."""
    theta = np.angle(_as_hv(basis))
    phi = np.angle(_as_hv(encoded))
    mask = np.abs(theta) > 0.25
    if not np.any(mask):
        return 0.0
    ratios = phi[mask] / theta[mask]
    return float(np.median(ratios))
