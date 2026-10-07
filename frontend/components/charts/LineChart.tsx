"use client";

import { useId, useState } from "react";
import { inr } from "@/lib/format";
import { labelIndices, linePath, niceTicks, scaleLinear, useWidth } from "./util";

export interface LineSeries {
  id: string;
  label: string;
  /** CSS colour, e.g. "var(--synapse)" */
  color: string;
  data: (number | null)[];
  dashed?: boolean;
  /** faint area under the line down to the zero line */
  area?: boolean;
}
export interface ChartEvent {
  /** must equal one of the x labels */
  x: string;
  label: string;
}
export interface ChartThreshold {
  value: number;
  label: string;
  color?: string;
}
export interface ChartBand {
  from: string;
  to: string;
  label?: string;
}

interface Props {
  x: string[];
  series: LineSeries[];
  height?: number;
  format?: (v: number | null) => string;
  xFormat?: (label: string) => string;
  events?: ChartEvent[];
  thresholds?: ChartThreshold[];
  bands?: ChartBand[];
  /** Written description of what the chart shows (read by screen readers). */
  summary: string;
}

const M = { l: 56, r: 14, t: 10, b: 26 };

/** Multi-series line chart with a hover / arrow-key crosshair whose values appear in the legend. */
export default function LineChart({ x, series, height = 240, format = inr, xFormat = (s) => s, events = [], thresholds = [], bands = [], summary }: Props) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const uid = useId();
  const n = x.length;
  const iw = Math.max(0, width - M.l - M.r);
  const ih = height - M.t - M.b;

  const vals = series.flatMap((s) => s.data).filter((v): v is number => v !== null && Number.isFinite(v));
  const all = [...vals, ...thresholds.map((t) => t.value)];
  const lo = all.length ? Math.min(...all) : 0;
  const hi = all.length ? Math.max(...all) : 1;
  const ticks = niceTicks(Math.min(lo, series.some((s) => s.area) ? 0 : lo), Math.max(hi, series.some((s) => s.area) ? 0 : hi), 5);
  const y0 = ticks[0];
  const y1 = ticks[ticks.length - 1];
  const sy = scaleLinear(y0, y1, M.t + ih, M.t);
  const xs = x.map((_, i) => M.l + (n <= 1 ? iw / 2 : (i * iw) / (n - 1)));
  const idx = (label: string) => x.indexOf(label);
  const active = hover ?? n - 1;

  const onMove = (clientX: number, rect: DOMRect) => {
    if (n < 2 || iw <= 0) return;
    const i = Math.round(((clientX - rect.left - M.l) / iw) * (n - 1));
    setHover(Math.max(0, Math.min(n - 1, i)));
  };

  return (
    <div ref={ref} className="w-full">
      <div className="mb-2 flex flex-wrap items-center gap-x-5 gap-y-1 text-sm" aria-live="off">
        <span className="text-fog">{n ? xFormat(x[active]) : ""}</span>
        {series.map((s) => (
          <span key={s.id} className="inline-flex items-center gap-1.5">
            <svg width="16" height="8" aria-hidden>
              <line x1="0" x2="16" y1="4" y2="4" stroke={s.color} strokeWidth="2" strokeDasharray={s.dashed ? "4 3" : undefined} />
            </svg>
            <span className="text-fog">{s.label}</span>
            <span className="font-semibold">{format(s.data[active] ?? null)}</span>
          </span>
        ))}
      </div>
      {width > 0 && (
        <svg
          width={width}
          height={height}
          role="img"
          aria-label={summary}
          tabIndex={0}
          className="block touch-none outline-offset-2"
          onPointerMove={(e) => onMove(e.clientX, e.currentTarget.getBoundingClientRect())}
          onPointerLeave={() => setHover(null)}
          onBlur={() => setHover(null)}
          onKeyDown={(e) => {
            if (e.key === "ArrowLeft") setHover(Math.max(0, active - 1));
            else if (e.key === "ArrowRight") setHover(Math.min(n - 1, active + 1));
            else if (e.key === "Escape") setHover(null);
          }}
        >
          {bands.map((b, i) => {
            const a = idx(b.from);
            const z = idx(b.to);
            if (a < 0 || z < 0) return null;
            return (
              <g key={i}>
                <rect x={xs[a]} y={M.t} width={Math.max(1, xs[z] - xs[a])} height={ih} fill="var(--synapse)" opacity="0.08" />
                {b.label && (
                  <text x={xs[a] + 6} y={M.t + 12} fontSize="12" fill="var(--fog)">
                    {b.label}
                  </text>
                )}
              </g>
            );
          })}
          {ticks.map((t) => (
            <g key={t}>
              <line x1={M.l} x2={M.l + iw} y1={sy(t)} y2={sy(t)} stroke="var(--line)" strokeWidth="1" />
              <text x={M.l - 8} y={sy(t) + 4} textAnchor="end" fontSize="12" fill="var(--fog)">
                {format(t)}
              </text>
            </g>
          ))}
          {y0 < 0 && y1 > 0 && <line x1={M.l} x2={M.l + iw} y1={sy(0)} y2={sy(0)} stroke="var(--fog)" strokeWidth="1" />}
          {labelIndices(n, Math.max(2, Math.floor(iw / 90))).map((i) => (
            <text key={i} x={xs[i]} y={height - 6} textAnchor={i === 0 ? "start" : i === n - 1 ? "end" : "middle"} fontSize="12" fill="var(--fog)">
              {xFormat(x[i])}
            </text>
          ))}
          {thresholds.map((t, i) => (
            <g key={i}>
              <line x1={M.l} x2={M.l + iw} y1={sy(t.value)} y2={sy(t.value)} stroke={t.color ?? "var(--risk)"} strokeWidth="1" strokeDasharray="5 4" />
              <text x={M.l + iw - 4} y={sy(t.value) - 5} textAnchor="end" fontSize="12" fill={t.color ?? "var(--risk-fg)"}>
                {t.label}
              </text>
            </g>
          ))}
          {series.map((s) => {
            const ys = s.data.map((v) => (v === null ? null : sy(v)));
            const d = linePath(xs, ys);
            return (
              <g key={s.id}>
                {s.area && d && (
                  <path
                    d={`${d}L${xs[n - 1].toFixed(1)},${sy(Math.max(y0, Math.min(0, y1))).toFixed(1)}L${xs[0].toFixed(1)},${sy(Math.max(y0, Math.min(0, y1))).toFixed(1)}Z`}
                    fill={s.color}
                    opacity="0.1"
                  />
                )}
                <path d={d} fill="none" stroke={s.color} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" strokeDasharray={s.dashed ? "6 4" : undefined} />
              </g>
            );
          })}
          {events.map((ev, i) => {
            const k = idx(ev.x);
            if (k < 0) return null;
            return (
              <g key={i}>
                <line x1={xs[k]} x2={xs[k]} y1={M.t} y2={M.t + ih} stroke="var(--fog)" strokeWidth="1" strokeDasharray="2 3" />
                <circle cx={xs[k]} cy={M.t + 4} r="4" fill="var(--slate)" stroke="var(--fog)" strokeWidth="1.5" />
                <text x={xs[k] + (xs[k] > width - 140 ? -8 : 8)} y={M.t + 8} textAnchor={xs[k] > width - 140 ? "end" : "start"} fontSize="12" fill="var(--fog)">
                  {ev.label}
                </text>
              </g>
            );
          })}
          {hover !== null && (
            <g pointerEvents="none">
              <line x1={xs[hover]} x2={xs[hover]} y1={M.t} y2={M.t + ih} stroke="var(--bone)" strokeWidth="1" opacity="0.5" />
              {series.map((s) => {
                const v = s.data[hover];
                return v === null || v === undefined ? null : <circle key={`${uid}${s.id}`} cx={xs[hover]} cy={sy(v)} r="4" fill="var(--slate)" stroke={s.color} strokeWidth="2" />;
              })}
            </g>
          )}
        </svg>
      )}
    </div>
  );
}
