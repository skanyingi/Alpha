# Hypervector RAG — Catastrophe Reinsurance Analytics

Five isolated layers: Google Workspace ingestion, Jev System-One triage, FHRR hyperdimensional spatial memory, deterministic Excess-of-Loss math, Leaflet GeoJSON. Hazard lookup, depth-damage curves, and an exceedance-probability curve sit between triage and the treaty waterfall. Layer 4 payouts stay `Decimal` cents. Bundled flood grids and proxy damage curves are tagged `synthetic: true`.

## Documents

| File | Contents |
|------|----------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | System context, sequence, module map, mermaid diagrams |
| [FULL_CODEBASE.txt](FULL_CODEBASE.txt) | Concatenated dump of every source file |

## Quick start

```bash
pip install -r requirements.txt
python scripts/run_sample_job.py
python -m pytest tests -q
uvicorn main:app --port 8000
```

- Webhook: `POST /v1/process-bordereau`
- Map payload: `GET /api/v1/leaflet-export`
- Flood evaluate: `POST /api/v1/flood/evaluate`
- 3D elevation grid: `POST /api/spatial/elevation`
- 3D Tiles session: `GET /api/spatial/3d-tiles-session`
- Blender manifest: `GET /api/export/blender-manifest`
- Building footprints: `GET /api/v1/flood/footprints`
- Audit: `GET /api/v1/audit/{event_id}`

Flood exposure on the map is a sidecar. Set `GOOGLE_MAPS_API_KEY` and `GEMINI_API_KEY` in `.env` for geocoding, Static Maps / Street View, and Gemini vision. XL payouts come only from `catmod/finance/`.

Physical loss path, in order: Jev occupancy → `catmod/hazard/` (Miami, Nairobi, Nzoia, or a CSV / ASCII / GeoTIFF raster) → `catmod/vulnerability/` (`TIV × damage ratio`, cents) → Layer 4. `loss_basis=auto` keeps a positive reported ground-up loss as the contractual input and still prices the modeled loss beside it. `loss_basis=modeled` sends the curve loss into the primary waterfall. The job payload includes `ep_curve` (10, 25, 50, 100, 250, and 500-year) and `synthetic`.

Google Apps Script: copy `appsscript.js` into the project and replace the manifest with `appsscript.json`. Script properties:

| Property | What to paste |
|----------|----------------|
| `BACKEND_URL` | Public FastAPI origin, no path (`https://your-api.example.com`) |
| `REGISTRY_SHEET_ID` | Spreadsheet id from `docs.google.com/spreadsheets/d/<id>/edit` |
| `REPORT_TEMPLATE_ID` | Doc id from `docs.google.com/document/d/<id>/edit` |
| `SLIDES_TEMPLATE_ID` | Slides id, or leave blank to auto-build the four-slide deck |
| `DRIVE_FOLDER_ID` | Folder id from `drive.google.com/drive/folders/<id>` |
| `TASKS_LIST_ID` | Task list id, or leave blank for `@default` |
| `UNDERWRITER_EMAIL` | Desk address used when the inbound message has no Reply-To |

Create Gmail label `Catastrophe-Bordereaux` and a 5-minute trigger on `processIncomingBordereaux`. From the editor, run `testTasksIntegration`, `testDriveArchiving`, and `testSlidesGeneration` once to grant scopes. Processed threads are labeled `Catastrophe-Bordereaux/Processed` or `Catastrophe-Bordereaux/Failed`.

Treaty math never uses Jev or HDC. Spatial scores are flags only. Regenerate the source dump with `python scripts/dump_codebase.py`.
