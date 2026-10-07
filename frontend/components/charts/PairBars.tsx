"use client";

import { inr } from "@/lib/format";
import { scaleLinear, useWidth } from "./util";

export interface PairItem {
  label: string;
  a: number;
  b: number;
  /** short text at the end of the row, e.g. "Platform overstates by 11%" */
  note?: string;
}
interface Props {
  items: PairItem[];
  aLabel: string;
  bLabel: string;
  format?: (v: number | null) => string;
  summary: string;
}

const ROW = 46;

/** Two bars per row: what the platform claims vs what the store verified. Not red/green: neither bar is "bad" by itself. */
export default function PairBars({ items, aLabel, bLabel, format = inr, summary }: Props) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const labelW = Math.min(150, Math.max(96, width * 0.22));
  const noteW = width > 640 ? 210 : 0;
  const valueW = 64;
  const left = labelW + 8;
  const iw = Math.max(0, width - left - valueW - noteW);
  const max = Math.max(1e-9, ...items.flatMap((i) => [i.a, i.b]));
  const sx = scaleLinear(0, max, 0, iw);

  return (
    <div ref={ref} className="w-full">
      <div className="mb-2 flex gap-5 text-sm text-fog">
        <span className="inline-flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-sm" style={{ background: "var(--factor-budget)" }} />
          {aLabel}
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-sm" style={{ background: "var(--synapse)" }} />
          {bLabel}
        </span>
      </div>
      {width > 0 && (
        <svg width={width} height={items.length * ROW} role="img" aria-label={summary} className="block">
          {items.map((it, i) => {
            const y = i * ROW + 4;
            return (
              <g key={it.label}>
                <text x={0} y={y + 20} fontSize="14" fill="var(--bone)">
                  {it.label}
                </text>
                <rect x={left} y={y + 4} width={Math.max(2, sx(it.a))} height="14" rx="3" fill="var(--factor-budget)" />
                <text x={left + sx(it.a) + 6} y={y + 16} fontSize="12" fill="var(--fog)">
                  {format(it.a)}
                </text>
                <rect x={left} y={y + 22} width={Math.max(2, sx(it.b))} height="14" rx="3" fill="var(--synapse)" />
                <text x={left + sx(it.b) + 6} y={y + 34} fontSize="12" fontWeight="600" fill="var(--bone)">
                  {format(it.b)}
                </text>
                {noteW > 0 && it.note && (
                  <text x={width - noteW + 12} y={y + 25} fontSize="12" fill="var(--fog)">
                    {it.note}
                  </text>
                )}
              </g>
            );
          })}
        </svg>
      )}
    </div>
  );
}
