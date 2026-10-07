"use client";

import dynamic from "next/dynamic";
import { useEffect, useMemo, useState, useSyncExternalStore } from "react";
import { loadBrainData, type BrainData } from "@/components/brain/brainData";
import { useWidth } from "@/components/charts/util";
import { CLUSTER_ANCHORS, key, layoutGhosts, layoutNeurons, layoutSources, type V3 } from "@/lib/brain/layout";
import { webglAvailable } from "@/lib/brain/tokens";
import { newBus, type MapPick } from "@/lib/brain/types";
import type { Anchors } from "@/lib/brain/types";
import type { BrainRegion, BrainSnapshot } from "@/lib/types";
import BrainOverlay from "./BrainOverlay";

const Scene3D = dynamic(() => import("./Scene3D"), { ssr: false });
const noop = () => () => {};
const WIDE = "(min-width: 768px)";
const subscribeWide = (cb: () => void) => {
  const mq = window.matchMedia(WIDE);
  mq.addEventListener("change", cb);
  return () => mq.removeEventListener("change", cb);
};

export interface LiveBrainProps {
  snapshot: BrainSnapshot;
  /** "map" is the compact Engine map (neurons only); "full" is the neural view */
  variant?: "map" | "full";
  /** dot budget: <= 4000 in the Engine map, <= 10000 on the neural page */
  maxDots: number;
  height?: number;
  /** overlay key (see lib/brain/layout `key`) the camera should focus */
  focusKey?: string | null;
  sway?: boolean;
  /* Optional, additive (the Pitch page): every one defaults to the original behaviour. */
  /** ease the camera toward a region's centre */
  focusRegion?: BrainRegion | null;
  /** tint these regions' dots with the region colour */
  tintRegions?: BrainRegion[];
  /** fade everything outside the highlighted targets / tinted regions */
  dimOthers?: boolean;
  /** neuron ids, or overlay keys for other items, to ring and keep at full strength */
  highlightTargets?: string[];
  /** half-swing of the yaw sway in radians (default 0.16) */
  swayAmp?: number;
  /** screen positions of the region centres and the ghosts, about 30 times a second */
  onAnchorsProjected?: (a: Anchors) => void;
  onHover: (p: MapPick | null, at?: { x: number; y: number }) => void;
  onPick: (p: MapPick) => void;
}

function useBrainCloud() {
  const [data, setData] = useState<BrainData | null>(null);
  useEffect(() => {
    let alive = true;
    loadBrainData().then((d) => alive && setData(d));
    return () => {
      alive = false;
    };
  }, []);
  return data;
}

/** The brain as a live map: dot cloud and pulses in WebGL, items in SVG. Without WebGL (or on a phone) it is a flat cluster map. */
export default function LiveBrain({ snapshot, variant = "map", maxDots, height = 320, focusKey = null, sway = true, focusRegion = null, tintRegions, dimOthers = false, highlightTargets, swayAmp, onAnchorsProjected, onHover, onPick }: LiveBrainProps) {
  const [wrap, width] = useWidth<HTMLDivElement>();
  const [bus] = useState(newBus);
  const webgl = useSyncExternalStore(noop, webglAvailable, () => null);
  const hidden = useSyncExternalStore(
    (cb) => {
      document.addEventListener("visibilitychange", cb);
      return () => document.removeEventListener("visibilitychange", cb);
    },
    () => document.hidden,
    () => false,
  );
  const wide = useSyncExternalStore(subscribeWide, () => window.matchMedia(WIDE).matches, () => null);
  const data = useBrainCloud();
  const use3d = webgl === true && wide === true && !!data;
  const full = variant === "full";

  const neuronById = useMemo(() => (data ? layoutNeurons(data.positions, snapshot.nodes) : null), [data, snapshot.nodes]);
  /** every projected item, keyed for the overlay and the projector */
  const positions = useMemo<Map<string, V3> | null>(() => {
    if (!neuronById) return null;
    const m = new Map<string, V3>();
    for (const [id, p] of neuronById) m.set(key.neuron(id), p);
    if (full) {
      for (const [id, p] of layoutSources(snapshot.sources)) m.set(key.source(id), p);
      for (const [id, p] of layoutGhosts(snapshot.ghosts, neuronById)) m.set(key.ghost(id), p);
      for (const c of snapshot.clusters) m.set(key.cluster(c.id), CLUSTER_ANCHORS[c.id] ?? CLUSTER_ANCHORS.catalog);
    }
    return m;
  }, [neuronById, full, snapshot.sources, snapshot.ghosts, snapshot.clusters]);

  const hlKeys = useMemo(() => new Set((highlightTargets ?? []).map((t) => (/^[ncsg]:/.test(t) ? t : key.neuron(t)))), [highlightTargets]);
  const fit = full ? 1.45 : 1;
  // Flat positions: the static map, and the starting point before the 3D projector takes over.
  const placed = useMemo(() => {
    const m = new Map<string, { x: number; y: number }>();
    if (!positions) return m;
    const s = Math.min(width / (2.3 * fit), height / (1.45 * fit));
    for (const [k, p] of positions) m.set(k, { x: width / 2 + p[0] * s, y: height / 2 - p[1] * s });
    return m;
  }, [positions, width, height, fit]);

  return (
    <div ref={wrap} className="relative w-full select-none" style={{ height }}>
      {use3d && data && positions && neuronById && <Scene3D data={data} maxDots={maxDots} positions={positions} neuronById={neuronById} bus={bus} scope={wrap} sway={sway} fit={fit} focusKey={focusKey} focusRegion={focusRegion} tintRegions={tintRegions} dimOthers={dimOthers} swayAmp={swayAmp} onAnchors={onAnchorsProjected} paused={hidden} />}
      {width > 0 && positions && <BrainOverlay snapshot={snapshot} variant={variant} placed={placed} bus={bus} width={width} height={height} focusKey={focusKey} dimOthers={dimOthers} highlightKeys={hlKeys} onHover={onHover} onPick={onPick} />}
    </div>
  );
}
