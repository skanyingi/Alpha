from catmod.flood.maps import heuristic_inundation_card, normalize_geocode
from catmod.geo.fallback import fetch_with_fallback, google_status_reason


def test_fetch_with_fallback_swallows_request_denied():
    calls = {"fallback": 0}

    def primary():
        raise RuntimeError("REQUEST_DENIED: You must enable Billing on the Google Cloud Project")

    def fallback():
        calls["fallback"] += 1
        return {"lat": -4.05, "lng": 39.67, "displayName": "Mombasa"}

    out = fetch_with_fallback(
        service="Geocoding",
        primary=primary,
        fallback=fallback,
        fallback_name="OSM Nominatim",
    )
    assert calls["fallback"] == 1
    assert out["displayName"] == "Mombasa"


def test_google_status_reason_detects_billing_deny():
    reason = google_status_reason(
        {
            "status": "REQUEST_DENIED",
            "error_message": "You must enable Billing on the Google Cloud Project.",
        }
    )
    assert reason is not None
    assert "REQUEST_DENIED" in reason


def test_normalize_geocode_aliases():
    out = normalize_geocode(
        {
            "latitude": -4.05052,
            "longitude": 39.667169,
            "formatted_address": "Mombasa, Kenya",
            "provider": "nominatim",
        }
    )
    assert out["lat"] == out["latitude"] == -4.05052
    assert out["lng"] == out["longitude"] == 39.667169
    assert out["displayName"] == "Mombasa, Kenya"


def test_heuristic_street_card_is_svg():
    payload, mime = heuristic_inundation_card(-4.05, 39.67, depth_m=1.2)
    assert mime == "image/svg+xml"
    assert b"Ground-level inundation" in payload
    assert b"1.20 m" in payload


def test_fallback_log_redacts_api_keys(caplog):
    import logging

    from catmod.geo.fallback import log_fallback

    with caplog.at_level(logging.WARNING, logger="catmod.fallback"):
        log_fallback(
            "Photorealistic 3D Tiles",
            "404 for url 'https://tile.googleapis.com/v1/3dtiles/root.json?key=AIzaSyFakeKeyForUnitTestOnly123456'",
            "procedural terrain",
        )
    assert "AIzaSyFake" not in caplog.text
    assert "REDACTED" in caplog.text
