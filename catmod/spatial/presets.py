"""Shader / stylization metadata for future Cesium, Three.js, and Blender/Blosm renders.

Python is the source of truth. static/renderPresets.js mirrors these values for
browser and Blender script loaders. Nothing here loads WebGL.
"""

from __future__ import annotations

from typing import Any, Literal

ShaderId = Literal["VICE_CITY_NEON", "GTA_STYLIZED", "PHOTOREAL_DEFAULT"]

STOREY_HEIGHT_M = 3.5

RENDER_PRESETS: dict[str, dict[str, Any]] = {
    "VICE_CITY_NEON": {
        "id": "VICE_CITY_NEON",
        "label": "Vice City Neon",
        "engine_hint": "stylized_pbr",
        "palette": {
            "sky": "#12061F",
            "fog": "#3B0A58",
            "emissive_a": "#FF2BD6",
            "emissive_b": "#00F5FF",
            "building": "#1B1030",
            "water": "#5B2CFF",
            "risk_low": "#00F5FF",
            "risk_moderate": "#C77DFF",
            "risk_high": "#FF2BD6",
        },
        "flood_heatmap": "purple_cyan",
        "material": {
            "wetness": 0.85,
            "roughness": 0.18,
            "metalness": 0.35,
            "rain_ripples": True,
            "neon_bloom": 1.4,
            "outline_width": 0.0,
        },
        "water_plane": {
            "opacity": 0.72,
            "refraction": 0.25,
            "animation": "rain_stylized",
        },
        "blender": {
            "eevee_bloom": True,
            "film_transparent": False,
            "world_shader": "vice_city_gradient",
        },
    },
    "GTA_STYLIZED": {
        "id": "GTA_STYLIZED",
        "label": "GTA Stylized",
        "engine_hint": "cel_shaded",
        "palette": {
            "sky": "#7EC8E3",
            "fog": "#F2D0A4",
            "emissive_a": "#FF6B00",
            "emissive_b": "#FFE566",
            "building": "#E8D5B7",
            "water": "#2E86AB",
            "risk_low": "#2A9D4A",
            "risk_moderate": "#F4A259",
            "risk_high": "#D62828",
        },
        "flood_heatmap": "high_contrast_hazard",
        "material": {
            "wetness": 0.15,
            "roughness": 0.85,
            "metalness": 0.05,
            "rain_ripples": False,
            "neon_bloom": 0.0,
            "outline_width": 2.0,
            "cel_bands": 3,
        },
        "water_plane": {
            "opacity": 0.55,
            "refraction": 0.05,
            "animation": "none",
        },
        "blender": {
            "eevee_bloom": False,
            "freestyle_outlines": True,
            "world_shader": "gta_sun_disk",
        },
    },
    "PHOTOREAL_DEFAULT": {
        "id": "PHOTOREAL_DEFAULT",
        "label": "Photoreal",
        "aliases": ["PHOTOREAL"],
        "engine_hint": "photoreal_3d_tiles",
        "palette": {
            "sky": "#87CEEB",
            "fog": "#C9D6DF",
            "emissive_a": "#FFFFFF",
            "emissive_b": "#FFFFFF",
            "building": "#B8B0A8",
            "water": "#4C8DDE",
            "risk_low": "#2A9D4A",
            "risk_moderate": "#E0B825",
            "risk_high": "#C1121F",
        },
        "flood_heatmap": "true_color_inundation",
        "material": {
            "wetness": 0.35,
            "roughness": 0.55,
            "metalness": 0.12,
            "rain_ripples": False,
            "neon_bloom": 0.0,
            "outline_width": 0.0,
            "use_satellite_textures": True,
            "use_google_3d_tiles": True,
        },
        "water_plane": {
            "opacity": 0.45,
            "refraction": 0.4,
            "animation": "gerstner_light",
        },
        "blender": {
            "eevee_bloom": False,
            "cycles_preferred": True,
            "world_shader": "nishita_sky",
            "blosm_provider": "google-3d-tiles",
        },
    },
}


def resolve_preset(name: str | None) -> dict[str, Any]:
    key = (name or "PHOTOREAL_DEFAULT").strip().upper().replace("-", "_")
    if key == "PHOTOREAL":
        key = "PHOTOREAL_DEFAULT"
    preset = RENDER_PRESETS.get(key)
    if preset is None:
        raise ValueError(
            f"Unknown shader_preset {name!r}. Use VICE_CITY_NEON, GTA_STYLIZED, or PHOTOREAL_DEFAULT."
        )
    return preset


def list_presets() -> dict[str, Any]:
    return {
        "default": "PHOTOREAL_DEFAULT",
        "storey_height_m": STOREY_HEIGHT_M,
        "presets": RENDER_PRESETS,
    }
