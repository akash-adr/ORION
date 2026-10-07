"use client";

import { Lock } from "lucide-react";
import { PairBars, StockBar } from "@/components/charts";
import CampaignName from "@/components/CampaignName";
import PageHeader from "@/components/PageHeader";
import { LoadState, Panel } from "@/components/Panel";
import { inrDay, pct, ratio, tone } from "@/lib/format";
import { channelDisplay } from "@/lib/names";
import { useCampaigns, useChannels, useMetaConfig } from "@/lib/queries";
import type { Headroom } from "@/lib/types";

const HEADROOM: Record<NonNullable<Headroom>, string> = { scale: "Room to scale", hold: "Hold", cut: "Past saturation", locked: "Locked by stock guard" };

export default function PerformancePage() {
  const ch = useChannels();
  const cmp = useCampaigns();
  const cfg = useMetaConfig();
  const guard = cfg.data?.detection.STOCK_COVER_RISK_DAYS ?? 7;
  return (
    <div className="grid gap-5">
      <PageHeader title="Performance">Every channel and campaign over the last 7 days, per day.</PageHeader>
      <Panel title="Return on ad spend by channel" note="What platforms claim against what the store verified">
        <LoadState q={ch} what="the channels" height={240}>
          {(rows) => (
            <PairBars
              aLabel="Platform says"
              bLabel="Verified in the store"
              format={(v) => ratio(v)}
              items={rows.map((r) => ({ label: channelDisplay(r.channel), a: r.roas_platform ?? 0, b: r.roas_true ?? 0, note: r.inflation_pct < 0.005 ? "Platform matches the store" : `Platform overstates by ${pct(r.inflation_pct)}` }))}
              summary={`Platform versus verified return on ad spend for ${rows.length} channels.`}
            />
          )}
        </LoadState>
      </Panel>
      <Panel title="Campaigns" note="Last 7 days, per day">
        <LoadState q={cmp} what="the campaigns" height={300}>
          {(rows) => (
            <div className="overflow-x-auto">
              <table className="tbl">
                <thead>
                  <tr>
                    <th>Campaign</th>
                    <th className="num">Spend</th>
                    <th className="num">Profit</th>
                    <th className="num">Profit on spend</th>
                    <th>Headroom</th>
                    <th>Stock</th>
                  </tr>
                </thead>
                <tbody>
                  {[...rows].sort((a, b) => b.spend_7d - a.spend_7d).map((c) => (
                    <tr key={c.campaign_id}>
                      <td>
                        <CampaignName name={c.campaign_name} channel={c.channel} />
                      </td>
                      <td className="num">{inrDay(c.spend_7d)}</td>
                      <td className={`num font-semibold ${tone(c.profit_7d) === "loss" ? "tone-loss" : "tone-gain"}`}>{inrDay(c.profit_7d)}</td>
                      <td className="num">{ratio(c.poas_7d)}</td>
                      <td>
                        <span className="inline-flex items-center gap-1">
                          {c.headroom === "locked" && <Lock className="size-3.5" aria-hidden />}
                          {c.headroom ? HEADROOM[c.headroom] : "—"}
                        </span>
                      </td>
                      <td className="min-w-[180px]">
                        <StockBar days={c.days_cover} guard={guard} locked={c.headroom === "locked"} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </LoadState>
      </Panel>
    </div>
  );
}
