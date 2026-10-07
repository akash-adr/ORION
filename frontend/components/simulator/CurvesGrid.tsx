"use client";

import { LoadState, Panel } from "@/components/Panel";
import CampaignName from "@/components/CampaignName";
import { CurveChart } from "@/components/charts";
import { HeadroomChip } from "@/components/chips";
import { inrDay } from "@/lib/format";
import { useCurves, useOptimizeKey } from "@/lib/queries";
import { cn } from "@/lib/utils";

export default function CurvesGrid() {
  const q = useCurves();
  const plan = useOptimizeKey().data?.plan;
  return (
    <Panel title="Response curves" note="Profit per day against daily spend, best next rupee first">
      <p className="narrative mb-4">Marginal POAS is the profit from the next ₹1. Above 1, scaling adds profit; below 1, every extra rupee loses money.</p>
      <LoadState q={q} what="the response curves" height={420}>
        {(curves) => {
          const sorted = [...curves].sort((a, b) => (b.marginal_poas ?? -Infinity) - (a.marginal_poas ?? -Infinity));
          return (
            <div className="grid gap-4 min-[1000px]:grid-cols-2 min-[1200px]:grid-cols-3">
              {sorted.map((c) => {
                const m = c.marginal_poas;
                return (
                  <article key={c.campaign_id} className="min-w-0 rounded-lg border border-line p-3">
                    <header className="mb-1 flex flex-wrap items-center justify-between gap-2">
                      <CampaignName name={c.name} channel={c.channel} className="text-sm" />
                      <HeadroomChip h={c.headroom} />
                    </header>
                    <div className="mb-1 flex flex-wrap items-baseline justify-between gap-x-3 text-sm">
                      <span className={cn("font-bold", m === null ? "" : m >= 1 ? "tone-gain" : "tone-loss")}>
                        {m === null ? "—" : <>{m >= 1 ? "↑" : "↓"} ₹{m.toFixed(2)} on the next ₹1</>}
                      </span>
                      <span className="text-xs text-fog">Saturates at {inrDay(c.saturation_spend)}</span>
                    </div>
                    <CurveChart points={c.points} current={c.current_spend} planned={plan?.[c.campaign_id] ?? null} optimal={c.optimal_spend} saturation={c.saturation_spend} height={200} summary={`Profit curve for ${c.name}: now ${inrDay(c.current_spend)}, best ${inrDay(c.optimal_spend)}, saturates at ${inrDay(c.saturation_spend)}.`} />
                  </article>
                );
              })}
            </div>
          );
        }}
      </LoadState>
    </Panel>
  );
}
