import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { buildTwin } from "./kiccModel.js";

const app = document.getElementById("app");
const readout = document.getElementById("readout");
const loading = document.getElementById("loading");
const plates = document.getElementById("plates");
const plateRow = document.getElementById("plate-row");

const renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: "high-performance" });
renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
renderer.setSize(window.innerWidth, window.innerHeight);
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.05;
app.appendChild(renderer.domElement);

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x8ebfe6);
scene.fog = new THREE.Fog(0x8ebfe6, 180, 520);
scene.add(new THREE.HemisphereLight(0xffffff, 0xc4b6a6, 1.05));
const sun = new THREE.DirectionalLight(0xfff4e0, 1.35);
sun.position.set(80, 160, 40);
scene.add(sun);

const camera = new THREE.PerspectiveCamera(38, window.innerWidth / window.innerHeight, 0.4, 2000);
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.target.set(12, 48, 0);

const root = new THREE.Group();
scene.add(root);

let spec = null;
let bins = [];
let materials = [];
let fly = null;
let lastLod = null;
let lastResident = null;
let viewName = "";
const viewCursor = { aerial: 0, cube: 0, spatial: 0 };
const frustum = new THREE.Frustum();
const proj = new THREE.Matrix4();
const sphere = new THREE.Sphere();

window.addEventListener("resize", () => {
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
});

document.getElementById("btn-aerial").addEventListener("click", () => flyGroup("aerial"));
document.getElementById("btn-cube").addEventListener("click", () => flyGroup("cube"));
document.getElementById("btn-spatial").addEventListener("click", () => flyGroup("spatial"));
document.getElementById("btn-plates").addEventListener("click", (ev) => {
  const open = plates.hidden;
  plates.hidden = !open;
  ev.currentTarget.setAttribute("aria-pressed", open ? "true" : "false");
  if (open) showPlates(null);
});

load();
animate();

async function load() {
  try {
    const res = await fetch("/map/kicc/manifest.json");
    if (!res.ok) throw new Error("manifest " + res.status);
    spec = await res.json();
    if (spec.lidar !== false || spec.method !== "published_form_point_sample") {
      throw new Error("manifest is not the photo-space sample");
    }
    const model = buildTwin(spec);
    window.__kiccTwin = model.report;
    if (!model.report.ok) throw new Error(model.report.errors.join("; "));
    buildGround(spec);
    mountTiles(model);
    fillPlates(spec);
    const opening = (spec.views || []).find((view) => view.id === "aerial-ne") || spec.views[0];
    place(opening.eye, opening.look);
    viewName = opening.id;
    report(chooseLod(camera.position.length()), bins.length);
    loading.style.display = "none";
  } catch (err) {
    loading.textContent = "Photo space failed: " + err.message;
    readout.textContent = err.message;
  }
}

function buildGround(spec) {
  const radius = spec.amphitheatre_offset_east_m + spec.amphitheatre_radius_m + 18;
  const ground = new THREE.Mesh(
    new THREE.CircleGeometry(radius, 64),
    new THREE.MeshStandardMaterial({ color: 0xd7c3a4, roughness: 0.92 })
  );
  ground.rotation.x = -Math.PI / 2;
  ground.position.y = -0.05;
  root.add(ground);
}

function mountTiles(model) {
  materials = spec.lod_spacing_m.map((spacing) => pointMaterial(spacing));
  const grouped = new Map();
  for (const tile of model.tiles) {
    const key = tile.clusterId + "/" + tile.index;
    let bin = grouped.get(key);
    if (!bin) {
      const b = tile.bounds;
      const center = new THREE.Vector3((b.minX + b.maxX) / 2, (b.minY + b.maxY) / 2, (b.minZ + b.maxZ) / 2);
      bin = {
        lods: [],
        center,
        radius: center.distanceTo(new THREE.Vector3(b.maxX, b.maxY, b.maxZ)) + 0.8,
        mesh: null,
        resident: null,
      };
      grouped.set(key, bin);
    }
    bin.lods[tile.lod] = tile;
  }
  bins = [...grouped.values()];
}

function pointMaterial(spacing) {
  return new THREE.ShaderMaterial({
    uniforms: {
      uSpacing: { value: spacing },
      uFocal: { value: 800 },
      uPixelRatio: { value: renderer.getPixelRatio() },
      uLight: { value: new THREE.Vector3(0.45, 0.84, 0.28).normalize() },
    },
    vertexShader: `
      attribute vec3 aColor;
      attribute vec3 aNormal;
      uniform float uSpacing;
      uniform float uFocal;
      uniform float uPixelRatio;
      varying vec3 vColor;
      varying vec3 vNormal;
      void main() {
        vec4 mv = modelViewMatrix * vec4(position, 1.0);
        gl_PointSize = clamp(uSpacing * uFocal * uPixelRatio / max(0.5, -mv.z), 1.0, 10.0);
        gl_Position = projectionMatrix * mv;
        vColor = aColor;
        vNormal = normalize(normalMatrix * aNormal);
      }
    `,
    fragmentShader: `
      uniform vec3 uLight;
      varying vec3 vColor;
      varying vec3 vNormal;
      void main() {
        vec2 pc = gl_PointCoord * 2.0 - 1.0;
        if (dot(pc, pc) > 1.0) discard;
        float lambert = clamp(dot(normalize(vNormal), uLight), 0.0, 1.0);
        gl_FragColor = vec4(vColor * (0.42 + 0.7 * lambert), 1.0);
      }
    `,
  });
}

function makeMesh(tile) {
  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.BufferAttribute(tile.position, 3));
  geo.setAttribute("aNormal", new THREE.BufferAttribute(tile.normal, 3));
  geo.setAttribute("aColor", new THREE.BufferAttribute(tile.color, 3));
  const mesh = new THREE.Points(geo, materials[tile.lod]);
  mesh.frustumCulled = false;
  return mesh;
}

function updateTiles() {
  if (!bins.length) return;
  root.updateWorldMatrix(true, false);
  proj.multiplyMatrices(camera.projectionMatrix, camera.matrixWorldInverse);
  frustum.setFromProjectionMatrix(proj);
  const fov = camera.fov * Math.PI / 180;
  const focal = (renderer.domElement.height / 2) / Math.tan(fov / 2);
  for (const mat of materials) {
    mat.uniforms.uFocal.value = focal;
    mat.uniforms.uPixelRatio.value = renderer.getPixelRatio();
  }
  const dist = camera.position.distanceTo(controls.target);
  const lod = chooseLod(dist, lastLod);
  let resident = 0;
  for (const bin of bins) {
    sphere.center.copy(bin.center).applyMatrix4(root.matrixWorld);
    sphere.radius = bin.radius;
    if (!frustum.intersectsSphere(sphere)) {
      unload(bin);
      continue;
    }
    if (bin.resident !== lod) {
      unload(bin);
      const tile = bin.lods[lod];
      if (!tile) continue;
      bin.mesh = makeMesh(tile);
      bin.resident = lod;
      root.add(bin.mesh);
    }
    resident += 1;
  }
  if (lod !== lastLod || resident !== lastResident) {
    lastLod = lod;
    lastResident = resident;
    report(lod, resident);
  }
}

function unload(bin) {
  if (!bin.mesh) return;
  root.remove(bin.mesh);
  bin.mesh.geometry.dispose();
  bin.mesh = null;
  bin.resident = null;
}

function chooseLod(dist, prev) {
  if (prev === 0 && dist < 140) return 0;
  if (prev === 1 && dist >= 80 && dist < 420) return 1;
  if (prev === 2 && dist >= 360) return 2;
  if (dist < 110) return 0;
  if (dist < 380) return 1;
  return 2;
}

function place(eye, look) {
  camera.position.set(eye[0], eye[1], eye[2]);
  controls.target.set(look[0], look[1], look[2]);
  controls.update();
}

function flyGroup(group) {
  const views = (spec.views || []).filter((view) => view.group === group);
  if (!views.length) return;
  const index = viewCursor[group] % views.length;
  viewCursor[group] = index + 1;
  const view = views[index];
  fly = {
    t: 0,
    fromEye: camera.position.clone(),
    fromLook: controls.target.clone(),
    toEye: new THREE.Vector3(view.eye[0], view.eye[1], view.eye[2]),
    toLook: new THREE.Vector3(view.look[0], view.look[1], view.look[2]),
    id: view.id,
  };
  viewName = view.id;
  if (!plates.hidden) showPlates(group);
}

function stepFly(dt) {
  if (!fly) return;
  fly.t = Math.min(1, fly.t + dt / 1.5);
  const u = fly.t < 0.5 ? 2 * fly.t * fly.t : 1 - Math.pow(-2 * fly.t + 2, 2) / 2;
  camera.position.lerpVectors(fly.fromEye, fly.toEye, u);
  controls.target.lerpVectors(fly.fromLook, fly.toLook, u);
  if (fly.t >= 1) fly = null;
}

function fillPlates(spec) {
  const add = (file, caption) => {
    const fig = document.createElement("figure");
    const img = document.createElement("img");
    img.src = "/map/kicc/" + file;
    img.alt = caption;
    const cap = document.createElement("figcaption");
    cap.textContent = caption;
    fig.appendChild(img);
    fig.appendChild(cap);
    plateRow.appendChild(fig);
  };
  for (const file of spec.captures || []) add(file, "source");
  for (const plate of spec.plates || []) add(plate.file, plate.group + " synthetic");
}

function showPlates(group) {
  plates.hidden = false;
  for (const fig of plateRow.querySelectorAll("figure")) {
    const cap = fig.querySelector("figcaption").textContent;
    fig.hidden = group ? !(cap === "source" || cap.indexOf(group) === 0) : false;
  }
}

function report(lod, resident) {
  const info = window.__kiccTwin;
  if (!info) return;
  readout.textContent = [
    "KICC " + info.height_m.toFixed(1) + " m",
    "drawing diameter " + info.shaft_diameter_m + " m ± " + info.diameter_uncertainty_m + " m",
    "lod " + lod + " · tiles " + resident + " / " + bins.length,
    info.lod0_points.toLocaleString() + " pts · verify " + (info.ok ? "pass" : "fail"),
    "view " + viewName,
    "photo space only",
  ].join("\n");
}

let last = performance.now();
function animate() {
  requestAnimationFrame(animate);
  const now = performance.now();
  const dt = Math.min(0.05, (now - last) / 1000);
  last = now;
  stepFly(dt);
  controls.update();
  updateTiles();
  renderer.render(scene, camera);
}
