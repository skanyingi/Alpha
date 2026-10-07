"""Python backend core.

Template primitives (FHRR algebra, XL waterfall, Leaflet GeoJSON) plus the FastAPI app.

Run:
    pip install -r requirements.txt
    uvicorn main:app --reload --port 8000

Webhook (Google Apps Script):
    POST /v1/process-bordereau
Leaflet:
    GET  /api/v1/leaflet-export
"""

from __future__ import annotations

from typing import Any

from catmod.api import app
from catmod.finance.treaty import XLTreaty
from catmod.finance.waterfall import calculate_reinsurance_waterfall
from catmod.hdc.fhrr import DIM, bind, bundle, exponentiate, random_hypervector
from catmod.leaflet.geojson import generate_leaflet_geojson

__all__ = [
    "app",
    "DIM",
    "random_hypervector",
    "bind",
    "bundle",
    "exponentiate",
    "XLTreaty",
    "calculate_reinsurance_waterfall",
    "generate_leaflet_geojson",
]


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
