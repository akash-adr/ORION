"use client";

import { useState } from "react";
import { CurveChart } from "@/components/charts";
import CampaignName from "@/components/CampaignName";
import PageHeader from "@/components/PageHeader";
import { LoadState, Panel } from "@/components/Panel";
import { inrDay, num, pct } from "@/lib/format";
import { useCurves } from "@/lib/queries";

export default function SimulatorPage() {
  const q = useCurves();
  const [picked, setPicked] = useState<string | null>(null);
  return (
    <div className="grid gap-5">
      <PageHeader title="Simulator">How profit responds as one campaign&apos;s daily spend moves. The what-if controls arrive next.</PageHeader>
      <LoadState q={q} what="the response curves" height={360}>
        {(curves) => {
          const c = curves.find((x) => x.campaign_id === picked) ?? curves[0];
          return (
            <Panel title="Response curve" note="Profit per day against daily spend">
              <label className="mb-4 flex flex-wrap items-center gap-3 text-sm text-fog">
                Campaign
                <select value={c.campaign_id} onChange={(e) => setPicked(e.target.value)} className="h-9 rounded-lg border border-line bg-slate-2 px-2.5 text-sm font-semibold text-bone">
                  {curves.map((x) => (
                    <option key={x.campaign_id} value={x.campaign_id}>
                      {x.name}
                    </option>
                  ))}
                </select>
                <CampaignName name={c.name} channel={c.channel} className="text-bone" />
              </label>
              <CurveChart
                points={c.points}
                current={c.current_spend}
                optimal={c.optimal_spend}
                summary={`Profit curve for ${c.name}. Current spend ${inrDay(c.current_spend)}, best spend ${inrDay(c.optimal_spend)}.`}
              />
              <dl className="mt-4 grid grid-cols-2 gap-x-6 gap-y-3 text-sm min-[1000px]:grid-cols-4">
                <div>
                  <dt className="text-fog">Margin on the next ₹1 spent</dt>
                  <dd className="text-base font-bold">{c.marginal_poas === null ? "—" : `₹${c.marginal_poas.toFixed(2)}`}</dd>
                </div>
                <div>
                  <dt className="text-fog">Saturation spend</dt>
                  <dd className="text-base font-bold">{inrDay(c.saturation_spend)}</dd>
                </div>
                <div>
                  <dt className="text-fog">Curve uncertainty</dt>
                  <dd className="text-base font-bold">{pct(c.uncertainty)}</dd>
                </div>
                <div>
                  <dt className="text-fog">Stock cover</dt>
                  <dd className="text-base font-bold">{num(c.days_cover, 1)} days</dd>
                </div>
              </dl>
            </Panel>
          );
        }}
      </LoadState>
    </div>
  );
}
