"use client";

import { useEffect, useState } from "react";
import { useBrainPlayer } from "@/lib/brain/store";
import { nodeRadius } from "@/lib/brain/layout";
import type { BrainNode } from "@/lib/types";
import { useUiStore } from "@/lib/ui-store";

const HEALTH: Record<string, string> = { good: "var(--gain)", weak: "var(--risk)", losing: "var(--loss)" };

export type RefMap = Map<string, SVGGElement>;

interface Props {
  nodes: BrainNode[];
  /** static 2D pixel positions (also the initial positions before the 3D projector takes over) */
  placed: Map<string, { x: number; y: number }>;
  refs: React.RefObject<RefMap>;
  width: number;
  height: number;
  focusId?: string | null;
  onHover: (n: BrainNode | null, at?: { x: number; y: number }) => void;
  onSelect: (n: BrainNode) => void;
}

/** Neurons drawn as SVG over the brain: colour = health, size = spend, halo = headroom, pulse ring = alerting, lock = stock guard. */
export default function NeuronOverlay({ nodes, placed, refs, width, height, focusId, onHover, onSelect }: Props) {
  const maxSpend = Math.max(1, ...nodes.map((n) => n.spend_7d));
  const asked = useUiStore((s) => s.highlights);
  // Ids the player is currently highlighting; refreshed a few times a second (highlights expire on their own).
  const [playing, setPlaying] = useState<string>("");
  useEffect(() => {
    const read = () => {
      const now = performance.now();
      const ids = Object.entries(useBrainPlayer.getState().highlightUntil).filter(([, until]) => until > now).map(([id]) => id).sort().join(",");
      setPlaying((cur) => (cur === ids ? cur : ids));
    };
    const id = setInterval(read, 250);
    return () => clearInterval(id);
  }, []);
  const playingSet = new Set(playing ? playing.split(",") : []);
  return (
    <svg className="absolute inset-0" width={width} height={height} role="group" aria-label="Neurons: campaigns and products, coloured by health">
      {nodes.map((n) => {
        const pos = placed.get(n.entity_id);
        if (!pos) return null;
        const r = nodeRadius(n.spend_7d, maxSpend);
        const color = HEALTH[n.health] ?? "var(--fog)";
        const isSku = n.entity_type === "sku";
        const lit = playingSet.has(n.entity_id) || asked.some((h) => h.id === n.entity_id) || focusId === n.entity_id;
        const label = `${n.label}, ${n.health === "good" ? "healthy" : n.health === "weak" ? "weak" : "losing money"}${n.is_alerting ? ", alerting" : ""}${n.stock_locked ? ", locked by the stock guard" : ""}`;
        return (
          <g
            key={n.entity_id}
            ref={(el) => {
              if (el) refs.current.set(n.entity_id, el);
              else refs.current.delete(n.entity_id);
            }}
            transform={`translate(${pos.x} ${pos.y})`}
            tabIndex={0}
            role="button"
            aria-label={label}
            className="cursor-pointer outline-none [&:focus-visible>.focus-ring]:opacity-100"
            onPointerEnter={(e) => onHover(n, { x: e.clientX, y: e.clientY })}
            onPointerMove={(e) => onHover(n, { x: e.clientX, y: e.clientY })}
            onPointerLeave={() => onHover(null)}
            onFocus={(e) => {
              const b = e.currentTarget.getBoundingClientRect();
              onHover(n, { x: b.x + b.width / 2, y: b.y });
            }}
            onBlur={() => onHover(null)}
            onClick={() => onSelect(n)}
            onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), onSelect(n))}
          >
            <circle r={r + 8} fill="transparent" />
            {n.headroom === "scale" && <circle r={r + 5} fill="none" stroke="var(--gain)" strokeWidth="1.5" strokeDasharray="2 3" opacity="0.9" />}
            {n.headroom === "cut" && <circle r={Math.max(2, r - 2.5)} fill="none" stroke="var(--ink)" strokeWidth="1.5" opacity="0.55" />}
            {n.is_alerting && (
              <circle r={r + 3} fill="none" stroke={color} strokeWidth="2" className="neuron-alert" />
            )}
            {lit && <circle r={r + 7} fill="none" stroke="var(--bone)" strokeWidth="2" opacity="0.9" />}
            {isSku ? (
              <rect x={-r} y={-r} width={r * 2} height={r * 2} rx="2" transform="rotate(45)" fill={color} stroke="var(--ink)" strokeWidth="1.5" />
            ) : (
              <circle r={r} fill={color} stroke="var(--ink)" strokeWidth="1.5" />
            )}
            {n.stock_locked && (
              <g transform="translate(-6 -22)" aria-hidden>
                <rect width="12" height="12" rx="3" fill="var(--ink)" stroke="var(--risk)" />
                <path d="M3.8 5.5V4.4a2.2 2.2 0 0 1 4.4 0v1.1M3.3 5.5h5.4v3.6H3.3z" fill="none" stroke="var(--risk)" strokeWidth="1" strokeLinejoin="round" />
              </g>
            )}
            <circle className="focus-ring opacity-0" r={r + 6} fill="none" stroke="var(--synapse)" strokeWidth="2" />
          </g>
        );
      })}
    </svg>
  );
}
