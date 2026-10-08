"""Gemini multimodal extraction of occupancy, storeys, materials, and FFE cues."""

from __future__ import annotations

import base64
import json
import re
from typing import Any

import httpx

from catmod.config import Settings, get_settings

GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

EXTRACTION_PROMPT = """You are a catastrophe-risk surveyor inspecting ONE building for flood vulnerability.
You may receive a nadir satellite/aerial image, a street-level facade photo, and optional text context.

Return a single JSON object with EXACTLY these keys:
- occupancy_type: one of "Residential", "Commercial", "Industrial", "Agricultural", "Mixed", "Unknown"
- estimated_storeys: integer from 1 to 60
- roof_wall_material: one of "Reinforced Concrete", "Masonry", "Corrugated Metal", "Timber", "Steel", "Unknown"
- ground_clearance_elevation: one of "Ground level", "Raised steps", "Stilts/Piles", "Unknown"
- vulnerability_score: integer 1-10 where 10 is most vulnerable to coastal or riverine flood
- justification: one or two plain-English sentences citing visual evidence

Rules:
- Prefer industrial/warehouse cues (loading docks, metal roofs, large floorplates) when visible.
- Raised plinths, stairs, or piles reduce vulnerability; slab-on-grade at grade increases it.
- Do not invent a street address.
- If an image is missing, blurry, or a placeholder, still fill every field and say so in justification.
"""

FALLBACK: dict[str, Any] = {
    "occupancy_type": "Unknown",
    "estimated_storeys": 1,
    "roof_wall_material": "Unknown",
    "ground_clearance_elevation": "Unknown",
    "vulnerability_score": 5,
    "justification": "Image analysis was unavailable; heuristic defaults were applied.",
    "source": "fallback",
}

_ALLOWED_OCC = {
    "residential": "Residential",
    "commercial": "Commercial",
    "industrial": "Industrial",
    "agricultural": "Agricultural",
    "mixed": "Mixed",
    "unknown": "Unknown",
}
_ALLOWED_MAT = {
    "reinforced concrete": "Reinforced Concrete",
    "masonry": "Masonry",
    "corrugated metal": "Corrugated Metal",
    "timber": "Timber",
    "steel": "Steel",
    "unknown": "Unknown",
}
_ALLOWED_FFE = {
    "ground level": "Ground level",
    "raised steps": "Raised steps",
    "stilts/piles": "Stilts/Piles",
    "stilts": "Stilts/Piles",
    "piles": "Stilts/Piles",
    "unknown": "Unknown",
}


def gemini_configured(settings: Settings | None = None) -> bool:
    settings = settings or get_settings()
    return bool((settings.gemini_api_key or "").strip())


def _coerce(raw: dict[str, Any], source: str) -> dict[str, Any]:
    occ = str(raw.get("occupancy_type") or "Unknown")
    occ = _ALLOWED_OCC.get(occ.strip().lower(), "Unknown")
    mat = str(raw.get("roof_wall_material") or "Unknown")
    mat = _ALLOWED_MAT.get(mat.strip().lower(), "Unknown")
    ffe = str(raw.get("ground_clearance_elevation") or "Unknown")
    ffe_key = ffe.strip().lower()
    ffe = _ALLOWED_FFE.get(ffe_key, "Unknown")
    try:
        storeys = int(raw.get("estimated_storeys") or 1)
    except (TypeError, ValueError):
        storeys = 1
    storeys = max(1, min(60, storeys))
    try:
        score = int(round(float(raw.get("vulnerability_score") or 5)))
    except (TypeError, ValueError):
        score = 5
    score = max(1, min(10, score))
    justification = str(raw.get("justification") or FALLBACK["justification"]).strip()
    return {
        "occupancy_type": occ,
        "estimated_storeys": storeys,
        "roof_wall_material": mat,
        "ground_clearance_elevation": ffe,
        "vulnerability_score": score,
        "justification": justification[:600],
        "source": source,
    }


def _parse_json_blob(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.S)
    if fence:
        cleaned = fence.group(1)
    else:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start >= 0 and end > start:
            cleaned = cleaned[start : end + 1]
    return json.loads(cleaned)


def extract_vulnerability(
    *,
    aerial_bytes: bytes | None = None,
    aerial_mime: str = "image/jpeg",
    street_bytes: bytes | None = None,
    street_mime: str = "image/jpeg",
    context: str = "",
    settings: Settings | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    if not gemini_configured(settings):
        out = dict(FALLBACK)
        if context:
            out["justification"] = (
                "GEMINI_API_KEY is not configured; defaults applied. " + context[:240]
            )
        return out

    parts: list[dict[str, Any]] = [{"text": EXTRACTION_PROMPT}]
    if context:
        parts.append({"text": f"Context from the portfolio / geocoder:\n{context[:1500]}"})
    if aerial_bytes:
        parts.append(
            {
                "inlineData": {
                    "mimeType": aerial_mime or "image/jpeg",
                    "data": base64.b64encode(aerial_bytes).decode("ascii"),
                }
            }
        )
        parts.append({"text": "The previous image is a zoom-19 satellite/aerial view of the building."})
    if street_bytes:
        parts.append(
            {
                "inlineData": {
                    "mimeType": street_mime or "image/jpeg",
                    "data": base64.b64encode(street_bytes).decode("ascii"),
                }
            }
        )
        parts.append({"text": "The previous image is a Street View facade of the same building."})
    if not aerial_bytes and not street_bytes:
        parts.append({"text": "No photographs were available. Infer only from the text context."})

    model = (settings.gemini_model or "gemini-3.8-flash").strip()
    url = GEMINI_ENDPOINT.format(model=model)
    payload = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            "temperature": 0.1,
            "responseMimeType": "application/json",
        },
    }
    try:
        with httpx.Client(timeout=45.0) as client:
            response = client.post(
                url,
                params={"key": settings.gemini_api_key},
                json=payload,
            )
            response.raise_for_status()
            body = response.json()
        candidates = body.get("candidates") or []
        if not candidates:
            return dict(FALLBACK)
        text_parts = []
        for part in ((candidates[0].get("content") or {}).get("parts") or []):
            if "text" in part:
                text_parts.append(part["text"])
        parsed = _parse_json_blob("\n".join(text_parts) or "{}")
        return _coerce(parsed, source=f"gemini:{model}")
    except Exception as exc:
        out = dict(FALLBACK)
        out["justification"] = f"Gemini extraction failed ({type(exc).__name__}); defaults applied."
        return out
