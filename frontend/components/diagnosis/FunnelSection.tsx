"use client";

import { TriangleAlert } from "lucide-react";
import CampaignName from "@/components/CampaignName";
import { Panel } from "@/components/Panel";
import { FunnelBars } from "@/components/charts";
import { campaignMoves, funnelStages, funnelSteps } from "@/lib/diagnosis";
import { inr, pct } from "@/lib/format";
import { stageDisplay } from "@/lib/names";
import type { Diagnosis } from "@/lib/types";

/** Section 6: the shopper funnel, or for channel-level anomalies the campaigns that moved (worst first). */
export default function FunnelSection({ d }: { d: Diagnosis }) {
  const f = d.root_cause.funnel;
  const stages = funnelStages(f);
  const steps = funnelSteps(f);
  const moves = [...campaignMoves(f)].sort((a, b) => a.change - b.change);
  if (stages) {
    return (
      <Panel title="Where shoppers drop off" note="Recent window against the baseline, per day">
        <FunnelBars stages={stages} summary={`Funnel from ${stages[0].label} to ${stages[stages.length - 1].label}.`} />
        <table className="tbl mt-4">
          <thead>
            <tr>
              <th>Step</th>
              <th className="num">Baseline rate</th>
              <th className="num">Recent rate</th>
              <th className="num">Change</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {steps.map((s) => (
              <tr key={s.stage} className={s.is_biggest_drop && s.change_pct < -0.005 ? "bg-slate-2/60" : undefined}>
                <td>{stageDisplay(s.from)} to {stageDisplay(s.stage).toLowerCase()}</td>
                <td className="num">{pct(s.baseline_rate, 1)}</td>
                <td className="num font-semibold">{pct(s.recent_rate, 1)}</td>
                <td className={`num ${s.change_pct < -0.005 ? "tone-loss" : s.change_pct > 0.005 ? "tone-gain" : ""}`}>{Math.abs(s.change_pct) < 0.005 ? "No change" : `${s.change_pct < 0 ? "↓" : "↑"} ${pct(Math.abs(s.change_pct), 1)}`}</td>
                <td>
                  {s.is_biggest_drop && s.change_pct < -0.005 && (
                    <span className="inline-flex items-center gap-1 text-sm font-semibold tone-risk">
                      <TriangleAlert className="size-3.5" aria-hidden />
                      Biggest drop
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
    );
  }
  if (moves.length) {
    return (
      <Panel title="Campaigns that moved" note="Profit per day, worst first">
        <table className="tbl">
          <thead>
            <tr>
              <th>Campaign</th>
              <th className="num">Before</th>
              <th className="num">Now</th>
              <th className="num">Change</th>
              <th>Main cause</th>
            </tr>
          </thead>
          <tbody>
            {moves.map((m) => (
              <tr key={m.campaign_id}>
                <td><CampaignName name={m.campaign_name} /></td>
                <td className="num">{inr(m.baseline_profit)}</td>
                <td className="num font-semibold">{inr(m.recent_profit)}</td>
                <td className={`num font-semibold ${m.change < 0 ? "tone-loss" : "tone-gain"}`}>{m.change < 0 ? "↓" : "↑"} {inr(Math.abs(m.change))}</td>
                <td className="text-fog">{m.top_factor}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
    );
  }
  return null;
}
