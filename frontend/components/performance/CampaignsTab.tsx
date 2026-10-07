"use client";

import { Lock, TriangleAlert, X } from "lucide-react";
import CampaignName from "@/components/CampaignName";
import DataGrid, { type Col } from "@/components/DataGrid";
import Money from "@/components/Money";
import { LoadState, Panel } from "@/components/Panel";
import { AlertChip, HeadroomChip } from "@/components/chips";
import { CurveChart, LineChart } from "@/components/charts";
import { dateShort, inrDay, pct, ratio } from "@/lib/format";
import { channelDisplay } from "@/lib/names";
import { useBrainSnapshot, useCampaigns, useCurves, useDiagnosis, useMetaConfig } from "@/lib/queries";
import type { BrainNode, CampaignRow } from "@/lib/types";
import { cn } from "@/lib/utils";

interface Row extends CampaignRow {
  node?: BrainNode;
}

function Expanded({ r }: { r: Row }) {
  const curves = useCurves().data;
  const curve = curves?.find((c) => c.campaign_id === r.campaign_id);
  const anomalyId = r.node?.anomaly_id ?? null;
  const diag = useDiagnosis(anomalyId);
  const rows30 = diag.data?.evidence.daily.slice(-30);
  // only campaign-level evidence carries spend and profit; a product-level diagnosis has sessions and units instead
  const hist = rows30?.some((h) => typeof h.spend === "number" && typeof h.profit === "number") ? rows30 : undefined;
  const plannedPct = r.node?.planned_change_pct ?? null;
  const planned = plannedPct === null ? null : r.current_spend * (1 + plannedPct);
  return (
    <div className="grid gap-5 min-[1200px]:grid-cols-2">
      <div>
        <h3 className="mb-1 text-sm font-bold">Profit against daily spend</h3>
        {curve ? (
          <CurveChart points={curve.points} current={r.current_spend} planned={planned} optimal={r.optimal_spend} height={230} summary={`Profit curve for ${r.campaign_name}: now ${inrDay(r.current_spend)}, best spend ${inrDay(r.optimal_spend)}.`} />
        ) : (
          <p className="text-sm text-fog">No response curve for this campaign.</p>
        )}
      </div>
      <div>
        <h3 className="mb-1 text-sm font-bold">Last 30 days</h3>
        {hist?.length ? (
          <LineChart
            x={hist.map((h) => h.date)}
            xFormat={dateShort}
            series={[
              { id: "spend", label: "Ad spend", color: "var(--fog)", dashed: true, data: hist.map((h) => (typeof h.spend === "number" ? h.spend : null)) },
              { id: "profit", label: "Profit", color: "var(--synapse)", data: hist.map((h) => (typeof h.profit === "number" ? h.profit : null)) },
            ]}
            height={230}
            summary={`Daily spend and profit for ${r.campaign_name} over the last 30 days.`}
          />
        ) : (
          <p className="text-sm text-fog">The API has no daily history per campaign, so a trend is only shown for campaigns with an open diagnosis. The response curve on the left is what the engine uses.</p>
        )}
      </div>
    </div>
  );
}

export default function CampaignsTab({ channel, onClear }: { channel: string | null; onClear: () => void }) {
  const q = useCampaigns();
  const snap = useBrainSnapshot().data;
  const cfg = useMetaConfig().data;
  const guard = cfg?.detection.STOCK_COVER_RISK_DAYS ?? 7;
  return (
    <Panel title="Campaigns" note="Last 7 days unless stated. Click a row for its response curve">
      {channel && (
        <div className="mb-3 flex items-center gap-2 text-sm">
          <span className="text-fog">Showing</span>
          <button onClick={onClear} className="inline-flex items-center gap-1 rounded-full border border-line px-2.5 py-0.5 font-semibold hover:border-synapse" aria-label={`Clear the ${channelDisplay(channel)} filter`}>
            {channelDisplay(channel)}
            <X className="size-3" aria-hidden />
          </button>
        </div>
      )}
      <LoadState q={q} what="the campaigns" height={320}>
        {(all) => {
          const nodes = new Map((snap?.nodes ?? []).map((n) => [n.entity_id, n]));
          const rows: Row[] = all.filter((c) => !channel || c.channel === channel).map((c) => ({ ...c, node: nodes.get(c.campaign_id) }));
          const cols: Col<Row>[] = [
            { id: "name", label: "Campaign", sticky: true, sort: (r) => r.campaign_name, cell: (r) => <CampaignName name={r.campaign_name} channel={r.channel} className="flex-nowrap" /> },
            { id: "spend7", label: "Ad spend", sub: "7 days, per day", align: "right", sort: (r) => r.spend_7d, cell: (r) => inrDay(r.spend_7d) },
            { id: "spend28", label: "Ad spend", sub: "28 days, per day", align: "right", sort: (r) => r.spend_28d, cell: (r) => <span className="text-fog">{inrDay(r.spend_28d)}</span> },
            { id: "profit", label: "Profit", sub: "per day", align: "right", sort: (r) => r.profit_7d, cell: (r) => <Money v={r.profit_7d} /> },
            { id: "poas7", label: "Profit on spend", sub: "7 days", align: "right", hint: "Gross margin per ₹1 of ads", sort: (r) => r.poas_7d, cell: (r) => ratio(r.poas_7d) },
            { id: "poas28", label: "Profit on spend", sub: "28 days", align: "right", sort: (r) => r.poas_28d, cell: (r) => <span className="text-fog">{ratio(r.poas_28d)}</span> },
            {
              id: "marg",
              label: "Next ₹1 returns",
              sub: "marginal POAS",
              align: "right",
              hint: "Margin earned by the next ₹1 of spend. Above 1 scaling adds profit; below 1 every extra rupee loses money.",
              sort: (r) => r.marginal_poas,
              cell: (r) =>
                r.marginal_poas === null ? (
                  "—"
                ) : (
                  <span className={cn("inline-flex items-center gap-0.5 font-semibold", r.marginal_poas >= 1 ? "tone-gain" : "tone-loss")}>
                    {r.marginal_poas >= 1 ? "↑" : "↓"} ₹{r.marginal_poas.toFixed(2)}
                  </span>
                ),
            },
            { id: "head", label: "Headroom", sort: (r) => r.headroom ?? "", cell: (r) => <HeadroomChip h={r.headroom} /> },
            {
              id: "plan",
              label: "Planned change",
              sub: "current objective",
              align: "right",
              sort: (r) => r.node?.planned_change_pct,
              cell: (r) => (r.node?.planned_change_pct == null ? <span className="text-fog">None</span> : <span className={cn("font-semibold", r.node.planned_change_pct < 0 ? "tone-loss" : "tone-gain")}>{r.node.planned_change_pct < 0 ? "↓" : "↑"} {pct(Math.abs(r.node.planned_change_pct))}</span>),
            },
            { id: "ctr", label: "CTR", align: "right", hint: "Click-through rate", sort: (r) => r.ctr_7d, cell: (r) => pct(r.ctr_7d, 2) },
            { id: "cvr", label: "CVR", align: "right", hint: "Share of clicks that bought", sort: (r) => r.cvr_7d, cell: (r) => pct(r.cvr_7d, 2) },
            { id: "cpm", label: "CPM", align: "right", hint: "Cost per 1,000 impressions", sort: (r) => r.cpm_7d, cell: (r) => (r.cpm_7d == null ? "—" : `₹${r.cpm_7d.toFixed(0)}`) },
            { id: "freq", label: "Frequency", align: "right", hint: "Average times one person saw the ad", sort: (r) => r.freq_7d, cell: (r) => (r.freq_7d == null ? "—" : r.freq_7d.toFixed(1)) },
            {
              id: "cover",
              label: "Stock cover",
              sub: "of its product",
              align: "right",
              sort: (r) => r.days_cover,
              cell: (r) => (
                <span className={cn("inline-flex items-center gap-1", r.days_cover < guard && "font-semibold tone-loss")}>
                  {r.days_cover < guard && <TriangleAlert className="size-3.5" aria-hidden />}
                  {r.headroom === "locked" && <Lock className="size-3.5" aria-label="Spend locked" />}
                  {r.days_cover.toFixed(1)} days
                </span>
              ),
            },
            { id: "alert", label: "Alert", sort: (r) => r.node?.alert_kind ?? "", cell: (r) => <AlertChip kind={r.node?.alert_kind ?? null} anomalyId={r.node?.anomaly_id ?? null} severity={r.node?.alert_severity} /> },
          ];
          return <DataGrid rows={rows} cols={cols} rowKey={(r) => r.campaign_id} defaultSort={{ id: "spend7", dir: "desc" }} expand={(r) => <Expanded r={r} />} ariaLabel="Campaigns" empty={<p className="text-sm text-fog">No campaigns for this channel.</p>} />;
        }}
      </LoadState>
      <p className="mt-2 text-xs text-fog">Money is per day. Profit on spend is gross margin per ₹1 of ads.</p>
    </Panel>
  );
}
