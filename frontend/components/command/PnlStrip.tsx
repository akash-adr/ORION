"use client";

import { ArrowDown, ArrowUp, TriangleAlert } from "lucide-react";
import Link from "next/link";
import { LoadState } from "@/components/Panel";
import { Spark } from "@/components/charts";
import { inr, pct, ratio, tone as toneOf } from "@/lib/format";
import { channelDisplay } from "@/lib/names";
import { useChannels, useKpis, useTrend } from "@/lib/queries";
import type { Kpi, TrendPoint } from "@/lib/types";
import { cn } from "@/lib/utils";

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

function Cell({ label, hint, value, unit, valueTone, spark, period, children }: { label: string; hint?: string; value: string; unit?: string; valueTone?: "gain" | "loss"; spark?: { values: (number | null)[]; label: string }; period: string; children: React.ReactNode }) {
  return (
    <div className="flex min-w-0 flex-col bg-slate px-4 py-4 min-[1200px]:px-5">
      <div className="text-sm font-semibold">{label}</div>
      {hint && <div className="text-xs text-fog">{hint}</div>}
      <div className="mt-2 flex items-end justify-between gap-2">
        <div className={cn("t-kpi whitespace-nowrap", valueTone === "loss" && "tone-loss", valueTone === "gain" && "tone-gain")}>
          {value}
          {unit && <span className="ml-1 text-sm font-semibold text-fog">{unit}</span>}
        </div>
        {spark && <Spark values={spark.values} width={64} height={26} label={spark.label} />}
      </div>
      <div className="mt-1.5 min-h-5">{children}</div>
      <div className="mt-auto pt-2 text-xs text-fog">{period}</div>
    </div>
  );
}

const last = (t: TrendPoint[] | undefined, k: keyof TrendPoint) => (t ?? []).map((p) => p[k] as number | null);

/** The KPIs as ONE strip with dividers. /kpis values are daily averages over the period, so every cell says "per day". */
export default function PnlStrip({ period = 7 }: { period?: number }) {
  const q = useKpis(period);
  const trend = useTrend(14).data;
  const channels = useChannels().data;
  const t14 = trend?.slice(-14);
  return (
    <LoadState q={q} what="the P&L" height={150}>
      {(k) => {
        const d = k.period_days;
        const per = `Last ${d} days, average per day`;
        const risk = k.stock_at_risk.skus;
        const over = (channels ?? []).filter((c) => c.inflation_pct >= 0.05).map((c) => channelDisplay(c.channel));
        const sparkLabel = (what: string) => `${what} each day for the last 14 days`;
        return (
          <section aria-label={`P&L, last ${d} days, daily averages`} className="panel overflow-hidden">
            <div className="grid grid-cols-2 gap-px bg-line min-[700px]:grid-cols-3 min-[1200px]:grid-cols-6">
              <Cell label="Contribution profit" hint="After product costs and ad spend" value={inr(k.profit.value)} unit="/day" valueTone={k.profit.value !== null && k.profit.value < 0 ? "loss" : undefined} spark={{ values: last(t14, "profit"), label: sparkLabel("Profit") }} period={per}>
                <Change kpi={k.profit} days={d} />
              </Cell>
              <Cell label="Profit on spend" hint="Gross margin per ₹1 of ads" value={ratio(k.poas.value)} spark={{ values: last(t14, "poas"), label: sparkLabel("Profit on spend") }} period={per}>
                <Change kpi={k.poas} days={d} />
              </Cell>
              <Cell label="Ad spend" value={inr(k.spend.value)} unit="/day" spark={{ values: last(t14, "spend"), label: sparkLabel("Ad spend") }} period={per}>
                <div className="text-sm text-fog">
                  Store-verified ROAS <span className="font-semibold text-bone">{ratio(k.roas_true.value)}</span>, platforms claim {ratio(k.roas_platform.value)}
                </div>
                <Change kpi={k.spend} days={d} neutral />
              </Cell>
              <Cell label="Revenue" hint="Store-verified" value={inr(k.revenue.value)} unit="/day" spark={{ values: last(t14, "revenue"), label: sparkLabel("Revenue") }} period={per}>
                <Change kpi={k.revenue} days={d} />
              </Cell>
              <Cell label="Stock at risk" value={`${k.stock_at_risk.value} ${k.stock_at_risk.value === 1 ? "product" : "products"}`} valueTone={k.stock_at_risk.value > 0 ? "loss" : undefined} period="Latest stock, against the cover guard">
                {risk.length ? (
                  <ul className="text-sm tone-loss">
                    {risk.map((s) => (
                      <li key={s.sku_id} className="flex items-center gap-1">
                        <TriangleAlert className="size-3.5 shrink-0" aria-hidden />
                        {s.name}, {s.days_cover.toFixed(1)} days left
                      </li>
                    ))}
                  </ul>
                ) : (
                  <span className="text-sm text-fog">Every product has cover</span>
                )}
              </Cell>
              <Cell label="Data trust" hint="Weighted by ad spend" value={pct(k.data_trust)} period="Across all sources">
                {over.length > 0 ? (
                  <Link href="/data" className="text-sm font-semibold text-synapse-fg underline-offset-2 hover:underline">
                    {over.join(" and ")} over-report
                  </Link>
                ) : (
                  <span className="text-sm text-fog">Every platform matches the store</span>
                )}
              </Cell>
            </div>
          </section>
        );
      }}
    </LoadState>
  );
}
