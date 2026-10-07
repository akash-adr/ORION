"use client";

import { useEffect, useRef, useState } from "react";

/** Width of an element, kept current with a ResizeObserver. */
export function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    setWidth(Math.round(el.getBoundingClientRect().width));
    const ro = new ResizeObserver(([e]) => setWidth(Math.round(e.contentRect.width)));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, width] as const;
}

/** Round-number tick values covering [min, max]. */
export function niceTicks(min: number, max: number, count = 5): number[] {
  if (!Number.isFinite(min) || !Number.isFinite(max)) return [0];
  if (min === max) {
    const pad = Math.abs(min) * 0.1 || 1;
    min -= pad;
    max += pad;
  }
  const rawStep = (max - min) / Math.max(1, count - 1);
  const mag = Math.pow(10, Math.floor(Math.log10(rawStep)));
  const norm = rawStep / mag;
  const step = (norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 2.5 ? 2.5 : norm <= 5 ? 5 : 10) * mag;
  const start = Math.floor(min / step) * step;
  const end = Math.ceil(max / step) * step;
  const out: number[] = [];
  for (let v = start; v <= end + step / 2; v += step) out.push(Math.abs(v) < step * 1e-9 ? 0 : Number(v.toPrecision(12)));
  return out;
}

export function scaleLinear(d0: number, d1: number, r0: number, r1: number) {
  const k = d1 === d0 ? 0 : (r1 - r0) / (d1 - d0);
  return (v: number) => r0 + (v - d0) * k;
}

/** SVG path through points; null values break the line. */
export function linePath(xs: number[], ys: (number | null)[]): string {
  let d = "";
  let pen = false;
  ys.forEach((y, i) => {
    if (y === null || !Number.isFinite(y)) {
      pen = false;
      return;
    }
    d += `${pen ? "L" : "M"}${xs[i].toFixed(1)},${y.toFixed(1)}`;
    pen = true;
  });
  return d;
}

/** Evenly spaced indices for axis labels. */
export function labelIndices(n: number, want: number): number[] {
  if (n <= 0) return [];
  if (n <= want) return Array.from({ length: n }, (_, i) => i);
  const out: number[] = [];
  for (let i = 0; i < want; i++) out.push(Math.round((i * (n - 1)) / (want - 1)));
  return Array.from(new Set(out));
}
