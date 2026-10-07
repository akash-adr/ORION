"use client";

import { CircleCheck, PackageX, TriangleAlert, Warehouse } from "lucide-react";
import CampaignName from "@/components/CampaignName";
import DataGrid, { type Col } from "@/components/DataGrid";
import Money from "@/components/Money";
import { LoadState, Panel } from "@/components/Panel";
import { AlertChip, StatusChip } from "@/components/chips";
import { FunnelBars, StockBar } from "@/components/charts";
import { funnelStages } from "@/lib/diagnosis";
import { inrDay, num, pct, ratio } from "@/lib/format";
import { useBrainManifest, useBrainSnapshot, useCampaigns, useDiagnosis, useMetaConfig } from "@/lib/queries";
import type { BrainNode, CampaignRow } from "@/lib/types";

interface Row {
  node: BrainNode;
  category: string | null;
  margin: number | null;
  campaigns: CampaignRow[];
}

type Status = "risk" | "over" | "ok";

/** Price and units per day, from the product's diagnosis; the API only exposes them for products with an open diagnosis. */
function Fact({ anomalyId, field }: { anomalyId: string | null; field: "unit_price" | "units" }) {
  const d = useDiagnosis(anomalyId).data;
  const last = d?.evidence.daily.at(-1);
  const v = last?.[field];
  if (typeof v !== "number") return <span className="text-fog" title="The API exposes this only for products with an open diagnosis">—</span>;
  return <>{field === "unit_price" ? `₹${num(v)}` : num(v)}</>;
}

function Expanded({ r }: { r: Row }) {
  const d = useDiagnosis(r.node.anomaly_id).data;
  const stages = funnelStages(d?.root_cause.funnel ?? null);
  return (
    <div className="grid gap-4 min-[1200px]:grid-cols-2">
      <div>
        <h3 className="mb-2 text-sm font-bold">Shopper funnel</h3>
        {stages ? (
          <FunnelBars stages={stages} summary={`Shopper funnel for ${r.node.label}, from ${stages[0].label} to ${stages[stages.length - 1].label}.`} />
        ) : (
          <p className="text-sm text-fog">The API only exposes a funnel for products with an open diagnosis. {r.node.label} has none right now.</p>
        )}
      </div>
      <div>
        <h3 className="mb-2 text-sm font-bold">Campaigns promoting it</h3>
        {r.campaigns.length ? (
          <ul className="grid gap-1.5 text-sm">
            {r.campaigns.map((c) => (
              <li key={c.campaign_id} className="flex flex-wrap items-center justify-between gap-2">
                <CampaignName name={c.campaign_name} channel={c.channel} />
                <span className="text-fog">{inrDay(c.spend_7d)} spend, {ratio(c.poas_7d)} profit on spend</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-fog">No campaign is promoting this product.</p>
        )}
      </div>
    </div>
  );
}

export default function ProductsTab() {
  const snap = useBrainSnapshot();
  const manifest = useBrainManifest().data;
  const campaigns = useCampaigns().data;
  const cfg = useMetaConfig().data;
  const guard = cfg?.detection.STOCK_COVER_RISK_DAYS ?? 7;
  const over = cfg?.optimizer.OVERSTOCK_COVER_DAYS ?? 60;
  return (
    <Panel title="Products" note="Last 7 days for ads; stock is the latest. Click a row for the funnel and its campaigns">
      <LoadState q={snap} what="the products" height={320}>
        {(s) => {
          const neurons = new Map((manifest?.neurons ?? []).map((n) => [n.entity_id, n]));
          const rows: Row[] = s.nodes
            .filter((n) => n.entity_type === "sku")
            .map((n) => ({ node: n, category: neurons.get(n.entity_id)?.category ?? null, margin: neurons.get(n.entity_id)?.margin_pct ?? null, campaigns: (campaigns ?? []).filter((c) => c.sku_id === n.entity_id) }));
          const status = (r: Row): Status => ((r.node.days_cover ?? Infinity) < guard ? "risk" : (r.node.days_cover ?? 0) > over ? "over" : "ok");
          const cols: Col<Row>[] = [
            { id: "name", label: "Product", sticky: true, sort: (r) => r.node.label, cell: (r) => <span className="font-semibold">{r.node.label}</span> },
            { id: "cat", label: "Category", sort: (r) => r.category ?? "", cell: (r) => <span className="capitalize text-fog">{r.category ?? "—"}</span> },
            { id: "margin", label: "Margin", hint: "Share of the price left after product cost", align: "right", sort: (r) => r.margin, cell: (r) => pct(r.margin) },
            { id: "price", label: "Price", hint: "Latest unit price. Only available for products with an open diagnosis.", align: "right", cell: (r) => <Fact anomalyId={r.node.anomaly_id} field="unit_price" /> },
            { id: "units", label: "Units", sub: "per day", hint: "Latest daily units. Only available for products with an open diagnosis.", align: "right", cell: (r) => <Fact anomalyId={r.node.anomaly_id} field="units" /> },
            { id: "spend", label: "Ad spend", sub: "per day", align: "right", sort: (r) => r.node.spend_7d, cell: (r) => inrDay(r.node.spend_7d) },
            { id: "profit", label: "Profit", sub: "per day", align: "right", sort: (r) => r.node.profit_7d, cell: (r) => <Money v={r.node.profit_7d} /> },
            { id: "poas", label: "Profit on spend", sub: "of its ads", align: "right", sort: (r) => r.node.poas_7d, cell: (r) => ratio(r.node.poas_7d) },
            { id: "cover", label: "Days of cover", sort: (r) => r.node.days_cover, cell: (r) => <StockBar days={r.node.days_cover} guard={guard} locked={r.node.stock_locked} max={over} /> },
            {
              id: "status",
              label: "Stock status",
              sort: (r) => ({ risk: 0, ok: 1, over: 2 })[status(r)],
              cell: (r) => {
                const st = status(r);
                return st === "risk" ? (
                  <StatusChip tone="loss" icon={PackageX}>At risk</StatusChip>
                ) : st === "over" ? (
                  <StatusChip tone="risk" icon={Warehouse}>Overstocked</StatusChip>
                ) : (
                  <StatusChip tone="gain" icon={CircleCheck}>OK</StatusChip>
                );
              },
            },
            { id: "camps", label: "Campaigns", align: "right", sort: (r) => r.campaigns.length, cell: (r) => r.campaigns.length },
            { id: "alert", label: "Alert", sort: (r) => r.node.alert_kind ?? "", cell: (r) => <AlertChip kind={r.node.alert_kind} anomalyId={r.node.anomaly_id} severity={r.node.alert_severity} /> },
          ];
          return (
            <>
              <DataGrid rows={rows} cols={cols} rowKey={(r) => r.node.entity_id} defaultSort={{ id: "spend", dir: "desc" }} expand={(r) => <Expanded r={r} />} ariaLabel="Products" />
              <p className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-fog">
                <span className="inline-flex items-center gap-1">
                  <TriangleAlert className="size-3" aria-hidden />
                  At risk: under {guard} days of cover. Overstocked: over {over} days.
                </span>
                <span>Price, units, and paid against organic orders are not exposed per product by the API (price and units appear only for products with an open diagnosis).</span>
              </p>
            </>
          );
        }}
      </LoadState>
    </Panel>
  );
}
