import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

const M_PER_DEG = 111320;
const POINT_CAP = 150000;
const BUILDING_CAP = 4000;
const RETICLE_CAP = 8;
const CELLS = {
  cbd: { id: "cbd", name: "CBD", west: 36.812, south: -1.286, east: 36.828, north: -1.274 },
  westlands: { id: "westlands", name: "Westlands", west: 36.798, south: -1.271, east: 36.814, north: -1.259 },
  upperhill: { id: "upperhill", name: "Upper Hill", west: 36.805, south: -1.305, east: 36.821, north: -1.293 },
};

const MATERIALS = {
  masonry: { color: 0xd5e6ee, roughness: 0.18, metalness: 0.08 },
  metal: { color: 0xd7e4ea, roughness: 0.22, metalness: 0.42 },
  timber: { color: 0xe7d2b4, roughness: 0.28, metalness: 0.04 },
  steel: { color: 0xc9dbe6, roughness: 0.16, metalness: 0.32 },
};

const app = document.getElementById("app");
const loadingEl = document.getElementById("loading");
const statsEl = document.getElementById("stats");
const noteEl = document.getElementById("note");
const titleEl = document.getElementById("title");
const cellSelect = document.getElementById("cell");
const hudEl = document.getElementById("hud");
const pickEl = document.getElementById("pick");
const needleEl = document.getElementById("needle");
const compassModeEl = document.getElementById("compass-mode");
const boardBtn = document.getElementById("btn-board");
const streetsBtn = document.getElementById("btn-streets");

const renderer = new THREE.WebGLRenderer({ antialias: false, powerPreference: "high-performance" });
renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
renderer.setSize(window.innerWidth, window.innerHeight);
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.05;
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.shadowMap.enabled = false;
app.appendChild(renderer.domElement);

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x071018);
scene.fog = new THREE.FogExp2(0x0c2430, 0.00022);

const camera = new THREE.PerspectiveCamera(38, window.innerWidth / window.innerHeight, 0.8, 30000);
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.dampingFactor = 0.06;
controls.autoRotate = true;
controls.autoRotateSpeed = 0.15;
controls.minPolarAngle = 0.28 * Math.PI;
controls.maxPolarAngle = 0.48 * Math.PI;
controls.minDistance = 40;
controls.addEventListener("start", () => { controls.autoRotate = false; });
controls.addEventListener("end", () => { controls.autoRotate = mode === "HOLO"; });

scene.add(new THREE.HemisphereLight(0x9fd4e8, 0x0b1c24, 0.95));
const sun = new THREE.DirectionalLight(0xe7f7ff, 1.35);
sun.position.set(0.7, 1.3, 0.4);
scene.add(sun);

const content = new THREE.Group();
scene.add(content);
const meshGroup = new THREE.Group();
const floodGroup = new THREE.Group();
const markerGroup = new THREE.Group();
content.add(meshGroup);
content.add(floodGroup);
content.add(markerGroup);

const plinth = new THREE.Mesh(
  new THREE.CircleGeometry(1, 64),
  new THREE.MeshBasicMaterial({ color: 0x05080c, transparent: true, opacity: 0.72, depthWrite: false })
);
plinth.rotation.x = -Math.PI / 2;
plinth.position.y = -2.5;
scene.add(plinth);

const waterNormal = makeWaterNormal();
const raycaster = new THREE.Raycaster();
const pointer = new THREE.Vector2();
const lookDir = new THREE.Vector3();

let points = null;
let riskOn = false;
let running = true;
let job = 0;
let abort = null;
let massMid = 12;
let viewWidth = 800;
let mode = "HOLO";
let dive = null;
let roadPath = [];
let streetLocal = null;
let holoHome = null;
let analysis = [];
let pickMeshes = [];
let pointerDown = null;
let lastFrame = performance.now();
const riskShaders = [];

window.addEventListener("resize", () => {
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
});
document.addEventListener("visibilitychange", () => {
  running = document.visibilityState === "visible";
});

document.getElementById("tog-scan").addEventListener("click", (ev) => {
  const on = ev.currentTarget.getAttribute("aria-pressed") !== "true";
  ev.currentTarget.setAttribute("aria-pressed", on ? "true" : "false");
  if (points) points.visible = on;
});
document.getElementById("tog-mesh").addEventListener("click", (ev) => {
  const on = ev.currentTarget.getAttribute("aria-pressed") !== "true";
  ev.currentTarget.setAttribute("aria-pressed", on ? "true" : "false");
  meshGroup.visible = on;
  markerGroup.visible = on;
});
document.getElementById("tog-flood").addEventListener("click", (ev) => {
  const on = ev.currentTarget.getAttribute("aria-pressed") !== "true";
  ev.currentTarget.setAttribute("aria-pressed", on ? "true" : "false");
  floodGroup.visible = on;
});
document.getElementById("tog-risk").addEventListener("click", (ev) => {
  riskOn = ev.currentTarget.getAttribute("aria-pressed") !== "true";
  ev.currentTarget.setAttribute("aria-pressed", riskOn ? "true" : "false");
  for (const shader of riskShaders) shader.uniforms.uRisk.value = riskOn ? 1 : 0;
});
document.getElementById("tog-vex").addEventListener("click", (ev) => {
  const on = ev.currentTarget.getAttribute("aria-pressed") !== "true";
  ev.currentTarget.setAttribute("aria-pressed", on ? "true" : "false");
  ev.currentTarget.textContent = on ? "Vertical ×1.5 on" : "Vertical ×1.5";
  const oldTargetY = controls.target.y;
  content.scale.y = on ? 1.5 : 1;
  if (mode === "STREET" && streetLocal) controls.target.copy(streetWorldPose().look);
  else controls.target.copy(holoTarget());
  camera.position.y += controls.target.y - oldTargetY;
  controls.update();
});
cellSelect.addEventListener("change", () => loadCell(cellSelect.value));
boardBtn.addEventListener("click", () => goBoard());
streetsBtn.addEventListener("click", () => goStreets());
window.addEventListener("keydown", (ev) => {
  const tag = (ev.target && ev.target.tagName) || "";
  if (tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA") return;
  if (ev.key === "h" || ev.key === "H") goBoard();
  if (ev.key === "g" || ev.key === "G") goStreets();
  if (ev.key === "Escape" && mode !== "HOLO") goBoard();
});
renderer.domElement.addEventListener("pointerdown", (ev) => {
  pointerDown = { x: ev.clientX, y: ev.clientY };
});
renderer.domElement.addEventListener("pointerup", (ev) => {
  if (!pointerDown) return;
  const dx = ev.clientX - pointerDown.x;
  const dy = ev.clientY - pointerDown.y;
  pointerDown = null;
  if (dx * dx + dy * dy > 16) return;
  if (mode === "DIVE" || mode === "PULLBACK") return;
  pickAt(ev);
});

const params = new URLSearchParams(window.location.search);
const initial = CELLS[params.get("cell")] ? params.get("cell") : "cbd";
cellSelect.value = initial;
loadCell(initial);

function animate() {
  requestAnimationFrame(animate);
  const now = performance.now();
  const dt = Math.min(0.05, (now - lastFrame) / 1000);
  lastFrame = now;
  if (!running) return;
  waterNormal.offset.x += 0.0008;
  if (dive) stepDive(dt);
  else controls.update();
  updateCompass();
  renderer.render(scene, camera);
}
animate();

function goBoard() {
  if (mode === "HOLO") {
    frameHolo(viewWidth);
    return;
  }
  if (mode === "DIVE" && dive && !dive.returning) {
    dive.dir = -1;
    dive.returning = true;
    mode = "PULLBACK";
    hudEl.classList.add("is-flying");
    setModeLabel();
    return;
  }
  if (mode === "PULLBACK") return;
  const home = holoHome || {
    pos: toLocalY(holoPose(viewWidth).pos),
    target: toLocalY(holoPose(viewWidth).target),
  };
  dive = {
    returning: true,
    dir: 1,
    t: 0,
    duration: 8,
    pos: new THREE.CatmullRomCurve3(arcPoints(camera.position, toWorldY(home.pos))),
    tgt: new THREE.CatmullRomCurve3(arcPoints(controls.target, toWorldY(home.target))),
  };
  mode = "PULLBACK";
  controls.enabled = false;
  controls.autoRotate = false;
  hudEl.classList.add("is-flying");
  setModeLabel();
}

function goStreets() {
  if (mode !== "HOLO" || !streetLocal) return;
  const street = streetWorldPose();
  holoHome = { pos: toLocalY(camera.position), target: toLocalY(controls.target) };
  dive = {
    returning: false,
    dir: 1,
    t: 0,
    duration: 8,
    pos: new THREE.CatmullRomCurve3(arcPoints(camera.position, street.eye)),
    tgt: new THREE.CatmullRomCurve3(arcPoints(controls.target, street.look)),
  };
  mode = "DIVE";
  controls.enabled = false;
  controls.autoRotate = false;
  hudEl.classList.add("is-flying");
  setModeLabel();
}

function stepDive(dt) {
  dive.t += (dt / dive.duration) * dive.dir;
  if (dive.dir > 0 && dive.t >= 1) {
    dive.t = 1;
    land(dive.returning);
    return;
  }
  if (dive.dir < 0 && dive.t <= 0) {
    dive.t = 0;
    land(true);
    return;
  }
  const u = easeInOut(Math.min(1, Math.max(0, dive.t)));
  camera.position.copy(curvePoint(dive.pos, u));
  controls.target.copy(curvePoint(dive.tgt, u));
  camera.lookAt(controls.target);
}

function land(toHolo) {
  dive = null;
  if (toHolo) {
    const home = holoHome
      ? { pos: toWorldY(holoHome.pos), target: toWorldY(holoHome.target) }
      : holoPose(viewWidth);
    camera.position.copy(home.pos);
    controls.target.copy(home.target);
    applyHoloLimits(viewWidth);
    mode = "HOLO";
  } else {
    const street = streetWorldPose();
    camera.position.copy(street.eye);
    controls.target.copy(street.look);
    applyStreetLimits();
    mode = "STREET";
  }
  controls.enabled = true;
  controls.update();
  hudEl.classList.remove("is-flying");
  setModeLabel();
}

function setModeLabel() {
  compassModeEl.textContent = mode;
  streetsBtn.disabled = mode !== "HOLO";
}

function updateCompass() {
  camera.getWorldDirection(lookDir);
  const bearing = Math.atan2(lookDir.x, lookDir.z);
  needleEl.style.transform = "rotate(" + (-bearing) + "rad)";
}

function holoTarget() {
  return new THREE.Vector3(0, massMid * content.scale.y, 0);
}

function holoPose(width) {
  const target = holoTarget();
  const dist = 0.85 * Math.max(width, 80);
  const phi = 0.38 * Math.PI;
  const theta = 0.85;
  return {
    pos: new THREE.Vector3(
      target.x + dist * Math.sin(phi) * Math.sin(theta),
      target.y + dist * Math.cos(phi),
      target.z + dist * Math.sin(phi) * Math.cos(theta)
    ),
    target,
  };
}

function frameHolo(width) {
  const pose = holoPose(width);
  camera.position.copy(pose.pos);
  controls.target.copy(pose.target);
  applyHoloLimits(width);
  controls.enabled = true;
  controls.autoRotate = true;
  controls.update();
  holoHome = { pos: toLocalY(pose.pos), target: toLocalY(pose.target) };
  mode = "HOLO";
  dive = null;
  hudEl.classList.remove("is-flying");
  setModeLabel();
}

function applyHoloLimits(width) {
  controls.minPolarAngle = 0.28 * Math.PI;
  controls.maxPolarAngle = 0.48 * Math.PI;
  controls.minDistance = 40;
  controls.maxDistance = Math.max(2.2 * width, 400);
  controls.autoRotateSpeed = 0.15;
  controls.dampingFactor = 0.06;
}

function applyStreetLimits() {
  controls.minPolarAngle = 0.35 * Math.PI;
  controls.maxPolarAngle = 0.5 * Math.PI;
  controls.minDistance = 12;
  controls.maxDistance = 280;
  controls.autoRotate = false;
  controls.dampingFactor = 0.06;
}

function streetWorldPose() {
  return { eye: toWorldY(streetLocal.eye), look: toWorldY(streetLocal.look) };
}

function toLocalY(v) {
  const s = content.scale.y || 1;
  return new THREE.Vector3(v.x, v.y / s, v.z);
}

function toWorldY(v) {
  const s = content.scale.y || 1;
  return new THREE.Vector3(v.x, v.y * s, v.z);
}

function arcPoints(fromWorld, toWorld) {
  const a = toLocalY(fromWorld);
  const b = toLocalY(toWorld);
  const m1 = a.clone().lerp(b, 0.34);
  const m2 = a.clone().lerp(b, 0.67);
  const lift = Math.max(28, a.distanceTo(b) * 0.16);
  m1.y = Math.max(a.y, b.y) + lift;
  m2.y = b.y + lift * 0.4;
  return [a, m1, m2, b];
}

function curvePoint(curve, u) {
  return toWorldY(curve.getPoint(u));
}

function easeInOut(t) {
  return t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;
}

async function loadCell(id) {
  const cell = CELLS[id] || CELLS.cbd;
  job += 1;
  const token = job;
  if (abort) abort.abort();
  abort = new AbortController();
  const signal = abort.signal;
  loadingEl.style.display = "flex";
  loadingEl.textContent = "Loading " + cell.name + "…";
  titleEl.textContent = cell.name;
  pickEl.hidden = true;
  const q = "west=" + cell.west + "&south=" + cell.south + "&east=" + cell.east + "&north=" + cell.north;
  let elev = null;
  try {
    elev = await getJSON("/api/spatial/elevation?" + q + "&rows=20&cols=20", signal);
  } catch (err) {
    if (err && err.name === "AbortError") return;
    elev = null;
  }
  if (token !== job) return;
  const settled = await Promise.allSettled([
    getJSON("/api/spatial/osm-buildings?" + q, signal),
    getJSON("/api/spatial/osm-roads?" + q, signal),
    getJSON("/api/v1/flood/buildings?" + q, signal),
    getJSON("/api/export/blender-manifest?shader_preset=PHOTOREAL_DEFAULT&storey_height_m=3.5", signal),
    getJSON("/api/spatial/flood-depth?" + q + "&rows=32&cols=32&region=nairobi", signal),
    getJSON("/api/spatial/render-presets", signal),
    loadTerrainTexture("/api/v1/flood/imagery/terrain?" + q, signal),
  ]);
  if (token !== job) return;
  const osm = valueOf(settled[0]);
  const roads = valueOf(settled[1]);
  const local = valueOf(settled[2]);
  const manifest = valueOf(settled[3]);
  const depth = valueOf(settled[4]);
  const presets = valueOf(settled[5]);
  const texture = valueOf(settled[6]);
  let grid = elev;
  const notes = [];
  if (!grid || !grid.heightmap) {
    grid = flatGrid(cell);
    notes.push("Elevation failed. Flat plinth.");
  }
  if (grid.provider === "heuristic") notes.push("Elevation is a flat plinth.");
  if (!texture) notes.push("Satellite image unavailable. Terrain is clay.");
  if (!depth || !depth.depth_m) notes.push("Flood grid unavailable.");
  if (!osm) notes.push("OpenStreetMap buildings unavailable.");
  else if (osm.metadata && osm.metadata.note) notes.push(osm.metadata.note);
  const osmCount = osm && osm.features ? osm.features.length : 0;
  const localCount = local && local.features ? local.features.length : 0;
  if (!osmCount && !localCount) notes.push("No building geometries in this cell.");
  if (!roads || !(roads.features || []).length) notes.push("Dive follows the cell centerline.");
  try {
    buildScene(cell, grid, osm, roads, local, manifest, depth, presets, texture, notes, osmCount, localCount);
  } catch (err) {
    console.error(err);
    loadingEl.style.display = "flex";
    loadingEl.textContent = "Diorama failed to build";
    return;
  }
  loadingEl.style.display = "none";
}

function valueOf(settled) {
  return settled.status === "fulfilled" ? settled.value : null;
}

async function getJSON(url, signal) {
  const res = await fetch(url, { signal });
  if (!res.ok) throw new Error(url + " " + res.status);
  return res.json();
}

async function loadTerrainTexture(url, signal) {
  const res = await fetch(url, { signal });
  if (!res.ok) throw new Error("terrain imagery " + res.status);
  const blob = await res.blob();
  const objectUrl = URL.createObjectURL(blob);
  try {
    const tex = await new Promise((resolve, reject) => {
      new THREE.TextureLoader().load(objectUrl, resolve, undefined, reject);
    });
    tex.colorSpace = THREE.SRGBColorSpace;
    tex.anisotropy = 4;
    tex.userData.disposeMap = true;
    return tex;
  } finally {
    URL.revokeObjectURL(objectUrl);
  }
}

function buildScene(cell, elev, osm, roads, local, manifest, depth, presets, texture, notes, osmCount, localCount) {
  disposeContents();
  const palette = (presets && presets.presets && presets.presets.PHOTOREAL_DEFAULT && presets.presets.PHOTOREAL_DEFAULT.palette) || {};
  const waterHex = hexColor(palette.water, 0x4c8dde);
  scene.background = new THREE.Color(0x071018);
  scene.fog.color.setHex(0x0c2430);

  const lon0 = (cell.west + cell.east) / 2;
  const lat0 = (cell.south + cell.north) / 2;
  const baseline = Number(elev.baseline_elevation_m);
  const width = (cell.east - cell.west) * M_PER_DEG * Math.cos(lat0 * Math.PI / 180);
  const depthM = (cell.north - cell.south) * M_PER_DEG;
  const frame = { cell, lon0, lat0, baseline, width, depthM, elev };
  viewWidth = width;

  const drawn = buildDrawnDepth(frame, depth, manifest);
  meshGroup.add(buildTerrain(frame, drawn, texture).mesh);
  meshGroup.add(buildGrid(frame, Math.max(40, width / 28), 0.28));
  meshGroup.add(buildGrid(frame, Math.max(12, width / 90), 0.12));

  const built = buildBuildings(frame, osm, local, manifest, drawn);
  for (const mesh of built.meshes) meshGroup.add(mesh);
  if (built.edges) meshGroup.add(built.edges);
  analysis = built.records;
  pickMeshes = built.pickMeshes;
  massMid = built.massMid;

  const water = buildWater(frame, drawn, waterHex);
  if (water) floodGroup.add(water);
  floodGroup.visible = document.getElementById("tog-flood").getAttribute("aria-pressed") === "true";
  meshGroup.visible = document.getElementById("tog-mesh").getAttribute("aria-pressed") === "true";
  markerGroup.visible = meshGroup.visible;
  addReticles(built.records);

  const scan = buildScan(frame, drawn, built.records);
  points = scan.points;
  points.visible = document.getElementById("tog-scan").getAttribute("aria-pressed") === "true";
  content.add(points);

  roadPath = buildRoad(frame, roads);
  streetLocal = chooseStreet(roadPath);

  const radius = 1.2 * Math.hypot(width, depthM) / 2;
  plinth.geometry.dispose();
  plinth.geometry = new THREE.CircleGeometry(radius, 64);
  scene.fog.density = 0.35 / Math.max(width, 1);

  content.scale.y = document.getElementById("tog-vex").getAttribute("aria-pressed") === "true" ? 1.5 : 1;
  frameHolo(width);

  const bytes = bufferBytes(content) + bufferBytes(plinth);
  const resolution = elev.grid && elev.grid[0] ? elev.grid[0].resolution_m : 0;
  const published = built.records.map(publishRecord);
  const totals = {
    count: built.count,
    gross_volume_m3: built.gross,
    flooded_volume_m3: built.flooded,
    dry_volume_m3: built.gross - built.flooded,
    max_depth_m: drawn.maxDrawn,
    tallest_m: built.tallest,
    estimated_heights: built.estimatedCount,
    osm_ways: osmCount,
    open_buildings: localCount,
    truncated: built.truncated,
  };
  window.__nairobiAnalysis = { cell: cell.name, buildings: published, totals };
  window.__dioramaScan = {
    cell: cell.name,
    provider: elev.provider || "unknown",
    measured_count: scan.measured,
    synthetic_count: scan.synthetic,
    classes: scan.classes,
    baseline_elevation_m: baseline,
    vertical_noise_sigma_m: 0.25,
    buffer_bytes: bytes,
    method: "dem_footprint_densify",
    synthetic: true,
    disclaimer: "Densified from a posted elevation grid and footprints. Not a lidar survey.",
  };
  const bbox = cell.west.toFixed(3) + ", " + cell.south.toFixed(3) + " → " + cell.east.toFixed(3) + ", " + cell.north.toFixed(3);
  statsEl.textContent = [
    cell.name,
    bbox,
    "OSM " + osmCount + " · Open Buildings " + localCount,
    "buildings " + built.count + (built.truncated ? " (largest 4000)" : ""),
    "gross " + fmtM3(built.gross),
    "flooded " + fmtM3(built.flooded),
    "max depth " + drawn.maxDrawn.toFixed(2) + " m",
    "tallest " + built.tallest.toFixed(1) + " m",
    "estimated heights " + built.estimatedCount + " of " + built.count,
    "elevation " + (elev.provider || "unknown") + (resolution ? " · " + Math.round(resolution) + " m" : ""),
    "buffers " + (bytes / 1048576).toFixed(1) + " MB",
  ].join("\n");
  const extra = notes.slice();
  if (built.truncated) extra.push("Kept the 4000 largest footprints by area.");
  if (drawn.relief >= 2) extra.push("Water follows hazard depth on the lower ground. Ridge tops in this cell stay dry.");
  if (bytes > 100 * 1048576) extra.push("Buffer sum is over 100 MB.");
  noteEl.textContent = extra.filter(Boolean).join(" ");
}

function disposeContents() {
  riskShaders.length = 0;
  analysis = [];
  pickMeshes = [];
  roadPath = [];
  streetLocal = null;
  dive = null;
  for (const group of [meshGroup, floodGroup, markerGroup]) {
    for (const child of [...group.children]) disposeNode(child, group);
  }
  for (const child of content.children.filter((item) => item !== meshGroup && item !== floodGroup && item !== markerGroup)) {
    disposeNode(child, content);
  }
  points = null;
}

function disposeNode(node, parent) {
  node.traverse((child) => {
    if (child.geometry) child.geometry.dispose();
    const mats = child.material ? [].concat(child.material) : [];
    for (const mat of mats) {
      if (mat.map && mat.map.userData && mat.map.userData.disposeMap) mat.map.dispose();
      mat.dispose();
    }
  });
  parent.remove(node);
}

function publishRecord(rec) {
  return {
    name: rec.name,
    area_m2: rec.area_m2,
    height_m: rec.height_m,
    gross_volume_m3: rec.gross_volume_m3,
    depth_m: rec.depth_m,
    flooded_volume_m3: rec.flooded_volume_m3,
    dry_volume_m3: rec.dry_volume_m3,
    x: rec.x,
    y: rec.y,
    z: rec.z,
    lon: rec.lon,
    lat: rec.lat,
    source: rec.source,
    estimated_height: rec.estimated_height,
    material: rec.material,
  };
}

function buildDrawnDepth(frame, depth, manifest) {
  const rows = depth && depth.depth_m ? depth.rows : 2;
  const cols = depth && depth.depth_m ? depth.cols : 2;
  const table = depth && depth.depth_m ? depth.depth_m : [[0, 0], [0, 0]];
  let emin = Infinity;
  let emax = -Infinity;
  const heights = [];
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      const lat = frame.cell.south + (frame.cell.north - frame.cell.south) * (rows === 1 ? 0 : r / (rows - 1));
      const lon = frame.cell.west + (frame.cell.east - frame.cell.west) * (cols === 1 ? 0 : c / (cols - 1));
      const h = sampleElev(frame.elev, lon, lat);
      heights.push(h);
      if (h < emin) emin = h;
      if (h > emax) emax = h;
    }
  }
  const relief = emax - emin;
  const drawn = [];
  let maxDrawn = 0;
  let i = 0;
  for (let r = 0; r < rows; r++) {
    const line = [];
    for (let c = 0; c < cols; c++) {
      const hazard = Number(table[r] && table[r][c]) || 0;
      let keep = 1;
      if (relief >= 2) {
        const t = (heights[i] - emin) / relief;
        if (t > 0.72) keep = 0;
        else if (t > 0.42) keep = 1 - (t - 0.42) / 0.3;
      }
      let d = hazard * keep;
      if (d < 0.05) d = 0;
      line.push(d);
      if (d > maxDrawn) maxDrawn = d;
      i += 1;
    }
    drawn.push(line);
  }
  for (const stamp of manifestStamps(manifest, frame.cell)) {
    const vv = (stamp.lat - frame.cell.south) / (frame.cell.north - frame.cell.south);
    const uu = (stamp.lon - frame.cell.west) / (frame.cell.east - frame.cell.west);
    const rr = Math.max(0, Math.min(rows - 1, Math.round(vv * (rows - 1))));
    const cc = Math.max(0, Math.min(cols - 1, Math.round(uu * (cols - 1))));
    drawn[rr][cc] = Math.max(drawn[rr][cc], stamp.depth);
    if (drawn[rr][cc] > maxDrawn) maxDrawn = drawn[rr][cc];
  }
  return {
    rows, cols, drawn, relief, maxDrawn,
    west: frame.cell.west, south: frame.cell.south, east: frame.cell.east, north: frame.cell.north,
  };
}

function buildTerrain(frame, drawn, texture) {
  const seg = 255;
  const positions = new Float32Array((seg + 1) * (seg + 1) * 3);
  const colors = new Float32Array((seg + 1) * (seg + 1) * 3);
  const uvs = new Float32Array((seg + 1) * (seg + 1) * 2);
  const risk = new Float32Array((seg + 1) * (seg + 1) * 3);
  const wet = new Float32Array((seg + 1) * (seg + 1));
  const indices = new Uint32Array(seg * seg * 6);
  const tint = new THREE.Color(0x0e2a36);
  const water = new THREE.Color(0x4c8dde);
  let vcount = 0;
  for (let iy = 0; iy <= seg; iy++) {
    const v = iy / seg;
    const z = -frame.depthM / 2 + v * frame.depthM;
    for (let ix = 0; ix <= seg; ix++) {
      const u = ix / seg;
      const x = -frame.width / 2 + u * frame.width;
      const lon = frame.cell.west + u * (frame.cell.east - frame.cell.west);
      const lat = frame.cell.south + v * (frame.cell.north - frame.cell.south);
      const y = sampleElev(frame.elev, lon, lat) - frame.baseline;
      const flood = sampleGrid(drawn.drawn, drawn.rows, drawn.cols, u, v);
      const o = vcount * 3;
      positions[o] = x;
      positions[o + 1] = y;
      positions[o + 2] = z;
      const wash = Math.min(flood / 3, 0.18);
      const mix = 0.4;
      colors[o] = (1 - mix) + tint.r * mix;
      colors[o + 1] = (1 - mix) + tint.g * mix;
      colors[o + 2] = (1 - mix) + tint.b * mix;
      colors[o] = colors[o] * (1 - wash) + water.r * wash;
      colors[o + 1] = colors[o + 1] * (1 - wash) + water.g * wash;
      colors[o + 2] = colors[o + 2] * (1 - wash) + water.b * wash;
      uvs[vcount * 2] = u;
      uvs[vcount * 2 + 1] = v;
      wet[vcount] = flood > 0.3 ? 1 : 0;
      vcount += 1;
    }
  }
  let k = 0;
  for (let iy = 0; iy < seg; iy++) {
    for (let ix = 0; ix < seg; ix++) {
      const a = iy * (seg + 1) + ix;
      const b = a + 1;
      const c = a + (seg + 1);
      const d = c + 1;
      indices[k++] = a; indices[k++] = c; indices[k++] = b;
      indices[k++] = b; indices[k++] = c; indices[k++] = d;
    }
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.BufferAttribute(positions, 3));
  geo.setAttribute("color", new THREE.BufferAttribute(colors, 3));
  geo.setAttribute("uv", new THREE.BufferAttribute(uvs, 2));
  geo.setAttribute("riskTint", new THREE.BufferAttribute(risk, 3));
  geo.setAttribute("wetness", new THREE.BufferAttribute(wet, 1));
  geo.setIndex(new THREE.BufferAttribute(indices, 1));
  geo.computeVertexNormals();
  const mat = new THREE.MeshStandardMaterial({
    color: texture ? 0xffffff : 0xc4b6a6,
    map: texture || null,
    roughness: 0.92,
    metalness: 0,
    vertexColors: true,
    transparent: !!texture,
    opacity: texture ? 0.62 : 1,
    depthWrite: true,
  });
  hookRisk(mat);
  const mesh = new THREE.Mesh(geo, mat);
  mesh.renderOrder = 0;
  return { mesh };
}

function buildGrid(frame, step, opacity) {
  const positions = [];
  const x0 = -frame.width / 2;
  const x1 = frame.width / 2;
  const z0 = -frame.depthM / 2;
  const z1 = frame.depthM / 2;
  for (let x = x0; x <= x1 + 0.1; x += step) {
    positions.push(x, groundY(frame, x, z0) + 1.4, z0, x, groundY(frame, x, z1) + 1.4, z1);
  }
  for (let z = z0; z <= z1 + 0.1; z += step) {
    positions.push(x0, groundY(frame, x0, z) + 1.4, z, x1, groundY(frame, x1, z) + 1.4, z);
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
  const mat = new THREE.LineBasicMaterial({
    color: 0x3ee0ff,
    transparent: true,
    opacity,
    depthWrite: false,
  });
  const lines = new THREE.LineSegments(geo, mat);
  lines.renderOrder = 2;
  return lines;
}

function groundY(frame, x, z) {
  const lon = frame.lon0 + x / (M_PER_DEG * Math.cos(frame.lat0 * Math.PI / 180));
  const lat = frame.lat0 + z / M_PER_DEG;
  return sampleElev(frame.elev, lon, lat) - frame.baseline;
}

function buildBuildings(frame, osm, local, manifest, drawn) {
  const books = indexManifest(manifest);
  const prepared = [];
  for (const item of footprintItems(osm, local)) {
    const ring = ringOf(item.feature);
    const xz = simplifyRing(projectRing(ring, frame), 16);
    if (!xz.length) continue;
    const area = Math.abs(signedArea(xz.length >= 3 ? xz : projectRing(ring, frame)));
    prepared.push({ item, xz, area: area || Number((item.feature.properties || {}).area_m2) || 1 });
  }
  prepared.sort((a, b) => b.area - a.area);
  const truncated = prepared.length > BUILDING_CAP;
  const kept = prepared.slice(0, BUILDING_CAP);
  const buckets = new Map();
  const records = [];
  const edgePos = [];
  let gross = 0;
  let flooded = 0;
  let tallest = 0;
  let estimatedCount = 0;
  let midSum = 0;
  for (const row of kept) {
    const props = row.item.feature.properties || {};
    const centroid = ringCentroid(row.xz.length >= 3 ? row.xz : [[0, 0]]);
    const lon = frame.lon0 + centroid.x / (M_PER_DEG * Math.cos(frame.lat0 * Math.PI / 180));
    const lat = frame.lat0 + centroid.z / M_PER_DEG;
    const area = row.xz.length >= 3 ? Math.abs(signedArea(row.xz)) : row.area;
    const sized = resolveHeight(props, area);
    const book = matchBook(books, lat, lon);
    const materialName = materialLabel(props, book);
    const key = materialKey(materialName) + (sized.estimated ? ":est" : "");
    const baseY = sampleElev(frame.elev, lon, lat) - frame.baseline;
    let depthM = sampleDepthAt(drawn, lon, lat);
    if (book && book.depth >= 0.05) depthM = Math.max(depthM, book.depth);
    if (depthM < 0.05) depthM = 0;
    const floodedVolume = area * Math.min(depthM, sized.height);
    const grossVolume = area * sized.height;
    const risk = riskRGB(book && book.risk);
    const wet = depthM > 0.3 ? 1 : 0;
    const index = records.length;
    if (row.xz.length < 3) {
      addBox(buckets, key, row.xz.length ? row.xz : [[centroid.x, centroid.z]], baseY, sized.height, risk, wet, index, edgePos);
    } else {
      addPrism(bucketFor(buckets, key), row.xz, baseY, baseY + sized.height, risk, wet, index);
      addOutline(edgePos, row.xz, baseY, baseY + sized.height);
    }
    const rec = {
      name: props.name || "",
      area_m2: area,
      height_m: sized.height,
      gross_volume_m3: grossVolume,
      depth_m: depthM,
      flooded_volume_m3: floodedVolume,
      dry_volume_m3: grossVolume - floodedVolume,
      x: centroid.x,
      y: baseY + sized.height / 2,
      z: centroid.z,
      lon,
      lat,
      baseY,
      topY: baseY + sized.height,
      xz: row.xz.length >= 3 ? row.xz : null,
      source: row.item.source,
      estimated_height: sized.estimated,
      material: materialName,
    };
    records.push(rec);
    gross += grossVolume;
    flooded += floodedVolume;
    if (sized.height > tallest) tallest = sized.height;
    if (sized.estimated) estimatedCount += 1;
    midSum += rec.y;
  }
  const meshes = [];
  const pickList = [];
  for (const [key, bucket] of buckets) {
    if (bucket.pos.length) {
      const geo = new THREE.BufferGeometry();
      geo.setAttribute("position", new THREE.Float32BufferAttribute(bucket.pos, 3));
      geo.setAttribute("riskTint", new THREE.Float32BufferAttribute(bucket.risk, 3));
      geo.setAttribute("wetness", new THREE.Float32BufferAttribute(bucket.wet, 1));
      geo.setAttribute("bindex", new THREE.Float32BufferAttribute(bucket.bindex, 1));
      geo.computeVertexNormals();
      const mesh = new THREE.Mesh(geo, styleMaterial(key));
      mesh.renderOrder = 1;
      meshes.push(mesh);
      pickList.push(mesh);
    }
    if (bucket.instances.length) {
      const geo = new THREE.BoxGeometry(1, 1, 1);
      const riskAttr = new Float32Array(bucket.instances.length * 3);
      const wetAttr = new Float32Array(bucket.instances.length);
      const mesh = new THREE.InstancedMesh(geo, styleMaterial(key), bucket.instances.length);
      bucket.instances.forEach((inst, i) => {
        mesh.setMatrixAt(i, inst.matrix);
        riskAttr[i * 3] = inst.risk[0];
        riskAttr[i * 3 + 1] = inst.risk[1];
        riskAttr[i * 3 + 2] = inst.risk[2];
        wetAttr[i] = inst.wet;
      });
      geo.setAttribute("riskTint", new THREE.InstancedBufferAttribute(riskAttr, 3));
      geo.setAttribute("wetness", new THREE.InstancedBufferAttribute(wetAttr, 1));
      mesh.userData.records = bucket.instanceRecords;
      mesh.renderOrder = 1;
      meshes.push(mesh);
      pickList.push(mesh);
    }
  }
  let edges = null;
  if (edgePos.length) {
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.Float32BufferAttribute(edgePos, 3));
    edges = new THREE.LineSegments(geo, new THREE.LineBasicMaterial({
      color: 0x7af6ff,
      transparent: true,
      opacity: 0.85,
    }));
    edges.renderOrder = 3;
  }
  return {
    meshes,
    edges,
    records,
    pickMeshes: pickList,
    count: records.length,
    truncated,
    gross,
    flooded,
    tallest,
    estimatedCount,
    massMid: records.length ? midSum / records.length : 12,
  };
}

function addReticles(records) {
  const ranked = records
    .map((rec, index) => ({ rec, index }))
    .filter((row) => row.rec.flooded_volume_m3 > 0)
    .sort((a, b) => b.rec.flooded_volume_m3 - a.rec.flooded_volume_m3)
    .slice(0, RETICLE_CAP);
  for (const row of ranked) {
    const rec = row.rec;
    let radius = 8;
    if (rec.xz) {
      for (const p of rec.xz) radius = Math.max(radius, Math.hypot(p[0] - rec.x, p[1] - rec.z) * 0.72);
    }
    radius = Math.min(36, radius);
    const reticle = new THREE.Group();
    const ring = new THREE.Mesh(
      new THREE.TorusGeometry(radius, 0.55, 6, 28),
      new THREE.MeshBasicMaterial({ color: 0xf5d90a })
    );
    ring.rotation.x = Math.PI / 2;
    ring.position.set(rec.x, rec.topY + 1.6, rec.z);
    reticle.add(ring);
    const labelY = rec.topY + 18;
    const leaderGeo = new THREE.BufferGeometry();
    leaderGeo.setAttribute("position", new THREE.Float32BufferAttribute([
      rec.x, rec.topY + 1.6, rec.z,
      rec.x, labelY, rec.z,
    ], 3));
    reticle.add(new THREE.Line(leaderGeo, new THREE.LineBasicMaterial({
      color: 0x7af6ff,
      transparent: true,
      opacity: 0.9,
    })));
    const sprite = makeLabel((rec.name || "block") + "  " + Math.round(rec.gross_volume_m3).toLocaleString() + " m³");
    sprite.position.set(rec.x, labelY + 4, rec.z);
    reticle.add(sprite);
    markerGroup.add(reticle);
  }
}

function makeLabel(text) {
  const canvas = document.createElement("canvas");
  canvas.width = 512;
  canvas.height = 64;
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, 512, 64);
  ctx.font = "600 26px ui-monospace, Consolas, monospace";
  ctx.fillStyle = "#d7f6ff";
  ctx.textBaseline = "middle";
  const shown = text.length > 42 ? text.slice(0, 40) + "…" : text;
  ctx.fillText(shown, 8, 32);
  const tex = new THREE.CanvasTexture(canvas);
  tex.userData.disposeMap = true;
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, transparent: true, depthTest: false }));
  sprite.scale.set(150, 18, 1);
  sprite.renderOrder = 4;
  return sprite;
}

function buildRoad(frame, roads) {
  let best = null;
  let bestLen = 0;
  for (const feature of (roads && roads.features) || []) {
    const coords = feature.geometry && feature.geometry.type === "LineString" ? feature.geometry.coordinates : null;
    if (!coords || coords.length < 2) continue;
    const local = [];
    let len = 0;
    for (const pair of coords) {
      const y = sampleElev(frame.elev, pair[0], pair[1]) - frame.baseline;
      const p = toLocal(pair[0], pair[1], y + frame.baseline, frame);
      if (local.length) len += Math.hypot(p.x - local[local.length - 1].x, p.z - local[local.length - 1].z);
      local.push(new THREE.Vector3(p.x, p.y, p.z));
    }
    if (len > bestLen) {
      bestLen = len;
      best = local;
    }
  }
  if (!best) return centerline(frame);
  return resamplePath(best, 10);
}

function centerline(frame) {
  const alongX = frame.width >= frame.depthM;
  const length = alongX ? frame.width : frame.depthM;
  const n = Math.max(2, Math.ceil(length / 10));
  const pts = [];
  for (let i = 0; i <= n; i++) {
    const t = i / n;
    const x = alongX ? -frame.width / 2 + t * frame.width : 0;
    const z = alongX ? 0 : -frame.depthM / 2 + t * frame.depthM;
    pts.push(new THREE.Vector3(x, groundY(frame, x, z), z));
  }
  return pts;
}

function resamplePath(points, step) {
  if (points.length < 2) return points.map((p) => p.clone());
  const out = [points[0].clone()];
  let carry = 0;
  for (let i = 1; i < points.length; i++) {
    let a = points[i - 1];
    const b = points[i];
    let seg = a.distanceTo(b);
    if (seg < 1e-4) continue;
    let dist = step - carry;
    while (dist <= seg) {
      const t = dist / (seg || 1);
      const p = a.clone().lerp(b, Math.min(1, t));
      out.push(p);
      const left = seg - dist;
      a = p;
      seg = left;
      dist = step;
      carry = 0;
      if (out.length > 8000) return out;
    }
    carry += seg;
  }
  const last = points[points.length - 1];
  if (out[out.length - 1].distanceTo(last) > 1) out.push(last.clone());
  return out;
}

function chooseStreet(path) {
  if (!path || path.length < 2) return null;
  let idx = 0;
  for (let i = 0; i < path.length; i++) {
    let ahead = 0;
    for (let j = i; j < path.length - 1; j++) ahead += path[j].distanceTo(path[j + 1]);
    if (ahead >= 45) { idx = i; break; }
  }
  let remain = 45;
  let look = path[path.length - 1].clone();
  for (let j = idx; j < path.length - 1; j++) {
    const seg = path[j].distanceTo(path[j + 1]);
    if (seg >= remain && seg > 0) {
      look = path[j].clone().lerp(path[j + 1], remain / seg);
      break;
    }
    remain -= seg;
  }
  const eye = path[idx].clone();
  eye.y += 14;
  look.y += 14;
  return { eye, look };
}

function buildWater(frame, drawn, waterHex) {
  const seg = 96;
  const positions = [];
  const indices = [];
  const grid = [];
  for (let iy = 0; iy <= seg; iy++) {
    const row = [];
    const v = iy / seg;
    const z = -frame.depthM / 2 + v * frame.depthM;
    for (let ix = 0; ix <= seg; ix++) {
      const u = ix / seg;
      const x = -frame.width / 2 + u * frame.width;
      const lon = frame.cell.west + u * (frame.cell.east - frame.cell.west);
      const lat = frame.cell.south + v * (frame.cell.north - frame.cell.south);
      const flood = sampleGrid(drawn.drawn, drawn.rows, drawn.cols, u, v);
      const y = sampleElev(frame.elev, lon, lat) - frame.baseline + flood;
      row.push({ x, y, z, flood, index: positions.length / 3 });
      positions.push(x, y, z);
    }
    grid.push(row);
  }
  for (let iy = 0; iy < seg; iy++) {
    for (let ix = 0; ix < seg; ix++) {
      const a = grid[iy][ix];
      const b = grid[iy][ix + 1];
      const c = grid[iy + 1][ix];
      const d = grid[iy + 1][ix + 1];
      if ((a.flood + c.flood + b.flood) / 3 > 0.05) indices.push(a.index, c.index, b.index);
      if ((b.flood + c.flood + d.flood) / 3 > 0.05) indices.push(b.index, c.index, d.index);
    }
  }
  if (!indices.length) return null;
  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
  geo.setIndex(indices);
  geo.computeVertexNormals();
  const mat = new THREE.MeshStandardMaterial({
    color: waterHex,
    transparent: true,
    opacity: 0.45,
    roughness: 0.08,
    metalness: 0.05,
    normalMap: waterNormal,
    depthWrite: false,
  });
  const mesh = new THREE.Mesh(geo, mat);
  mesh.renderOrder = 2;
  return mesh;
}

function buildScan(frame, drawn, records) {
  const pos = new Float32Array(POINT_CAP * 3);
  const col = new Uint8Array(POINT_CAP * 3);
  const cls = new Uint8Array(POINT_CAP);
  let n = 0;
  const classes = { 1: 0, 2: 0, 6: 0, 9: 0 };
  let measured = 0;
  const rng = mulberry32(hashStr(frame.cell.id + ":" + frame.baseline));

  function add(x, y, z, r, g, b, klass) {
    if (n >= POINT_CAP) return false;
    const i = n * 3;
    pos[i] = x; pos[i + 1] = y; pos[i + 2] = z;
    col[i] = r; col[i + 1] = g; col[i + 2] = b;
    cls[n] = klass;
    classes[klass] = (classes[klass] || 0) + 1;
    n += 1;
    return true;
  }

  for (const sample of frame.elev.grid || []) {
    const local = toLocal(sample.lng, sample.lat, sample.elevation_m, frame);
    if (add(local.x, local.y, local.z, 210, 230, 236, 2)) measured += 1;
  }
  const groundN = 192;
  for (let iy = 0; iy < groundN && n < POINT_CAP; iy++) {
    for (let ix = 0; ix < groundN; ix++) {
      const u = Math.min(1, Math.max(0, (ix + 0.5 + (rng() * 2 - 1) * 0.35) / groundN));
      const v = Math.min(1, Math.max(0, (iy + 0.5 + (rng() * 2 - 1) * 0.35) / groundN));
      const lon = frame.cell.west + u * (frame.cell.east - frame.cell.west);
      const lat = frame.cell.south + v * (frame.cell.north - frame.cell.south);
      const local = toLocal(lon, lat, sampleElev(frame.elev, lon, lat), frame);
      const canopy = rng() < 0.02;
      const lift = canopy ? 0.4 + rng() * 0.8 : gauss(rng) * 0.25;
      const rgb = canopy ? [107, 143, 113] : [180, 206, 214];
      if (!add(local.x, local.y + lift, local.z, rgb[0], rgb[1], rgb[2], canopy ? 1 : 2)) break;
    }
  }
  for (const rec of records) {
    if (!rec.xz || n >= POINT_CAP) break;
    const ring = rec.xz;
    for (let i = 0; i < ring.length; i++) {
      const a = ring[i];
      const b = ring[(i + 1) % ring.length];
      const len = Math.hypot(b[0] - a[0], b[1] - a[1]);
      const steps = Math.max(1, Math.floor(len / 6));
      for (let s = 0; s < steps; s++) {
        const t = s / steps;
        const x = a[0] + (b[0] - a[0]) * t;
        const z = a[1] + (b[1] - a[1]) * t;
        for (let y = rec.baseY; y <= rec.topY; y += 3) {
          if (!add(x, y, z, 190, 220, 228, 6)) break;
        }
      }
    }
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  geo.setAttribute("color", new THREE.BufferAttribute(col, 3, true));
  geo.setAttribute("aclass", new THREE.BufferAttribute(cls, 1));
  geo.setDrawRange(0, n);
  const cloud = new THREE.Points(geo, new THREE.PointsMaterial({
    size: 1.2,
    sizeAttenuation: true,
    vertexColors: true,
    transparent: true,
    opacity: 0.35,
    depthWrite: false,
  }));
  cloud.renderOrder = 4;
  return { points: cloud, measured, synthetic: Math.max(0, n - measured), classes };
}

function pickAt(ev) {
  const rect = renderer.domElement.getBoundingClientRect();
  pointer.x = ((ev.clientX - rect.left) / rect.width) * 2 - 1;
  pointer.y = -((ev.clientY - rect.top) / rect.height) * 2 + 1;
  content.updateMatrixWorld(true);
  raycaster.setFromCamera(pointer, camera);
  const hits = raycaster.intersectObjects(pickMeshes, false);
  if (!hits.length) {
    pickEl.hidden = true;
    return;
  }
  const hit = hits[0];
  let rec = null;
  if (hit.instanceId != null && hit.object.userData.records) {
    const slot = hit.object.userData.records[hit.instanceId];
    rec = typeof slot === "number" ? analysis[slot] : slot;
  } else if (hit.face && hit.object.geometry.getAttribute("bindex")) {
    rec = analysis[Math.round(hit.object.geometry.getAttribute("bindex").getX(hit.face.a))];
  }
  if (!rec) {
    pickEl.hidden = true;
    return;
  }
  pickEl.hidden = false;
  pickEl.textContent = [
    rec.name || "block",
    "area " + Math.round(rec.area_m2).toLocaleString() + " m²",
    "height " + rec.height_m.toFixed(1) + " m",
    "gross " + fmtM3(rec.gross_volume_m3),
    "depth " + rec.depth_m.toFixed(2) + " m",
    "flooded " + fmtM3(rec.flooded_volume_m3),
    "material " + rec.material,
    "source " + rec.source,
    "estimated height " + (rec.estimated_height ? "yes" : "no"),
  ].join("\n");
}

function flatGrid(cell) {
  const rows = 4;
  const cols = 4;
  const heightmap = [];
  const grid = [];
  for (let r = 0; r < rows; r++) {
    const line = [];
    const lat = cell.south + (cell.north - cell.south) * r / (rows - 1);
    for (let c = 0; c < cols; c++) {
      const lng = cell.west + (cell.east - cell.west) * c / (cols - 1);
      line.push(2);
      grid.push({ lat, lng, elevation_m: 2, resolution_m: 0, provider: "heuristic" });
    }
    heightmap.push(line);
  }
  return { provider: "heuristic", baseline_elevation_m: 2, heightmap, grid, rows, cols, bbox: { west: cell.west, south: cell.south, east: cell.east, north: cell.north } };
}

function sampleElev(elev, lon, lat) {
  const west = elev.bbox ? elev.bbox.west : elev.grid[0].lng;
  const east = elev.bbox ? elev.bbox.east : elev.grid[elev.grid.length - 1].lng;
  const south = elev.bbox ? elev.bbox.south : elev.grid[0].lat;
  const north = elev.bbox ? elev.bbox.north : elev.grid[elev.grid.length - 1].lat;
  const u = east === west ? 0 : (lon - west) / (east - west);
  const v = north === south ? 0 : (lat - south) / (north - south);
  return sampleGrid(elev.heightmap, elev.rows, elev.cols, u, v);
}

function sampleDepthAt(drawn, lon, lat) {
  const u = (lon - drawn.west) / (drawn.east - drawn.west);
  const v = (lat - drawn.south) / (drawn.north - drawn.south);
  return sampleGrid(drawn.drawn, drawn.rows, drawn.cols, u, v);
}

function sampleGrid(grid, rows, cols, u, v) {
  const uu = Math.min(1, Math.max(0, u));
  const vv = Math.min(1, Math.max(0, v));
  if (!grid || rows < 2 || cols < 2) return Number(grid && grid[0] && grid[0][0]) || 0;
  const x = uu * (cols - 1);
  const y = vv * (rows - 1);
  const x0 = Math.min(cols - 2, Math.floor(x));
  const y0 = Math.min(rows - 2, Math.floor(y));
  const tx = x - x0;
  const ty = y - y0;
  const g00 = Number(grid[y0][x0]) || 0;
  const g10 = Number(grid[y0][x0 + 1]) || 0;
  const g01 = Number(grid[y0 + 1][x0]) || 0;
  const g11 = Number(grid[y0 + 1][x0 + 1]) || 0;
  return g00 * (1 - tx) * (1 - ty) + g10 * tx * (1 - ty) + g01 * (1 - tx) * ty + g11 * tx * ty;
}

function toLocal(lon, lat, elev, frame) {
  return {
    x: (lon - frame.lon0) * M_PER_DEG * Math.cos(frame.lat0 * Math.PI / 180),
    y: elev - frame.baseline,
    z: (lat - frame.lat0) * M_PER_DEG,
  };
}

function projectRing(ring, frame) {
  const out = [];
  if (!ring || ring.length < 3) return out;
  const open = ring[0][0] === ring[ring.length - 1][0] && ring[0][1] === ring[ring.length - 1][1]
    ? ring.slice(0, -1) : ring.slice();
  for (const pair of open) {
    const local = toLocal(pair[0], pair[1], frame.baseline, frame);
    out.push([local.x, local.z]);
  }
  return out;
}

function ringOf(feature) {
  const geom = (feature && feature.geometry) || {};
  if (geom.type === "Polygon" && geom.coordinates && geom.coordinates[0]) return geom.coordinates[0];
  return [];
}

function footprintItems(osm, local) {
  const raw = [];
  for (const feature of (osm && osm.features) || []) raw.push({ feature, source: "osm" });
  const osmCents = raw.map((item) => lonLatOf(item.feature));
  for (const feature of (local && local.features) || []) {
    const here = lonLatOf(feature);
    let hit = -1;
    if (Number.isFinite(here.lat) && Number.isFinite(here.lon)) {
      for (let i = 0; i < osmCents.length; i++) {
        if (haversine(here.lat, here.lon, osmCents[i].lat, osmCents[i].lon) < 12) { hit = i; break; }
      }
    }
    if (hit >= 0) {
      if (!String(raw[hit].source).includes("open_buildings")) raw[hit].source += "+open_buildings";
      continue;
    }
    const props = feature.properties || {};
    const estimatedSrc = props.match === "estimated" || props.source === "estimated_rectangle";
    raw.push({ feature, source: estimatedSrc ? "estimated" : "open_buildings" });
  }
  return raw;
}

function lonLatOf(feature) {
  const props = (feature && feature.properties) || {};
  const lat = Number(props.centroid_lat);
  const lon = Number(props.centroid_lng != null ? props.centroid_lng : props.centroid_lon);
  if (Number.isFinite(lat) && Number.isFinite(lon)) return { lat, lon };
  const ring = ringOf(feature);
  if (ring.length) {
    let slat = 0;
    let slon = 0;
    const n = ring[0][0] === ring[ring.length - 1][0] ? ring.length - 1 : ring.length;
    for (let i = 0; i < n; i++) { slon += ring[i][0]; slat += ring[i][1]; }
    return { lon: slon / n, lat: slat / n };
  }
  return { lat: NaN, lon: NaN };
}

function simplifyRing(points, maxCount) {
  const clean = [];
  for (const p of points) {
    const prev = clean[clean.length - 1];
    if (!prev || Math.hypot(p[0] - prev[0], p[1] - prev[1]) > 0.4) clean.push(p);
  }
  if (clean.length <= maxCount) return clean;
  let lo = 0;
  let hi = 500;
  let best = clean;
  for (let i = 0; i < 14; i++) {
    const mid = (lo + hi) / 2;
    const simplified = rdp(clean, mid);
    if (simplified.length > maxCount) lo = mid;
    else { best = simplified; hi = mid; }
  }
  if (best.length <= maxCount) return best;
  const stride = [];
  for (let i = 0; i < maxCount; i++) stride.push(clean[Math.floor(i * clean.length / maxCount)]);
  return stride;
}

function rdp(points, epsilon) {
  if (points.length < 3) return points.slice();
  let maxD = 0;
  let index = 0;
  const a = points[0];
  const b = points[points.length - 1];
  for (let i = 1; i < points.length - 1; i++) {
    const d = perp(points[i], a, b);
    if (d > maxD) { maxD = d; index = i; }
  }
  if (maxD > epsilon) {
    const left = rdp(points.slice(0, index + 1), epsilon);
    const right = rdp(points.slice(index), epsilon);
    return left.slice(0, -1).concat(right);
  }
  return [a, b];
}

function perp(p, a, b) {
  const dx = b[0] - a[0];
  const dz = b[1] - a[1];
  const len = Math.hypot(dx, dz) || 1;
  return Math.abs((p[0] - a[0]) * dz - (p[1] - a[1]) * dx) / len;
}

function signedArea(xz) {
  let area = 0;
  for (let i = 0; i < xz.length; i++) {
    const j = (i + 1) % xz.length;
    area += xz[i][0] * xz[j][1] - xz[j][0] * xz[i][1];
  }
  return area / 2;
}

function ringCentroid(xz) {
  let a = 0;
  let cx = 0;
  let cz = 0;
  for (let i = 0; i < xz.length; i++) {
    const j = (i + 1) % xz.length;
    const cross = xz[i][0] * xz[j][1] - xz[j][0] * xz[i][1];
    a += cross;
    cx += (xz[i][0] + xz[j][0]) * cross;
    cz += (xz[i][1] + xz[j][1]) * cross;
  }
  if (Math.abs(a) < 1e-4) {
    let sx = 0;
    let sz = 0;
    for (const p of xz) { sx += p[0]; sz += p[1]; }
    const n = xz.length || 1;
    return { x: sx / n, z: sz / n };
  }
  return { x: cx / (3 * a), z: cz / (3 * a) };
}

function bucketFor(buckets, key) {
  if (!buckets.has(key)) buckets.set(key, { pos: [], risk: [], wet: [], bindex: [], instances: [], instanceRecords: [] });
  return buckets.get(key);
}

function addPrism(bucket, xz, baseY, topY, risk, wet, index) {
  const ring = xz.slice();
  if (signedArea(ring) < 0) ring.reverse();
  const n = ring.length;
  function tri(ax, ay, az, bx, by, bz, cx, cy, cz) {
    bucket.pos.push(ax, ay, az, bx, by, bz, cx, cy, cz);
    for (let k = 0; k < 3; k++) {
      bucket.risk.push(risk[0], risk[1], risk[2]);
      bucket.wet.push(wet);
      bucket.bindex.push(index);
    }
  }
  for (let i = 1; i < n - 1; i++) {
    tri(ring[0][0], topY, ring[0][1], ring[i][0], topY, ring[i][1], ring[i + 1][0], topY, ring[i + 1][1]);
    tri(ring[0][0], baseY, ring[0][1], ring[i + 1][0], baseY, ring[i + 1][1], ring[i][0], baseY, ring[i][1]);
  }
  for (let i = 0; i < n; i++) {
    const j = (i + 1) % n;
    const a = ring[i];
    const b = ring[j];
    tri(a[0], baseY, a[1], a[0], topY, a[1], b[0], topY, b[1]);
    tri(a[0], baseY, a[1], b[0], topY, b[1], b[0], baseY, b[1]);
  }
}

function addOutline(edges, ring, baseY, topY) {
  const loop = ring.slice();
  if (signedArea(loop) < 0) loop.reverse();
  for (let i = 0; i < loop.length; i++) {
    const a = loop[i];
    const b = loop[(i + 1) % loop.length];
    edges.push(a[0], topY, a[1], b[0], topY, b[1]);
    edges.push(a[0], baseY, a[1], b[0], baseY, b[1]);
    edges.push(a[0], baseY, a[1], a[0], topY, a[1]);
  }
}

function addBox(buckets, key, xz, baseY, height, risk, wet, index, edges) {
  let minX = Infinity;
  let maxX = -Infinity;
  let minZ = Infinity;
  let maxZ = -Infinity;
  for (const p of xz) {
    if (p[0] < minX) minX = p[0];
    if (p[0] > maxX) maxX = p[0];
    if (p[1] < minZ) minZ = p[1];
    if (p[1] > maxZ) maxZ = p[1];
  }
  if (!Number.isFinite(minX)) { minX = -4; maxX = 4; minZ = -4; maxZ = 4; }
  const w = Math.max(4, (maxX - minX) || 8);
  const d = Math.max(4, (maxZ - minZ) || 8);
  const cx = (minX + maxX) / 2;
  const cz = (minZ + maxZ) / 2;
  const matrix = new THREE.Matrix4();
  matrix.compose(
    new THREE.Vector3(cx, baseY + height / 2, cz),
    new THREE.Quaternion(),
    new THREE.Vector3(w, height, d)
  );
  const bucket = bucketFor(buckets, key);
  bucket.instances.push({ matrix, risk, wet });
  bucket.instanceRecords.push(index);
  const top = baseY + height;
  const x0 = cx - w / 2;
  const x1 = cx + w / 2;
  const z0 = cz - d / 2;
  const z1 = cz + d / 2;
  const corners = [[x0, z0], [x1, z0], [x1, z1], [x0, z1]];
  for (let i = 0; i < 4; i++) {
    const a = corners[i];
    const b = corners[(i + 1) % 4];
    edges.push(a[0], top, a[1], b[0], top, b[1]);
    edges.push(a[0], baseY, a[1], b[0], baseY, b[1]);
    edges.push(a[0], baseY, a[1], a[0], top, a[1]);
  }
}

function styleMaterial(key) {
  const spec = MATERIALS[key.split(":")[0]] || MATERIALS.masonry;
  const estimated = key.endsWith(":est");
  const mat = new THREE.MeshStandardMaterial({
    color: spec.color,
    roughness: spec.roughness,
    metalness: spec.metalness,
    transparent: true,
    opacity: estimated ? 0.55 : 0.72,
    flatShading: true,
    depthWrite: true,
    side: THREE.DoubleSide,
  });
  hookGlass(mat);
  return mat;
}

function hookRisk(material) {
  material.onBeforeCompile = (shader) => {
    shader.uniforms.uRisk = { value: riskOn ? 1 : 0 };
    riskShaders.push(shader);
    shader.vertexShader = shader.vertexShader
      .replace("#include <color_pars_vertex>", "#include <color_pars_vertex>\nattribute vec3 riskTint;\nattribute float wetness;\nvarying vec3 vRiskTint;\nvarying float vWetness;")
      .replace("#include <color_vertex>", "#include <color_vertex>\nvRiskTint = riskTint;\nvWetness = wetness;");
    shader.fragmentShader = shader.fragmentShader
      .replace("#include <color_pars_fragment>", "#include <color_pars_fragment>\nvarying vec3 vRiskTint;\nvarying float vWetness;\nuniform float uRisk;")
      .replace("vec3 totalEmissiveRadiance = emissive;", "vec3 totalEmissiveRadiance = emissive + vRiskTint * uRisk * 0.15;")
      .replace("#include <roughnessmap_fragment>", "#include <roughnessmap_fragment>\nroughnessFactor = clamp(roughnessFactor - vWetness * 0.15, 0.04, 1.0);");
  };
  const previous = material.customProgramCacheKey.bind(material);
  material.customProgramCacheKey = () => previous() + ":diorama-risk";
}

function hookGlass(material) {
  material.onBeforeCompile = (shader) => {
    shader.uniforms.uRisk = { value: riskOn ? 1 : 0 };
    riskShaders.push(shader);
    shader.vertexShader = shader.vertexShader
      .replace("#include <color_pars_vertex>", "#include <color_pars_vertex>\nattribute vec3 riskTint;\nattribute float wetness;\nvarying vec3 vRiskTint;\nvarying float vWetness;\nvarying float vFloorY;")
      .replace("#include <color_vertex>", "#include <color_vertex>\nvRiskTint = riskTint;\nvWetness = wetness;\nvFloorY = position.y;");
    shader.fragmentShader = shader.fragmentShader
      .replace("#include <color_pars_fragment>", "#include <color_pars_fragment>\nvarying vec3 vRiskTint;\nvarying float vWetness;\nvarying float vFloorY;\nuniform float uRisk;")
      .replace("vec3 totalEmissiveRadiance = emissive;", "vec3 totalEmissiveRadiance = emissive + vRiskTint * uRisk * 0.15;")
      .replace("#include <color_fragment>", "#include <color_fragment>\nfloat band = smoothstep(0.08, 0.0, abs(fract(vFloorY / 3.2) - 0.62));\ndiffuseColor.rgb = mix(diffuseColor.rgb, vec3(0.93, 0.98, 1.0), band * 0.42);")
      .replace("#include <roughnessmap_fragment>", "#include <roughnessmap_fragment>\nroughnessFactor = clamp(roughnessFactor - vWetness * 0.15, 0.04, 1.0);");
  };
  const previous = material.customProgramCacheKey.bind(material);
  material.customProgramCacheKey = () => previous() + ":diorama-glass";
}

function indexManifest(manifest) {
  const rows = (manifest && manifest.buildings) || [];
  return rows.map((row) => ({
    lat: row.centroid && Number(row.centroid.latitude),
    lon: row.centroid && Number(row.centroid.longitude),
    material: row.predicted_material || "",
    depth: Number(row.inundation_depth_m) || 0,
    risk: row.risk_level || "",
  })).filter((row) => Number.isFinite(row.lat) && Number.isFinite(row.lon));
}

function manifestStamps(manifest, cell) {
  return indexManifest(manifest).filter((row) => (
    row.depth > 0.05 &&
    row.lon >= cell.west && row.lon <= cell.east &&
    row.lat >= cell.south && row.lat <= cell.north
  ));
}

function matchBook(books, lat, lon) {
  let best = null;
  let bestD = 35;
  for (const book of books) {
    const d = haversine(lat, lon, book.lat, book.lon);
    if (d < bestD) { best = book; bestD = d; }
  }
  return best;
}

function materialLabel(props, book) {
  const named = props["building:material"] || props.building_material;
  if (named) return String(named);
  const tag = String(props.building || "");
  if (tag && tag !== "yes" && /concrete|masonry|brick|timber|wood|steel|metal|mabati|corrug/i.test(tag)) return tag;
  if (book && book.material) return String(book.material);
  return "Unknown";
}

function materialKey(name) {
  const text = String(name || "").toLowerCase();
  if (text.includes("corrug") || text.includes("mabati")) return "metal";
  if (text.includes("timber") || text.includes("wood")) return "timber";
  if (text.includes("steel")) return "steel";
  return "masonry";
}

function riskRGB(level) {
  const text = String(level || "").toLowerCase();
  if (text.includes("high") || text.includes("severe")) return [0xc1 / 255, 0x12 / 255, 0x1f / 255];
  if (text.includes("mod") || text.includes("med")) return [0xe0 / 255, 0xb8 / 255, 0x25 / 255];
  if (text.includes("low")) return [0x2a / 255, 0x9d / 255, 0x4a / 255];
  return [0, 0, 0];
}

function resolveHeight(props, area) {
  const parsed = parseMetres(props.height);
  if (parsed >= 2 && parsed <= 120) return { height: parsed, estimated: false };
  const levels = parseMetres(props["building:levels"] != null ? props["building:levels"] : props.building_levels);
  if (levels > 0) {
    const height = levels * 3.2;
    if (height >= 2 && height <= 120) return { height, estimated: false };
  }
  const storeys = Math.min(Math.max(area, 0) / 80, 12);
  return { height: Math.max(3.5, storeys * 3.5), estimated: true };
}

function parseMetres(value) {
  if (value == null || value === "") return NaN;
  const text = String(value).trim().toLowerCase();
  if (text.includes("ft")) return NaN;
  const match = text.match(/-?\d+(\.\d+)?/);
  return match ? Number(match[0]) : NaN;
}

function haversine(lat1, lon1, lat2, lon2) {
  if (![lat1, lon1, lat2, lon2].every(Number.isFinite)) return Infinity;
  const p1 = lat1 * Math.PI / 180;
  const p2 = lat2 * Math.PI / 180;
  const dphi = (lat2 - lat1) * Math.PI / 180;
  const dl = (lon2 - lon1) * Math.PI / 180;
  const h = Math.sin(dphi / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) ** 2;
  return 2 * 6371000 * Math.asin(Math.min(1, Math.sqrt(h)));
}

function bufferBytes(root) {
  let total = 0;
  const seen = new Set();
  root.traverse((node) => {
    if (!node.geometry || seen.has(node.geometry.uuid)) return;
    seen.add(node.geometry.uuid);
    const geo = node.geometry;
    for (const name in geo.attributes) {
      const attr = geo.attributes[name];
      if (attr && attr.array) total += attr.array.byteLength;
    }
    if (geo.index && geo.index.array) total += geo.index.array.byteLength;
  });
  return total;
}

function fmtM3(n) {
  const value = Number(n) || 0;
  if (value >= 1e6) return (value / 1e6).toFixed(2) + " million m³";
  return Math.round(value).toLocaleString() + " m³";
}

function hexColor(value, fallback) {
  if (typeof value === "string" && /^#[0-9a-fA-F]{6}$/.test(value)) return parseInt(value.slice(1), 16);
  return fallback;
}

function hashStr(text) {
  let h = 2166136261;
  for (let i = 0; i < text.length; i++) h = Math.imul(h ^ text.charCodeAt(i), 16777619);
  return h >>> 0;
}

function mulberry32(seed) {
  let a = seed >>> 0;
  return function rng() {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function gauss(rng) {
  const u = Math.max(1e-9, 1 - rng());
  const v = rng();
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
}

function makeWaterNormal() {
  const canvas = document.createElement("canvas");
  canvas.width = 64;
  canvas.height = 64;
  const ctx = canvas.getContext("2d");
  const image = ctx.createImageData(64, 64);
  for (let y = 0; y < 64; y++) {
    for (let x = 0; x < 64; x++) {
      const i = (y * 64 + x) * 4;
      const nx = Math.sin(x * 0.45) * 0.18;
      const ny = Math.cos(y * 0.38) * 0.18;
      image.data[i] = (nx * 0.5 + 0.5) * 255;
      image.data[i + 1] = (ny * 0.5 + 0.5) * 255;
      image.data[i + 2] = 255;
      image.data[i + 3] = 255;
    }
  }
  ctx.putImageData(image, 0, 0);
  const tex = new THREE.CanvasTexture(canvas);
  tex.wrapS = THREE.RepeatWrapping;
  tex.wrapT = THREE.RepeatWrapping;
  tex.repeat.set(6, 6);
  return tex;
}
