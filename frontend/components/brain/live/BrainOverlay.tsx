"use client";

import { useEffect, useState } from "react";
import { key, nodeRadius } from "@/lib/brain/layout";
import { useBrainPlayer } from "@/lib/brain/store";
import type { MapPick, ProjectionBus } from "@/lib/brain/types";
import type { BrainSnapshot } from "@/lib/types";
import { inr, pct } from "@/lib/format";
import { useUiStore } from "@/lib/ui-store";

const HEALTH: Record<string, string> = { good: "var(--gain)", weak: "var(--risk)", losing: "var(--loss)" };
export type Placed = Map<string, { x: number; y: number }>;

interface Props {
  snapshot: BrainSnapshot;
  /** "map" draws neurons only; "full" adds sources, ghosts, cluster glows and synapse lines */
  variant: "map" | "full";
  placed: Placed;
  bus: ProjectionBus;
  width: number;
  height: number;
  focusKey?: string | null;
  /* Optional, additive (the Pitch page). */
  /** when set, items outside `highlightKeys` fade (only while highlightKeys is non-empty) */
  dimOthers?: boolean;
  /** overlay keys (see lib/brain/layout `key`) to ring and keep at full strength */
  highlightKeys?: Set<string>;
  onHover: (p: MapPick | null, at?: { x: number; y: number }) => void;
  onPick: (p: MapPick) => void;
}

const handlers = (pick: MapPick, o: { onHover: Props["onHover"]; onPick: Props["onPick"] }) => ({
  tabIndex: 0,
  role: "button" as const,
  className: "cursor-pointer outline-none [&:focus-visible_.focus-ring]:opacity-100",
  onPointerEnter: (e: React.PointerEvent) => o.onHover(pick, { x: e.clientX, y: e.clientY }),
  onPointerMove: (e: React.PointerEvent) => o.onHover(pick, { x: e.clientX, y: e.clientY }),
  onPointerLeave: () => o.onHover(null),
  onFocus: (e: React.FocusEvent<SVGGElement>) => {
    const b = e.currentTarget.getBoundingClientRect();
    o.onHover(pick, { x: b.x + b.width / 2, y: b.y });
  },
  onBlur: () => o.onHover(null),
  onClick: () => o.onPick(pick),
  onKeyDown: (e: React.KeyboardEvent) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      o.onPick(pick);
    }
  },
});

/** Everything the brain shows, drawn from the snapshot: colour = health, size = spend, halo = headroom, lock = stock guard. */
export default function BrainOverlay({ snapshot: s, variant, placed, bus, width, height, focusKey, dimOthers = false, highlightKeys, onHover, onPick }: Props) {
  const maxSpend = Math.max(1, ...s.nodes.map((n) => n.spend_7d));
  const asked = useUiStore((st) => st.highlights);
  const [playing, setPlaying] = useState("");
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
  const h = { onHover, onPick };
  const hl = highlightKeys ?? new Set<string>();
  const fade = (k: string): React.CSSProperties => ({ opacity: dimOthers && hl.size && !hl.has(k) ? 0.3 : 1, transition: "opacity 150ms" });
  const full = variant === "full";
  const at = (k: string) => placed.get(k);

  const lines: { id: string; a: string; b: string; w: number; o: number; dash?: string }[] = [];
  if (full) {
    for (const e of s.synapses) {
      const a = key.neuron(e.source);
      const b = key.neuron(e.target);
      if (placed.has(a) && placed.has(b)) lines.push({ id: `${a}|${b}`, a, b, w: Math.max(0.6, 0.6 + (e.strength - 1) * 4), o: Math.min(0.55, 0.14 + Math.max(0, e.strength - 1) * 0.9) });
    }
    for (const g of s.ghosts) {
      const a = key.ghost(g.id);
      const b = key.neuron(g.sku_id);
      if (placed.has(a) && placed.has(b)) lines.push({ id: `${a}|${b}`, a, b, w: 1, o: g.launched ? 0.7 : 0.35, dash: g.launched ? undefined : "3 4" });
    }
  }

  return (
    <svg className="absolute inset-0" width={width} height={height} role="group" aria-label="The engine map: campaigns and products coloured by health">
      {lines.map((l) => {
        const a = at(l.a)!;
        const b = at(l.b)!;
        return (
          <line
            key={l.id}
            ref={(el) => {
              if (el) bus.lines.set(l.id, { el, a: l.a, b: l.b });
              else bus.lines.delete(l.id);
            }}
            x1={a.x}
            y1={a.y}
            x2={b.x}
            y2={b.y}
            stroke="var(--synapse)"
            strokeWidth={l.w}
            strokeDasharray={l.dash}
            opacity={l.o}
            pointerEvents="none"
          />
        );
      })}

      {full &&
        s.clusters.map((c) => {
          const p = at(key.cluster(c.id));
          if (!p) return null;
          const a = c.alert;
          const tone = a ? (a.direction === "gain" ? "var(--gain)" : "var(--loss)") : "var(--fog)";
          return (
            <g key={c.id} ref={(el) => void (el ? bus.els.set(key.cluster(c.id), el) : bus.els.delete(key.cluster(c.id)))} transform={`translate(${p.x} ${p.y})`} aria-label={`${c.label} cluster${a ? `, alert: ${a.message}` : ""}`} {...handlers({ kind: "cluster", cluster: c }, h)}>
              <g style={fade(key.cluster(c.id))}>
              <circle r={a ? 52 : 40} fill={a ? tone : "none"} fillOpacity={a ? 0.12 : 0} stroke={tone} strokeOpacity={a ? 0.8 : 0.35} strokeDasharray={a ? undefined : "3 5"} />
              <text y={a ? 66 : 54} textAnchor="middle" fontSize="12" fill="var(--fog)">
                {c.label}
              </text>
              <circle className="focus-ring opacity-0" r={46} fill="none" stroke="var(--synapse)" strokeWidth="2" />
              </g>
            </g>
          );
        })}

      {full &&
        s.sources.map((src) => {
          const p = at(key.source(src.id));
          if (!p) return null;
          const warn = src.status === "warn";
          const col = warn ? "var(--risk)" : "var(--fog)";
          const sub = src.verified ? "Store-verified" : warn && src.inflation_pct ? `${pct(src.inflation_pct)} over-reported` : null;
          return (
            <g key={src.id} ref={(el) => void (el ? bus.els.set(key.source(src.id), el) : bus.els.delete(key.source(src.id)))} transform={`translate(${p.x} ${p.y})`} aria-label={`${src.label}${warn ? ", needs attention" : ""}${src.verified ? ", store-verified" : ""}`} {...handlers({ kind: "source", source: src }, h)}>
              <g style={fade(key.source(src.id))}>
              <rect x={-5} y={-5} width={10} height={10} rx={2} fill={warn ? col : "var(--slate)"} stroke={col} strokeWidth="1.5" />
              <text y={20} textAnchor="middle" fontSize="12" fill={warn ? "var(--risk)" : "var(--fog)"}>
                {src.label}
              </text>
              {sub && (
                <text y={34} textAnchor="middle" fontSize="12" fill={src.verified ? "var(--gain)" : "var(--risk)"}>
                  {sub}
                </text>
              )}
              <circle className="focus-ring opacity-0" r={14} fill="none" stroke="var(--synapse)" strokeWidth="2" />
              </g>
            </g>
          );
        })}

      {full &&
        s.ghosts.map((g) => {
          const p = at(key.ghost(g.id));
          if (!p) return null;
          return (
            <g key={g.id} ref={(el) => void (el ? bus.els.set(key.ghost(g.id), el) : bus.els.delete(key.ghost(g.id)))} transform={`translate(${p.x} ${p.y})`} aria-label={`Untested idea: ${g.id}${g.launched ? ", test running" : ""}`} {...handlers({ kind: "ghost", ghost: g }, h)}>
              <g style={fade(key.ghost(g.id))}>
              <circle r={14} fill="transparent" />
              <circle r={6} fill={g.launched ? "var(--synapse)" : "none"} fillOpacity={0.9} stroke="var(--synapse)" strokeWidth="1.5" strokeDasharray={g.launched ? undefined : "2 3"} opacity={g.launched ? 1 : 0.7} />
              {g.launched && (
                <text y={-11} textAnchor="middle" fontSize="12" fontWeight="700" fill="var(--synapse)">
                  Test
                </text>
              )}
              <circle className="focus-ring opacity-0" r={11} fill="none" stroke="var(--synapse)" strokeWidth="2" />
              </g>
            </g>
          );
        })}

      {s.nodes.map((n) => {
        const k = key.neuron(n.entity_id);
        const pos = at(k);
        if (!pos) return null;
        const r = nodeRadius(n.spend_7d, maxSpend);
        const color = HEALTH[n.health] ?? "var(--fog)";
        const isSku = n.entity_type === "sku";
        const askedHit = asked.some((x) => x.id === n.entity_id);
        const hlHit = hl.has(k);
        const lit = playingSet.has(n.entity_id) || askedHit || focusKey === k || hlHit;
        const trustRing = (n.channel === "meta" || n.channel === "google") && n.trust_score !== null && n.trust_score < 0.995;
        const label = `${n.label}, ${n.health === "good" ? "healthy" : n.health === "weak" ? "weak" : "losing money"}${n.is_alerting ? ", alerting" : ""}${n.stock_locked ? ", locked by the stock guard" : ""}`;
        return (
          <g key={k} ref={(el) => void (el ? bus.els.set(k, el) : bus.els.delete(k))} transform={`translate(${pos.x} ${pos.y})`} aria-label={label} {...handlers({ kind: "neuron", node: n }, h)}>
            <g style={fade(k)}>
            <circle r={r + 8} fill="transparent" />
            {n.headroom === "scale" && <circle r={r + 5} fill="none" stroke="var(--gain)" strokeWidth="1.5" strokeDasharray="2 3" opacity="0.9" />}
            {n.headroom === "cut" && <circle r={Math.max(2, r - 2.5)} fill="none" stroke="var(--ink)" strokeWidth="1.5" opacity="0.55" />}
            {trustRing && <circle r={r + 4 + (1 - (n.trust_score ?? 1)) * 14} fill="none" stroke="var(--risk)" strokeWidth="1.25" strokeDasharray="1.5 2.5" opacity="0.9" />}
            {n.is_alerting && <circle r={r + 3} fill="none" stroke={color} strokeWidth="2" className="neuron-alert" />}
            {lit && <circle r={r + 7} fill="none" stroke="var(--bone)" strokeWidth="2" opacity="0.9" className={askedHit || hlHit ? "neuron-alert" : undefined} />}
            {isSku ? <rect x={-r} y={-r} width={r * 2} height={r * 2} rx="2" transform="rotate(45)" fill={color} stroke="var(--ink)" strokeWidth="1.5" /> : <circle r={r} fill={color} stroke="var(--ink)" strokeWidth="1.5" />}
            {n.stock_locked && (
              <g transform="translate(-6 -22)" aria-hidden>
                <rect width="12" height="12" rx="3" fill="var(--ink)" stroke="var(--risk)" />
                <path d="M3.8 5.5V4.4a2.2 2.2 0 0 1 4.4 0v1.1M3.3 5.5h5.4v3.6H3.3z" fill="none" stroke="var(--risk)" strokeWidth="1" strokeLinejoin="round" />
              </g>
            )}
            <circle className="focus-ring opacity-0" r={r + 6} fill="none" stroke="var(--synapse)" strokeWidth="2" />
            </g>
          </g>
        );
      })}
      <title>{`Engine map, profit ${inr(s.headline.current_profit)} a day`}</title>
    </svg>
  );
}
