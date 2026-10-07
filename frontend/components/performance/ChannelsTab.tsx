"use client";

import { TriangleAlert } from "lucide-react";
import ChannelBadge from "@/components/ChannelBadge";
import DataGrid, { type Col } from "@/components/DataGrid";
import Money from "@/components/Money";
import { LoadState, Panel } from "@/components/Panel";
import { PairBars } from "@/components/charts";
import { inrDay, num, pct, ratio } from "@/lib/format";
import { channelDisplay } from "@/lib/names";
import { useBrainSnapshot, useChannels, useReconciliation } from "@/lib/queries";
import type { ChannelRow, ReconciliationRow } from "@/lib/types";

type Row = ChannelRow & { rec?: ReconciliationRow };

export default function ChannelsTab({ onPick }: { onPick: (channel: string) => void }) {
  const ch = useChannels();
  const rec = useReconciliation();
  const warn = new Set((useBrainSnapshot().data?.sources ?? []).filter((x) => x.kind === "ad_platform" && x.status === "warn").map((x) => x.channel));
  return (
    <div className="grid gap-5">
      <Panel title="Return on ad spend by channel" note="Last 7 days. What platforms claim against what the store verified">
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
      <Panel title="Channels" note="Last 7 days, per day. Click a channel to see its campaigns">
        <LoadState q={ch} what="the channels" height={260}>
          {(rows) => {
            const byChannel = new Map((rec.data ?? []).map((r) => [r.channel, r]));
            const data: Row[] = rows.map((r) => ({ ...r, rec: byChannel.get(r.channel) }));
            const cols: Col<Row>[] = [
              { id: "channel", label: "Channel", sticky: true, sort: (r) => r.name, cell: (r) => <ChannelBadge channel={r.channel} /> },
              { id: "spend", label: "Ad spend", sub: "per day", align: "right", sort: (r) => r.spend, cell: (r) => inrDay(r.spend) },
              { id: "revenue", label: "Revenue", sub: "store-verified, per day", align: "right", sort: (r) => r.revenue, cell: (r) => inrDay(r.revenue) },
              { id: "profit", label: "Profit", sub: "per day", align: "right", sort: (r) => r.profit, cell: (r) => <Money v={r.profit} /> },
              { id: "poas", label: "Profit on spend", hint: "Gross margin per ₹1 of ads", align: "right", sort: (r) => r.poas, cell: (r) => ratio(r.poas) },
              { id: "roasT", label: "Verified ROAS", hint: "Store revenue per ₹1 of ads", align: "right", sort: (r) => r.roas_true, cell: (r) => <span className="font-semibold">{ratio(r.roas_true)}</span> },
              { id: "roasP", label: "Platform ROAS", hint: "Revenue the platform claims per ₹1 of ads", align: "right", sort: (r) => r.roas_platform, cell: (r) => ratio(r.roas_platform) },
              {
                id: "over",
                label: "Over-reporting",
                hint: "How many more conversions the platform claims than the store recorded",
                align: "right",
                sort: (r) => r.inflation_pct,
                cell: (r) =>
                  warn.has(r.channel) ? (
                    <span className="inline-flex items-center gap-1 font-semibold tone-risk">
                      <TriangleAlert className="size-3.5" aria-hidden />
                      {pct(r.inflation_pct)}
                    </span>
                  ) : (
                    <span className="text-fog">None</span>
                  ),
              },
              { id: "trust", label: "Trust", hint: "How closely this source matches the store", align: "right", sort: (r) => r.trust_score, cell: (r) => pct(r.trust_score) },
              { id: "conv", label: "Conversions", sub: "claimed / real orders", align: "right", sort: (r) => r.rec?.platform_conversions, cell: (r) => (r.rec ? `${num(r.rec.platform_conversions)} / ${num(r.rec.store_orders)}` : "—") },
            ];
            return <DataGrid rows={data} cols={cols} rowKey={(r) => r.channel} defaultSort={{ id: "spend", dir: "desc" }} onRowClick={(r) => onPick(r.channel)} ariaLabel="Channels, last 7 days" maxHeight="none" />;
          }}
        </LoadState>
      </Panel>
    </div>
  );
}
