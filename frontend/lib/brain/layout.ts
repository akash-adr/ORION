import type { BrainNode } from "@/lib/types";

export type V3 = [number, number, number];

/**
 * Where each channel cluster sits on the cortex, in the brain's normalised space (x: back −1 … front +1, y: up, z: towards the viewer).
 * The positions are fixed; neurons are placed around them deterministically, so the map looks the same on every load.
 */
export const CLUSTER_ANCHORS: Record<string, V3> = {
  meta: [0.55, 0.38, 0.42],
  google: [0.05, 0.62, 0.3],
  amazon: [-0.5, 0.4, 0.38],
  tiktok: [0.5, -0.05, 0.45],
  programmatic: [-0.55, -0.08, 0.4],
  catalog: [0.0, -0.4, 0.4],
};

/** FNV-1a hash of a string → [0, 1). */
export function hash01(s: string, salt = 0): number {
  let h = 2166136261 ^ salt;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return ((h >>> 0) % 100000) / 100000;
}

const MIN_GAP = 0.1;

/**
 * Neuron position = cluster anchor + seeded jitter, snapped to the nearest surface point of the brain cloud
 * (that is not too close to a neuron already placed).
 */
export function layoutNeurons(points: Float32Array, nodes: Pick<BrainNode, "entity_id" | "cluster">[]): Map<string, V3> {
  const n = points.length / 3;
  const out = new Map<string, V3>();
  const placed: V3[] = [];
  const sorted = [...nodes].sort((a, b) => a.entity_id.localeCompare(b.entity_id));
  const count = new Map<string, number>();
  for (const n of nodes) count.set(n.cluster, (count.get(n.cluster) ?? 0) + 1);
  for (const node of sorted) {
    const a = CLUSTER_ANCHORS[node.cluster] ?? CLUSTER_ANCHORS.catalog;
    // a bigger cluster spreads over a bigger patch of cortex
    const spread = 0.1 + 0.07 * Math.sqrt(count.get(node.cluster) ?? 1);
    const r = spread * Math.sqrt(hash01(node.entity_id, 1));
    const th = hash01(node.entity_id, 2) * Math.PI * 2;
    const target: V3 = [a[0] + Math.cos(th) * r, a[1] + Math.sin(th) * r * 0.8, a[2] + (hash01(node.entity_id, 3) - 0.5) * 0.12];
    let best = -1;
    let bestD = Infinity;
    for (let i = 0; i < n; i++) {
      const x = points[i * 3];
      const y = points[i * 3 + 1];
      const z = points[i * 3 + 2];
      if (z < 0.05) continue; // the visible side only
      const d = (x - target[0]) ** 2 + (y - target[1]) ** 2 + (z - target[2]) ** 2;
      if (d >= bestD) continue;
      if (placed.some((p) => (p[0] - x) ** 2 + (p[1] - y) ** 2 + (p[2] - z) ** 2 < MIN_GAP * MIN_GAP)) continue;
      bestD = d;
      best = i;
    }
    const p: V3 = best >= 0 ? [points[best * 3], points[best * 3 + 1], points[best * 3 + 2]] : target;
    placed.push(p);
    out.set(node.entity_id, p);
  }
  return out;
}

/** Node radius in pixels from 7-day spend (square-root scale so the biggest spender is not 100× the smallest). */
export function nodeRadius(spend: number, maxSpend: number, min = 3, span = 6.5): number {
  return min + span * Math.sqrt(Math.max(0, spend) / Math.max(1, maxSpend));
}

/** Where each data source floats around the brain, in the same normalised space (outside the cortex). */
export const SOURCE_POSITIONS: Record<string, V3> = {
  meta_ads: [0.98, 0.58, 0.35],
  google_ads: [0.1, 0.98, 0.25],
  amazon_ads: [-0.98, 0.6, 0.3],
  tiktok_ads: [1.08, -0.2, 0.4],
  programmatic: [-1.08, -0.12, 0.35],
  store: [-1.05, -0.6, 0.3],
  inventory: [-0.55, -0.9, 0.3],
  ga4: [0.45, -0.9, 0.3],
  pricing: [1.0, -0.62, 0.35],
};

/** Source positions: fixed anchors, with a seeded fallback ring for any source the table does not know. */
export function layoutSources(sources: { id: string }[]): Map<string, V3> {
  const out = new Map<string, V3>();
  sources.forEach((s, i) => {
    const th = (i / Math.max(1, sources.length)) * Math.PI * 2;
    out.set(s.id, SOURCE_POSITIONS[s.id] ?? [Math.cos(th) * 1.1, Math.sin(th) * 0.8, 0.3]);
  });
  return out;
}

/** A ghost (an untested combination) floats between its product and its channel's cluster, linked to the product. */
export function layoutGhosts(ghosts: { id: string; sku_id: string; cluster: string }[], neurons: Map<string, V3>): Map<string, V3> {
  const out = new Map<string, V3>();
  for (const g of ghosts) {
    const sku = neurons.get(g.sku_id) ?? CLUSTER_ANCHORS.catalog;
    const a = CLUSTER_ANCHORS[g.cluster] ?? CLUSTER_ANCHORS.catalog;
    const t = 0.45 + 0.2 * hash01(g.id, 4);
    const th = hash01(g.id, 5) * Math.PI * 2;
    out.set(g.id, [sku[0] + (a[0] - sku[0]) * t + Math.cos(th) * 0.07, sku[1] + (a[1] - sku[1]) * t + Math.sin(th) * 0.07, Math.max(0.2, sku[2] + (a[2] - sku[2]) * t)]);
  }
  return out;
}

/** Keys used by the overlay and the projector, so a neuron, a source and a cluster can never collide. */
export const key = {
  neuron: (id: string) => `n:${id}`,
  source: (id: string) => `s:${id}`,
  ghost: (id: string) => `g:${id}`,
  cluster: (id: string) => `c:${id}`,
};
