"""Google Maps Platform: Geocoding, Places, Static Maps, Street View.

Keys stay on the server. Imagery is proxied so the browser never sees GOOGLE_MAPS_API_KEY.
Every Google request is wrapped with an open-stack fallback (Nominatim / Esri / heuristic card).
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

import httpx

from catmod.config import Settings, get_settings
from catmod.geo.fallback import fetch_with_fallback, google_status_reason, log_fallback

GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
PLACES_TEXT_URL = "https://maps.googleapis.com/maps/api/place/textsearch/json"
STATIC_MAP_URL = "https://maps.googleapis.com/maps/api/staticmap"
STREET_VIEW_URL = "https://maps.googleapis.com/maps/api/streetview"
STREET_VIEW_META_URL = "https://maps.googleapis.com/maps/api/streetview/metadata"
NOMINATIM_SEARCH = "https://nominatim.openstreetmap.org/search"
NOMINATIM_REVERSE = "https://nominatim.openstreetmap.org/reverse"
ESRI_EXPORT_URL = (
    "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/export"
)
NOMINATIM_HEADERS = {
    "User-Agent": "HypervectorRAG-CAT/1.0 (local flood desk; nominatim fallback)",
    "Accept-Language": "en",
}


class MapsError(RuntimeError):
    pass


def _key(settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    key = (settings.google_maps_api_key or "").strip()
    if not key:
        raise MapsError("GOOGLE_MAPS_API_KEY is not configured")
    return key


def maps_configured(settings: Settings | None = None) -> bool:
    settings = settings or get_settings()
    return bool((settings.google_maps_api_key or "").strip())


def _google_status_error(body: dict[str, Any], action: str) -> MapsError:
    status = body.get("status") or "UNKNOWN"
    detail = body.get("error_message") or ""
    if "Billing" in detail or "billing" in detail:
        return MapsError(
            f"{action} failed: {status}. Google Maps billing is not enabled on this project. "
            "Enable billing at https://console.cloud.google.com/project/_/billing/enable "
            "(or the search will use OpenStreetMap Nominatim)."
        )
    if detail:
        return MapsError(f"{action} failed: {status} — {detail}")
    return MapsError(f"{action} failed: {status}")


def normalize_geocode(result: dict[str, Any]) -> dict[str, Any]:
    """Uniform {lat, lng, displayName} plus existing latitude/longitude/formatted_address."""
    lat = float(result.get("latitude") if result.get("latitude") is not None else result.get("lat") or 0.0)
    lng = float(result.get("longitude") if result.get("longitude") is not None else result.get("lng") or 0.0)
    name = str(result.get("formatted_address") or result.get("displayName") or result.get("display_name") or "")
    result["latitude"] = lat
    result["longitude"] = lng
    result["lat"] = lat
    result["lng"] = lng
    result["formatted_address"] = name
    result["displayName"] = name
    return result


def geocode_nominatim(address: str) -> dict[str, Any]:
    """OSM Nominatim fallback when Google Geocoding is denied or unconfigured."""
    params = {"q": address, "format": "json", "limit": 1, "addressdetails": 1}
    with httpx.Client(timeout=20.0, headers=NOMINATIM_HEADERS) as client:
        response = client.get(NOMINATIM_SEARCH, params=params)
        response.raise_for_status()
        rows = response.json()
    if not rows:
        raise MapsError(f"No geocoding match for {address!r}")
    top = rows[0]
    return normalize_geocode(
        {
            "latitude": float(top["lat"]),
            "longitude": float(top["lon"]),
            "formatted_address": top.get("display_name") or address,
            "place_id": str(top.get("place_id") or ""),
            "types": [top.get("type") or "unknown"],
            "location_type": top.get("category"),
            "viewport": None,
            "address_components": top.get("address") or {},
            "provider": "nominatim",
            "google_fallback": True,
        }
    )


def reverse_geocode_nominatim(latitude: float, longitude: float) -> dict[str, Any]:
    params = {
        "lat": latitude,
        "lon": longitude,
        "format": "json",
        "zoom": 18,
        "addressdetails": 1,
    }
    with httpx.Client(timeout=20.0, headers=NOMINATIM_HEADERS) as client:
        response = client.get(NOMINATIM_REVERSE, params=params)
        response.raise_for_status()
        body = response.json()
    if not body or body.get("error"):
        return normalize_geocode(
            {
                "latitude": float(latitude),
                "longitude": float(longitude),
                "formatted_address": f"{latitude:.5f}, {longitude:.5f}",
                "place_id": None,
                "types": [],
                "provider": "nominatim",
                "status": "ZERO_RESULTS",
                "google_fallback": True,
            }
        )
    return normalize_geocode(
        {
            "latitude": float(body.get("lat", latitude)),
            "longitude": float(body.get("lon", longitude)),
            "formatted_address": body.get("display_name") or f"{latitude:.5f}, {longitude:.5f}",
            "place_id": str(body.get("place_id") or ""),
            "types": [body.get("type") or "unknown"],
            "location_type": body.get("category"),
            "viewport": None,
            "address_components": body.get("address") or {},
            "provider": "nominatim",
            "status": "OK",
            "google_fallback": True,
        }
    )


def geocode_google_places(address: str, settings: Settings | None = None) -> dict[str, Any]:
    params = {"query": address, "key": _key(settings)}
    with httpx.Client(timeout=8.0) as client:
        response = client.get(PLACES_TEXT_URL, params=params)
        if response.status_code in {400, 401, 403, 429}:
            raise MapsError(f"Places HTTP {response.status_code}")
        response.raise_for_status()
        body = response.json()
    deny = google_status_reason(body)
    results = body.get("results") or []
    if body.get("status") == "OK" and results:
        top = results[0]
        loc = (top.get("geometry") or {}).get("location") or {}
        return normalize_geocode(
            {
                "latitude": float(loc["lat"]),
                "longitude": float(loc["lng"]),
                "formatted_address": top.get("formatted_address") or top.get("name") or address,
                "place_id": top.get("place_id"),
                "types": top.get("types") or [],
                "location_type": (top.get("geometry") or {}).get("location_type"),
                "viewport": (top.get("geometry") or {}).get("viewport"),
                "address_components": [],
                "provider": "google_places",
            }
        )
    raise _google_status_error(body if deny or body else {"status": "UNKNOWN"}, "Places")


def geocode_google(address: str, settings: Settings | None = None) -> dict[str, Any]:
    params = {"address": address, "key": _key(settings)}
    with httpx.Client(timeout=8.0) as client:
        response = client.get(GEOCODE_URL, params=params)
        if response.status_code in {400, 401, 403, 429}:
            raise MapsError(f"Geocoding HTTP {response.status_code}")
        response.raise_for_status()
        body = response.json()
    status = body.get("status")
    results = body.get("results") or []
    if status == "OK" and results:
        top = results[0]
        loc = top["geometry"]["location"]
        return normalize_geocode(
            {
                "latitude": float(loc["lat"]),
                "longitude": float(loc["lng"]),
                "formatted_address": top.get("formatted_address") or address,
                "place_id": top.get("place_id"),
                "types": top.get("types") or [],
                "location_type": (top.get("geometry") or {}).get("location_type"),
                "viewport": (top.get("geometry") or {}).get("viewport"),
                "address_components": top.get("address_components") or [],
                "provider": "google",
            }
        )
    raise _google_status_error(body, "Geocoding")


def reverse_geocode_google(latitude: float, longitude: float, settings: Settings | None = None) -> dict[str, Any]:
    params = {"latlng": f"{latitude},{longitude}", "key": _key(settings)}
    with httpx.Client(timeout=8.0) as client:
        response = client.get(GEOCODE_URL, params=params)
        if response.status_code in {400, 401, 403, 429}:
            raise MapsError(f"Reverse geocoding HTTP {response.status_code}")
        response.raise_for_status()
        body = response.json()
    status = body.get("status")
    results = body.get("results") or []
    if status == "OK" and results:
        top = results[0]
        loc = (top.get("geometry") or {}).get("location") or {}
        return normalize_geocode(
            {
                "latitude": float(loc.get("lat", latitude)),
                "longitude": float(loc.get("lng", longitude)),
                "formatted_address": top.get("formatted_address") or f"{latitude:.5f}, {longitude:.5f}",
                "place_id": top.get("place_id"),
                "types": top.get("types") or [],
                "location_type": (top.get("geometry") or {}).get("location_type"),
                "viewport": (top.get("geometry") or {}).get("viewport"),
                "address_components": top.get("address_components") or [],
                "provider": "google",
                "status": "OK",
            }
        )
    raise _google_status_error(body, "Reverse geocoding")


def geocode_address(address: str, settings: Settings | None = None) -> dict[str, Any]:
    """Forward geocode. Prefer Google Places/Geocoding; fall back to Nominatim on billing/deny errors."""
    settings = settings or get_settings()

    def primary() -> dict[str, Any]:
        if not maps_configured(settings):
            raise MapsError("GOOGLE_MAPS_API_KEY is not configured")
        try:
            return geocode_google_places(address, settings)
        except Exception as places_exc:
            log_fallback("Places", str(places_exc), "Google Geocoding API")
            return geocode_google(address, settings)

    return fetch_with_fallback(
        service="Geocoding",
        primary=primary,
        fallback=lambda: geocode_nominatim(address),
        fallback_name="OSM Nominatim",
    )


def reverse_geocode(latitude: float, longitude: float, settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()

    def primary() -> dict[str, Any]:
        if not maps_configured(settings):
            raise MapsError("GOOGLE_MAPS_API_KEY is not configured")
        return reverse_geocode_google(latitude, longitude, settings)

    return fetch_with_fallback(
        service="Geocoding",
        primary=primary,
        fallback=lambda: reverse_geocode_nominatim(latitude, longitude),
        fallback_name="OSM Nominatim",
    )


def static_map_url(
    latitude: float,
    longitude: float,
    *,
    zoom: int = 19,
    width: int = 640,
    height: int = 400,
    maptype: str = "satellite",
    settings: Settings | None = None,
) -> str:
    params = {
        "center": f"{latitude},{longitude}",
        "zoom": str(zoom),
        "size": f"{width}x{height}",
        "maptype": maptype,
        "scale": "2",
        "key": _key(settings),
    }
    return f"{STATIC_MAP_URL}?{urlencode(params)}"


def esri_aerial_url(
    latitude: float,
    longitude: float,
    *,
    width: int = 640,
    height: int = 400,
) -> str:
    dlat = 0.0018
    dlng = 0.0022
    west, south = longitude - dlng, latitude - dlat
    east, north = longitude + dlng, latitude + dlat
    params = {
        "bbox": f"{west},{south},{east},{north}",
        "bboxSR": "4326",
        "imageSR": "3857",
        "size": f"{width},{height}",
        "format": "jpg",
        "f": "image",
    }
    return f"{ESRI_EXPORT_URL}?{urlencode(params)}"


def street_view_url(
    latitude: float,
    longitude: float,
    *,
    width: int = 640,
    height: int = 400,
    fov: int = 80,
    pitch: int = 10,
    heading: int | None = None,
    settings: Settings | None = None,
) -> str:
    params = {
        "location": f"{latitude},{longitude}",
        "size": f"{width}x{height}",
        "fov": str(fov),
        "pitch": str(pitch),
        "source": "outdoor",
        "key": _key(settings),
    }
    if heading is not None:
        params["heading"] = str(heading)
    return f"{STREET_VIEW_URL}?{urlencode(params)}"


def heuristic_inundation_card(
    latitude: float,
    longitude: float,
    *,
    depth_m: float | None = None,
    reason: str = "Google Street View blocked (billing/authorization).",
) -> tuple[bytes, str]:
    """Local SVG summary card — never a broken <img> when Street View is denied."""
    depth_txt = f"{depth_m:.2f} m" if depth_m is not None else "see flood score"
    warn = "HIGH INUNDATION" if (depth_m is not None and depth_m >= 0.3) else "GROUND-LEVEL CHECK"
    svg = f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="640" height="200" viewBox="0 0 640 200">
  <rect width="640" height="200" fill="#1b2838"/>
  <rect x="0" y="0" width="10" height="200" fill="#C1121F"/>
  <text x="28" y="44" fill="#f3f6fb" font-family="Segoe UI, system-ui, sans-serif" font-size="18" font-weight="700">{warn}</text>
  <text x="28" y="78" fill="#c9d4e3" font-family="Segoe UI, system-ui, sans-serif" font-size="14">Street View unavailable — heuristic summary</text>
  <text x="28" y="112" fill="#ffffff" font-family="Segoe UI, system-ui, sans-serif" font-size="16">Ground-level inundation: {depth_txt}</text>
  <text x="28" y="142" fill="#9fb0c3" font-family="Segoe UI, system-ui, sans-serif" font-size="12">{latitude:.5f}, {longitude:.5f}</text>
  <text x="28" y="172" fill="#7f93a8" font-family="Segoe UI, system-ui, sans-serif" font-size="11">{reason[:110]}</text>
</svg>
"""
    return svg.encode("utf-8"), "image/svg+xml"


def fetch_image_bytes(url: str, timeout: float = 20.0) -> tuple[bytes, str]:
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        response = client.get(url)
        if response.status_code in {400, 401, 403, 429}:
            raise MapsError(f"Imagery HTTP {response.status_code}")
        response.raise_for_status()
        content_type = response.headers.get("content-type", "image/jpeg").split(";")[0]
        payload = response.content
    if len(payload) < 64:
        raise MapsError("Imagery response was empty")
    if content_type.startswith("text") or content_type.startswith("application/json"):
        raise MapsError("Imagery endpoint returned an error payload, not an image")
    return payload, content_type or "image/jpeg"


def fetch_aerial(
    latitude: float,
    longitude: float,
    settings: Settings | None = None,
) -> tuple[bytes, str]:
    def primary() -> tuple[bytes, str]:
        if not maps_configured(settings):
            raise MapsError("GOOGLE_MAPS_API_KEY is not configured")
        return fetch_image_bytes(static_map_url(latitude, longitude, settings=settings))

    return fetch_with_fallback(
        service="Static Maps",
        primary=primary,
        fallback=lambda: fetch_image_bytes(esri_aerial_url(latitude, longitude)),
        fallback_name="ESRI World Imagery",
    )


def fetch_street_view(
    latitude: float,
    longitude: float,
    settings: Settings | None = None,
    *,
    depth_m: float | None = None,
) -> tuple[bytes, str]:
    def primary() -> tuple[bytes, str]:
        if not maps_configured(settings):
            raise MapsError("GOOGLE_MAPS_API_KEY is not configured")
        if not street_view_available(latitude, longitude, settings):
            raise MapsError("Street View metadata status is not OK")
        return fetch_image_bytes(street_view_url(latitude, longitude, settings=settings))

    return fetch_with_fallback(
        service="Street View",
        primary=primary,
        fallback=lambda: heuristic_inundation_card(latitude, longitude, depth_m=depth_m),
        fallback_name="heuristic inundation card",
    )


def street_view_available(latitude: float, longitude: float, settings: Settings | None = None) -> bool:
    if not maps_configured(settings):
        return False
    params = {"location": f"{latitude},{longitude}", "key": _key(settings)}
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.get(STREET_VIEW_META_URL, params=params)
            if response.status_code in {400, 401, 403, 429}:
                return False
            response.raise_for_status()
            body = response.json() or {}
        reason = google_status_reason(body)
        if reason:
            return False
        return body.get("status") == "OK"
    except Exception as exc:
        log_fallback("Street View", str(exc), "heuristic inundation card")
        return False
