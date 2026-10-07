"use client";

import { Lock, TriangleAlert } from "lucide-react";
import { scaleLinear } from "./util";

interface Props {
  /** days of stock left at the current sales rate */
  days: number | null;
  /** the stock guard, in days (from /meta/config) */
  guard: number;
  /** the campaign is capped by the stock guard */
  locked?: boolean;
  /** upper end of the bar; defaults to 3 × the guard */
  max?: number;
}

/** Days of cover against the stock guard: the marker is the guard, the fill is the stock left. */
export default function StockBar({ days, guard, locked = false, max }: Props) {
  if (days === null || !Number.isFinite(days)) return <span className="text-fog">No stock data</span>;
  const top = Math.max(max ?? guard * 3, days, guard * 1.2);
  const sx = scaleLinear(0, top, 0, 100);
  const low = days < guard;
  const label = `${days.toFixed(1)} days of cover, guard at ${guard} days${low ? ", below the guard" : ""}${locked ? ", spend locked" : ""}`;
  return (
    <div className="min-w-[160px]" role="img" aria-label={label}>
      <div className="relative h-2.5 rounded-full bg-slate-2">
        <div className="absolute inset-y-0 left-0 rounded-full" style={{ width: `${sx(days)}%`, background: low ? "var(--loss)" : "var(--gain)" }} />
        <div className="absolute -inset-y-1 w-0.5 rounded bg-bone" style={{ left: `${sx(guard)}%` }} aria-hidden />
      </div>
      <div className="mt-1.5 flex items-center justify-between gap-2 text-xs text-fog">
        <span className={low ? "inline-flex items-center gap-1 font-semibold tone-loss" : "font-semibold text-bone"}>
          {low && <TriangleAlert className="size-3.5" aria-hidden />}
          {days.toFixed(1)} days left
        </span>
        <span className="inline-flex items-center gap-1">
          {locked && <Lock className="size-3.5" aria-hidden />}
          {locked ? "Spend locked, " : ""}guard {guard} days
        </span>
      </div>
    </div>
  );
}
