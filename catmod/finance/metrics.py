"""TVaR and PML from an auditable empirical loss sample. No model approximation."""

from __future__ import annotations

from typing import Sequence

import numpy as np


def _sorted(losses: Sequence[float]) -> np.ndarray:
    arr = np.asarray(list(losses), dtype=np.float64)
    if arr.size == 0:
        return arr
    arr = np.sort(arr)
    return arr


def var(losses: Sequence[float], alpha: float = 0.99) -> float:
    arr = _sorted(losses)
    if arr.size == 0:
        return 0.0
    return float(np.quantile(arr, alpha, method="linear"))


def tvar(losses: Sequence[float], alpha: float = 0.99) -> float:
    """Tail Value-at-Risk: E[L | L >= VaR_alpha]."""
    arr = _sorted(losses)
    if arr.size == 0:
        return 0.0
    threshold = var(arr, alpha)
    tail = arr[arr >= threshold]
    if tail.size == 0:
        return float(threshold)
    return float(np.mean(tail))


def pml(losses: Sequence[float], return_period: float = 100.0) -> float:
    """Occurrence PML as the empirical quantile at 1 - 1/RP.

    For a single-event portfolio this equals the event aggregate when
    `losses` is a one-element catalog; pass a catalog of event totals
    for a true OEP PML.
    """
    if return_period <= 1:
        raise ValueError("return_period must be > 1")
    alpha = 1.0 - 1.0 / return_period
    return var(losses, alpha)


def portfolio_tail_metrics(
    per_policy_covered: Sequence[float],
    event_total: float,
    catalog_event_losses: Sequence[float] | None = None,
) -> dict[str, float]:
    loc = list(per_policy_covered)
    catalog = list(catalog_event_losses) if catalog_event_losses else [event_total]
    return {
        "event_occurrence_loss": float(event_total),
        "location_var_95": var(loc, 0.95) if loc else 0.0,
        "location_tvar_95": tvar(loc, 0.95) if loc else 0.0,
        "location_var_99": var(loc, 0.99) if loc else 0.0,
        "location_tvar_99": tvar(loc, 0.99) if loc else 0.0,
        "pml_100": pml(catalog, 100.0),
        "pml_250": pml(catalog, 250.0),
        "tvar_99_event_catalog": tvar(catalog, 0.99),
    }
