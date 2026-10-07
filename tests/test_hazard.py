"""Hazard raster, coordinate, and anomaly lookups."""

from decimal import Decimal
from pathlib import Path

from catmod.hazard.geotiff import write_geotiff
from catmod.hazard.raster import IS_OUT_OF_BOUNDS, NULL_ISLAND, load_hazard_file
from catmod.hazard.service import HazardService, lookup_hazard


def test_nzoia_depth_is_bounded_and_grows_with_return_period():
    short = lookup_hazard(0.45, 34.22, return_period=10, region="nzoia")
    long = lookup_hazard(0.45, 34.22, return_period=500, region="nzoia")
    assert short.in_bounds is True
    assert short.anomaly is None
    assert short.synthetic is True
    assert short.region == "nzoia"
    assert short.depth_m is not None and long.depth_m is not None
    assert Decimal("0") < short.depth_m <= Decimal("10")
    assert long.depth_m > short.depth_m


def test_null_island_and_out_of_bounds_are_flagged():
    island = lookup_hazard(0.0, 0.0)
    assert island.anomaly == NULL_ISLAND
    assert island.in_bounds is False
    assert island.depth_m is None
    assert island.message == "Null Island"
    assert island.synthetic is True

    missing = lookup_hazard(51.5, -0.12)
    assert missing.anomaly == IS_OUT_OF_BOUNDS
    assert missing.message == "IS_OUT_OF_BOUNDS"
    assert missing.depth_m is None


def _ascii(path: Path) -> Path:
    path.write_text(
        "\n".join(
            [
                "ncols 2",
                "nrows 2",
                "xllcorner -1",
                "yllcorner -1",
                "cellsize 1",
                "NODATA_value -9999",
                "1 2",
                "3 4",
            ]
        ),
        encoding="utf-8",
    )
    return path


def test_ascii_raster_and_null_island_precedence(tmp_path: Path):
    path = _ascii(tmp_path / "origin.asc")
    raster = load_hazard_file(path, synthetic=True, name="origin")
    service = HazardService([raster])
    island = service.lookup(0.0, 0.0)
    assert island.anomaly == NULL_ISLAND
    inside = service.lookup(0.5, -0.5, return_period=100)
    assert inside.in_bounds is True
    assert inside.depth_m == Decimal("1.0000")
    outside = service.lookup(5.0, 5.0)
    assert outside.anomaly == IS_OUT_OF_BOUNDS


def test_coordinate_csv_nearest_neighbour(tmp_path: Path):
    path = tmp_path / "points.csv"
    path.write_text("latitude,longitude,susceptibility\n-1.29,36.82,0.50\n", encoding="utf-8")
    index = load_hazard_file(path, synthetic=True, name="sparse")
    service = HazardService([index])
    near = service.lookup(-1.291, 36.821, return_period=100)
    assert near.in_bounds is True
    assert near.synthetic is True
    assert near.value_kind == "susceptibility"
    # 0.50 susceptibility × 4.0 m documented Nairobi-style conversion.
    assert near.base_depth_m == Decimal("2.0000")
    assert "4.0" in (near.message or "")
    far = service.lookup(0.45, 34.22)
    assert far.anomaly == IS_OUT_OF_BOUNDS


def test_geotiff_roundtrip(tmp_path: Path):
    path = tmp_path / "grid.tif"
    write_geotiff(
        path,
        [[1.0, 2.0], [3.0, 4.0]],
        west=0.0,
        north=2.0,
        cell_lon=1.0,
        cell_lat=1.0,
    )
    raster = load_hazard_file(path, synthetic=False, name="grid")
    assert raster.synthetic is False
    service = HazardService([raster])
    hit = service.lookup(1.5, 0.5, return_period=100)
    assert hit.in_bounds is True
    assert hit.synthetic is False
    assert hit.depth_m == Decimal("1.0000")
    assert service.lookup(9.0, 9.0).anomaly == IS_OUT_OF_BOUNDS


def test_nairobi_susceptibility_uses_documented_four_metre_assumption():
    hit = lookup_hazard(-1.2921, 36.8219, region="nairobi", return_period=100)
    assert hit.in_bounds is True
    assert hit.value_kind == "susceptibility"
    assert hit.synthetic is True
    assert hit.proxy is True
    assert hit.depth_m is not None
    assert Decimal("0") < hit.depth_m <= Decimal("4")
    assert "4.0" in hit.message
    assert "susceptibility" in hit.message


def test_nzoia_geotiff_depth_passes_through_and_dry_cells_are_zero(tmp_path: Path):
    from catmod.hazard.provenance import JRC_NZOIA_SOURCE

    path = tmp_path / "nzoia_rp100.tif"
    dry = -3.402823466e38
    write_geotiff(
        path,
        [[dry, 2.5], [2.5, 2.5]],
        west=34.0,
        north=1.0,
        cell_lon=0.5,
        cell_lat=0.5,
        nodata=dry,
    )
    raster = load_hazard_file(path)
    assert raster.synthetic is False
    assert raster.value_kind == "depth_m"
    assert raster.source == JRC_NZOIA_SOURCE
    service = HazardService([raster])
    wet = service.lookup(0.75, 34.75, return_period=100, region="nzoia")
    dry_cell = service.lookup(0.75, 34.25, return_period=100, region="nzoia")
    assert wet.synthetic is False
    assert wet.proxy is False
    assert wet.value_kind == "depth_m"
    assert wet.depth_m == Decimal("2.5000")
    assert wet.message == ""
    assert dry_cell.in_bounds is True
    assert dry_cell.depth_m == Decimal("0.0000")
