"use client";

import { inr, MINUS } from "@/lib/format";
import { factorColor } from "@/lib/names";
import { niceTicks, scaleLinear, useWidth } from "./util";

export interface WaterfallFactor {
  name: string;
  /** signed, in the same unit as the net */
  impact: number;
}

interface Props {
  factors: WaterfallFactor[];
  /** unit shown after each value, e.g. "/day" */
  unit?: string;
  /** label of the final bar */
  netLabel?: string;
  summary: string;
}

const ROW = 34;
const AXIS = 24;
const VALUE_W = 104;

const signed = (v: number, unit: string) => {
  if (v === 0) return "no change";
  const body = inr(Math.abs(v)) + unit;
  return v > 0 ? `↑ ${body}` : `↓ ${MINUS}${body}`;
};

/**
 * Horizontal waterfall: each factor is a bar that starts where the previous one ended (in the order given), coloured by the
 * M4 factor contract, with an arrow and ₹ value. The last bar is the net, drawn from zero, and ends exactly where the last
 * factor ends (the net is the running sum, so they cannot differ).
 */
export default function Waterfall({ factors, unit = "/day", netLabel = "Net change", summary }: Props) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const labelW = Math.min(200, Math.max(120, width * 0.34));
  const left = labelW + 12;
  const iw = Math.max(0, width - left - VALUE_W);

  const rows = factors.reduce<(WaterfallFactor & { from: number; to: number })[]>((acc, f) => {
    const from = acc.length ? acc[acc.length - 1].to : 0;
    acc.push({ ...f, from, to: from + f.impact });
    return acc;
  }, []);
  const net = rows.length ? rows[rows.length - 1].to : 0;
  const points = [0, ...rows.flatMap((r) => [r.from, r.to]), net];
  const lo = Math.min(...points);
  const hi = Math.max(...points);
  const ticks = niceTicks(lo, hi, 5);
  const sx = scaleLinear(ticks[0], ticks[ticks.length - 1], left, left + iw);
  const height = (rows.length + 1) * ROW + AXIS + 4;

  return (
    <div ref={ref} className="w-full">
      {width > 0 && (
        <svg width={width} height={height} role="img" aria-label={summary} className="block">
          {ticks.map((t) => (
            <g key={t}>
              <line x1={sx(t)} x2={sx(t)} y1={0} y2={height - AXIS} stroke="var(--line)" />
              <text x={sx(t)} y={height - 6} textAnchor="middle" fontSize="12" fill="var(--fog)">
                {t === 0 ? "₹0" : t < 0 ? `${MINUS}${inr(-t)}` : inr(t)}
              </text>
            </g>
          ))}
          <line x1={sx(0)} x2={sx(0)} y1={0} y2={height - AXIS} stroke="var(--fog)" />
          {rows.map((r, i) => {
            const y = i * ROW + 6;
            const x0 = sx(Math.min(r.from, r.to));
            const w = Math.max(r.impact === 0 ? 2 : 3, Math.abs(sx(r.to) - sx(r.from)));
            const labelX = Math.max(x0 + w, sx(Math.max(r.from, r.to))) + 8;
            return (
              <g key={r.name}>
                <rect x={0} y={y + 8} width="10" height="10" rx="2" fill={factorColor(r.name)} />
                <text x={18} y={y + 17} fontSize="14" fill="var(--bone)">
                  {r.name}
                </text>
                <rect x={x0} y={y + 3} width={w} height={ROW - 12} rx="3" fill={factorColor(r.name)} />
                <line x1={sx(r.to)} x2={sx(r.to)} y1={y + ROW - 9} y2={y + ROW + 3} stroke="var(--fog)" strokeDasharray="2 2" />
                <text x={labelX} y={y + 17} fontSize="14" fontWeight="600" fill={r.impact === 0 ? "var(--fog)" : r.impact > 0 ? "var(--gain-fg)" : "var(--loss-fg)"}>
                  {signed(r.impact, unit)}
                </text>
              </g>
            );
          })}
          {(() => {
            const y = rows.length * ROW + 6;
            const x0 = sx(Math.min(0, net));
            const w = Math.max(3, Math.abs(sx(net) - sx(0)));
            return (
              <g>
                <line x1={0} x2={width} y1={y - 3} y2={y - 3} stroke="var(--line)" />
                <text x={18} y={y + 17} fontSize="14" fontWeight="700" fill="var(--bone)">
                  {netLabel}
                </text>
                <rect x={x0} y={y + 3} width={w} height={ROW - 12} rx="3" fill="var(--synapse)" />
                <text x={Math.max(sx(net), sx(0)) + 8} y={y + 17} fontSize="14" fontWeight="700" fill={net >= 0 ? "var(--gain-fg)" : "var(--loss-fg)"}>
                  {signed(net, unit)}
                </text>
              </g>
            );
          })()}
        </svg>
      )}
    </div>
  );
}

export { signed as waterfallLabel };
