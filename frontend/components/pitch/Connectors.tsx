"use client";

import { useEffect, useRef } from "react";
import { prefersReducedMotion } from "@/lib/brain/tokens";
import type { Anchors } from "@/lib/brain/types";

export interface ConnLine {
  id: string;
  /** data-pitch value of the start element, or "anchor:<region>" */
  a: string;
  b: string;
  color: string;
  active: boolean;
  /** moving dots along the line (ingest events) */
  particles?: boolean;
}

interface Pt {
  x: number;
  y: number;
}

/** A point on the edge of an element, on the side facing `toward`. */
function edge(r: DOMRect, c: DOMRect, toward: Pt): Pt {
  const cx = r.left + r.width / 2 - c.left;
  const cy = r.top + r.height / 2 - c.top;
  const dx = toward.x - cx;
  const dy = toward.y - cy;
  if (Math.abs(dx) * r.height > Math.abs(dy) * r.width) return { x: dx > 0 ? r.right - c.left : r.left - c.left, y: cy };
  return { x: cx, y: dy > 0 ? r.bottom - c.top : r.top - c.top };
}
const bez = (p0: Pt, c1: Pt, c2: Pt, p1: Pt, t: number): Pt => {
  const u = 1 - t;
  return { x: u * u * u * p0.x + 3 * u * u * t * c1.x + 3 * u * t * t * c2.x + t * t * t * p1.x, y: u * u * u * p0.y + 3 * u * u * t * c1.y + 3 * u * t * t * c2.y + t * t * t * p1.y };
};

interface Props {
  container: React.RefObject<HTMLElement | null>;
  /** the canvas box the brain anchors are relative to */
  canvas: React.RefObject<HTMLElement | null>;
  anchors: React.RefObject<Anchors | null>;
  lines: ConnLine[];
}

/**
 * Connector lines between the panels, the callouts and the brain. Endpoints are measured from the DOM and from the
 * projected brain anchors about 30 times a second (and paused while the tab is hidden), written straight to the SVG paths.
 */
export default function Connectors({ container, canvas, anchors, lines }: Props) {
  const paths = useRef(new Map<string, SVGPathElement>());
  const dots = useRef(new Map<string, SVGCircleElement[]>());
  const linesRef = useRef(lines);
  useEffect(() => {
    linesRef.current = lines;
  }, [lines]);

  useEffect(() => {
    const reduce = prefersReducedMotion();
    let raf = 0;
    let last = 0;
    const tick = (now: number) => {
      raf = requestAnimationFrame(tick);
      if (document.hidden || now - last < 33) return;
      last = now;
      const c = container.current;
      if (!c) return;
      const cr = c.getBoundingClientRect();
      const kr = canvas.current?.getBoundingClientRect();
      const find = (k: string) => c.querySelector<HTMLElement>(`[data-pitch="${k}"]`);
      const resolveCentre = (k: string): { pt: Pt; rect?: DOMRect } | null => {
        if (k.startsWith("anchor:")) {
          const a = anchors.current?.[k.slice(7) as keyof Anchors];
          return a && kr ? { pt: { x: a.x + kr.left - cr.left, y: a.y + kr.top - cr.top } } : null;
        }
        const el = find(k);
        if (!el) return null;
        const r = el.getBoundingClientRect();
        return { pt: { x: r.left + r.width / 2 - cr.left, y: r.top + r.height / 2 - cr.top }, rect: r };
      };
      for (const l of linesRef.current) {
        const path = paths.current.get(l.id);
        if (!path) continue;
        const A = resolveCentre(l.a);
        const B = resolveCentre(l.b);
        if (!A || !B) {
          path.setAttribute("d", "");
          continue;
        }
        const p0 = A.rect ? edge(A.rect, cr, B.pt) : A.pt;
        const p1 = B.rect ? edge(B.rect, cr, A.pt) : B.pt;
        const mx = (p0.x + p1.x) / 2;
        const c1 = { x: mx, y: p0.y };
        const c2 = { x: mx, y: p1.y };
        path.setAttribute("d", `M${p0.x.toFixed(1)} ${p0.y.toFixed(1)}C${c1.x.toFixed(1)} ${c1.y.toFixed(1)} ${c2.x.toFixed(1)} ${c2.y.toFixed(1)} ${p1.x.toFixed(1)} ${p1.y.toFixed(1)}`);
        const ds = dots.current.get(l.id);
        if (ds) {
          ds.forEach((d, i) => {
            if (!l.particles || reduce) return d.setAttribute("opacity", "0");
            const t = ((now / 1400 + i / ds.length) % 1);
            const p = bez(p0, c1, c2, p1, t);
            d.setAttribute("cx", p.x.toFixed(1));
            d.setAttribute("cy", p.y.toFixed(1));
            d.setAttribute("opacity", "1");
          });
        }
      }
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [container, canvas, anchors]);

  return (
    <svg className="pointer-events-none absolute inset-0 z-10 h-full w-full overflow-visible" aria-hidden>
      {lines.map((l) => (
        <g key={l.id}>
          <path ref={(el) => void (el ? paths.current.set(l.id, el) : paths.current.delete(l.id))} fill="none" stroke={l.active ? l.color : "var(--line)"} strokeWidth={l.active ? 1.75 : 1} strokeLinecap="round" strokeLinejoin="round" style={{ transition: "stroke 150ms, stroke-width 150ms" }} />
          {l.particles &&
            [0, 1, 2].map((i) => (
              <circle
                key={i}
                r="2.5"
                fill={l.color}
                opacity="0"
                ref={(el) => {
                  if (!el) return;
                  const arr = dots.current.get(l.id) ?? [];
                  arr[i] = el;
                  dots.current.set(l.id, arr);
                }}
              />
            ))}
        </g>
      ))}
    </svg>
  );
}
