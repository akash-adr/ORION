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
