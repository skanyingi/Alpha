"""Photoreal diorama data contracts. No Google 3D tile mesh is fetched."""

import json
import subprocess
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient

from catmod.api import app
from catmod.flood.maps import esri_terrain_url
from catmod.spatial.flooddepth import flood_depth_grid
from catmod.spatial.osm import ways_to_features

ROOT = Path(__file__).resolve().parents[1]


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
    assert "KICC photo space" in page.text
    assert "Enter streets" not in page.text
    script = client.get("/map/diorama.js")
    assert script.status_code == 200
    assert "tile.googleapis.com" not in script.text
    assert "osm-buildings" not in script.text
    assert "kicc/manifest.json" in script.text
    assert "photo space only" in script.text
    assert client.get("/map/vendor/three/three.module.js").status_code == 200


def test_kicc_twin_is_a_published_form_point_sample_not_lidar():
    client = TestClient(app)
    page = client.get("/map/diorama.html")
    assert page.status_code == 200
    assert "Not surveyed LiDAR" in page.text
    assert "published cylinder, cone, and helipad" in page.text
    script = client.get("/map/diorama.js")
    assert script.status_code == 200
    assert "kicc/manifest.json" in script.text
    manifest = json.loads((ROOT / "static" / "kicc" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["lidar"] is False
    assert manifest["method"] == "published_form_point_sample"
    assert manifest["height_m"] == 105.2
    assert manifest["latitude"] == -1.28861
    assert manifest["longitude"] == 36.82306
    assert manifest["shaft_diameter_uncertainty_m"] >= 6
    assert manifest["tile_cap"] <= 50000
    assert manifest["amphitheatre_floor_sqft_published"] == 28697
    assert "not a roof diameter" in manifest["amphitheatre_radius_note"]
    served = TestClient(app).get("/map/kicc/manifest.json")
    assert served.status_code == 200
    assert served.json()["height_m"] == 105.2
    proc = subprocess.run(
        [
            "node",
            "--input-type=module",
            "-e",
            (
                "import { readFileSync } from 'fs';"
                "import { buildTwin } from './static/kiccModel.js';"
                "const spec = JSON.parse(readFileSync('static/kicc/manifest.json','utf8'));"
                "const model = buildTwin(spec);"
                "const maxTile = model.tiles.reduce((m,t)=>Math.max(m,t.count),0);"
                "console.log(JSON.stringify({ok:model.report.ok, errors:model.report.errors,"
                " apex:model.report.apex_m, maxTile, points:model.report.lod0_points}));"
            ),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    report = json.loads(proc.stdout)
    assert report["ok"] is True
    assert report["errors"] == []
    assert abs(report["apex"] - 105.2) < 0.05
    assert report["maxTile"] <= 50000
    assert report["points"] > 1000


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
