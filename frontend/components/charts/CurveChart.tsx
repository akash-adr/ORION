"use client";

import { inr, MINUS } from "@/lib/format";
import { niceTicks, scaleLinear, useWidth } from "./util";

export interface CurvePointLite {
  spend: number;
  profit: number;
}
interface Props {
  points: CurvePointLite[];
  current?: number | null;
  planned?: number | null;
  optimal?: number | null;
  height?: number;
  summary: string;
}

const M = { l: 60, r: 16, t: 14, b: 40 };

function profitAt(points: CurvePointLite[], spend: number): number {
  if (!points.length) return 0;
  if (spend <= points[0].spend) return points[0].profit;
  for (let i = 1; i < points.length; i++) {
    if (spend <= points[i].spend) {
      const a = points[i - 1];
      const b = points[i];
      const t = b.spend === a.spend ? 0 : (spend - a.spend) / (b.spend - a.spend);
      return a.profit + t * (b.profit - a.profit);
    }
  }
  return points[points.length - 1].profit;
}

/** Profit (₹/day) against daily spend for one campaign, with the current, planned and optimal spend marked and the zero line drawn. */
export default function CurveChart({ points, current, planned, optimal, height = 260, summary }: Props) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const iw = Math.max(0, width - M.l - M.r);
  const ih = height - M.t - M.b;
  const xt = niceTicks(points[0]?.spend ?? 0, points[points.length - 1]?.spend ?? 1, 5);
  const profits = points.map((p) => p.profit);
  const yt = niceTicks(Math.min(0, ...profits), Math.max(0, ...profits), 5);
  const sx = scaleLinear(xt[0], xt[xt.length - 1], M.l, M.l + iw);
  const sy = scaleLinear(yt[0], yt[yt.length - 1], M.t + ih, M.t);
  const path = points.map((p, i) => `${i ? "L" : "M"}${sx(p.spend).toFixed(1)},${sy(p.profit).toFixed(1)}`).join("");
  const fmt = (v: number) => (v < 0 ? `${MINUS}${inr(-v)}` : inr(v));

  const marks: { key: string; spend: number; label: string; shape: "dot" | "ring" | "diamond" }[] = [];
  if (current != null) marks.push({ key: "current", spend: current, label: "Now", shape: "dot" });
  if (planned != null) marks.push({ key: "planned", spend: planned, label: "Planned", shape: "ring" });
  if (optimal != null) marks.push({ key: "optimal", spend: optimal, label: "Best spend", shape: "diamond" });

  return (
    <div ref={ref} className="w-full">
      <div className="mb-2 flex flex-wrap gap-x-5 gap-y-1 text-sm text-fog">
        {marks.map((m) => (
          <span key={m.key} className="inline-flex items-center gap-1.5">
            <svg width="12" height="12" aria-hidden>
              {m.shape === "dot" && <circle cx="6" cy="6" r="4.5" fill="var(--bone)" />}
              {m.shape === "ring" && <circle cx="6" cy="6" r="4" fill="var(--slate)" stroke="var(--synapse)" strokeWidth="2" />}
              {m.shape === "diamond" && <path d="M6 0.5L11.5 6L6 11.5L0.5 6Z" fill="var(--gain)" />}
            </svg>
            {m.label} <span className="font-semibold text-bone">{inr(m.spend)}/day</span>
          </span>
        ))}
      </div>
      {width > 0 && (
        <svg width={width} height={height} role="img" aria-label={summary} className="block">
          {yt.map((t) => (
            <g key={t}>
              <line x1={M.l} x2={M.l + iw} y1={sy(t)} y2={sy(t)} stroke="var(--line)" />
              <text x={M.l - 8} y={sy(t) + 4} textAnchor="end" fontSize="12" fill="var(--fog)">
                {fmt(t)}
              </text>
            </g>
          ))}
          {xt.map((t) => (
            <text key={t} x={sx(t)} y={height - 22} textAnchor="middle" fontSize="12" fill="var(--fog)">
              {inr(t)}
            </text>
          ))}
          <text x={M.l + iw / 2} y={height - 5} textAnchor="middle" fontSize="12" fill="var(--fog)">
            Daily spend on this campaign
          </text>
          {yt[0] < 0 && yt[yt.length - 1] > 0 && (
            <>
              <line x1={M.l} x2={M.l + iw} y1={sy(0)} y2={sy(0)} stroke="var(--fog)" />
              <text x={M.l + 6} y={sy(0) - 5} fontSize="12" fill="var(--fog)">
                Break-even
              </text>
            </>
          )}
          <path d={path} fill="none" stroke="var(--synapse)" strokeWidth="2.5" strokeLinejoin="round" />
          {marks.map((m) => {
            const cx = sx(m.spend);
            const cy = sy(profitAt(points, m.spend));
            return (
              <g key={m.key}>
                <line x1={cx} x2={cx} y1={cy} y2={M.t + ih} stroke="var(--fog)" strokeDasharray="2 3" opacity="0.6" />
                {m.shape === "dot" && <circle cx={cx} cy={cy} r="6" fill="var(--bone)" stroke="var(--slate)" strokeWidth="2" />}
                {m.shape === "ring" && <circle cx={cx} cy={cy} r="6" fill="var(--slate)" stroke="var(--synapse)" strokeWidth="2.5" />}
                {m.shape === "diamond" && <path d={`M${cx},${cy - 8}L${cx + 8},${cy}L${cx},${cy + 8}L${cx - 8},${cy}Z`} fill="var(--gain)" stroke="var(--slate)" strokeWidth="1.5" />}
              </g>
            );
          })}
        </svg>
      )}
    </div>
  );
}
