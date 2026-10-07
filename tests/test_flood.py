from catmod.flood.buildings import match_footprint, point_in_ring, ring_area_m2, ring_centroid
from catmod.flood.hazard import risk_color, risk_level, score_asset
from catmod.flood.service import evaluate_asset, footprints_for_points, hazard_collection


def test_open_buildings_contains_sample_warehouse():
    hit = match_footprint(-1.2921, 36.8219)
    assert hit["geometry"]["type"] == "Polygon"
    assert hit["properties"]["match"] in {"contains", "nearest"}
    assert hit["properties"]["area_m2"] > 100
    ring = hit["geometry"]["coordinates"][0]
    assert point_in_ring(-1.2921, 36.8219, ring)
    lat_c, lon_c = ring_centroid(ring)
    assert abs(lat_c - -1.2921) < 0.01
    assert ring_area_m2(ring) > 100


def test_null_island_gets_estimated_footprint():
    hit = match_footprint(0.0, 0.0, max_distance_m=10)
    assert hit["properties"]["match"] == "estimated"
    assert hit["properties"]["source"] == "estimated_rectangle"


def test_heuristic_evaluate_without_api_keys():
    result = evaluate_asset(
        latitude=-1.2921,
        longitude=36.8219,
        occupancy_hint="whse",
        ground_elevation_m=2.0,
        asset_id="A-001",
        fetch_imagery=False,
        use_gemini=False,
    )
    assert result["gemini"]["occupancy_type"] == "Industrial"
    assert result["flood"]["risk_level"] in {"Low", "Moderate", "High"}
    assert result["geojson"]["geometry"]["type"] == "Polygon"
    props = result["geojson"]["properties"]
    assert props["badge"].endswith("RISK")
    assert props["aerial_url"].startswith("/api/v1/flood/imagery/aerial")
    assert "occupancy_type" in props
    assert "estimated_storeys" in props
    assert "roof_wall_material" in props
    assert "ground_clearance_elevation" in props


def test_risk_colors_and_inundation():
    gemini = {
        "occupancy_type": "Residential",
        "estimated_storeys": 1,
        "ground_clearance_elevation": "Ground level",
        "vulnerability_score": 8,
    }
    flood = score_asset(ground_elevation_m=1.0, water_surface_m=2.5, gemini=gemini)
    assert flood["inundation_depth_m"] > 1.0
    assert flood["risk_level"] == "High"
    assert risk_color(flood["risk_score"]).startswith("#")
    assert risk_level(2) == "Low"
    assert risk_level(5) == "Moderate"


def test_footprints_skip_null_island_and_emit_collection():
    geo = footprints_for_points(
        [
            {"asset_id": "N-001", "latitude": -1.2921, "longitude": 36.8219, "occupancy": "whse", "elevation": 2},
            {"asset_id": "A-005", "latitude": 0.0, "longitude": 0.0, "occupancy": "res", "elevation": 0},
        ]
    )
    assert geo["type"] == "FeatureCollection"
    assert len(geo["features"]) == 1
    assert geo["features"][0]["properties"]["asset_id"] == "N-001"


def test_hazard_extent_present():
    hazard = hazard_collection()
    assert hazard["features"]
    assert hazard["features"][0]["geometry"]["type"] == "Polygon"


def test_evaluate_requires_coordinates_or_address():
    try:
        evaluate_asset()
        assert False, "expected ValueError"
    except ValueError:
        pass
