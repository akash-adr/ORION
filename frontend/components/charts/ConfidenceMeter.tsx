"use client";

import { pct } from "@/lib/format";

interface Props {
  /** fraction, e.g. 0.67 */
  value: number | null;
  /** the engine's confidence floor and ceiling (from /meta/config), e.g. 0.45 and 0.95 */
  min: number;
  max: number;
  segments?: number;
}

/** Segmented bar from the engine's confidence floor to its ceiling, with the value beside it. */
export default function ConfidenceMeter({ value, min, max, segments = 10 }: Props) {
  if (value === null || !Number.isFinite(value)) return <span className="text-fog">—</span>;
  const filled = Math.max(0, Math.min(segments, Math.ceil(((value - min) / (max - min)) * segments - 1e-9)));
  return (
    <div className="inline-flex items-center gap-2" role="meter" aria-valuemin={Math.round(min * 100)} aria-valuemax={Math.round(max * 100)} aria-valuenow={Math.round(value * 100)} aria-label={`Confidence ${pct(value)}, engine range ${pct(min)} to ${pct(max)}`}>
      <div className="flex gap-[3px]" aria-hidden>
        {Array.from({ length: segments }, (_, i) => (
          <span key={i} className="h-3.5 w-2 rounded-[2px]" style={{ background: i < filled ? "var(--synapse)" : "var(--slate-2)", boxShadow: i < filled ? undefined : "inset 0 0 0 1px var(--line)" }} />
        ))}
      </div>
      <span className="text-sm font-semibold">{pct(value)}</span>
    </div>
  );
}
