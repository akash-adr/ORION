"use client";

import dynamic from "next/dynamic";
import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { loadBrainData, type BrainData } from "@/components/brain/brainData";
import { layoutNeurons, type V3 } from "@/lib/brain/layout";
import { webglAvailable } from "@/lib/brain/tokens";
import { useWidth } from "@/components/charts/util";
import type { BrainNode, BrainSnapshot } from "@/lib/types";
import NeuronOverlay, { type RefMap } from "./NeuronOverlay";

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
  /** dot budget: <= 4000 in the Engine map, <= 10000 on the neural page */
  maxDots: number;
  height?: number;
  focusId?: string | null;
  sway?: boolean;
  onHover: (n: BrainNode | null, at?: { x: number; y: number }) => void;
  onSelect: (n: BrainNode) => void;
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

/** The brain as a live map: a dot cloud and pulses in WebGL, neurons in SVG. Without WebGL (or on a phone) it is a flat cluster map. */
export default function LiveBrain({ snapshot, maxDots, height = 320, focusId, sway = true, onHover, onSelect }: LiveBrainProps) {
  const [wrap, width] = useWidth<HTMLDivElement>();
  const refs = useRef<RefMap>(new Map());
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

  const positions = useMemo<Map<string, V3> | null>(() => (data ? layoutNeurons(data.positions, snapshot.nodes) : null), [data, snapshot.nodes]);

  // Flat positions: also the starting point before the 3D projector takes over.
  const placed = useMemo(() => {
    const m = new Map<string, { x: number; y: number }>();
    if (!positions) return m;
    const s = Math.min(width / 2.3, height / 1.45);
    for (const [id, p] of positions) m.set(id, { x: width / 2 + p[0] * s, y: height / 2 - p[1] * s });
    return m;
  }, [positions, width, height]);

  return (
    <div
      ref={wrap}
      className="relative w-full select-none"
      style={{ height }}
    >
      {use3d && data && positions && <Scene3D data={data} maxDots={maxDots} positions={positions} refs={refs} scope={wrap} sway={sway} paused={hidden} />}
      {!use3d && positions && (
        <svg className="absolute inset-0" width={width} height={height} aria-hidden>
          {snapshot.clusters.map((c) => {
            const members = snapshot.nodes.filter((n) => n.cluster === c.id).map((n) => placed.get(n.entity_id)).filter(Boolean) as { x: number; y: number }[];
            if (!members.length) return null;
            const cx = members.reduce((a, p) => a + p.x, 0) / members.length;
            const cy = members.reduce((a, p) => a + p.y, 0) / members.length;
            return <circle key={c.id} cx={cx} cy={cy} r={44} fill="none" stroke="var(--line)" strokeDasharray="3 5" />;
          })}
        </svg>
      )}
      {width > 0 && positions && <NeuronOverlay nodes={snapshot.nodes} placed={placed} refs={refs} width={width} height={height} focusId={focusId} onHover={onHover} onSelect={onSelect} />}
    </div>
  );
}
