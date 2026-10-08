"""Photoreal diorama data contracts. No Google 3D tile mesh is fetched."""

from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient

from catmod.api import app
from catmod.flood.maps import esri_terrain_url
from catmod.spatial.flooddepth import flood_depth_grid


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
    script = client.get("/map/diorama.js")
    assert script.status_code == 200
    assert "tile.googleapis.com" not in script.text
    assert "dem_footprint_densify" in script.text
    assert client.get("/map/vendor/three/three.module.js").status_code == 200
