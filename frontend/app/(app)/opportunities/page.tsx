"use client";

import CampaignName from "@/components/CampaignName";
import PageHeader from "@/components/PageHeader";
import { LoadState, Panel } from "@/components/Panel";
import { inrDay, num, pct, ratio } from "@/lib/format";
import { channelDisplay } from "@/lib/names";
import { useOpportunities } from "@/lib/queries";

export default function OpportunitiesPage() {
  const q = useOpportunities();
  return (
    <div>
      <PageHeader title="Opportunities">Product, channel and audience combinations the engine has not tried yet, ranked by predicted return.</PageHeader>
      <Panel title="Untested combinations" note="Scored by a model fitted on your campaigns">
        <LoadState q={q} what="the opportunities" height={320}>
          {(o) => (
            <>
              <div className="overflow-x-auto">
                <table className="tbl">
                  <thead>
                    <tr>
                      <th className="num">Rank</th>
                      <th>Combination</th>
                      <th className="num">Predicted profit on spend</th>
                      <th className="num">Orders per 1,000 clicks</th>
                      <th className="num">Stock cover</th>
                      <th className="num">Test budget</th>
                    </tr>
                  </thead>
                  <tbody>
                    {o.opportunities.map((r) => (
                      <tr key={r.rank}>
                        <td className="num font-semibold">{r.rank}</td>
                        <td>
                          <CampaignName name={`${channelDisplay(r.channel)} · ${r.sku_name} · ${r.audience}`} channel={r.channel} />
                        </td>
                        <td className="num font-semibold">{ratio(r.predicted_poas)}</td>
                        <td className="num">{num(r.predicted_conv_per_1k, 1)}</td>
                        <td className="num">{num(r.stock_days, 0)} days</td>
                        <td className="num">{inrDay(r.test_budget)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="mt-3 text-sm text-fog">On data it had not seen, the model explains {pct(o.model_r2_holdout)} of the variation (R² {o.model_r2_holdout.toFixed(2)}).</p>
            </>
          )}
        </LoadState>
      </Panel>
    </div>
  );
}
