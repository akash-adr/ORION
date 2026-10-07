import {
  BufferGeometry,
  Euler,
  Mesh,
  MeshBasicMaterial,
  SphereGeometry,
  Vector3,
} from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { mergeGeometries } from "three/examples/jsm/utils/BufferGeometryUtils.js";
import { MeshSurfaceSampler } from "three/examples/jsm/math/MeshSurfaceSampler.js";
import { createNoise3D } from "simplex-noise";
import { REGIONS, type Region } from "./regions";

export const MODEL_URL = "/models/brain.glb";
/** Optional pre-extracted particle centres (see scripts/extract-brain-points.mjs): ~120KB vs 17MB. */
export const POINTS_URL = "/models/brain-points.bin";
export const POINT_COUNT = 8000;

/**
 * Rotation applied to the GLB's coordinates so the brain's long (front↔back) axis lies
 * along X with the front at +X, and up = +Y. This model has front = -Z, up = +Y.
 */
const MODEL_ORIENTATION = new Euler(0, -Math.PI / 2, 0);

export interface BrainData {
  /** Normalised positions; long axis spans [-1, 1] on X, centred on the origin. */
  positions: Float32Array;
  /** Region index per point (see REGIONS). */
  regions: Float32Array;
  rands: Float32Array;
  centroids: Record<Region, Vector3>;
  source: "points" | "glb" | "procedural";
}

/** Small deterministic PRNG so the brain looks identical on every load. */
function mulberry32(seed: number) {
  return () => {
    seed |= 0;
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function sampleSurface(geometry: BufferGeometry, count: number, rand: () => number): Float32Array {
  const mesh = new Mesh(geometry, new MeshBasicMaterial());
  const sampler = new MeshSurfaceSampler(mesh);
  // setRandomGenerator exists at runtime but is missing from @types/three.
  (sampler as unknown as { setRandomGenerator(f: () => number): void }).setRandomGenerator(rand);
  sampler.build();
  const out = new Float32Array(count * 3);
  const p = new Vector3();
  for (let i = 0; i < count; i++) {
    sampler.sample(p);
    out.set([p.x, p.y, p.z], i * 3);
  }
  return out;
}

/** Procedural fallback: two displaced, squashed hemispheres with a visible centre gap (already oriented). */
function proceduralBrain(rand: () => number): Float32Array {
  const noise = createNoise3D(mulberry32(7));
  const parts: BufferGeometry[] = [];
  for (const side of [-1, 1]) {
    const sphere = new SphereGeometry(1, 128, 96) as BufferGeometry;
    const pos = sphere.attributes.position;
    const v = new Vector3();
    for (let i = 0; i < pos.count; i++) {
      v.fromBufferAttribute(pos, i);
      const dir = v.clone().normalize();
      const large = noise(dir.x * 1.3 + side * 5, dir.y * 1.3, dir.z * 1.3) * 0.1;
      const folds = noise(dir.x * 4.2 + side * 9, dir.y * 4.2, dir.z * 4.2) * 0.045;
      const r = 1 + large + folds;
      v.set(dir.x * r * 1.1, dir.y * r * 0.78, dir.z * r * 0.5 + side * 0.56);
      if (Math.sign(v.z) === side) v.z = side * Math.max(Math.abs(v.z), 0.1);
      pos.setXYZ(i, v.x, v.y, v.z);
    }
    for (const k of Object.keys(sphere.attributes)) if (k !== "position") sphere.deleteAttribute(k);
    parts.push(sphere);
  }
  const merged = mergeGeometries(parts.map((p) => (p.index ? p.toNonIndexed() : p)))!;
  return sampleSurface(merged, POINT_COUNT, rand);
}

/**
 * The supplied GLB is a particle system: thousands of tiny icospheres. Sampling their
 * surfaces smears the structure, so use each particle's centre instead. For an ordinary
 * mesh (few disconnected parts) fall back to sampling its surface.
 */
function pointsFromGltfScene(scene: import("three").Object3D, rand: () => number): Float32Array {
  scene.updateMatrixWorld(true);
  const centres: number[] = [];
  const meshes: Mesh[] = [];
  const v = new Vector3();
  scene.traverse((o) => {
    const mesh = o as Mesh;
    if (!mesh.isMesh || !mesh.geometry.index) return;
    meshes.push(mesh);
    const pos = mesh.geometry.attributes.position;
    const idx = mesh.geometry.index.array;
    const parent = new Int32Array(pos.count).map((_, i) => i);
    const find = (x: number) => {
      while (parent[x] !== x) x = parent[x] = parent[parent[x]];
      return x;
    };
    for (let i = 0; i < idx.length; i += 3) {
      const a = find(idx[i]);
      parent[find(idx[i + 1])] = a;
      parent[find(idx[i + 2])] = a;
    }
    const acc = new Map<number, { x: number; y: number; z: number; n: number }>();
    for (let i = 0; i < pos.count; i++) {
      v.fromBufferAttribute(pos, i).applyMatrix4(mesh.matrixWorld);
      const r = find(i);
      const e = acc.get(r) ?? { x: 0, y: 0, z: 0, n: 0 };
      e.x += v.x; e.y += v.y; e.z += v.z; e.n++;
      acc.set(r, e);
    }
    for (const e of acc.values()) centres.push(e.x / e.n, e.y / e.n, e.z / e.n);
  });

  if (centres.length / 3 >= 2000) return new Float32Array(centres);

  const parts = meshes.map((m) => {
    let g = m.geometry.clone();
    for (const k of Object.keys(g.attributes)) if (k !== "position") g.deleteAttribute(k);
    if (g.index) g = g.toNonIndexed();
    g.applyMatrix4(m.matrixWorld);
    return g;
  });
  if (!parts.length) throw new Error("GLB contains no meshes");
  return sampleSurface(mergeGeometries(parts)!, POINT_COUNT, rand);
}

async function loadRawPoints(rand: () => number): Promise<{ raw: Float32Array; source: BrainData["source"] }> {
  try {
    const res = await fetch(POINTS_URL);
    const type = res.headers.get("content-type") ?? "";
    if (res.ok && !type.includes("text/html")) {
      return { raw: new Float32Array(await res.arrayBuffer()), source: "points" };
    }
  } catch {
    /* fall through to GLB */
  }
  try {
    const gltf = await new GLTFLoader().loadAsync(MODEL_URL);
    return { raw: pointsFromGltfScene(gltf.scene, rand), source: "glb" };
  } catch (err) {
    console.warn("[brain] GLB unavailable, using procedural brain:", err);
    return { raw: proceduralBrain(rand), source: "procedural" };
  }
}

function classify(nx: number, ny: number, nz: number): number {
  if (Math.hypot(nx, ny, nz) < 0.4) return 3; // learn (core)
  if (ny > 0.32) return 1; // diagnose (top)
  return nx < 0 ? 0 : 2; // ingest (back) / decide (front)
}

function percentile(sorted: number[], q: number) {
  return sorted[Math.min(sorted.length - 1, Math.floor(q * sorted.length))];
}

function build(raw: Float32Array, source: BrainData["source"], rand: () => number): BrainData {
  const total = raw.length / 3;

  // Pick POINT_COUNT points (deterministic random subset when there are more).
  const order = Array.from({ length: total }, (_, i) => i);
  for (let i = total - 1; i > 0; i--) {
    const j = Math.floor(rand() * (i + 1));
    [order[i], order[j]] = [order[j], order[i]];
  }
  const n = Math.min(POINT_COUNT, total);
  const pts: Vector3[] = [];
  const orient = source === "procedural" ? null : MODEL_ORIENTATION;
  for (let k = 0; k < n; k++) {
    const i = order[k];
    const p = new Vector3(raw[i * 3], raw[i * 3 + 1], raw[i * 3 + 2]);
    if (orient) p.applyEuler(orient);
    pts.push(p);
  }

  // Centre on the mean; extents from robust percentiles so a stray stem/outlier doesn't skew things.
  const mean = new Vector3();
  pts.forEach((p) => mean.add(p));
  mean.divideScalar(n);
  const half = [0, 1, 2].map((a) => {
    const d = pts.map((p) => Math.abs(p.getComponent(a) - mean.getComponent(a))).sort((x, y) => x - y);
    return percentile(d, 0.995);
  });
  const s = 1 / Math.max(...half);

  const positions = new Float32Array(n * 3);
  const regions = new Float32Array(n);
  const rands = new Float32Array(n);
  const sums = REGIONS.map(() => new Vector3());
  const counts = REGIONS.map(() => 0);
  pts.forEach((p, i) => {
    p.sub(mean);
    const region = classify(p.x / half[0], p.y / half[1], p.z / half[2]);
    p.multiplyScalar(s);
    positions.set([p.x, p.y, p.z], i * 3);
    regions[i] = region;
    rands[i] = rand();
    sums[region].add(p);
    counts[region]++;
  });
  const centroids = Object.fromEntries(
    REGIONS.map((r, i) => [r, sums[i].divideScalar(Math.max(1, counts[i]))]),
  ) as Record<Region, Vector3>;

  return { positions, regions, rands, centroids, source };
}

let cached: Promise<BrainData> | null = null;

/** Loads the brain point cloud (pre-extracted bin → GLB → procedural) and prepares per-point attributes. */
export function loadBrainData(): Promise<BrainData> {
  cached ??= (async () => {
    const rand = mulberry32(42);
    const { raw, source } = await loadRawPoints(rand);
    return build(raw, source, rand);
  })();
  return cached;
}
