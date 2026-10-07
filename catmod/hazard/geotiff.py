"""Classic-TIFF GeoTIFF reader and writer for one uncompressed float band.

No GDAL or rasterio dependency. The reader accepts little- or big-endian
classic TIFF (magic 42) with ModelPixelScale (33550) and ModelTiepoint (33922).
The upper-left tiepoint is the outer corner of pixel (0, 0).
"""

from __future__ import annotations

import struct
from pathlib import Path

from catmod.hazard.raster import HazardFormatError, HazardRaster

_TYPE_SIZE = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 11: 4, 12: 8}


def load_geotiff(path: str | Path, *, provenance=None, synthetic: bool | None = None, name: str | None = None) -> HazardRaster:
    from catmod.hazard.provenance import apply_synthetic_override, infer_provenance

    source = Path(path)
    prov = apply_synthetic_override(provenance or infer_provenance(source), synthetic)
    raster = parse_geotiff(source.read_bytes(), source=prov.source if prov.name else str(source), synthetic=prov.synthetic, name=name or prov.name or source.stem)
    raster.proxy = prov.proxy
    raster.value_kind = prov.value_kind
    raster.susceptibility_depth_m = prov.susceptibility_depth_m
    raster.native_return_period = prov.native_return_period
    raster.apply_return_period_scale = prov.apply_return_period_scale
    return raster


def parse_geotiff(data: bytes, *, source: str, synthetic: bool, name: str) -> HazardRaster:
    if len(data) < 8:
        raise HazardFormatError("GeoTIFF is truncated")
    if data[:2] == b"II":
        endian = "<"
    elif data[:2] == b"MM":
        endian = ">"
    else:
        raise HazardFormatError("not a TIFF (missing II/MM byte order)")
    magic = struct.unpack_from(endian + "H", data, 2)[0]
    if magic != 42:
        raise HazardFormatError("BigTIFF and non-classic TIFF are not supported")
    ifd = struct.unpack_from(endian + "I", data, 4)[0]
    tags = _read_ifd(data, endian, ifd)
    width = int(_one(tags, 256, "ImageWidth"))
    height = int(_one(tags, 257, "ImageLength"))
    bits = int(_one(tags, 258, "BitsPerSample"))
    compression = int(_one(tags, 259, "Compression")) if 259 in tags else 1
    if compression != 1:
        raise HazardFormatError(f"compressed GeoTIFF (code {compression}) is not supported")
    sample_format = int(_one(tags, 339, "SampleFormat")) if 339 in tags else 1
    samples = int(_one(tags, 277, "SamplesPerPixel")) if 277 in tags else 1
    if samples != 1:
        raise HazardFormatError("only single-band GeoTIFF hazard grids are supported")
    strip_offsets = [int(v) for v in tags.get(273, [])]
    strip_bytes = [int(v) for v in tags.get(279, [])]
    if not strip_offsets or len(strip_offsets) != len(strip_bytes):
        raise HazardFormatError("GeoTIFF strips are missing")
    blob = b"".join(data[off : off + count] for off, count in zip(strip_offsets, strip_bytes))
    values = _decode_band(blob, width, height, bits, sample_format, endian)
    if 33550 not in tags or 33922 not in tags:
        raise HazardFormatError("GeoTIFF is missing ModelPixelScale or ModelTiepoint")
    scale_x, scale_y = float(tags[33550][0]), float(tags[33550][1])
    tie = tags[33922]
    if len(tie) < 6:
        raise HazardFormatError("ModelTiepoint must contain I,J,K,X,Y,Z")
    # Pixel (0, 0) corner maps to (origin_x, origin_y) at the upper left.
    origin_x = float(tie[3]) - float(tie[0]) * scale_x
    origin_y = float(tie[4]) + float(tie[1]) * scale_y
    nodata = -9999.0
    if 42113 in tags:
        text = str(tags[42113][0]).strip()
        if text and text.lower() != "nan":
            nodata = float(text)
    return HazardRaster(
        values=values,
        west=origin_x,
        south=origin_y - height * scale_y,
        east=origin_x + width * scale_x,
        north=origin_y,
        name=name,
        source=source,
        synthetic=synthetic,
        nodata=nodata,
    )


def write_geotiff(
    path: str | Path,
    values: list[list[float]],
    *,
    west: float,
    north: float,
    cell_lon: float,
    cell_lat: float,
    nodata: float = -9999.0,
) -> None:
    """Write a little-endian uncompressed float32 GeoTIFF."""
    rows = len(values)
    cols = len(values[0]) if values else 0
    if rows == 0 or cols == 0:
        raise HazardFormatError("cannot write an empty GeoTIFF")
    raster = b"".join(struct.pack("<f", float(v)) for row in values for v in row)
    scale = struct.pack("<3d", float(cell_lon), float(cell_lat), 0.0)
    tie = struct.pack("<6d", 0.0, 0.0, 0.0, float(west), float(north), 0.0)
    nodata_bytes = str(nodata).encode("ascii") + b"\x00"
    raster_off = 8
    scale_off = raster_off + len(raster)
    tie_off = scale_off + len(scale)
    nodata_off = tie_off + len(tie)
    ifd_off = nodata_off + len(nodata_bytes)
    tags = [
        (256, 4, 1, struct.pack("<I", cols)),
        (257, 4, 1, struct.pack("<I", rows)),
        (258, 3, 1, struct.pack("<H", 32) + b"\x00\x00"),
        (259, 3, 1, struct.pack("<H", 1) + b"\x00\x00"),
        (262, 3, 1, struct.pack("<H", 1) + b"\x00\x00"),
        (273, 4, 1, struct.pack("<I", raster_off)),
        (277, 3, 1, struct.pack("<H", 1) + b"\x00\x00"),
        (278, 4, 1, struct.pack("<I", rows)),
        (279, 4, 1, struct.pack("<I", len(raster))),
        (284, 3, 1, struct.pack("<H", 1) + b"\x00\x00"),
        (339, 3, 1, struct.pack("<H", 3) + b"\x00\x00"),
        (33550, 12, 3, struct.pack("<I", scale_off)),
        (33922, 12, 6, struct.pack("<I", tie_off)),
        (42113, 2, len(nodata_bytes), struct.pack("<I", nodata_off)),
    ]
    ifd = struct.pack("<H", len(tags))
    for tag, typ, count, payload in tags:
        ifd += struct.pack("<HHI", tag, typ, count) + payload
    ifd += struct.pack("<I", 0)
    blob = b"II" + struct.pack("<HI", 42, ifd_off) + raster + scale + tie + nodata_bytes + ifd
    Path(path).write_bytes(blob)


def _read_ifd(data: bytes, endian: str, offset: int) -> dict[int, list[object]]:
    count = struct.unpack_from(endian + "H", data, offset)[0]
    tags: dict[int, list[object]] = {}
    cursor = offset + 2
    for _ in range(count):
        tag, typ, n = struct.unpack_from(endian + "HHI", data, cursor)
        raw = data[cursor + 8 : cursor + 12]
        size = _TYPE_SIZE.get(typ)
        if size is None:
            cursor += 12
            continue
        nbytes = size * n
        if nbytes <= 4:
            payload = raw
        else:
            ptr = struct.unpack_from(endian + "I", raw, 0)[0]
            payload = data[ptr : ptr + nbytes]
        tags[tag] = _decode_values(payload, typ, n, endian)
        cursor += 12
    return tags


def _decode_values(payload: bytes, typ: int, count: int, endian: str) -> list[object]:
    values: list[object] = []
    if typ == 2:
        text = payload[:count].split(b"\x00", 1)[0].decode("ascii", errors="replace")
        return [text]
    fmt = {1: "B", 3: "H", 4: "I", 11: "f", 12: "d"}.get(typ)
    if fmt is None and typ == 5:
        for i in range(count):
            num, den = struct.unpack_from(endian + "II", payload, i * 8)
            values.append(num / den if den else 0.0)
        return values
    if fmt is None:
        return []
    for i in range(count):
        values.append(struct.unpack_from(endian + fmt, payload, i * _TYPE_SIZE[typ])[0])
    return values


def _one(tags: dict[int, list[object]], tag: int, label: str) -> object:
    if tag not in tags or not tags[tag]:
        raise HazardFormatError(f"GeoTIFF tag {label} is missing")
    return tags[tag][0]


def _decode_band(
    blob: bytes,
    width: int,
    height: int,
    bits: int,
    sample_format: int,
    endian: str,
) -> list[list[float]]:
    if bits == 32 and sample_format == 3:
        fmt = endian + "f"
        step = 4
    elif bits == 32 and sample_format in {1, 2}:
        fmt = endian + ("i" if sample_format == 2 else "I")
        step = 4
    elif bits == 16:
        fmt = endian + ("h" if sample_format == 2 else "H")
        step = 2
    else:
        raise HazardFormatError(f"unsupported sample bits={bits} format={sample_format}")
    expected = width * height * step
    if len(blob) < expected:
        raise HazardFormatError("GeoTIFF strip data is shorter than the raster")
    values: list[list[float]] = []
    cursor = 0
    for _ in range(height):
        row: list[float] = []
        for _col in range(width):
            row.append(float(struct.unpack_from(fmt, blob, cursor)[0]))
            cursor += step
        values.append(row)
    return values
