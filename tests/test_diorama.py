"""Photoreal diorama data contracts. No Google 3D tile mesh is fetched."""

from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient

from catmod.api import app
from catmod.flood.maps import esri_terrain_url
from catmod.spatial.flooddepth import flood_depth_grid
from catmod.spatial.osm import ways_to_features


def test_flood_depth_grid_stays_on_the_local_atlas():
    grid = flood_depth_grid(36.812, -1.286, 36.828, -1.274, rows=5, cols=5)
    assert grid["rows"] == 5 and grid["cols"] == 5
    assert grid["vertical_meaning"] == "metres_above_local_ground"
    assert 0.0 <= grid["min_depth_m"] <= grid["max_depth_m"] <= 10.0
    assert grid["max_depth_m"] > 0.0
    # Southwest of the Nairobi susceptibility field is the wetter corner.
    assert grid["depth_m"][0][0] >= grid["depth_m"][-1][-1]


def test_esri_terrain_url_uses_the_cell_and_caps_the_longest_side():
    url = esri_terrain_url(36.812, -1.286, 36.828, -1.274)
    assert "arcgisonline.com" in url
    assert "tile.googleapis.com" not in url
    query = parse_qs(urlparse(url).query)
    assert query["bboxSR"] == ["4326"]
    width, height = (int(part) for part in query["size"][0].split(","))
    assert max(width, height) == 1024
    assert min(width, height) >= 64


def test_diorama_http_and_page_do_not_call_photoreal_tiles(monkeypatch):
    monkeypatch.setattr(
        "catmod.api.fetch_terrain_image",
        lambda *_args, **_kwargs: (b"\xff\xd8\xff" + b"x" * 80, "image/jpeg"),
    )
    client = TestClient(app)
    depth = client.get(
        "/api/spatial/flood-depth",
        params={"west": 36.812, "south": -1.286, "east": 36.828, "north": -1.274, "rows": 4, "cols": 4},
    )
    assert depth.status_code == 200
    body = depth.json()
    assert body["max_depth_m"] <= 10.0
    assert "flood_wse_m is not an AMSL plane" in body["note"]

    image = client.get(
        "/api/v1/flood/imagery/terrain",
        params={"west": 36.812, "south": -1.286, "east": 36.828, "north": -1.274},
    )
    assert image.status_code == 200
    assert image.headers["content-type"].startswith("image/jpeg")

    page = client.get("/map/diorama.html")
    assert page.status_code == 200
    assert "tile.googleapis.com" not in page.text
    assert "Not surveyed LiDAR" in page.text
    assert "Enter streets" in page.text
    assert "SURVEY" in page.text
    assert 'id="tog-scan" aria-pressed="false"' in page.text
    script = client.get("/map/diorama.js")
    assert script.status_code == 200
    assert "tile.googleapis.com" not in script.text
    assert "dem_footprint_densify" in script.text
    assert "osm-buildings" in script.text
    assert "No building geometries in this cell." in script.text
    assert "gross_volume_m3" in script.text
    assert client.get("/map/vendor/three/three.module.js").status_code == 200


def test_osm_buildings_parse_and_empty_on_overpass_failure(monkeypatch):
    elements = [{
        "type": "way",
        "id": 42,
        "tags": {
            "building": "yes",
            "name": "KICC",
            "height": "20",
            "building:levels": "5",
            "building:material": "concrete",
        },
        "geometry": [
            {"lon": 36.82, "lat": -1.28},
            {"lon": 36.821, "lat": -1.28},
            {"lon": 36.821, "lat": -1.279},
            {"lon": 36.82, "lat": -1.28},
        ],
    }]
    features = ways_to_features(elements, kind="building", cap=10)
    assert features[0]["geometry"]["type"] == "Polygon"
    assert features[0]["properties"]["name"] == "KICC"
    assert features[0]["properties"]["height"] == "20"
    assert features[0]["geometry"]["coordinates"][0][0] == features[0]["geometry"]["coordinates"][0][-1]

    def boom(_query):
        raise RuntimeError("down")

    monkeypatch.setattr("catmod.spatial.osm.fetch_overpass", boom)
    client = TestClient(app)
    empty = client.get(
        "/api/spatial/osm-buildings",
        params={"west": 36.812, "south": -1.286, "east": 36.828, "north": -1.274},
    )
    assert empty.status_code == 200
    body = empty.json()
    assert body["features"] == []
    assert "Overpass" in body["metadata"]["note"]

    wide = client.get(
        "/api/spatial/osm-roads",
        params={"west": 36.7, "south": -1.4, "east": 36.9, "north": -1.1},
    )
    assert wide.status_code == 200
    assert wide.json()["features"] == []

    def roads(_query):
        return [{
            "type": "way",
            "id": 9,
            "tags": {"highway": "primary", "name": "Kenyatta"},
            "geometry": [
                {"lon": 36.82, "lat": -1.28},
                {"lon": 36.822, "lat": -1.279},
            ],
        }]

    monkeypatch.setattr("catmod.spatial.osm.fetch_overpass", roads)
    road = client.get(
        "/api/spatial/osm-roads",
        params={"west": 36.812, "south": -1.286, "east": 36.828, "north": -1.274},
    )
    assert road.status_code == 200
    feature = road.json()["features"][0]
    assert feature["geometry"]["type"] == "LineString"
    assert feature["properties"]["name"] == "Kenyatta"
