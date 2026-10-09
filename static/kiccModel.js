// Point samples of the published KICC form. Every point carries a cluster id
// from the catalogue built out of manifest.json. This file does not import Three.

export function buildTwin(spec) {
  const catalogue = buildCatalogue(spec);
  const tiles = [];
  const spacings = spec.lod_spacing_m || [0.55, 1.4, 3.6];
  for (let lod = 0; lod < spacings.length; lod++) {
    const buckets = sampleClusters(spec, catalogue, spacings[lod], lod === 0);
    for (const cluster of catalogue) {
      const pts = buckets.get(cluster.id) || [];
      const chunks = octreeChunks(pts, spec.tile_cap || 50000);
      chunks.forEach((chunk, index) => {
        tiles.push(packTile(cluster, lod, index, chunk));
      });
    }
  }
  const report = verifyTwin(spec, catalogue, tiles);
  return { catalogue, tiles, report };
}

export function buildCatalogue(spec) {
  const clusters = [];
  const concrete = spec.palette.concrete_rgb;
  const saucer = spec.palette.saucer_rgb;
  const cone = spec.palette.amphitheatre_rgb;
  clusters.push(cluster("podium", "podium", concrete, "Photo-derived slab under the published cylinder and cone."));
  clusters.push(cluster("tower_shaft", "cylinder", concrete, "Published cylinder. Radius is the drawing diameter."));
  for (let i = 0; i < spec.ring_count; i++) {
    const id = "ring_" + String(i).padStart(2, "0");
    clusters.push(cluster(id, "ring", concrete, "Sunshade ring " + (i + 1) + " of " + spec.ring_count + "."));
  }
  clusters.push(cluster("restaurant_saucer", "frustum", saucer, "Wide roof disc under the helipad. Color from the skyline capture."));
  clusters.push(cluster("helipad_cone", "cone", saucer, "Published helipad cone. Apex is the architectural top."));
  clusters.push(cluster("amphitheatre_cone", "cone", cone, "Published amphitheatre cone. Radius and bearing are drawing values."));
  return clusters;
}

function cluster(id, kind, rgb, note) {
  return { id, kind, rgb, note, index: 0 };
}

function sampleClusters(spec, catalogue, spacing, withApex) {
  catalogue.forEach((item, index) => { item.index = index; });
  const byId = new Map(catalogue.map((item) => [item.id, item]));
  const buckets = new Map(catalogue.map((item) => [item.id, []]));
  const R = spec.shaft_diameter_m / 2;
  const yRing0 = spec.podium_height_m;
  const yRing1 = spec.shaft_top_m;
  const pitch = (yRing1 - yRing0) / spec.ring_count;
  const half = spec.ring_thickness_m / 2;

  samplePodium(buckets.get("podium"), spec, spacing);
  for (let i = 0; i < spec.ring_count; i++) {
    const mid = yRing0 + (i + 0.5) * pitch;
    const y0 = mid - half;
    const y1 = mid + half;
    sampleShaftGap(
      buckets.get("tower_shaft"),
      R,
      i === 0 ? yRing0 : yRing0 + (i - 0.5) * pitch + half,
      y0,
      spacing
    );
    sampleRing(buckets.get("ring_" + String(i).padStart(2, "0")), R, R + spec.ring_overhang_m, y0, y1, spacing);
  }
  sampleShaftGap(
    buckets.get("tower_shaft"),
    R,
    yRing0 + (spec.ring_count - 0.5) * pitch + half,
    yRing1,
    spacing
  );
  sampleFrustum(
    buckets.get("restaurant_saucer"),
    R * 0.72,
    spec.saucer_radius_m,
    spec.shaft_top_m,
    spec.saucer_top_m,
    spacing
  );
  sampleCone(
    buckets.get("helipad_cone"),
    spec.helipad_radius_m,
    spec.saucer_top_m,
    spec.height_m,
    0,
    0,
    spacing,
    withApex
  );
  sampleCone(
    buckets.get("amphitheatre_cone"),
    spec.amphitheatre_radius_m,
    spec.podium_height_m,
    spec.amphitheatre_apex_m,
    spec.amphitheatre_offset_east_m,
    0,
    spacing,
    false
  );
  for (const [id, pts] of buckets) {
    const meta = byId.get(id);
    for (const pt of pts) pt.cluster = meta.index;
  }
  return buckets;
}

function samplePodium(out, spec, spacing) {
  const cx = spec.amphitheatre_offset_east_m * 0.5;
  const rx = spec.amphitheatre_offset_east_m * 0.5 + spec.amphitheatre_radius_m + 4;
  const rz = spec.amphitheatre_radius_m + 6;
  const y1 = spec.podium_height_m;
  const nA = Math.max(24, Math.round((2 * Math.PI * Math.max(rx, rz)) / spacing));
  for (let i = 0; i < nA; i++) {
    const a = (i / nA) * Math.PI * 2;
    const c = Math.cos(a);
    const s = Math.sin(a);
    const x = cx + rx * c;
    const z = rz * s;
    const nx = c / rx;
    const nz = s / rz;
    const len = Math.hypot(nx, nz) || 1;
    out.push(pt(x, y1, z, 0, 1, 0));
    const wallSteps = Math.max(2, Math.round(y1 / spacing));
    for (let k = 0; k < wallSteps; k++) {
      const y = ((k + 0.5) / wallSteps) * y1;
      out.push(pt(x, y, z, nx / len, 0, nz / len));
    }
  }
}

function sampleShaftGap(out, radius, y0, y1, spacing) {
  if (y1 - y0 < 0.05) return;
  const nA = Math.max(20, Math.round((2 * Math.PI * radius) / spacing));
  const nY = Math.max(1, Math.round((y1 - y0) / spacing));
  for (let iy = 0; iy < nY; iy++) {
    const y = y0 + ((iy + 0.5) / nY) * (y1 - y0);
    for (let ia = 0; ia < nA; ia++) {
      const a = (ia / nA) * Math.PI * 2;
      const c = Math.cos(a);
      const s = Math.sin(a);
      out.push(pt(radius * c, y, radius * s, c, 0, s));
    }
  }
}

function sampleRing(out, rIn, rOut, y0, y1, spacing) {
  const nA = Math.max(20, Math.round((2 * Math.PI * rOut) / spacing));
  const nR = Math.max(2, Math.round((rOut - rIn) / spacing));
  const nY = Math.max(1, Math.round((y1 - y0) / Math.max(spacing, 0.2)));
  for (let ia = 0; ia < nA; ia++) {
    const a = (ia / nA) * Math.PI * 2;
    const c = Math.cos(a);
    const s = Math.sin(a);
    for (let ir = 0; ir < nR; ir++) {
      const r = rIn + ((ir + 0.5) / nR) * (rOut - rIn);
      out.push(pt(r * c, y1, r * s, 0, 1, 0));
      out.push(pt(r * c, y0, r * s, 0, -1, 0));
    }
    for (let iy = 0; iy < nY; iy++) {
      const y = y0 + ((iy + 0.5) / nY) * (y1 - y0);
      out.push(pt(rOut * c, y, rOut * s, c, 0, s));
    }
  }
}

function sampleFrustum(out, rBottom, rTop, y0, y1, spacing) {
  const height = y1 - y0;
  const nY = Math.max(2, Math.round(height / spacing));
  const nRtop = Math.max(2, Math.round(rTop / spacing));
  for (let iy = 0; iy < nY; iy++) {
    const t = (iy + 0.5) / nY;
    const y = y0 + t * height;
    const radius = rBottom + (rTop - rBottom) * t;
    const nA = Math.max(16, Math.round((2 * Math.PI * radius) / spacing));
    const slopeX = height;
    const slopeY = rBottom - rTop;
    const slopeLen = Math.hypot(slopeX, slopeY) || 1;
    for (let ia = 0; ia < nA; ia++) {
      const a = (ia / nA) * Math.PI * 2;
      const c = Math.cos(a);
      const s = Math.sin(a);
      out.push(pt(radius * c, y, radius * s, (c * slopeX) / slopeLen, slopeY / slopeLen, (s * slopeX) / slopeLen));
    }
  }
  const nA = Math.max(16, Math.round((2 * Math.PI * rTop) / spacing));
  for (let ir = 0; ir < nRtop; ir++) {
    const r = ((ir + 0.5) / nRtop) * rTop;
    for (let ia = 0; ia < nA; ia++) {
      const a = (ia / nA) * Math.PI * 2;
      out.push(pt(r * Math.cos(a), y1, r * Math.sin(a), 0, 1, 0));
    }
  }
}

function sampleCone(out, radius, y0, y1, ox, oz, spacing, withApex) {
  const height = y1 - y0;
  const nY = Math.max(2, Math.round(height / spacing));
  for (let iy = 0; iy < nY; iy++) {
    const t = iy / nY;
    const y = y0 + t * height;
    const r = radius * (1 - t);
    if (r < spacing * 0.35) continue;
    const nA = Math.max(10, Math.round((2 * Math.PI * r) / spacing));
    const slopeLen = Math.hypot(height, radius) || 1;
    for (let ia = 0; ia < nA; ia++) {
      const a = (ia / nA) * Math.PI * 2;
      const c = Math.cos(a);
      const s = Math.sin(a);
      out.push(pt(ox + r * c, y, oz + r * s, (c * height) / slopeLen, radius / slopeLen, (s * height) / slopeLen));
    }
  }
  if (withApex) out.push(pt(ox, y1, oz, 0, 1, 0));
}

function pt(x, y, z, nx, ny, nz) {
  return { x, y, z, nx, ny, nz, cluster: 0 };
}

export function octreeChunks(points, cap) {
  const out = [];
  split(points, 0);
  return out.length ? out : [[]];

  function split(items, depth) {
    if (items.length <= cap || depth > 10) {
      if (items.length) out.push(items);
      return;
    }
    let cx = 0;
    let cy = 0;
    let cz = 0;
    for (const p of items) {
      cx += p.x;
      cy += p.y;
      cz += p.z;
    }
    cx /= items.length;
    cy /= items.length;
    cz /= items.length;
    const bins = [[], [], [], [], [], [], [], []];
    for (const p of items) {
      const key = (p.x >= cx ? 1 : 0) | (p.y >= cy ? 2 : 0) | (p.z >= cz ? 4 : 0);
      bins[key].push(p);
    }
    const used = bins.filter((bin) => bin.length);
    if (used.length < 2) {
      for (let i = 0; i < items.length; i += cap) out.push(items.slice(i, i + cap));
      return;
    }
    for (const bin of used) split(bin, depth + 1);
  }
}

function packTile(cluster, lod, index, points) {
  const count = points.length;
  const position = new Float32Array(count * 3);
  const normal = new Float32Array(count * 3);
  const color = new Float32Array(count * 3);
  const intensity = new Float32Array(count);
  const clusterId = new Float32Array(count);
  const rgb = cluster.rgb;
  let minX = Infinity;
  let minY = Infinity;
  let minZ = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  let maxZ = -Infinity;
  for (let i = 0; i < count; i++) {
    const p = points[i];
    position[i * 3] = p.x;
    position[i * 3 + 1] = p.y;
    position[i * 3 + 2] = p.z;
    normal[i * 3] = p.nx;
    normal[i * 3 + 1] = p.ny;
    normal[i * 3 + 2] = p.nz;
    color[i * 3] = rgb[0] / 255;
    color[i * 3 + 1] = rgb[1] / 255;
    color[i * 3 + 2] = rgb[2] / 255;
    intensity[i] = Math.max(0, p.ny) * 0.55 + 0.45;
    clusterId[i] = p.cluster;
    if (p.x < minX) minX = p.x;
    if (p.y < minY) minY = p.y;
    if (p.z < minZ) minZ = p.z;
    if (p.x > maxX) maxX = p.x;
    if (p.y > maxY) maxY = p.y;
    if (p.z > maxZ) maxZ = p.z;
  }
  return {
    id: cluster.id + "/lod" + lod + "/" + index,
    clusterId: cluster.id,
    clusterIndex: cluster.index,
    lod,
    index,
    count,
    position,
    normal,
    color,
    intensity,
    cluster: clusterId,
    bounds: { minX, minY, minZ, maxX, maxY, maxZ },
  };
}

export function verifyTwin(spec, catalogue, tiles) {
  const errors = [];
  const cap = spec.tile_cap || 50000;
  const ids = new Set(catalogue.map((item) => item.id));
  const seen = new Set();
  let apex = -Infinity;
  let lowest = Infinity;
  if (spec.lidar !== false) errors.push("lidar flag must stay false");
  if (!(spec.shaft_diameter_uncertainty_m > 0)) errors.push("shaft diameter uncertainty missing");
  const lod0 = tiles.filter((tile) => tile.lod === 0);
  for (const tile of tiles) {
    if (tile.count > cap) errors.push(tile.id + " has " + tile.count + " points");
    if (!ids.has(tile.clusterId)) errors.push("unknown cluster " + tile.clusterId);
    if (tile.lod === 0 && tile.count > 0) seen.add(tile.clusterId);
    for (let i = 0; i < tile.count; i++) {
      const x = tile.position[i * 3];
      const y = tile.position[i * 3 + 1];
      const z = tile.position[i * 3 + 2];
      const c = tile.cluster[i];
      if (!Number.isFinite(x) || !Number.isFinite(y) || !Number.isFinite(z)) {
        errors.push("non-finite point in " + tile.id);
        break;
      }
      if (c < 0 || c >= catalogue.length || catalogue[c].id !== tile.clusterId) {
        errors.push("cluster id mismatch in " + tile.id);
        break;
      }
      if (tile.lod === 0) {
        if (y > apex) apex = y;
        if (y < lowest) lowest = y;
      }
    }
  }
  for (const item of catalogue) {
    if (!seen.has(item.id)) errors.push("missing cluster " + item.id);
  }
  if (Math.abs(apex - spec.height_m) > 0.05) errors.push("apex " + apex + " is not " + spec.height_m);
  if (lowest < -0.05) errors.push("point below entrance datum");
  const ratio = spec.height_m / spec.shaft_diameter_m;
  return {
    ok: errors.length === 0,
    errors: errors.slice(0, 12),
    apex_m: apex,
    lowest_m: lowest,
    height_m: spec.height_m,
    shaft_diameter_m: spec.shaft_diameter_m,
    height_over_diameter: ratio,
    diameter_uncertainty_m: spec.shaft_diameter_uncertainty_m,
    lod0_points: lod0.reduce((sum, tile) => sum + tile.count, 0),
    lod0_tiles: lod0.length,
    clusters: catalogue.length,
    method: spec.method,
    lidar: false,
  };
}
