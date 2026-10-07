"""Flood exposure & asset vulnerability — sidecar layer.

Does not participate in XL payout math. Jev occupancy and finance remain authoritative
for treaty calculations; this layer only annotates maps and underwriting popups.
"""

from catmod.flood.service import evaluate_asset, footprints_for_points, hazard_collection

__all__ = ["evaluate_asset", "footprints_for_points", "hazard_collection"]
