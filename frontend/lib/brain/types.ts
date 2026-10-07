import type { BrainCluster, BrainGhost, BrainNode, BrainSource } from "@/lib/types";

/** Anything on the map that can be hovered, focused or clicked. */
export type MapPick =
  | { kind: "neuron"; node: BrainNode }
  | { kind: "cluster"; cluster: BrainCluster }
  | { kind: "source"; source: BrainSource }
  | { kind: "ghost"; ghost: BrainGhost };

/** The 3D projector writes screen positions straight into these SVG elements each frame (no React re-render). */
export interface ProjectionBus {
  els: Map<string, SVGGElement>;
  lines: Map<string, { el: SVGLineElement; a: string; b: string }>;
}
export const newBus = (): ProjectionBus => ({ els: new Map(), lines: new Map() });

/** Screen positions (px, relative to the canvas) of each brain region's centre and of the ghost neurons. */
export type Anchors = Record<"ingest" | "diagnose" | "decide" | "learn" | "ghost", { x: number; y: number }>;
