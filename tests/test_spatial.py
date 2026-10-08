from catmod.spatial.blender import build_blender_manifest
from catmod.spatial.elevation import assemble_heightmap, polygon_bbox, sample_grid
from catmod.spatial.presets import STOREY_HEIGHT_M, list_presets, resolve_preset
from catmod.spatial.tiles3d import create_3d_tiles_session


def test_render_presets_include_three_engines():
    catalog = list_presets()
    for key in ("VICE_CITY_NEON", "GTA_STYLIZED", "PHOTOREAL_DEFAULT"):
        assert key in catalog["presets"]
        assert catalog["presets"][key]["palette"]["risk_high"].startswith("#")
    assert resolve_preset("PHOTOREAL")["id"] == "PHOTOREAL_DEFAULT"
    try:
        resolve_preset("DOOM")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_heightmap_assembly_without_google():
    points = sample_grid(36.80, -1.31, 36.84, -1.27, 4, 4)
    assert len(points) == 16
    samples = [
        {"lat": lat, "lng": lon, "elevation_m": 2.0 + i * 0.1, "resolution_m": 1.0}
        for i, (lat, lon) in enumerate(points)
    ]
    grid = assemble_heightmap(
        samples, west=36.80, south=-1.31, east=36.84, north=-1.27, rows=4, cols=4
    )
    assert grid["rows"] == 4 and grid["cols"] == 4
    assert len(grid["heightmap"]) == 4
    assert len(grid["heightmap"][0]) == 4
    assert grid["baseline_elevation_m"] == min(s["elevation_m"] for s in samples)
    assert grid["usage"] == "3d_flood_displacement_plane"
    west, south, east, north = polygon_bbox([[36.78, -1.32], [36.86, -1.26]])
    assert west == 36.78 and north == -1.26


def test_blender_manifest_from_open_buildings():
    manifest = build_blender_manifest(shader_preset="GTA_STYLIZED")
    assert manifest["format"] == "catmod.blender_manifest.v1"
    assert manifest["shader_preset"] == "GTA_STYLIZED"
    assert manifest["building_count"] == len(manifest["buildings"])
    if manifest["buildings"]:
        b = manifest["buildings"][0]
        assert b["height_m"] == b["storeys"] * STOREY_HEIGHT_M
        assert "predicted_material" in b
        assert "first_floor_clearance" in b
        assert "footprint_lonlat" in b
    assert "absolute_water_surface_m" in manifest["water_levels"]
    assert manifest["photoreal_tiles"]["load_in_leaflet"] is False
    bbox = manifest["bounding_box"]
    assert bbox["west"] < bbox["east"]
    assert "grid" in manifest["terrain"] or manifest["terrain"].get("fallback") is True


def test_3d_tiles_session_falls_back_without_maps_key():
    from catmod.flood.maps import maps_configured

    if maps_configured():
        return
    payload = create_3d_tiles_session(west=36.80, south=-1.31, east=36.84, north=-1.27)
    assert payload["provider"] == "open_stack_procedural"
    assert payload["fallback"] is True
    assert payload["session"] is None
    assert payload["renderer_hints"]["blosm"]["provider"] == "osm-buildings"


def test_blender_manifest_http_and_elevation_without_key():
    from fastapi.testclient import TestClient

    from catmod.api import app
    from catmod.flood.maps import maps_configured

    client = TestClient(app)
    res = client.get("/api/export/blender-manifest", params={"shader_preset": "VICE_CITY_NEON"})
    assert res.status_code == 200
    body = res.json()
    assert body["shader_preset"] == "VICE_CITY_NEON"
    assert "buildings" in body
    dl = client.get("/api/export/blender-manifest", params={"download": True})
    assert dl.status_code == 200
    assert "attachment" in dl.headers.get("content-disposition", "")
    elev = client.get("/api/spatial/elevation", params={"lat": -1.2921, "lng": 36.8219})
    assert elev.status_code == 200
    elev_body = elev.json()
    assert "heightmap" in elev_body
    assert elev_body.get("provider") in {"google", "open_meteo", "heuristic"}
    presets = client.get("/api/spatial/render-presets")
    assert presets.status_code == 200
    assert "GTA_STYLIZED" in presets.json()["presets"]
    tiles = client.get("/api/spatial/3d-tiles-session")
    assert tiles.status_code == 200
    if not maps_configured():
        assert tiles.json()["fallback"] is True
