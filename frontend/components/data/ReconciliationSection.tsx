"use client";

import { LoadState, Panel } from "@/components/Panel";
import { PairBars } from "@/components/charts";
import ChannelBadge from "@/components/ChannelBadge";
import { inr, num, pct, ratio } from "@/lib/format";
import { channelDisplay } from "@/lib/names";
import { useKpis, useReconciliation } from "@/lib/queries";

function joinNames(names: string[]): string {
  return names.length <= 1 ? (names[0] ?? "") : `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
}

export default function ReconciliationSection() {
  const q = useReconciliation();
  const kpis = useKpis(7).data;
  return (
    <Panel title="Platform claims against the store" note="Over the whole data range">
      <LoadState q={q} what="the reconciliation" height={300}>
        {(rows) => {
          const over = rows.filter((r) => r.inflation_pct >= 0.05).map((r) => channelDisplay(r.channel));
          return (
            <div className="grid gap-5">
              <PairBars
                aLabel="Platform says"
                bLabel="Verified in the store"
                format={(v) => ratio(v)}
                items={rows.map((r) => ({ label: channelDisplay(r.channel), a: r.roas_platform, b: r.roas_true, note: r.inflation_pct < 0.005 ? "Platform matches the store" : `Platform overstates by ${pct(r.inflation_pct)}` }))}
                summary={`Return on ad spend as claimed by each platform against verified in the store, for ${rows.length} channels.`}
              />
              <table className="tbl">
                <thead>
                  <tr>
                    <th>Channel</th>
                    <th className="num">Conversions claimed</th>
                    <th className="num">Store orders</th>
                    <th className="num">Revenue claimed</th>
                    <th className="num">Revenue verified</th>
                    <th className="num">Over-reporting</th>
                    <th className="num">Trust</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.channel}>
                      <td><ChannelBadge channel={r.channel} /></td>
                      <td className="num">{num(r.platform_conversions)}</td>
                      <td className="num">{num(r.store_orders)}</td>
                      <td className="num">{inr(r.platform_revenue)}</td>
                      <td className="num font-semibold">{inr(r.true_revenue)}</td>
                      <td className="num">{r.inflation_pct >= 0.005 ? <span className="font-semibold tone-risk">{pct(r.inflation_pct)}</span> : <span className="text-fog">None</span>}</td>
                      <td className="num">{pct(r.trust_score)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div className="flex flex-wrap items-baseline gap-x-8 gap-y-3">
                <div>
                  <div className="text-sm text-fog">Data trust, weighted by ad spend</div>
                  <div className="t-kpi">{pct(kpis?.data_trust ?? null)}</div>
                </div>
                <p className="narrative flex-1">
                  Every decision uses store-verified numbers.{" "}
                  {over.length ? `Optimising on platform numbers would over-fund ${joinNames(over)}.` : "Every platform currently matches the store."}
                </p>
              </div>
            </div>
          );
        }}
      </LoadState>
    </Panel>
  );
}
