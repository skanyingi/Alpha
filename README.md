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
python scripts/run_sample_job.py path\to\bordereau.csv
python -m pytest tests -q
uvicorn main:app --port 8000
```

Live service: [https://alpha.onrender.com](https://alpha.onrender.com) (`GET /health`, desk at `/map/`).

The homepage is eight cards. **Upload** opens the source notebook and Gemini writes the summary immediately. Questions in that ask bar also go to Gemini (`POST /api/v1/nlp/summary`, `POST /api/v1/nlp/query`); Jev is not on that path. When `GEMINI_API_KEY` is unset, that path falls back to OpenRouter if `OPENROUTER_API_KEY` is set, and otherwise to a local keyword search. The **AI risk briefing** feeds the modeled statistics, the EP curve, and the ten largest losses to the same LLM chain and returns a short underwriter-readable narrative (`POST /api/v1/nlp/briefing`); it falls back to a deterministic briefing when no provider is available. Studio slides in a preview for Google Docs, Google Slides, graphs, Google Sheets, Google Tasks, and Gmail from the latest job. The desk does not use browser storage. The Nairobi shortcut opens the fullscreen Leaflet map. The answer card Map tab is the other map. **Modeled events** lists jobs held on the server. A bordereau CSV in an upload is modeled and joins the queue. New Apps Script jobs show as colored cards from the top center. Known phrases on the main bar run the desk. Jev standardizes occupancy. Gemini also scores flood imagery when a key is set.

- Webhook: `POST /v1/process-bordereau`
- Map payload: `GET /api/v1/leaflet-export`
- Risk briefing: `POST /api/v1/nlp/briefing`
- Flood evaluate: `POST /api/v1/flood/evaluate`
- 3D elevation grid: `POST /api/spatial/elevation`
- 3D Tiles session: `GET /api/spatial/3d-tiles-session`
- Blender manifest: `GET /api/export/blender-manifest`
- Building footprints: `GET /api/v1/flood/footprints`
- Audit: `GET /api/v1/audit/{event_id}`

Flood exposure on the map is a sidecar. Set `GOOGLE_MAPS_API_KEY` and `GEMINI_API_KEY` in `.env` for geocoding, Static Maps / Street View, and Gemini vision. Set `OPENROUTER_API_KEY` (optional `OPENROUTER_MODEL`, default `openai/gpt-4.1-nano`, and comma-separated `OPENROUTER_FALLBACKS`) to serve the studio chat and summary through OpenRouter when `GEMINI_API_KEY` is unset or its call fails. XL payouts come only from `catmod/finance/`.

Physical loss path, in order: Jev occupancy → `catmod/hazard/` (Nairobi susceptibility converted as `score × 4.0 m`, Nzoia depth, or a CSV / ASCII / GeoTIFF raster) → `catmod/vulnerability/` (`TIV × damage ratio`, cents) → Layer 4. Mounted `nzoia_rp*.tif` files are JRC metre depths and replace the synthetic Nzoia stand-in. `loss_basis=auto` keeps a positive reported ground-up loss as the contractual input and still prices the modeled loss beside it. `loss_basis=modeled` sends the curve loss into the primary waterfall. The job payload includes `ep_curve` (10, 25, 50, 100, 250, and 500-year) and `synthetic`. `python scripts/run_sample_job.py path\to\bordereau.csv` models a CSV you supply. Questions and the Nairobi and Nzoia books use that upload, not a portfolio stored in the repository. `execution_mode=stochastic` adds a synthetic event catalog and Beta damage samples beside that job; the default remains `deterministic`.

Google Apps Script: copy `appsscript.js` into the project and replace the manifest with `appsscript.json`. Script properties:

| Property | What to paste |
|----------|----------------|
| `BACKEND_URL` | `https://alpha.onrender.com` |
| `REGISTRY_SHEET_ID` | Spreadsheet id from `docs.google.com/spreadsheets/d/<id>/edit` |
| `REPORT_TEMPLATE_ID` | Doc id from `docs.google.com/document/d/<id>/edit` |
| `SLIDES_TEMPLATE_ID` | Slides id, or leave blank to auto-build the four-slide deck |
| `DRIVE_FOLDER_ID` | Folder id from `drive.google.com/drive/folders/<id>` |
| `TASKS_LIST_ID` | Task list id, or leave blank for `@default` |
| `UNDERWRITER_EMAIL` | Desk address used when the inbound message has no Reply-To |

Create Gmail label `Catastrophe-Bordereaux` and a 5-minute trigger on `processIncomingBordereaux`. Paste `setup.js` as `setup.gs` and run `setupEnvironment` once to create the archive, registry, and templates. From the editor, run `testTasksIntegration`, `testDriveArchiving`, and `testSlidesGeneration` once to grant scopes. Processed threads are labeled `Catastrophe-Bordereaux/Processed` or `Catastrophe-Bordereaux/Failed`.

Treaty math never uses Jev or HDC. Spatial scores are flags only. Regenerate the source dump with `python scripts/dump_codebase.py`.
