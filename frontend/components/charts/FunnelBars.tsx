"use client";

import { TriangleAlert } from "lucide-react";
import { num, pct } from "@/lib/format";

export interface FunnelStageView {
  label: string;
  /** recent count per day */
  count: number;
  /** step conversion from the previous stage in the recent window (null for the first stage) */
  rate: number | null;
  /** the same step in the baseline window */
  baselineRate?: number | null;
  biggestDrop?: boolean;
}
interface Props {
  stages: FunnelStageView[];
  summary: string;
}

/** GA4 funnel: bar length is the daily count; each step shows its conversion rate against the baseline. */
export default function FunnelBars({ stages, summary }: Props) {
  const top = Math.max(1, ...stages.map((s) => s.count));
  return (
    <div role="img" aria-label={summary} className="grid gap-2.5">
      {stages.map((s) => {
        const change = s.rate !== null && s.baselineRate ? s.rate / s.baselineRate - 1 : null;
        return (
          <div key={s.label} className="grid grid-cols-[minmax(110px,150px)_1fr] items-center gap-3 sm:grid-cols-[150px_1fr_220px]">
            <span className="text-sm">{s.label}</span>
            <div className="flex items-center gap-2">
              <div className="h-4 rounded-sm" style={{ width: `${Math.max(1.5, (s.count / top) * 100)}%`, background: "var(--factor-traffic)" }} />
              <span className="text-sm font-semibold whitespace-nowrap">{num(s.count)}</span>
              <span className="text-xs whitespace-nowrap text-fog">a day</span>
            </div>
            <div className="hidden text-sm sm:block">
              {s.rate === null ? (
                <span className="text-fog">Entry point</span>
              ) : (
                <span className="inline-flex flex-wrap items-center gap-x-2">
                  <span className="font-semibold">{pct(s.rate, 1)} step rate</span>
                  {change !== null && Math.abs(change) >= 0.005 && (
                    <span className={change < 0 ? "tone-loss" : "tone-gain"}>
                      {change < 0 ? "↓" : "↑"} {pct(Math.abs(change), 0)} vs baseline
                    </span>
                  )}
                  {s.biggestDrop && (
                    <span className="inline-flex items-center gap-1 tone-risk">
                      <TriangleAlert className="size-3.5" aria-hidden />
                      Biggest drop
                    </span>
                  )}
                </span>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
