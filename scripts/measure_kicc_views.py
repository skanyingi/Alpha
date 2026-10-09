"""Measure KICC proportions from the three source captures. Not a survey."""
import json
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
ASSETS = Path(r"C:\Users\grvns\.cursor\projects\c-Users-grvns-Pictures-Hypervector-RAG\assets")
FILES = {
    "skyline": ASSETS / "c__Users_grvns_AppData_Roaming_Cursor_User_workspaceStorage_2722d3be9081fba0873ad0fbbad807fa_images_image-bfe87012-4a52-4e2f-8505-7213d802e4b1.png",
    "plaza": ASSETS / "c__Users_grvns_AppData_Roaming_Cursor_User_workspaceStorage_2722d3be9081fba0873ad0fbbad807fa_images_image-3240f4b0-4fed-493b-a2fc-1c6dd27996d5.png",
    "overcast": ASSETS / "c__Users_grvns_AppData_Roaming_Cursor_User_workspaceStorage_2722d3be9081fba0873ad0fbbad807fa_images_image-baba9d27-8ac9-40f3-8977-ae964700aa31.png",
}
OUT = ROOT / "static" / "kicc" / "capture_measurements.json"


def mask_of(rgb):
    r = rgb[:, :, 0].astype(np.int16)
    g = rgb[:, :, 1].astype(np.int16)
    b = rgb[:, :, 2].astype(np.int16)
    pink = (r > 145) & (r < 230) & (r > g + 10) & (r > b + 4) & (g > 85) & (g < 195) & (b > 80) & (b < 195)
    return pink


def largest_column_band(mask, min_frac=0.08):
    cols = mask.sum(axis=0)
    if cols.max() < mask.shape[0] * min_frac:
        return None
    hot = cols > cols.max() * 0.45
    idx = np.flatnonzero(hot)
    if idx.size == 0:
        return None
    # Keep the densest contiguous run.
    splits = np.where(np.diff(idx) > 8)[0]
    ranges = []
    start = 0
    for cut in list(splits) + [len(idx) - 1]:
        run = idx[start:cut + 1]
        ranges.append(run)
        start = cut + 1
    run = max(ranges, key=lambda item: int(cols[item].sum()))
    return int(run[0]), int(run[-1])


def row_span(mask, x0, x1):
    rows = mask[:, x0:x1 + 1].sum(axis=1)
    hot = np.flatnonzero(rows > max(3, (x1 - x0) * 0.15))
    if hot.size == 0:
        return None
    return int(hot[0]), int(hot[-1])


def ring_count(rgb, mask, x0, x1, y0, y1):
    shaft = rgb[y0:y1 + 1, x0:x1 + 1].astype(np.float32)
    m = mask[y0:y1 + 1, x0:x1 + 1]
    if shaft.size == 0 or m.sum() < 50:
        return None
    gray = shaft.mean(axis=2)
    profile = []
    for row, on in zip(gray, m):
        if on.sum() < 4:
            profile.append(np.nan)
        else:
            profile.append(float(row[on].mean()))
    profile = np.array(profile, dtype=np.float32)
    valid = np.isfinite(profile)
    if valid.sum() < 16:
        return None
    filled = profile.copy()
    idx = np.arange(len(filled))
    filled[~valid] = np.interp(idx[~valid], idx[valid], profile[valid])
    kernel = np.array([1, 2, 3, 2, 1], dtype=np.float32)
    kernel /= kernel.sum()
    smooth = np.convolve(filled, kernel, mode="same")
    # Drop the top cap, which is a solid disc rather than rings.
    body = smooth[int(len(smooth) * 0.08): int(len(smooth) * 0.92)]
    deriv = np.diff(body)
    # A ring edge is a local swing larger than a fraction of the profile range.
    span = float(body.max() - body.min()) or 1.0
    thresh = max(1.2, span * 0.08)
    peaks = 0
    last = -999
    for i in range(1, len(deriv) - 1):
        if deriv[i - 1] > 0 and deriv[i] <= 0 and abs(deriv[i - 1]) + abs(deriv[i]) > thresh:
            if i - last > 2:
                peaks += 1
                last = i
    return {
        "edge_peaks": int(peaks),
        "profile_span": round(span, 2),
        "body_rows": int(len(body)),
    }


def widths_by_row(mask, x0, x1, y0, y1):
    out = []
    for y in range(y0, y1 + 1):
        xs = np.flatnonzero(mask[y, x0:x1 + 1])
        if xs.size < 2:
            continue
        out.append((y - y0, int(xs[-1] - xs[0] + 1)))
    return out


def ring_column_score(gray):
    """Columns whose vertical profile has a regular stack of edges."""
    gy = np.abs(np.diff(gray.astype(np.float32), axis=0))
    scores = []
    h, w = gy.shape
    for x in range(w):
        col = gy[:, x]
        # Ignore the lower foreground.
        col = col[: int(h * 0.78)]
        thresh = max(8.0, float(np.percentile(col, 92)))
        hot = col > thresh
        peaks = 0
        last = -99
        for i, on in enumerate(hot):
            if on and i - last > 2:
                peaks += 1
                last = i
        scores.append(peaks)
    return np.array(scores)


def band_from_scores(scores):
    if scores.max() < 6:
        return None
    thresh = max(6, int(scores.max() * 0.55))
    hot = np.flatnonzero(scores >= thresh)
    if hot.size == 0:
        return None
    splits = np.where(np.diff(hot) > 6)[0]
    ranges = []
    start = 0
    for cut in list(splits) + [len(hot) - 1]:
        ranges.append(hot[start:cut + 1])
        start = cut + 1
    run = max(ranges, key=lambda item: float(scores[item].sum()))
    return int(run[0]), int(run[-1]), int(scores[run].max())


def measure_edge_band(name, rgb, gray, scored):
    if not scored:
        return None
    x0, x1, peak_max = scored
    h, w = gray.shape
    gy = np.abs(np.diff(gray, axis=0))
    # Vertical extent: rows where this x-band has repeated edges.
    band = gy[:, x0:x1 + 1].mean(axis=1)
    thresh = max(4.0, float(np.percentile(band, 75)))
    hot = np.flatnonzero(band > thresh)
    if hot.size < 8:
        return None
    y0, y1 = int(hot[0]), int(min(h - 1, hot[-1] + 1))
    # Shaft width is the scored column run. Saucer is darker and wider, so search
    # a short strip under the top of the band for a luminance drop that is wider.
    shaft_w = float(x1 - x0 + 1)
    tower_h = float(y1 - y0 + 1)
    mid_y0 = y0 + int(tower_h * 0.28)
    mid_y1 = y0 + int(tower_h * 0.62)
    cx = (x0 + x1) // 2
    sample = rgb[mid_y0:mid_y1, max(0, cx - 6):min(w, cx + 7)]
    color = [int(v) for v in np.median(sample.reshape(-1, 3), axis=0)] if sample.size else None
    profile = gray[y0:y1, cx]
    # High-pass peak spacing along the shaft, excluding the top 18% (saucer).
    body = profile[int(len(profile) * 0.18): int(len(profile) * 0.9)]
    if len(body) > 12:
        smooth = np.convolve(body, np.array([1, 2, 1]) / 4.0, mode="same")
        deriv = np.diff(smooth)
        span = float(np.max(smooth) - np.min(smooth)) or 1.0
        thresh_d = max(0.6, span * 0.045)
        gaps = []
        last = None
        for i in range(1, len(deriv) - 1):
            swing = abs(float(deriv[i - 1])) + abs(float(deriv[i]))
            if deriv[i - 1] > 0 and deriv[i] <= 0 and swing > thresh_d:
                if last is not None and 2 <= i - last <= 18:
                    gaps.append(i - last)
                last = i
        median_gap = float(np.median(gaps)) if gaps else None
        body_rows = int(len(body))
        ring_estimate = int(round(body_rows / median_gap)) if median_gap else None
    else:
        median_gap = None
        ring_estimate = None
        body_rows = int(len(body))
    crop_dir = OUT.parent / "crops"
    crop_dir.mkdir(parents=True, exist_ok=True)
    pad = 18
    crop = rgb[max(0, y0 - pad):min(h, y1 + pad), max(0, x0 - pad):min(w, x1 + pad)]
    Image.fromarray(crop).save(crop_dir / f"{name}.png")
    return {
        "x0": x0,
        "x1": x1,
        "y0": y0,
        "y1": y1,
        "peak_max": peak_max,
        "tower_height_px": tower_h,
        "shaft_width_px": shaft_w,
        "height_over_shaft_width": round(tower_h / shaft_w, 3) if shaft_w else None,
        "shaft_rgb": color,
        "ring_gap_px": None if median_gap is None else round(median_gap, 2),
        "ring_estimate": ring_estimate,
        "body_rows": body_rows,
    }


def analyze(name, path):
    rgb = np.asarray(Image.open(path).convert("RGB"))
    gray = rgb.astype(np.float32).mean(axis=2)
    scores = ring_column_score(gray)
    scored = band_from_scores(scores)
    mask = mask_of(rgb)
    band = largest_column_band(mask)
    record_scores = None
    if scored:
        record_scores = {"x0": scored[0], "x1": scored[1], "peak_max": scored[2]}
    record = {
        "id": name,
        "file": path.name,
        "width_px": int(rgb.shape[1]),
        "height_px": int(rgb.shape[0]),
        "mask_px": int(mask.sum()),
        "median_rgb": None,
    }
    if mask.sum() > 20:
        cols = rgb[mask]
        record["median_rgb"] = [int(v) for v in np.median(cols, axis=0)]
    record["edge_band"] = measure_edge_band(name, rgb, gray, scored)
    if not band:
        record["tower"] = None
        return record
    x0, x1 = band
    span = row_span(mask, x0, x1)
    if not span:
        record["tower"] = None
        return record
    y0, y1 = span
    pairs = widths_by_row(mask, max(0, x0 - 40), min(rgb.shape[1] - 1, x1 + 40), y0, y1)
    if len(pairs) < 8:
        record["tower"] = None
        return record
    heights = np.array([p[0] for p in pairs])
    widths = np.array([p[1] for p in pairs])
    # Mid-shaft: middle 40% of the detected column, where the saucer and podium are excluded.
    lo, hi = np.quantile(heights, [0.35, 0.72])
    mid = widths[(heights >= lo) & (heights <= hi)]
    top = widths[heights <= np.quantile(heights, 0.12)]
    shaft_w = float(np.median(mid)) if mid.size else float(np.median(widths))
    saucer_w = float(np.median(top)) if top.size else shaft_w
    tower_h = float(y1 - y0 + 1)
    record["tower"] = {
        "x0": x0,
        "x1": x1,
        "y0": y0,
        "y1": y1,
        "tower_height_px": tower_h,
        "shaft_width_px": round(shaft_w, 2),
        "saucer_width_px": round(saucer_w, 2),
        "height_over_shaft_width": round(tower_h / shaft_w, 3) if shaft_w else None,
        "saucer_over_shaft": round(saucer_w / shaft_w, 3) if shaft_w else None,
        "rings": ring_count(rgb, mask, x0, x1, y0, y1),
    }
    return record


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for name, path in FILES.items():
        rows.append(analyze(name, path))
    aspects = [
        row["tower"]["height_over_shaft_width"]
        for row in rows
        if row.get("tower") and row["tower"].get("height_over_shaft_width")
    ]
    peaks = [
        row["tower"]["rings"]["edge_peaks"]
        for row in rows
        if row.get("tower") and row["tower"].get("rings")
    ]
    summary = {
        "height_m_published": 105.2,
        "aspects": aspects,
        "median_aspect": float(np.median(aspects)) if aspects else None,
        "implied_shaft_diameter_m": None,
        "ring_peak_counts": peaks,
        "views": rows,
        "note": "Single-image proportions from the three supplied captures. Not stereo, not lidar.",
    }
    if summary["median_aspect"]:
        summary["implied_shaft_diameter_m"] = round(105.2 / summary["median_aspect"], 2)
    OUT.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(OUT)
    edges = {row["id"]: row.get("edge_band") for row in rows}
    print(json.dumps(edges, indent=2))


if __name__ == "__main__":
    main()
