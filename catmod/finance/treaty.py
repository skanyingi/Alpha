"""Deterministic Excess-of-Loss treaty terms. No ML in this module."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class XLTreaty:
    attachment_point: float
    limit: float
    co_participation: float
    reinstatement_cost: float
    reinstatements: int = 1
    original_premium: float = 0.0

    def __post_init__(self) -> None:
        if self.attachment_point < 0:
            raise ValueError("attachment_point must be >= 0")
        if self.limit <= 0:
            raise ValueError("limit must be > 0")
        if not 0.0 <= self.co_participation <= 1.0:
            raise ValueError("co_participation must be in [0, 1]")
        if self.reinstatement_cost < 0:
            raise ValueError("reinstatement_cost must be >= 0")
        if self.reinstatements < 0:
            raise ValueError("reinstatements must be >= 0")

    @property
    def layer_label(self) -> str:
        xs = self.attachment_point
        lim = self.limit
        share = self.co_participation * 100.0
        return f"KSh {lim:,.0f} xs KSh {xs:,.0f} ({share:.0f}% share)"
