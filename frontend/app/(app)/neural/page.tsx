"use client";

import { TriangleAlert } from "lucide-react";
import CampaignName from "@/components/CampaignName";
import PageHeader from "@/components/PageHeader";
import { LoadState, Panel } from "@/components/Panel";
import { inr, inrDay } from "@/lib/format";
import { kindDisplay } from "@/lib/names";
import { useBrainSnapshot } from "@/lib/queries";

export default function NeuralPage() {
  const q = useBrainSnapshot();
  return (
    <div>
      <PageHeader title="Neural view">The engine as a live map of campaigns, products and data sources. The 3D map arrives next; this is the data it will draw.</PageHeader>
      <LoadState q={q} what="the neural map" height={320}>
        {(s) => {
          const campaigns = s.nodes.filter((n) => n.entity_type === "campaign");
          return (
            <div className="grid gap-5">
              <Panel title="Neurons" note="Campaigns, last 7 days, per day">
                <table className="tbl">
                  <thead>
                    <tr>
                      <th>Campaign</th>
                      <th className="num">Spend</th>
                      <th className="num">Profit</th>
                      <th>Health</th>
                      <th>Alert</th>
                    </tr>
                  </thead>
                  <tbody>
                    {campaigns.map((n) => (
                      <tr key={n.entity_id}>
                        <td>
                          <CampaignName name={n.label} channel={n.channel} />
                        </td>
                        <td className="num">{inrDay(n.spend_7d)}</td>
                        <td className={`num font-semibold ${n.profit_7d < 0 ? "tone-loss" : "tone-gain"}`}>{inr(n.profit_7d)}/day</td>
                        <td>{n.health === "good" ? "Healthy" : n.health === "weak" ? "Weak" : "Losing money"}</td>
                        <td>
                          {n.is_alerting ? (
                            <span className="inline-flex items-center gap-1 tone-risk">
                              <TriangleAlert className="size-3.5" aria-hidden />
                              {kindDisplay(n.alert_kind)}
                            </span>
                          ) : (
                            <span className="text-fog">None</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Panel>
            </div>
          );
        }}
      </LoadState>
    </div>
  );
}
