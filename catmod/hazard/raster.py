"""Point-in-raster and coordinate-index flood hazard lookups.

Bundled atlases are synthetic. File loaders preserve an explicit ``synthetic``
flag so a real survey raster is not labeled as a generated proxy.
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

NULL_ISLAND = "NULL_ISLAND"
IS_OUT_OF_BOUNDS = "IS_OUT_OF_BOUNDS"
MAX_DEPTH_M = Decimal("10")


class HazardFormatError(ValueError):
    """Raised when a hazard file cannot be read."""


def is_null_island(latitude: float, longitude: float) -> bool:
    return abs(latitude) < 1e-6 and abs(longitude) < 1e-6


def _dec(value: float | Decimal | str) -> Decimal:
    return Decimal(str(value))


@dataclass(frozen=True)
class HazardHit:
    latitude: float
    longitude: float
    depth_m: Decimal | None
    base_depth_m: Decimal | None
    susceptibility: Decimal | None
    in_bounds: bool
    anomaly: str | None
    synthetic: bool
    proxy: bool
    source: str
    region: str
    return_period: int
    value_kind: str
    message: str = ""

    def as_dict(self) -> dict[str, object]:
        def _fmt(value: Decimal | None) -> str | None:
            if value is None:
                return None
            return format(value, "f")

        return {
            "latitude": self.latitude,
            "longitude": self.longitude,
            "depth_m": _fmt(self.depth_m),
            "base_depth_m": _fmt(self.base_depth_m),
            "susceptibility": _fmt(self.susceptibility),
            "in_bounds": self.in_bounds,
            "anomaly": self.anomaly,
            "synthetic": self.synthetic,
            "proxy": self.proxy,
            "source": self.source,
            "region": self.region,
            "return_period": self.return_period,
            "value_kind": self.value_kind,
            "message": self.message,
        }


@dataclass
class HazardRaster:
    """North-up regular grid. Row 0 is the northern edge."""

    values: list[list[float]]
    west: float
    south: float
    east: float
    north: float
    name: str
    source: str
    synthetic: bool
    value_kind: str = "depth_m"
    nodata: float = -9999.0
    proxy: bool = False
    susceptibility_depth_m: Decimal | None = None
    native_return_period: int | None = None
    apply_return_period_scale: bool = True

    def __post_init__(self) -> None:
        if not self.values or not self.values[0]:
            raise ValueError("hazard raster is empty")
        width = len(self.values[0])
        if any(len(row) != width for row in self.values):
            raise ValueError("hazard raster rows must be rectangular")
        if self.east <= self.west or self.north <= self.south:
            raise ValueError("hazard raster bounds are degenerate")

    @property
    def rows(self) -> int:
        return len(self.values)

    @property
    def cols(self) -> int:
        return len(self.values[0])

    def covers(self, latitude: float, longitude: float) -> bool:
        return self.south <= latitude <= self.north and self.west <= longitude <= self.east

    def sample_base(self, latitude: float, longitude: float) -> Decimal:
        """Bilinear sample. Dry / no-data cells contribute 0 m and do not smear neighbors."""
        dlon = (self.east - self.west) / self.cols
        dlat = (self.north - self.south) / self.rows
        x = (longitude - self.west) / dlon - 0.5
        y = (self.north - latitude) / dlat - 0.5
        x = min(max(x, 0.0), self.cols - 1)
        y = min(max(y, 0.0), self.rows - 1)
        x0 = int(math.floor(x))
        y0 = int(math.floor(y))
        x1 = min(x0 + 1, self.cols - 1)
        y1 = min(y0 + 1, self.rows - 1)
        tx = _dec(x - x0)
        ty = _dec(y - y0)
        v00 = self._cell(y0, x0)
        v10 = self._cell(y0, x1)
        v01 = self._cell(y1, x0)
        v11 = self._cell(y1, x1)
        top = v00 * (Decimal("1") - tx) + v10 * tx
        bottom = v01 * (Decimal("1") - tx) + v11 * tx
        return top * (Decimal("1") - ty) + bottom * ty

    def _cell(self, row: int, col: int) -> Decimal:
        value = self.values[row][col]
        if self._is_nodata(value):
            return Decimal("0")
        return _dec(value)

    def _is_nodata(self, value: float) -> bool:
        """Dry JRC cells use a huge negative float. ASCII grids use -9999."""
        if not math.isfinite(value):
            return True
        if value < -1.0e30:
            return True
        if math.isfinite(self.nodata) and self.nodata <= -999 and abs(value - self.nodata) <= 1e-3:
            return True
        return False


@dataclass
class CoordinateHazardIndex:
    """Nearest-neighbour lookup for sparse susceptibility or depth points."""

    points: list[tuple[float, float, float]]
    name: str
    source: str
    synthetic: bool
    value_kind: str = "depth_m"
    max_distance_deg: float = 0.05
    proxy: bool = False
    susceptibility_depth_m: Decimal | None = None
    native_return_period: int | None = None
    apply_return_period_scale: bool = True

    def covers(self, latitude: float, longitude: float) -> bool:
        return self._nearest(latitude, longitude) is not None

    def sample_base(self, latitude: float, longitude: float) -> Decimal:
        found = self._nearest(latitude, longitude)
        if found is None:
            raise HazardFormatError("coordinate index sample outside max distance")
        return _dec(found[2])

    def _nearest(self, latitude: float, longitude: float) -> tuple[float, float, float] | None:
        best: tuple[float, tuple[float, float, float]] | None = None
        for lat, lon, value in self.points:
            dist = _distance_deg(latitude, longitude, lat, lon)
            if best is None or dist < best[0]:
                best = (dist, (lat, lon, value))
        if best is None or best[0] > self.max_distance_deg:
            return None
        return best[1]


def _distance_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    mean_lat = math.radians((lat1 + lat2) / 2.0)
    dlat = lat1 - lat2
    dlon = (lon1 - lon2) * math.cos(mean_lat)
    return math.hypot(dlat, dlon)


def load_hazard_file(
    path: str | Path,
    *,
    synthetic: bool | None = None,
    name: str | None = None,
) -> HazardRaster | CoordinateHazardIndex:
    from catmod.hazard.provenance import apply_synthetic_override, infer_provenance

    source = Path(path)
    provenance = apply_synthetic_override(infer_provenance(source), synthetic)
    suffix = source.suffix.lower()
    label = name or provenance.name or source.stem
    if suffix == ".csv":
        return _load_csv(source, provenance=provenance, name=label)
    if suffix == ".asc":
        return _load_ascii(source, provenance=provenance, name=label)
    if suffix in {".tif", ".tiff"}:
        from catmod.hazard.geotiff import load_geotiff

        return load_geotiff(source, provenance=provenance, name=label)
    raise HazardFormatError(f"unsupported hazard format {suffix or source.name!r}")


def _load_csv(path: Path, *, provenance, name: str) -> HazardRaster | CoordinateHazardIndex:
    from catmod.hazard.provenance import NAIROBI_SUSCEPTIBILITY_DEPTH_M

    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise HazardFormatError("hazard CSV has no header")
        fields = {_norm_key(f): f for f in reader.fieldnames}
        lat_key = _pick(fields, ("latitude", "lat", "y"))
        lon_key = _pick(fields, ("longitude", "lon", "lng", "x"))
        if "depth_m" in fields or "depth" in fields:
            value_key = fields.get("depth_m") or fields["depth"]
            value_kind = "depth_m"
        elif "susceptibility" in fields or "score" in fields:
            value_key = fields.get("susceptibility") or fields["score"]
            value_kind = "susceptibility"
        elif "value" in fields:
            value_key = fields["value"]
            value_kind = "depth_m"
        elif provenance.name == "nairobi_hotspots":
            value_key = None
            value_kind = "susceptibility"
        else:
            raise HazardFormatError("hazard CSV needs depth_m, susceptibility, or value")
        points: list[tuple[float, float, float]] = []
        for row in reader:
            raw = "1" if value_key is None else row[value_key]
            points.append((float(row[lat_key]), float(row[lon_key]), float(raw)))
    if not points:
        raise HazardFormatError("hazard CSV has no rows")
    kind = provenance.value_kind if provenance.name else value_kind
    depth_ref = provenance.susceptibility_depth_m
    if kind == "susceptibility" and depth_ref is None:
        depth_ref = NAIROBI_SUSCEPTIBILITY_DEPTH_M
    source = provenance.source if provenance.name else str(path)
    grid = _as_regular_grid(points)
    if grid is None:
        return CoordinateHazardIndex(
            points=points,
            name=name,
            source=source,
            synthetic=provenance.synthetic,
            value_kind=kind,
            proxy=provenance.proxy,
            susceptibility_depth_m=depth_ref,
            native_return_period=provenance.native_return_period,
            apply_return_period_scale=provenance.apply_return_period_scale,
        )
    values, west, south, east, north = grid
    return HazardRaster(
        values=values,
        west=west,
        south=south,
        east=east,
        north=north,
        name=name,
        source=source,
        synthetic=provenance.synthetic,
        value_kind=kind,
        proxy=provenance.proxy,
        susceptibility_depth_m=depth_ref,
        native_return_period=provenance.native_return_period,
        apply_return_period_scale=provenance.apply_return_period_scale,
    )


def _load_ascii(path: Path, *, provenance, name: str) -> HazardRaster:
    header: dict[str, float] = {}
    rows: list[list[float]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            parts = line.split()
            if not parts:
                continue
            key = parts[0].lower()
            if key in {"ncols", "nrows", "xllcorner", "yllcorner", "xllcenter", "yllcenter", "cellsize", "nodata_value"}:
                header[key] = float(parts[1])
                continue
            rows.append([float(p) for p in parts])
    if "ncols" not in header or "nrows" not in header or "cellsize" not in header:
        raise HazardFormatError("ESRI ASCII grid is missing ncols, nrows, or cellsize")
    ncols = int(header["ncols"])
    nrows = int(header["nrows"])
    if len(rows) != nrows or any(len(row) != ncols for row in rows):
        raise HazardFormatError("ESRI ASCII grid body does not match ncols/nrows")
    cell = header["cellsize"]
    if "xllcorner" in header:
        west = header["xllcorner"]
        south = header["yllcorner"]
    else:
        west = header["xllcenter"] - cell / 2.0
        south = header["yllcenter"] - cell / 2.0
    nodata = header.get("nodata_value", -9999.0)
    source = provenance.source if provenance.name else str(path)
    return HazardRaster(
        values=rows,
        west=west,
        south=south,
        east=west + ncols * cell,
        north=south + nrows * cell,
        name=name,
        source=source,
        synthetic=provenance.synthetic,
        value_kind=provenance.value_kind,
        nodata=nodata,
        proxy=provenance.proxy,
        susceptibility_depth_m=provenance.susceptibility_depth_m,
        native_return_period=provenance.native_return_period,
        apply_return_period_scale=provenance.apply_return_period_scale,
    )


def _norm_key(value: str) -> str:
    return value.strip().lower()


def _pick(fields: dict[str, str], names: tuple[str, ...]) -> str:
    for name in names:
        if name in fields:
            return fields[name]
    raise HazardFormatError(f"hazard CSV missing column {names[0]}")


def _as_regular_grid(
    points: list[tuple[float, float, float]],
) -> tuple[list[list[float]], float, float, float, float] | None:
    lats = sorted({round(p[0], 8) for p in points})
    lons = sorted({round(p[1], 8) for p in points})
    if len(lats) * len(lons) != len(points):
        return None
    by_key = {(round(lat, 8), round(lon, 8)): value for lat, lon, value in points}
    if len(by_key) != len(points):
        return None
    # Row 0 is north.
    values = [[by_key[(lat, lon)] for lon in lons] for lat in reversed(lats)]
    if len(lats) == 1 or len(lons) == 1:
        return None
    dlat = lats[1] - lats[0]
    dlon = lons[1] - lons[0]
    if dlat <= 0 or dlon <= 0:
        return None
    west = lons[0] - dlon / 2.0
    east = lons[-1] + dlon / 2.0
    south = lats[0] - dlat / 2.0
    north = lats[-1] + dlat / 2.0
    return values, west, south, east, north
