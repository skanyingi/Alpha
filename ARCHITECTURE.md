# Hypervector RAG — Full Architecture

Catastrophe modeling and reinsurance portfolio analytics. The system ingests messy cedant/broker bordereaux through Google Workspace, triages each line with a sub-second System-One harness (Jev), looks up flood depth, converts that depth to a damage ratio and a cents-rounded ground-up loss, stores the event footprint in a single FHRR hypervector, calculates Excess-of-Loss payouts with deterministic actuarial math, and emits an exceedance-probability curve, Leaflet GeoJSON, and an executive audit report.

**Rule of isolation:** Layers 2 and 3 may classify and interpolate. Hazard severity and damage ratios are physical. Layer 4 money is `Decimal` cents (`ROUND_HALF_EVEN`) and is never approximated by a model or a vector. Bundled flood grids and proxy damage curves are tagged `synthetic: true`.

---

## 1. What the system does

| Step | Layer | Input | Output |
|------|-------|--------|--------|
| 1 | Google Workspace | Gmail `.csv` / `.xlsx` / `.pdf` | Client Index ID, Sheet row, webhook POST |
| 2 | Jev System-One | Raw bordereau lines | Occupancy Choice, fraud Noul, spatial Score, route |
| 2b | Hazard | Latitude, longitude, return period | Flood depth (m) or susceptibility, anomaly flags |
| 2c | Vulnerability | Occupancy code, depth, TIV | Damage ratio in `[0, 1]`, ground-up loss in Decimal cents |
| 3 | HDC / FHRR | Location, occupancy, damage ratio | Superposition memory `M`, interpolation, clusters, `M(t+Δt)` |
| 4 | Finance | Selected GUL, deductibles, limits, treaty | Cedant net, reinsurer paid, reinstatement, TVaR/PML |
| 5 | Leaflet + EP + Docs | Enriched claims, scenario catalog | GeoJSON, OEP curve, Google Doc PDF email |

```text
Exposure → hazard depth → damage ratio → TIV × DR → ground-up loss (Decimal cents)
        → deductible → limit → XL layer → reinstatement
        → FHRR memory update and EP / Leaflet export
```

Default treaty: `$100M xs $40M`, 90% share, one reinstatement at 100% of the layer premium. Portfolios come from an uploaded bordereau. `python scripts/run_sample_job.py path\to\bordereau.csv` models that file. The desk does not read a sample portfolio from the repository. Jev batch budget is 500 ms. Full pipeline budget is 1000 ms.

---

## 2. System context

```mermaid
flowchart LR
  subgraph External
    C[Cedant / broker]
    U[Underwriter]
    JevAPI[Optional hosted Jev<br/>jevtypesafeai.com]
  end

  subgraph GoogleWorkspace["Layer 1 — Google Workspace"]
    Gmail[Gmail label<br/>Catastrophe-Bordereaux]
    Sheet[Master registry Sheet]
    Docs[Audit report Doc]
  end

  subgraph Backend["Python API — main:app"]
    WH[POST /v1/process-bordereau]
    Pipe[catmod.pipeline.run_pipeline]
    Map[GET /api/v1/leaflet-export]
    Ev[GET /api/v1/events]
    Aud[GET /api/v1/audit/event_id]
  end

  subgraph Browser
    Desk[CatMod desk + toasts<br/>static/index.html]
    Leaf[Leaflet map<br/>static/map.html]
  end

  C -->|bordereau email| Gmail
  Gmail --> Sheet
  Gmail -->|JSON + CSV/base64| WH
  WH --> Pipe
  Pipe -.->|occupancy UNK + JEV_API_KEY| JevAPI
  Pipe --> Map
  Pipe --> Ev
  Pipe --> Aud
  WH -->|placeholders + totals| Docs
  Docs -->|PDF cover note| U
  Desk -->|poll new event ids| Ev
  Leaf --> Map
```

---

## 3. Runtime sequence

```mermaid
sequenceDiagram
  autonumber
  participant GAS as Apps Script
  participant API as FastAPI
  participant P as pipeline
  participant J as Jev harness
  participant H as FHRR memory
  participant F as XL waterfall
  participant L as Leaflet GeoJSON
  participant A as audit JSONL

  GAS->>API: POST /v1/process-bordereau
  API->>P: BordereauWebhook
  P->>A: L1 webhook + parse
  P->>J: triage_batch(claims)
  J-->>P: Choice / Score / Noul + route
  P->>A: L2 jev_triage_complete
  P->>P: hazard lookup, then depth-damage Decimal GUL
  P->>A: L8 hazard_lookup_complete / L9 vulnerability_complete
  P->>H: encode location, occupancy, damage ratio into M
  P->>H: physics_validate if route=hdc_physics
  P->>H: exposure_clusters + project_time
  P->>A: L3 hdc_query_complete
  P->>F: selected GUL → terms → XL → RP → TVaR
  P->>F: modeled Decimal GUL through the same waterfall
  Note over F: Decimal cents, no LLM, no vectors
  P->>A: L4 financial_waterfall_complete
  P->>L: OEP curve + FeatureCollection + hazard polygon
  P->>A: L10 ep_curve_complete / L5 leaflet_geojson_emitted
  API-->>GAS: event_id, payouts, placeholders, geojson, ep_curve, audit
  GAS->>GAS: fill {{PLACEHOLDERS}}, email PDF
```

---

## 4. Separation of duties

```mermaid
flowchart TB
  subgraph L2["Layer 2 — Jev  (semantic, fast, non-authoritative for money)"]
    Occ[Occupancy Choice]
    Fraud[Fraud Noul]
    Sev[Spatial Score]
    Route{confidence > 0.95<br/>and clean?}
    Occ --> Route
    Fraud --> Route
    Sev --> Route
  end

  subgraph PhysModel["Hazard + vulnerability  (physical, Decimal at the money boundary)"]
    Haz[Depth or susceptibility]
    DR["DR in 0..1"]
    MGUL["GUL = TIV × DR, cents"]
    Haz --> DR --> MGUL
  end

  subgraph L3["Layer 3 — HDC  (spatial memory, not contractual)"]
    Enc["H includes location, occupancy, DR"]
    Mem[M = Σ H_i]
    Phys[Interpolation + physics flag]
    Enc --> Mem --> Phys
  end

  subgraph L4["Layer 4 — Finance  (sole source of payout)"]
    GUL[min(GUL, limit) − deductible]
    Coin[× coinsurance]
    XL["layer = min(max(gross − attach, 0), limit)"]
    Share[× coparticipation]
    RP["RP = min(exhaustion, reinstatements) × rate × premium"]
    GUL --> Coin --> XL --> Share --> RP
  end

  Occ --> Haz
  Route -->|finance| L4
  Route -->|hdc_physics| L3
  MGUL -->|loss_basis modeled, or reported GUL is 0| GUL
  L3 -->|flag / interpolation score only| L4
  L4 -->|covered + allocated XL| L5[Layer 5 GeoJSON + EP curve]
```

HDC interpolation **never** overwrites `ground_up_loss`, `reinsurer_payout`, or `cedant_retained_loss`. Those fields come only from `catmod/finance/`. When `loss_basis` is `auto` (the default) or `reported`, a positive bordereau ground-up loss stays the contractual input. `loss_basis=modeled`, or a zero reported ground-up loss, sends the vulnerability module's `Decimal` cents into that same waterfall. The modeled waterfall always runs beside it and is audited as `modeled_vulnerability_waterfall`.

---

## 5. File and module map

```text
Hypervector RAG/
├── main.py                      FastAPI entry; re-exports FHRR + XL + GeoJSON
├── appsscript.js                Layer 1 Gmail / Sheets / Docs / Slides / Tasks
├── appsscript.json              OAuth scopes
├── setup.js                     one-shot Apps Script environment bootstrap
├── render.yaml                  Render Starter blueprint (service name alpha)
├── requirements.txt
├── pytest.ini
├── .env.example
├── ARCHITECTURE.md              this file
├── README.md
├── FULL_CODEBASE.txt            concatenated source dump
├── save-the-earth.html          public flood leaflet page
├── catmod/
│   ├── api.py                   HTTP surface
│   ├── pipeline.py              job orchestrator
│   ├── schemas.py               Pydantic contracts
│   ├── config.py                env settings
│   ├── audit.py                 JSONL layer verification
│   ├── ingestion/               parse CSV / XLSX / PDF + IDs
│   ├── jev/                     Choice / Score / Noul harness
│   ├── hazard/                  raster, GeoTIFF, provenance, stochastic catalog
│   ├── vulnerability/           depth-damage curves, Beta samples, Decimal GUL
│   ├── analytics/               OEP/AEP curve, EAL, VaR, TVaR, PML
│   ├── hdc/                     FHRR algebra, memory, physics
│   ├── finance/                 treaty, waterfall, empirical TVaR/PML
│   ├── leaflet/                 GeoJSON + style
│   ├── flood/                   map sidecar (geocode, vision, footprints)
│   ├── geo/                     open-stack fallbacks
│   └── spatial/                 elevation, 3D Tiles, Blender, presets
├── data/
│   └── flood_hazard/                    hazard extent overlay
├── templates/reinsurance_audit_report.txt
├── static/
│   ├── index.html               CatMod desk: search, event queue, toasts
│   ├── map.html                 Leaflet loss map
│   ├── modes.js                 answer-card tabs
│   ├── renderPresets.js         browser mirror of spatial presets
│   └── samples/                 desk CSV fixtures
├── scripts/run_sample_job.py    Nairobi modeled job
├── scripts/dump_codebase.py     regenerates FULL_CODEBASE.txt
├── tests/
└── audit_logs/                  per-event JSONL
```

```mermaid
flowchart TB
  subgraph Root
    main[main.py]
    gas[appsscript.js]
  end

  subgraph catmod
    api[api.py]
    pipe[pipeline.py]
    schemas[schemas.py]
    cfg[config.py]
    audit[audit.py]
  end

  subgraph ingest["ingestion/"]
    parser[parser.py]
    idx[indexing.py]
  end

  subgraph jev["jev/"]
    harness[harness.py]
    occ[occupancy.py]
    prim[primitives.py]
    client[client.py]
  end

  subgraph hdc["hdc/"]
    fhrr[fhrr.py]
    enc[encoding.py]
    mem[memory.py]
    phys[physics.py]
  end

  subgraph fin["finance/"]
    treaty[treaty.py]
    water[waterfall.py]
    metrics[metrics.py]
  end

  subgraph haz["hazard/"]
    raster[raster.py]
    geotiff[geotiff.py]
    surfaces[surfaces.py]
    prov[provenance.py]
    hsvc[service.py]
  end

  subgraph side["Sidecar — not contractual money"]
    flood[flood/]
    fallback[geo/fallback.py]
    spatial[spatial/]
  end

  subgraph vuln["vulnerability/"]
    curves[curves.py]
    veng[engine.py]
  end

  subgraph analytics["analytics/"]
    ep[ep_curve.py]
  end

  subgraph leaf["leaflet/"]
    geo[geojson.py]
  end

  gas --> api
  main --> api
  api --> pipe
  pipe --> parser
  pipe --> idx
  pipe --> harness
  pipe --> hsvc
  pipe --> veng
  pipe --> ep
  pipe --> enc
  pipe --> mem
  pipe --> phys
  pipe --> water
  pipe --> metrics
  pipe --> geo
  pipe --> audit
  hsvc --> raster
  hsvc --> surfaces
  hsvc --> prov
  raster --> geotiff
  surfaces --> prov
  api --> flood
  api --> spatial
  flood --> fallback
  spatial --> fallback
  veng --> curves
  ep --> hsvc
  ep --> veng
  harness --> occ
  harness --> prim
  harness --> client
  enc --> fhrr
  mem --> fhrr
  water --> treaty
  pipe --> schemas
  pipe --> cfg

  water -.->|forbidden| hdc
  water -.->|forbidden| jev
  water -.->|forbidden| haz
  water -.->|forbidden| analytics
```

---

## 6. HTTP and Google contracts

| Method | Path | Role |
|--------|------|------|
| GET | `/health` | Liveness |
| GET | `/` | Redirect to `/map/` |
| POST | `/v1/process-bordereau` | Apps Script / CLI webhook |
| GET | `/api/v1/leaflet-export?event_id=` | GeoJSON for the map |
| GET | `/api/v1/audit/{event_id}` | Layer verification |
| GET | `/api/v1/events` | In-memory job index (last 32) |
| GET | `/api/v1/flood/status` | Maps, Gemini, and fallback names |
| GET | `/api/v1/flood/geocode?q=` | Address to coordinates |
| POST | `/api/v1/flood/evaluate` | Geocode, footprint, imagery, flood score |
| GET | `/api/v1/flood/footprints?event_id=` | Footprints for a job |
| GET | `/api/v1/flood/hazard` | Surge polygon |
| GET | `/api/v1/flood/buildings` | Viewport footprints |
| GET | `/api/v1/flood/imagery/aerial` | Aerial image bytes |
| GET | `/api/v1/flood/imagery/street` | Street-level image bytes |
| GET, POST | `/api/spatial/elevation` | Point or grid heights |
| GET, POST | `/api/spatial/3d-tiles-session` | Cesium session or procedural fallback |
| GET | `/api/spatial/render-presets` | Shader presets |
| GET, POST | `/api/export/blender-manifest` | Blender scene JSON |
| GET | `/map/` | CatMod desk (`static/index.html`) |
| GET | `/map/map.html` | Leaflet loss map for one event |

Webhook body (`BordereauWebhook`): `client_email`, `filename`, `data` (CSV text) or `data_base64` (xlsx/pdf), optional `treaty`, `hazard_polygon`, `client_index_id`, `source_urls` (Drive or document links taken from the email body). Catastrophe-model fields: `loss_basis` (`auto` | `reported` | `modeled`), `return_period` (10, 25, 50, 100, 250, 500; default 100), `hazard_region` (`nairobi`, `nzoia`), `hazard_raster_path` (CSV, ESRI ASCII `.asc`, or uncompressed GeoTIFF).

Job JSON adds `modeled_ground_up_loss`, `modeled_waterfall`, `ep_curve`, `treaty` (`attachment_point`, `limit`, `label`), `source_urls`, and a `synthetic` object. Leaflet metadata carries `synthetic: true` and the same EP curve.

Report placeholders filled by Apps Script:

`{{CLIENT_NAME}}` `{{EVENT_ID}}` `{{GROUND_UP_LOSS}}` `{{REINSURER_PAYOUT}}` `{{CEDANT_RETENTION}}` `{{FRAUD_FLAG_COUNT}}` `{{MODELED_GROUND_UP_LOSS}}` `{{EXPECTED_ANNUAL_LOSS}}` `{{SYNTHETIC}}` `{{SYNTHETIC_HAZARD}}` `{{SYNTHETIC_VULNERABILITY}}` `{{SYNTHETIC_EXPOSURE}}` `{{HAZARD_REGION}}`

### Desk

`static/index.html` is the CatMod search desk. The bar and answer card fill the viewport with a small edge inset. The apps menu runs the Nairobi modeled portfolio, the Nzoia depth portfolio, the hazard catalogue, desk status, the event queue, or a folder upload. A free-text string of eight or more characters that is not one of those commands is geocoded. Jev classifies occupancy on each bordereau line; it does not answer open questions about the job list. Gemini is used only for flood-imagery occupancy, and a missing key falls back to the local heuristic. Google geocoding, elevation, imagery, and 3D Tiles fall through `catmod/geo/fallback.py` to Nominatim, Open-Meteo, Esri imagery, a heuristic inundation card, and a procedural OSM scene.

**Modeled events**, **Events**, and **Upload** open the event dashboard (the queue layout: rail, search, tabs, rows). Upload reads a real folder in the browser. File text stays in that tab until refresh. A bordereau CSV in the folder is posted to `/v1/process-bordereau` and joins the in-memory event list. The dashboard search, and the main bar, match names and text in that session library.

The desk polls `GET /api/v1/events` every four seconds. The first response is the baseline. Each event id that appears after that — the Apps Script webhook, or a folder upload — drops a card from the top center. The card uses the same icon, title, and subtitle layout as the home shortcuts. Clean jobs are green, flagged jobs are amber, and a positive reinsurer payout is blue. The card leaves on its own. If the queue is already open, it refreshes with the new row.

The answer card does not repeat the query or the webhook path. **Categories** lays each figure out as its own rounded card with a distinct icon, beside Answer, the EP curve, and the map. The query icons sit after the full search text.

---

## 7. Layer internals

### Layer 2 — Jev primitives

Evaluated in one non-autoregressive pass per line:

| Primitive | Question | Meaning |
|-----------|----------|---------|
| Choice | `occupancy` | HAZUS-like code (`COM_WHSE`, `RES_SF`, …) |
| Noul | `fraud_or_discrepancy` | P(yes) in `[0, 1]` |
| Noul | `clean_for_finance` | May skip extra physics |
| Score | `spatial_severity` | 0 = consistent … 4 = physically impossible |

Routing: occupancy confidence **and** clean Noul **> 0.95** and no spatial flag → `finance`; else → `hdc_physics`. Local lexicon handles `whse`, `steel-shed`, `storage`, and informal sheet housing (`mabati`, `iron sheet` → `informal_iron_sheet`). Hosted Jev is optional (`JEV_API_KEY`). The standardized occupancy code is the vulnerability curve key.

### Hazard lookup

`catmod/hazard/` samples a north-up grid (bilinear) or a nearest coordinate index. `catmod/hazard/provenance.py` decides whether a file is synthetic, a proxy, a depth grid, or a susceptibility score.

- Bundled synthetic atlases: Nairobi pluvial susceptibility and a Nzoia corridor depth stand-in. Nairobi susceptibility in `[0, 1]` becomes `depth_m = score × 4.0`, then the return-period scale, then a clip to `[0, 10] m`. Nzoia’s bundled grid is already depth in metres.
- Mounted files under `data/` replace a bundled atlas when present: `nzoia_rp*.tif` keeps JRC metre depths (`synthetic: false`, no extra return-period scale; the return period is in the filename), `nairobi_pluvial_proxy_*.tif` stays a synthetic susceptibility proxy, and `nairobi_hotspots_geocoded.csv` is a county hotspot product (`synthetic: false`) that still uses the 4.0 m conversion.
- Return-period scales on a stored 100-year field, used only when `apply_return_period_scale` is true: 10 → 0.35, 25 → 0.55, 50 → 0.78, 100 → 1, 250 → 1.28, 500 → 1.55.
- When the webhook omits `hazard_region`, the job uses `CATMOD_HAZARD_REGION`. The Render host sets that to `nairobi`.
- `(0, 0)` is `NULL_ISLAND` (“Null Island”) before any raster test. Coordinates outside the selected surface are `IS_OUT_OF_BOUNDS`. Both are JSONL audit rows on layer 8.
- Loaders: `load_hazard_file` for `.csv`, `.asc`, and classic uncompressed GeoTIFF (ModelPixelScale + ModelTiepoint). No GDAL dependency.

### Stochastic catalog

`execution_mode` defaults to `deterministic`, which is the contractual job. `stochastic` adds an Oasis-style catalog beside it and does not replace the reported waterfall.

- `catmod/hazard/stochastic.py` builds a synthetic event set for `nairobi` or `nzoia`. Each return-period bin’s rates sum to `1 / RP`. Intensity is a Gumbel magnitude times a symmetric RBF random field. Footprint depths are Decimal metres at a `0.01` quantum, tagged `synthetic: true` and `stochastic: true`.
- `catmod/vulnerability/stochastic_engine.py` interpolates mean damage and a stddev `0.20 × √(μ(1−μ))`, draws a Beta sample, and returns `TIV × DR` in cents. It does not apply deductibles or treaty terms.
- The pipeline runs one Decimal waterfall per event, stores up to 48 event footprints in the FHRR memory, and writes audit steps `stochastic_hazard_simulated` (layer 8), `secondary_uncertainty_evaluated` (layer 9), and `stochastic_ep_curve_generated` (layer 10). The catalog curve reports OEP, AEP, EAL (`Σ rate × loss`), VaR, and TVaR at 95%, 99%, 99.5%, and 99.8%.
- Webhook fields: `stochastic_event_count` (default 36, maximum 10,000) and `stochastic_samples` (default 24). The generator’s own default catalog size is 10,000.

### Vulnerability

`catmod/vulnerability/` maps the Jev code onto a proxy depth-damage curve shaped like the JRC / Huizinga flood functions. The bundled knots are a proxy, so every result has `synthetic: true` and `curve_family: jrc_huizinga_proxy`.

Linear interpolation on `Decimal` knots stays inside `[0, 1]`. Ground-up loss is `TIV × damage ratio`, quantized to cents with `ROUND_HALF_EVEN`, and that `Decimal` is what Layer 4 receives on the modeled path.

### Exceedance probability

`catmod/analytics/ep_curve.py` sums modeled ground-up loss at each catalog return period. Exceedance probability is `1 / RP`, so it is strictly decreasing in the return period. Scenario losses must be non-decreasing in the return period.

- EAL is the trapezoid of loss versus exceedance probability, with loss 0 at probability 1 and a flat tail from the rarest scenario down to probability 0.
- PML at a return period is the scenario loss (interpolated in exceedance space when the period is not a catalog knot).
- TVaR at α is the mean of the piecewise-linear quantile from α to 1. VaR at the same α is the loss at exceedance `1 − α`.
- The return-period curve also carries an AEP column, `1 − exp(−1/RP)`, beside the OEP frequency `1/RP`.
- The curve is embedded in the job payload and in Leaflet `metadata.ep_curve`, and audited on layer 10.

### Layer 3 — FHRR

- Representation: unit-modulus complex vectors, **D = 10,000**
- Bind `⊗`: Hadamard product (phase addition)
- Bundle `⊕`: superposition sum
- Continuous scalar: `H = B^x` (coarse globe scale + ~2 km fine scale for lat/lon)
- Portfolio: `M = Σ H_claim_i`
- Each claim binds location, occupancy, and the physical damage ratio into that one vector
- Time: `M(t+Δt) = M(t) ⊗ P^{Δt}`
- Query: unbind / similarity — no vector database
- The decoded vector never replaces a treaty payout

### Layer 4 — Waterfall

1. Covered = `max(0, min(GUL, limit) − deductible) × coinsurance`
2. Gross = sum of covered (occurrence)
3. Layer loss = `min(max(gross − attachment, 0), limit)`
4. Reinsurer = layer × coparticipation (default 0.90)
5. Cedant = gross − reinsurer
6. Reinstatement = `min(layer/limit, reinstatements) × rate × original_premium`
7. TVaR / PML from the empirical covered sample (`catmod/finance/metrics.py`)

Money uses `Decimal` quantized to cents, `ROUND_HALF_EVEN`. `catmod/finance/waterfall.py` accepts the vulnerability module's `Decimal` ground-up loss directly. A second call, `modeled_vulnerability_waterfall`, always prices `TIV × DR` on the same treaty terms and is marked `synthetic: true`.

`loss_basis`:

| Value | Primary ground-up loss |
|-------|------------------------|
| `auto` (default) | Reported value when it is positive; otherwise the modeled cents |
| `reported` | Bordereau ground-up loss |
| `modeled` | Vulnerability `Decimal` cents |

### Audit layers

| Layer | Name | Successful step the verifier requires |
|-------|------|----------------------------------------|
| 1 | `google_workspace_ingestion` | `apps_script_webhook_received`, `bordereau_parsed`, or `job_opened` |
| 2 | `jev_system_one` | `jev_triage_complete` |
| 3 | `hdc_fhrr_spatial_memory` | `hdc_portfolio_encoded` or `hdc_query_complete` |
| 4 | `deterministic_reinsurance_finance` | `financial_waterfall_complete` |
| 5 | `leaflet_geojson_export` | `leaflet_geojson_emitted` |
| 6 | `flood_exposure_vulnerability` | Flood sidecar. Not required on a bordereau job |
| 7 | `spatial_3d_game_engine_export` | Elevation, 3D Tiles, Blender manifest. Not required on a bordereau job |
| 8 | `hazard_raster_lookup` | `hazard_lookup_complete` (anomalies use status `NULL_ISLAND` or `IS_OUT_OF_BOUNDS`) |
| 9 | `vulnerability_damage_function` | `vulnerability_complete` |
| 10 | `exceedance_probability_analytics` | `ep_curve_complete` |

The verifier still requires layers 1–5. Layers 8–10 are written on every bordereau job. Layers 6 and 7 are reserved names for the flood sidecar and the 3D export. A bordereau job does not record them, and neither path writes `ground_up_loss`, `reinsurer_payout`, or `cedant_retained_loss`.

Shader presets (`VICE_CITY_NEON`, `GTA_STYLIZED`, `PHOTOREAL_DEFAULT`) live in `catmod/spatial/presets.py`. `static/renderPresets.js` mirrors them for the browser. The default is `PHOTOREAL_DEFAULT`. Storey height in the Blender manifest defaults to 3.5 m.

### Layer 5 — Map style

| Color | Meaning |
|-------|---------|
| `#2A9D4A` | Low retained loss |
| `#E07A3D` | Material cedant retention |
| `#C1121F` | Reinsured XL allocation |
| `#7B1E3A` | Fraud / spatial flag |

---

## 8. Deployment view

```mermaid
flowchart LR
  subgraph GAS_runtime["Google Apps Script"]
    Trigger[Time trigger 5 min]
    Code[appsscript.js]
  end

  subgraph Py["Render Starter — Python 3.12.8"]
    UV[uvicorn main:app workers 1]
    Disk["/var/data/audit_logs"]
    Mem[(in-memory last 32 jobs)]
  end

  subgraph GCloud["Google APIs"]
    GmailAPI[Gmail]
    DriveAPI[Drive / Docs / Slides]
    SheetsAPI[Sheets]
    TasksAPI[Tasks]
  end

  Trigger --> Code
  Code --> GmailAPI
  Code --> SheetsAPI
  Code --> UV
  UV --> Disk
  UV --> Mem
  Code --> DriveAPI
  Code --> TasksAPI
```

Script properties (Apps Script project settings):

| Property | Purpose |
|----------|---------|
| `BACKEND_URL` | `https://alpha.onrender.com` |
| `REGISTRY_SHEET_ID` | Master registry spreadsheet id |
| `REPORT_TEMPLATE_ID` | Google Doc template id |
| `SLIDES_TEMPLATE_ID` | Slides template id, or blank to auto-build the four-slide deck |
| `DRIVE_FOLDER_ID` | Parent folder. Jobs land in `Catastrophe_Archive/YYYY-MM/Client/Event` |
| `TASKS_LIST_ID` | Tasks list id. Blank uses `@default` |
| `UNDERWRITER_EMAIL` | Fallback recipient when the message has no Reply-To |

Gmail label `Catastrophe-Bordereaux`, 5-minute trigger on `processIncomingBordereaux`. Editor checks: `testTasksIntegration`, `testDriveArchiving`, `testSlidesGeneration`. Manifest: `appsscript.json`. Paste `setup.js` as `setup.gs` and run `setupEnvironment` once to create the archive folder, registry, report template, and slides template, then write those script properties. A second run reuses the same files.

Live host: [https://alpha.onrender.com](https://alpha.onrender.com), Render plan `starter`, one instance, health check `GET /health`, audit disk mounted at `/var/data`. Blueprint: `render.yaml`. Jobs stay in process memory, so the service must stay at one instance.

---

## 9. How to run

```bash
pip install -r requirements.txt
python scripts/run_sample_job.py
python -m pytest tests -q
uvicorn main:app --port 8000
```

Then open `/map/` after posting a bordereau, or `GET /api/v1/leaflet-export`.

Full verbatim source of every project file: [`FULL_CODEBASE.txt`](FULL_CODEBASE.txt).
