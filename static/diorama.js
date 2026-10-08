import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

const M_PER_DEG = 111320;
const POINT_CAP = 150000;
const BUILDING_CAP = 8000;
const CELLS = {
  cbd: { id: "cbd", name: "CBD", west: 36.812, south: -1.286, east: 36.828, north: -1.274 },
  westlands: { id: "westlands", name: "Westlands", west: 36.798, south: -1.271, east: 36.814, north: -1.259 },
  upperhill: { id: "upperhill", name: "Upper Hill", west: 36.805, south: -1.305, east: 36.821, north: -1.293 },
};

const MATERIALS = {
  masonry: { color: 0xb8b0a8, roughness: 0.62, metalness: 0.12 },
  metal: { color: 0x8e9794, roughness: 0.35, metalness: 0.45 },
  timber: { color: 0x8c6a45, roughness: 0.8, metalness: 0.05 },
  steel: { color: 0x9aa3a8, roughness: 0.32, metalness: 0.55 },
};

const app = document.getElementById("app");
const loadingEl = document.getElementById("loading");
const statsEl = document.getElementById("stats");
const noteEl = document.getElementById("note");
const titleEl = document.getElementById("title");
const cellSelect = document.getElementById("cell");

const renderer = new THREE.WebGLRenderer({ antialias: false, powerPreference: "high-performance" });
renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
renderer.setSize(window.innerWidth, window.innerHeight);
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.0;
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.shadowMap.enabled = false;
app.appendChild(renderer.domElement);

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x87ceeb);
scene.fog = new THREE.FogExp2(0xc9d6df, 0.00045);

const camera = new THREE.PerspectiveCamera(40, window.innerWidth / window.innerHeight, 1, 20000);
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.dampingFactor = 0.06;
controls.autoRotate = true;
controls.autoRotateSpeed = 0.25;
controls.maxPolarAngle = Math.PI * 0.49;
controls.minDistance = 80;
controls.addEventListener("start", () => { controls.autoRotate = false; });
controls.addEventListener("end", () => { controls.autoRotate = true; });

scene.add(new THREE.HemisphereLight(0x87ceeb, 0x6b5e52, 0.7));
const sun = new THREE.DirectionalLight(0xffffff, 1.6);
sun.position.set(1, 1.4, 1);
scene.add(sun);

const content = new THREE.Group();
scene.add(content);
const meshGroup = new THREE.Group();
const floodGroup = new THREE.Group();
content.add(meshGroup);
content.add(floodGroup);

const plinth = new THREE.Mesh(
  new THREE.CircleGeometry(1, 48),
  new THREE.MeshBasicMaterial({ color: 0x000000, transparent: true, opacity: 0.45, depthWrite: false })
);
plinth.rotation.x = -Math.PI / 2;
plinth.position.y = -1.5;
scene.add(plinth);

const waterNormal = makeWaterNormal();
let points = null;
let riskOn = false;
let running = true;
let job = 0;
let abort = null;
let meanRelief = 8;
const lastElev = new Map();
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
  content.scale.y = on ? 1.5 : 1;
  controls.target.y = meanRelief * content.scale.y;
});
cellSelect.addEventListener("change", () => loadCell(cellSelect.value));

const params = new URLSearchParams(window.location.search);
const initial = CELLS[params.get("cell")] ? params.get("cell") : "cbd";
cellSelect.value = initial;
loadCell(initial);

function animate() {
  requestAnimationFrame(animate);
  if (!running) return;
  waterNormal.offset.x += 0.0008;
  controls.update();
  renderer.render(scene, camera);
}
animate();

async function loadCell(id) {
  const cell = CELLS[id] || CELLS.cbd;
  job += 1;
  const token = job;
  if (abort) abort.abort();
  abort = new AbortController();
  const signal = abort.signal;
  loadingEl.style.display = "flex";
  loadingEl.textContent = "Loading " + cell.name + "…";
  titleEl.textContent = cell.name + " · Nairobi";
  const q = "west=" + cell.west + "&south=" + cell.south + "&east=" + cell.east + "&north=" + cell.north;
  // 20×20 stays inside the elevation API cap and is three or four Open-Meteo
  // calls. A 48×48 grid trips the free-tier rate limit and collapses to a flat plinth.
  let elev = null;
  try {
    elev = await getJSON("/api/spatial/elevation?" + q + "&rows=20&cols=20", signal);
  } catch (err) {
    if (err && err.name === "AbortError") return;
    elev = null;
  }
  if (token !== job) return;
  const settled = await Promise.allSettled([
    getJSON("/api/v1/flood/buildings?" + q, signal),
    getJSON("/api/export/blender-manifest?shader_preset=PHOTOREAL_DEFAULT&storey_height_m=3.5", signal),
    getJSON("/api/spatial/flood-depth?" + q + "&rows=32&cols=32&region=nairobi", signal),
    getJSON("/api/spatial/render-presets", signal),
    getJSON("/api/v1/flood/hazard", signal),
    loadTerrainTexture("/api/v1/flood/imagery/terrain?" + q, signal),
  ]);
  if (token !== job) return;
  const buildings = valueOf(settled[0]);
  const manifest = valueOf(settled[1]);
  const depth = valueOf(settled[2]);
  const presets = valueOf(settled[3]);
  const texture = valueOf(settled[5]);
  let grid = elev;
  const notes = [];
  if (!grid || !grid.heightmap) {
    grid = lastElev.get(cell.id) || flatGrid(cell);
    notes.push(grid.provider === "heuristic"
      ? "Elevation failed. Flat plinth at the heuristic height."
      : "Elevation failed. Showing the last good grid for this cell.");
  } else {
    lastElev.set(cell.id, grid);
  }
  if (grid.provider === "heuristic") notes.push("Elevation provider is heuristic. Terrain is a flat plinth.");
  if (!texture) notes.push("Satellite image unavailable. Terrain is clay.");
  if (!depth || !depth.depth_m) notes.push("Flood grid unavailable.");
  if (!buildings || !buildings.features || !buildings.features.length) notes.push("No footprints in this cell. Terrain and the scan only.");
  try {
    buildScene(cell, grid, buildings, manifest, depth, presets, texture, notes);
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

function buildScene(cell, elev, buildingsFc, manifest, depth, presets, texture, notes) {
  disposeContents();
  const palette = (presets && presets.presets && presets.presets.PHOTOREAL_DEFAULT && presets.presets.PHOTOREAL_DEFAULT.palette) || {};
  const sky = hexColor(palette.sky, 0x87ceeb);
  const fog = hexColor(palette.fog, 0xc9d6df);
  const waterHex = hexColor(palette.water, 0x4c8dde);
  scene.background = new THREE.Color(sky);
  scene.fog.color.setHex(fog);

  const lon0 = (cell.west + cell.east) / 2;
  const lat0 = (cell.south + cell.north) / 2;
  const baseline = Number(elev.baseline_elevation_m);
  const width = (cell.east - cell.west) * M_PER_DEG * Math.cos(lat0 * Math.PI / 180);
  const depthM = (cell.north - cell.south) * M_PER_DEG;
  const frame = { cell, lon0, lat0, baseline, width, depthM, elev };

  const drawn = buildDrawnDepth(frame, depth, manifest);
  const terrain = buildTerrain(frame, drawn, texture, waterHex);
  meshGroup.add(terrain.mesh);
  const built = buildBuildings(frame, buildingsFc, manifest, drawn);
  for (const mesh of built.meshes) meshGroup.add(mesh);
  const water = buildWater(frame, drawn, waterHex);
  if (water) floodGroup.add(water);
  floodGroup.visible = document.getElementById("tog-flood").getAttribute("aria-pressed") === "true";
  meshGroup.visible = document.getElementById("tog-mesh").getAttribute("aria-pressed") === "true";

  const scan = buildScan(frame, drawn, built.records);
  points = scan.points;
  points.visible = document.getElementById("tog-scan").getAttribute("aria-pressed") === "true";
  content.add(points);

  const radius = 1.15 * Math.hypot(width, depthM) / 2;
  plinth.geometry.dispose();
  plinth.geometry = new THREE.CircleGeometry(radius, 64);
  scene.fog.density = 1.15 / Math.max(radius * 2, 1);

  meanRelief = terrain.meanRelief;
  content.scale.y = document.getElementById("tog-vex").getAttribute("aria-pressed") === "true" ? 1.5 : 1;
  camera.position.set(0.9 * width, 0.55 * width, 0.9 * width);
  controls.target.set(0, meanRelief * content.scale.y, 0);
  controls.maxDistance = 2.5 * width;
  controls.update();

  const bytes = bufferBytes(content) + bufferBytes(plinth);
  const heap = window.performance && performance.memory ? performance.memory.usedJSHeapSize : 0;
  const resolution = elev.grid && elev.grid[0] ? elev.grid[0].resolution_m : 0;
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
    bbox,
    "elevation " + (elev.provider || "unknown") + (resolution ? " · posting " + resolution + " m" : ""),
    "measured " + scan.measured + " · synthetic " + scan.synthetic,
    "buildings " + built.count + (built.truncated ? " (capped)" : ""),
    "max depth " + drawn.maxDrawn.toFixed(2) + " m",
    "buffers " + (bytes / 1048576).toFixed(1) + " MB" + (heap ? " · heap " + (heap / 1048576).toFixed(0) + " MB" : ""),
  ].join("\n");
  const extra = [];
  if (drawn.relief >= 2) extra.push("Water follows hazard depth on the lower ground. Ridge tops in this cell stay dry.");
  if (bytes > 100 * 1048576) extra.push("Buffer sum is over 100 MB.");
  noteEl.textContent = notes.concat(extra).join(" ");
}

function disposeContents() {
  riskShaders.length = 0;
  for (const group of [meshGroup, floodGroup, content]) {
    const children = group === content ? group.children.filter((child) => child !== meshGroup && child !== floodGroup) : [...group.children];
    for (const child of children) {
      child.traverse((node) => {
        if (node.geometry) node.geometry.dispose();
        const mats = node.material ? [].concat(node.material) : [];
        for (const mat of mats) {
          if (mat.map && mat.map.userData.disposeMap) mat.map.dispose();
          mat.dispose();
        }
      });
      group.remove(child);
    }
  }
  points = null;
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
  const stamps = manifestStamps(manifest, frame.cell);
  for (const stamp of stamps) {
    const v = (stamp.lat - frame.cell.south) / (frame.cell.north - frame.cell.south);
    const u = (stamp.lon - frame.cell.west) / (frame.cell.east - frame.cell.west);
    const r = Math.max(0, Math.min(rows - 1, Math.round(v * (rows - 1))));
    const c = Math.max(0, Math.min(cols - 1, Math.round(u * (cols - 1))));
    drawn[r][c] = Math.max(drawn[r][c], stamp.depth);
    if (drawn[r][c] > maxDrawn) maxDrawn = drawn[r][c];
  }
  return {
    rows, cols, drawn, relief, maxDrawn,
    west: frame.cell.west, south: frame.cell.south, east: frame.cell.east, north: frame.cell.north,
  };
}

function buildTerrain(frame, drawn, texture, waterHex) {
  const seg = 255;
  const positions = new Float32Array((seg + 1) * (seg + 1) * 3);
  const colors = new Float32Array((seg + 1) * (seg + 1) * 3);
  const uvs = new Float32Array((seg + 1) * (seg + 1) * 2);
  const risk = new Float32Array((seg + 1) * (seg + 1) * 3);
  const wet = new Float32Array((seg + 1) * (seg + 1));
  const indices = new Uint32Array(seg * seg * 6);
  const water = new THREE.Color(waterHex);
  let reliefSum = 0;
  let vcount = 0;
  for (let iy = 0; iy <= seg; iy++) {
    const v = iy / seg;
    const z = -frame.depthM / 2 + v * frame.depthM;
    for (let ix = 0; ix <= seg; ix++) {
      const u = ix / seg;
      const x = -frame.width / 2 + u * frame.width;
      const lon = frame.cell.west + u * (frame.cell.east - frame.cell.west);
      const lat = frame.cell.south + v * (frame.cell.north - frame.cell.south);
      const elev = sampleElev(frame.elev, lon, lat);
      const y = elev - frame.baseline;
      const flood = sampleGrid(drawn.drawn, drawn.rows, drawn.cols, u, v);
      const o = vcount * 3;
      positions[o] = x;
      positions[o + 1] = y;
      positions[o + 2] = z;
      const tint = Math.min(Math.max(flood / 2, 0), 0.45);
      colors[o] = 1 * (1 - tint) + water.r * tint;
      colors[o + 1] = 1 * (1 - tint) + water.g * tint;
      colors[o + 2] = 1 * (1 - tint) + water.b * tint;
      uvs[vcount * 2] = u;
      uvs[vcount * 2 + 1] = v;
      wet[vcount] = flood > 0.3 ? 1 : 0;
      reliefSum += y;
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
  });
  if (texture) mat.userData.disposeMap = false;
  hookRisk(mat);
  const mesh = new THREE.Mesh(geo, mat);
  mesh.renderOrder = 0;
  return { mesh, meanRelief: reliefSum / vcount };
}

function buildBuildings(frame, buildingsFc, manifest, drawn) {
  const features = (buildingsFc && buildingsFc.features) || [];
  const books = indexManifest(manifest);
  const buckets = new Map();
  const records = [];
  let count = 0;
  let truncated = false;
  for (const feature of features) {
    if (count >= BUILDING_CAP) { truncated = true; break; }
    const ring = ringOf(feature);
    if (ring.length < 4) continue;
    const props = feature.properties || {};
    const lat = Number(props.centroid_lat);
    const lon = Number(props.centroid_lng);
    const book = matchBook(books, lat, lon);
    const estimated = props.match === "estimated" || props.source === "estimated_rectangle";
    const materialName = (book && book.material) || props.roof_wall_material || "Unknown";
    const key = materialKey(materialName) + (estimated ? ":est" : "");
    const storeys = Number(props.estimated_storeys);
    const height = book && book.height
      ? Number(book.height)
      : (storeys > 0 ? storeys * 3.5 : heightFromArea(props.area_m2));
    const baseElev = sampleElev(frame.elev, lon, lat);
    const baseY = baseElev - frame.baseline;
    const flood = book && book.depth > 0 ? Math.max(book.depth, sampleDepthAt(drawn, lon, lat)) : sampleDepthAt(drawn, lon, lat);
    const xz = simplifyRing(projectRing(ring, frame), 12);
    const risk = riskRGB(book && book.risk);
    const wet = flood > 0.3 ? 1 : 0;
    if (xz.length < 3) {
      addBox(buckets, key, xz.length ? xz : projectRing(ring, frame), baseY, height, risk, wet, estimated);
    } else {
      addPrism(bucketFor(buckets, key, estimated), xz, baseY, baseY + height, risk, wet);
    }
    records.push({ xz: xz.length >= 3 ? xz : null, lon, lat, baseY, height, materialName, estimated, flood });
    count += 1;
  }
  const meshes = [];
  for (const [key, bucket] of buckets) {
    if (bucket.pos.length) {
      const geo = new THREE.BufferGeometry();
      geo.setAttribute("position", new THREE.Float32BufferAttribute(bucket.pos, 3));
      geo.setAttribute("riskTint", new THREE.Float32BufferAttribute(bucket.risk, 3));
      geo.setAttribute("wetness", new THREE.Float32BufferAttribute(bucket.wet, 1));
      geo.computeVertexNormals();
      const mat = styleMaterial(key);
      hookRisk(mat);
      const mesh = new THREE.Mesh(geo, mat);
      mesh.renderOrder = 1;
      meshes.push(mesh);
    }
    if (bucket.instances.length) {
      const spec = MATERIALS[key.split(":")[0]] || MATERIALS.masonry;
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
      mesh.material.color.setHex(spec.color);
      hookRisk(mesh.material);
      mesh.renderOrder = 1;
      meshes.push(mesh);
    }
  }
  return { meshes, records, count, truncated };
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
    depthWrite: true,
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

  const samples = frame.elev.grid || [];
  for (const sample of samples) {
    const local = toLocal(sample.lng, sample.lat, sample.elevation_m, frame);
    if (add(local.x, local.y, local.z, 230, 224, 214, 2)) measured += 1;
  }

  const groundN = 192;
  for (let iy = 0; iy < groundN; iy++) {
    for (let ix = 0; ix < groundN; ix++) {
      const ju = (rng() * 2 - 1) * 0.35;
      const jv = (rng() * 2 - 1) * 0.35;
      const u = Math.min(1, Math.max(0, (ix + 0.5 + ju) / groundN));
      const v = Math.min(1, Math.max(0, (iy + 0.5 + jv) / groundN));
      const lon = frame.cell.west + u * (frame.cell.east - frame.cell.west);
      const lat = frame.cell.south + v * (frame.cell.north - frame.cell.south);
      const elev = sampleElev(frame.elev, lon, lat);
      const local = toLocal(lon, lat, elev, frame);
      const canopy = rng() < 0.02;
      const lift = canopy ? 0.4 + rng() * 0.8 : gauss(rng) * 0.25;
      const klass = canopy ? 1 : 2;
      const rgb = canopy ? [107, 143, 113] : [196, 184, 168];
      if (!add(local.x, local.y + lift, local.z, rgb[0], rgb[1], rgb[2], klass)) break;
    }
  }

  let ringStep = 4;
  let wallStep = 2;
  let roofStep = 3;
  const remain = POINT_CAP - n;
  const estimate = records.length * 80;
  if (estimate > remain && remain > 0) {
    const scale = Math.sqrt(estimate / remain);
    ringStep *= scale;
    wallStep *= scale;
    roofStep *= scale;
  }
  for (const rec of records) {
    if (!rec.xz || n >= POINT_CAP) break;
    const rgb = materialRGB(rec.materialName);
    const wall = rgb.map((ch) => Math.round(ch * 0.72));
    const ring = rec.xz;
    for (let i = 0; i < ring.length; i++) {
      const a = ring[i];
      const b = ring[(i + 1) % ring.length];
      const len = Math.hypot(b[0] - a[0], b[1] - a[1]);
      const steps = Math.max(1, Math.floor(len / ringStep));
      for (let s = 0; s < steps; s++) {
        const t = s / steps;
        const x = a[0] + (b[0] - a[0]) * t;
        const z = a[1] + (b[1] - a[1]) * t;
        for (let y = rec.baseY; y <= rec.baseY + rec.height; y += wallStep) {
          if (!add(x, y, z, wall[0], wall[1], wall[2], 6)) break;
        }
      }
    }
    let minX = Infinity, maxX = -Infinity, minZ = Infinity, maxZ = -Infinity;
    for (const p of ring) {
      if (p[0] < minX) minX = p[0];
      if (p[0] > maxX) maxX = p[0];
      if (p[1] < minZ) minZ = p[1];
      if (p[1] > maxZ) maxZ = p[1];
    }
    for (let x = minX; x <= maxX; x += roofStep) {
      for (let z = minZ; z <= maxZ; z += roofStep) {
        if (!inside(x, z, ring)) continue;
        if (!add(x, rec.baseY + rec.height, z, rgb[0], rgb[1], rgb[2], 6)) break;
      }
    }
  }

  const waterStep = 6;
  for (let z = -frame.depthM / 2; z <= frame.depthM / 2; z += waterStep) {
    for (let x = -frame.width / 2; x <= frame.width / 2; x += waterStep) {
      const u = (x + frame.width / 2) / frame.width;
      const v = (z + frame.depthM / 2) / frame.depthM;
      const flood = sampleGrid(drawn.drawn, drawn.rows, drawn.cols, u, v);
      if (flood <= 0.05) continue;
      const lon = frame.cell.west + u * (frame.cell.east - frame.cell.west);
      const lat = frame.cell.south + v * (frame.cell.north - frame.cell.south);
      const y = sampleElev(frame.elev, lon, lat) - frame.baseline + flood + 0.2;
      if (!add(x, y, z, 76, 141, 222, 9)) break;
    }
  }

  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  geo.setAttribute("color", new THREE.BufferAttribute(col, 3, true));
  geo.setAttribute("aclass", new THREE.BufferAttribute(cls, 1));
  geo.setDrawRange(0, n);
  const mat = new THREE.PointsMaterial({
    size: 2.2,
    sizeAttenuation: true,
    vertexColors: true,
    transparent: true,
    opacity: 0.72,
    depthWrite: false,
  });
  const cloud = new THREE.Points(geo, mat);
  cloud.renderOrder = 3;
  return { points: cloud, measured, synthetic: Math.max(0, n - measured), classes };
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
  return {
    provider: "heuristic",
    baseline_elevation_m: 2,
    heightmap,
    grid,
    rows,
    cols,
    flat: true,
  };
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
  if (rows < 2 || cols < 2) return Number(grid[0][0]) || 0;
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
  const open = ring[0][0] === ring[ring.length - 1][0] && ring[0][1] === ring[ring.length - 1][1]
    ? ring.slice(0, -1) : ring.slice();
  for (const pair of open) {
    const local = toLocal(pair[0], pair[1], frame.baseline, frame);
    out.push([local.x, local.z]);
  }
  return out;
}

function ringOf(feature) {
  const geom = feature.geometry || {};
  if (geom.type === "Polygon" && geom.coordinates && geom.coordinates[0]) return geom.coordinates[0];
  return [];
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

function bucketFor(buckets, key) {
  if (!buckets.has(key)) buckets.set(key, { pos: [], risk: [], wet: [], instances: [] });
  return buckets.get(key);
}

function addPrism(bucket, xz, baseY, topY, risk, wet) {
  const ring = xz.slice();
  if (signedArea(ring) < 0) ring.reverse();
  const n = ring.length;
  function tri(ax, ay, az, bx, by, bz, cx, cy, cz) {
    bucket.pos.push(ax, ay, az, bx, by, bz, cx, cy, cz);
    for (let k = 0; k < 3; k++) {
      bucket.risk.push(risk[0], risk[1], risk[2]);
      bucket.wet.push(wet);
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

function addBox(buckets, key, xz, baseY, height, risk, wet) {
  let minX = Infinity, maxX = -Infinity, minZ = Infinity, maxZ = -Infinity;
  for (const p of xz) {
    if (p[0] < minX) minX = p[0];
    if (p[0] > maxX) maxX = p[0];
    if (p[1] < minZ) minZ = p[1];
    if (p[1] > maxZ) maxZ = p[1];
  }
  const w = Math.max(4, (maxX - minX) || 8);
  const d = Math.max(4, (maxZ - minZ) || 8);
  const matrix = new THREE.Matrix4();
  matrix.compose(
    new THREE.Vector3((minX + maxX) / 2 || 0, baseY + height / 2, (minZ + maxZ) / 2 || 0),
    new THREE.Quaternion(),
    new THREE.Vector3(w, height, d)
  );
  bucketFor(buckets, key).instances.push({ matrix, risk, wet });
}

function styleMaterial(key) {
  const spec = MATERIALS[key.split(":")[0]] || MATERIALS.masonry;
  const estimated = key.endsWith(":est");
  return new THREE.MeshStandardMaterial({
    color: spec.color,
    roughness: spec.roughness,
    metalness: spec.metalness,
    transparent: estimated,
    opacity: estimated ? 0.55 : 1,
  });
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

function indexManifest(manifest) {
  const rows = (manifest && manifest.buildings) || [];
  return rows.map((row) => ({
    lat: row.centroid && Number(row.centroid.latitude),
    lon: row.centroid && Number(row.centroid.longitude),
    height: Number(row.height_m) || 0,
    material: row.predicted_material || "Unknown",
    depth: Number(row.inundation_depth_m) || 0,
    risk: row.risk_level || "",
  })).filter((row) => Number.isFinite(row.lat) && Number.isFinite(row.lon));
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

function manifestStamps(manifest, cell) {
  return indexManifest(manifest).filter((row) => (
    row.depth > 0.05 &&
    row.lon >= cell.west && row.lon <= cell.east &&
    row.lat >= cell.south && row.lat <= cell.north
  ));
}

function materialKey(name) {
  const text = String(name || "").toLowerCase();
  if (text.includes("corrug") || text.includes("mabati")) return "metal";
  if (text.includes("timber") || text.includes("wood")) return "timber";
  if (text.includes("steel")) return "steel";
  return "masonry";
}

function materialRGB(name) {
  const spec = MATERIALS[materialKey(name)] || MATERIALS.masonry;
  return [(spec.color >> 16) & 255, (spec.color >> 8) & 255, spec.color & 255];
}

function riskRGB(level) {
  const text = String(level || "").toLowerCase();
  if (text.includes("high") || text.includes("severe")) return [0xc1 / 255, 0x12 / 255, 0x1f / 255];
  if (text.includes("mod") || text.includes("med")) return [0xe0 / 255, 0xb8 / 255, 0x25 / 255];
  if (text.includes("low")) return [0x2a / 255, 0x9d / 255, 0x4a / 255];
  return [0, 0, 0];
}

function heightFromArea(area) {
  const storeys = Math.min((Number(area) || 80) / 80, 12);
  return Math.max(3.5, storeys * 3.5);
}

function haversine(lat1, lon1, lat2, lon2) {
  const p1 = lat1 * Math.PI / 180;
  const p2 = lat2 * Math.PI / 180;
  const dphi = (lat2 - lat1) * Math.PI / 180;
  const dl = (lon2 - lon1) * Math.PI / 180;
  const h = Math.sin(dphi / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) ** 2;
  return 2 * 6371000 * Math.asin(Math.min(1, Math.sqrt(h)));
}

function inside(x, z, ring) {
  let hit = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const xi = ring[i][0];
    const zi = ring[i][1];
    const xj = ring[j][0];
    const zj = ring[j][1];
    if ((zi > z) !== (zj > z) && x < ((xj - xi) * (z - zi)) / ((zj - zi) || 1e-9) + xi) hit = !hit;
  }
  return hit;
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
