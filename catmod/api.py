"""FastAPI surface: Apps Script webhook + Leaflet export + audit."""

from __future__ import annotations

from typing import Any
import json

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from catmod.config import get_settings
from catmod.jobs import JobStore
from catmod.flood.gemini import gemini_configured
from catmod.flood.maps import MapsError, fetch_aerial, fetch_street_view, geocode_address, maps_configured
from catmod.spatial.elevation import lookup_elevation_m
from catmod.flood.service import (
    buildings_in_viewport,
    evaluate_asset,
    footprints_for_points,
    hazard_collection,
)
from catmod.pipeline import run_pipeline
from catmod.schemas import (
    BlenderManifestIn,
    BordereauWebhook,
    ElevationIn,
    FloodEvaluateIn,
    TilesSessionIn,
)
from catmod.spatial.blender import build_blender_manifest
from catmod.spatial.elevation import build_elevation_payload
from catmod.spatial.presets import list_presets, resolve_preset
from catmod.spatial.tiles3d import create_3d_tiles_session

app = FastAPI(
    title="Catastrophe Reinsurance Analytics",
    version="1.0.0",
    description=(
        "Layered CAT/reinsurance engine: Google Workspace ingestion, Jev System-One triage, "
        "FHRR hyperdimensional spatial memory, deterministic XL math, Leaflet GeoJSON."
    ),
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_STORE: JobStore | None = None


def job_store() -> JobStore:
    global _STORE
    if _STORE is None:
        settings = get_settings()
        _STORE = JobStore(settings.jobs_dir, settings.jobs_keep)
    return _STORE


def _remember(result: dict[str, Any]) -> dict[str, Any]:
    return job_store().remember(result)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/")
def desk_home() -> RedirectResponse:
    return RedirectResponse(url="/map/")


@app.post("/v1/process-bordereau")
def process_bordereau(payload: BordereauWebhook) -> JSONResponse:
    try:
        result = _remember(run_pipeline(payload))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse(result)


@app.get("/api/v1/leaflet-export")
def leaflet_export(event_id: str | None = Query(default=None)) -> JSONResponse:
    store = job_store()
    if not store:
        raise HTTPException(status_code=404, detail="No modeled events saved yet. POST /v1/process-bordereau first.")
    if event_id:
        job = store.get(event_id)
        if job is None:
            raise HTTPException(status_code=404, detail=f"Unknown event_id {event_id}")
    else:
        job = store.latest()
    return JSONResponse(job["geojson"])


@app.get("/api/v1/audit/{event_id}")
def audit(event_id: str) -> JSONResponse:
    job = job_store().get(event_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Unknown event_id {event_id}")
    return JSONResponse(job["audit"])


@app.get("/api/v1/events")
def events() -> dict[str, Any]:
    return {
        "events": [
            {
                "event_id": j["event_id"],
                "client_index_id": j["client_index_id"],
                "total_gross_claim": j["total_gross_claim"],
                "reinsurer_payout": j["reinsurer_payout"],
                "flagged_count": j["flagged_count"],
            }
            for j in job_store().values()
        ]
    }


@app.get("/api/v1/flood/status")
def flood_status() -> dict[str, Any]:
    settings = get_settings()
    return {
        "maps_configured": maps_configured(settings),
        "gemini_configured": gemini_configured(settings),
        "flood_wse_m": settings.flood_wse_m,
        "gemini_model": settings.gemini_model,
        "fallbacks": {
            "geocoding": "nominatim",
            "elevation": "open_meteo",
            "tiles": "esri_world_imagery",
            "street_view": "heuristic_inundation_card",
            "tiles_3d": "procedural_osm",
        },
    }


@app.get("/api/v1/flood/geocode")
def flood_geocode(q: str = Query(..., min_length=3)) -> JSONResponse:
    try:
        return JSONResponse(geocode_address(q))
    except MapsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/v1/flood/evaluate")
def flood_evaluate(payload: FloodEvaluateIn) -> JSONResponse:
    try:
        result = evaluate_asset(
            address=payload.address,
            latitude=payload.latitude,
            longitude=payload.longitude,
            occupancy_hint=payload.occupancy_hint,
            ground_elevation_m=payload.ground_elevation_m,
            asset_id=payload.asset_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except MapsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse(result)


@app.get("/api/v1/flood/footprints")
def flood_footprints(event_id: str | None = Query(default=None)) -> JSONResponse:
    store = job_store()
    if event_id:
        job = store.get(event_id)
        if job is None:
            raise HTTPException(status_code=404, detail=f"Unknown event_id {event_id}")
    elif store:
        job = store.latest()
    else:
        return JSONResponse(footprints_for_points([]))
    return JSONResponse(footprints_for_points(job.get("claims") or []))


@app.get("/api/v1/flood/hazard")
def flood_hazard() -> JSONResponse:
    return JSONResponse(hazard_collection())


@app.get("/api/v1/flood/buildings")
def flood_buildings(
    west: float = Query(...),
    south: float = Query(...),
    east: float = Query(...),
    north: float = Query(...),
) -> JSONResponse:
    return JSONResponse(buildings_in_viewport(west, south, east, north))


@app.get("/api/v1/flood/imagery/aerial")
def flood_aerial(lat: float = Query(...), lng: float = Query(...)) -> Response:
    try:
        payload, mime = fetch_aerial(lat, lng)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Aerial imagery fetch failed: {exc}") from exc
    return Response(content=payload, media_type=mime)


@app.get("/api/v1/flood/imagery/street")
def flood_street(lat: float = Query(...), lng: float = Query(...)) -> Response:
    depth_m = None
    try:
        elev = lookup_elevation_m(lat, lng)
        depth_m = max(0.0, float(get_settings().flood_wse_m) - float(elev))
    except Exception:
        depth_m = None
    try:
        payload, mime = fetch_street_view(lat, lng, depth_m=depth_m)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Street View fetch failed: {exc}") from exc
    return Response(content=payload, media_type=mime)


def _job_or_none(event_id: str | None) -> dict[str, Any] | None:
    store = job_store()
    if event_id:
        job = store.get(event_id)
        if job is None:
            raise HTTPException(status_code=404, detail=f"Unknown event_id {event_id}")
        return job
    return store.latest()


def _blender_payload(event_id: str | None, shader_preset: str, storey_height_m: float) -> dict[str, Any]:
    try:
        resolve_preset(shader_preset)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return build_blender_manifest(
        job=_job_or_none(event_id),
        shader_preset=shader_preset,
        storey_height_m=storey_height_m,
    )


def _blender_response(payload: dict[str, Any], download: bool) -> Response:
    if not download:
        return JSONResponse(payload)
    body = json.dumps(payload, indent=2).encode("utf-8")
    event = payload.get("event_id") or "scene"
    filename = f"blender_manifest_{event}.json"
    return Response(
        content=body,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/api/spatial/elevation")
def spatial_elevation(payload: ElevationIn) -> JSONResponse:
    locations = None
    if payload.locations:
        locations = [(p.latitude, p.longitude) for p in payload.locations]
    bbox = None
    if payload.bbox is not None:
        if len(payload.bbox) != 4:
            raise HTTPException(status_code=400, detail="bbox must be [west, south, east, north]")
        bbox = (payload.bbox[0], payload.bbox[1], payload.bbox[2], payload.bbox[3])
    try:
        result = build_elevation_payload(
            locations=locations,
            bbox=bbox,
            polygon=payload.polygon,
            rows=payload.rows,
            cols=payload.cols,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse(result)


@app.get("/api/spatial/elevation")
def spatial_elevation_get(
    lat: float | None = Query(default=None),
    lng: float | None = Query(default=None),
    west: float | None = Query(default=None),
    south: float | None = Query(default=None),
    east: float | None = Query(default=None),
    north: float | None = Query(default=None),
    rows: int = Query(default=12, ge=2, le=64),
    cols: int = Query(default=12, ge=2, le=64),
) -> JSONResponse:
    locations = [(lat, lng)] if lat is not None and lng is not None else None
    bbox = (west, south, east, north) if None not in (west, south, east, north) else None
    try:
        result = build_elevation_payload(locations=locations, bbox=bbox, rows=rows, cols=cols)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse(result)


@app.post("/api/spatial/3d-tiles-session")
def spatial_3d_tiles_session_post(payload: TilesSessionIn) -> JSONResponse:
    result = create_3d_tiles_session(
        west=payload.west,
        south=payload.south,
        east=payload.east,
        north=payload.north,
        renderer=payload.renderer,
    )
    return JSONResponse(result)


@app.get("/api/spatial/3d-tiles-session")
def spatial_3d_tiles_session_get(
    west: float | None = Query(default=None),
    south: float | None = Query(default=None),
    east: float | None = Query(default=None),
    north: float | None = Query(default=None),
    renderer: str = Query(default="cesium"),
) -> JSONResponse:
    result = create_3d_tiles_session(
        west=west, south=south, east=east, north=north, renderer=renderer
    )
    return JSONResponse(result)


@app.get("/api/spatial/render-presets")
def spatial_render_presets() -> JSONResponse:
    return JSONResponse(list_presets())


@app.get("/api/export/blender-manifest")
def blender_manifest_get(
    event_id: str | None = Query(default=None),
    shader_preset: str = Query(default="PHOTOREAL_DEFAULT"),
    storey_height_m: float = Query(default=3.5, gt=0, le=10),
    download: bool = Query(default=False),
) -> Response:
    payload = _blender_payload(event_id, shader_preset, storey_height_m)
    return _blender_response(payload, download)


@app.post("/api/export/blender-manifest")
def blender_manifest_post(
    payload: BlenderManifestIn,
    download: bool = Query(default=False),
) -> Response:
    body = _blender_payload(payload.event_id, payload.shader_preset, payload.storey_height_m)
    return _blender_response(body, download)


try:
    app.mount("/map", StaticFiles(directory="static", html=True), name="map")
except RuntimeError:
    pass
