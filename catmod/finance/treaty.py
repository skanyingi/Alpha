"""Deterministic Excess-of-Loss treaty terms. No ML in this module."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


def _decimal(value: Decimal | float | str | int) -> Decimal:
    return Decimal(str(value))


@dataclass(frozen=True, slots=True)
class XLTreaty:
    attachment_point: Decimal
    limit: Decimal
    co_participation: Decimal
    reinstatement_cost: Decimal
    reinstatements: int = 1
    original_premium: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        attachment = _decimal(self.attachment_point)
        limit = _decimal(self.limit)
        share = _decimal(self.co_participation)
        reinstatement = _decimal(self.reinstatement_cost)
        premium = _decimal(self.original_premium)
        object.__setattr__(self, "attachment_point", attachment)
        object.__setattr__(self, "limit", limit)
        object.__setattr__(self, "co_participation", share)
        object.__setattr__(self, "reinstatement_cost", reinstatement)
        object.__setattr__(self, "original_premium", premium)
        if attachment < 0:
            raise ValueError("attachment_point must be >= 0")
        if limit <= 0:
            raise ValueError("limit must be > 0")
        if not Decimal("0") <= share <= Decimal("1"):
            raise ValueError("co_participation must be in [0, 1]")
        if reinstatement < 0:
            raise ValueError("reinstatement_cost must be >= 0")
        if self.reinstatements < 0:
            raise ValueError("reinstatements must be >= 0")

    @property
    def layer_label(self) -> str:
        xs = self.attachment_point
        lim = self.limit
        share = self.co_participation * Decimal("100")
        return f"${lim:,.0f} xs ${xs:,.0f} ({share:.0f}% share)"
