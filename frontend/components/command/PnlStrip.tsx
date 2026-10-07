"use client";

import { ArrowDown, ArrowUp, TriangleAlert } from "lucide-react";
import { inr, pct, ratio, tone as toneOf } from "@/lib/format";
import { useKpis } from "@/lib/queries";
import type { Kpi } from "@/lib/types";
import { cn } from "@/lib/utils";
import { LoadState } from "@/components/Panel";

function Change({ kpi, days, neutral }: { kpi: Kpi; days: number; neutral?: boolean }) {
  if (kpi.change === null) return <span className="text-sm text-fog">No previous period</span>;
  if (Math.abs(kpi.change) < 0.005) return <span className="text-sm text-fog">Flat vs previous {days} days</span>;
  const t = neutral ? "muted" : toneOf(kpi.change);
  const Icon = kpi.change < 0 ? ArrowDown : ArrowUp;
  return (
    <span className={cn("inline-flex flex-wrap items-center gap-x-1.5 text-sm", t === "gain" ? "tone-gain" : t === "loss" ? "tone-loss" : "tone-muted")}>
      <span className="inline-flex items-center gap-0.5 font-semibold">
        <Icon className="size-3.5" aria-hidden />
        {pct(Math.abs(kpi.change), 0)}
      </span>
      <span className="text-fog">vs previous {days} days</span>
    </span>
  );
}

function Cell({ label, value, unit, valueTone, children }: { label: string; value: string; unit?: string; valueTone?: "gain" | "loss" | "muted"; children: React.ReactNode }) {
  return (
    <div className="bg-slate px-4 py-4 min-[1200px]:px-5">
      <div className="text-sm text-fog">{label}</div>
      <div className={cn("t-kpi mt-1 whitespace-nowrap", valueTone === "loss" && "tone-loss", valueTone === "gain" && "tone-gain")}>
        {value}
        {unit && <span className="ml-1 text-sm font-semibold text-fog">{unit}</span>}
      </div>
      <div className="mt-1.5 min-h-5">{children}</div>
    </div>
  );
}

/** The KPIs as ONE strip with dividers. Values are daily averages over the period (see lib/types.ts). */
export default function PnlStrip({ period = 7 }: { period?: number }) {
  const q = useKpis(period);
  return (
    <LoadState q={q} what="the P&L" height={118}>
      {(k) => {
        const d = k.period_days;
        const risk = k.stock_at_risk.skus[0];
        return (
          <section aria-label={`P&L, last ${d} days, daily averages`} className="panel overflow-hidden">
            <div className="grid grid-cols-2 gap-px bg-line min-[700px]:grid-cols-3 min-[1200px]:grid-cols-6">
              <Cell label={`Profit, last ${d} days`} value={inr(k.profit.value)} unit="/day" valueTone={k.profit.value !== null && k.profit.value < 0 ? "loss" : undefined}>
                <Change kpi={k.profit} days={d} />
              </Cell>
              <Cell label="Revenue" value={inr(k.revenue.value)} unit="/day">
                <Change kpi={k.revenue} days={d} />
              </Cell>
              <Cell label="Ad spend" value={inr(k.spend.value)} unit="/day">
                <Change kpi={k.spend} days={d} neutral />
              </Cell>
              <Cell label="Profit on spend" value={ratio(k.poas.value)}>
                <Change kpi={k.poas} days={d} />
              </Cell>
              <Cell label="Verified ad return" value={ratio(k.roas_true.value)}>
                <span className="text-sm text-fog">Platforms claim {ratio(k.roas_platform.value)}</span>
              </Cell>
              <Cell label="Stock at risk" value={`${k.stock_at_risk.value} ${k.stock_at_risk.value === 1 ? "product" : "products"}`} valueTone={k.stock_at_risk.value > 0 ? "loss" : undefined}>
                {risk ? (
                  <span className="inline-flex items-center gap-1 text-sm tone-loss">
                    <TriangleAlert className="size-3.5" aria-hidden />
                    {risk.name}, {risk.days_cover.toFixed(1)} days left
                  </span>
                ) : (
                  <span className="text-sm text-fog">Every product has cover</span>
                )}
              </Cell>
            </div>
          </section>
        );
      }}
    </LoadState>
  );
}
