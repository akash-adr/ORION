"use client";

import { FlaskConical, Info, Sparkles } from "lucide-react";
import { useState } from "react";
import ChannelBadge from "@/components/ChannelBadge";
import DataGrid, { type Col } from "@/components/DataGrid";
import DecisionRow from "@/components/ledger/DecisionRow";
import PageHeader from "@/components/PageHeader";
import { LoadState, Panel } from "@/components/Panel";
import { StatusChip } from "@/components/chips";
import { inrDay, num, pct, ratio } from "@/lib/format";
import { useBrainSnapshot, useMetaConfig, useOpportunities, useRecommendations } from "@/lib/queries";
import type { Decision, Opportunity } from "@/lib/types";

type Launch = { sku_id: string; channel: string; audience: string };
const launchOf = (d: Decision) => (d.action as { launch?: Launch }).launch;

function Expanded({ o, guard }: { o: Opportunity; guard: number }) {
  const recs = useRecommendations().data;
  const [open, setOpen] = useState(false);
  const match = [...(recs?.pending ?? []), ...(recs?.history ?? [])].find((d) => {
    const l = d.action.type === "launch_test" ? launchOf(d) : undefined;
    return l && l.sku_id === o.sku_id && l.channel === o.channel && l.audience === o.audience;
  });
  return (
    <div className="grid gap-4">
      <p className="flex items-start gap-1.5 text-sm text-fog">
        <Info className="mt-0.5 size-3.5 shrink-0" aria-hidden />
        <span>
          Score {o.score.toFixed(2)} is the predicted profit on spend ({ratio(o.predicted_poas)}) times a stock factor of {o.stock_factor.toFixed(2)}×.{" "}
          {o.sku_name} has {num(o.stock_days)} days of stock, so it can serve the extra demand; a product under {guard} days would score zero and drop out.
        </span>
      </p>
      {match ? (
        <ul className="overflow-hidden rounded-lg border border-line">
          <DecisionRow d={match} open={open} onToggle={() => setOpen((v) => !v)} />
        </ul>
      ) : (
        <p className="text-sm text-fog">{o.launched ? "A test is already running for this combination." : "No launch decision exists for this combination yet. Run the loop now to look again."}</p>
      )}
    </div>
  );
}

export default function OpportunitiesPage() {
  const q = useOpportunities();
  const cfg = useMetaConfig().data;
  const snap = useBrainSnapshot().data;
  const guard = cfg?.detection.STOCK_COVER_RISK_DAYS ?? 7;
  const excluded = (snap?.nodes ?? []).filter((n) => n.entity_type === "sku" && n.days_cover !== null && n.days_cover < guard).map((n) => n.label);
  return (
    <div className="grid gap-5">
      <PageHeader title="Opportunities">Product, channel and audience combinations the engine has never run, ranked by predicted return. Open a row to launch a small test.</PageHeader>
      <Panel title="Untested combinations" note="Best first. Click a row for the decision">
        <LoadState q={q} what="the opportunities" height={360}>
          {(o) => {
            const cols: Col<Opportunity>[] = [
              { id: "rank", label: "Rank", align: "right", sort: (r) => r.rank, cell: (r) => <span className="font-semibold">{r.rank}</span> },
              { id: "sku", label: "Product", sort: (r) => r.sku_name, cell: (r) => <span className="font-semibold">{r.sku_name}</span> },
              { id: "ch", label: "Channel", sort: (r) => r.channel, cell: (r) => <ChannelBadge channel={r.channel} /> },
              { id: "aud", label: "Audience", sort: (r) => r.audience, cell: (r) => <span className="text-fog">{r.audience}</span> },
              { id: "conv", label: "Orders", sub: "per ₹1,000 of ads", hint: "Predicted orders for every ₹1,000 spent", align: "right", sort: (r) => r.predicted_conv_per_1k, cell: (r) => num(r.predicted_conv_per_1k, 1) },
              { id: "poas", label: "Predicted profit on spend", align: "right", sort: (r) => r.predicted_poas, cell: (r) => <span className="font-semibold">{ratio(r.predicted_poas)}</span> },
              { id: "stock", label: "Stock cover", align: "right", sort: (r) => r.stock_days, cell: (r) => `${num(r.stock_days)} days` },
              { id: "score", label: "Score", hint: "Predicted profit on spend times a stock factor", align: "right", sort: (r) => r.score, cell: (r) => r.score.toFixed(2) },
              { id: "budget", label: "Test budget", sub: "per day", align: "right", sort: (r) => r.test_budget, cell: (r) => inrDay(r.test_budget) },
              {
                id: "status",
                label: "Status",
                sort: (r) => (r.launched ? 1 : 0),
                cell: (r) => (r.launched ? <StatusChip tone="gain" icon={FlaskConical}>Test running</StatusChip> : <StatusChip tone="muted" icon={Sparkles}>Predicted</StatusChip>),
              },
            ];
            return <DataGrid rows={o.opportunities} cols={cols} rowKey={(r) => r.label} defaultSort={{ id: "rank", dir: "asc" }} expand={(r) => <Expanded o={r} guard={guard} />} ariaLabel="Untested combinations ranked by predicted return" maxHeight="none" />;
          }}
        </LoadState>
      </Panel>

      <div className="grid gap-5 min-[1200px]:grid-cols-2">
        <Panel title="How honest is the model?" note="A ranking signal, not a forecast">
          <LoadState q={q} what="the model" height={140}>
            {(o) => (
              <div className="grid gap-3">
                <p className="narrative">
                  Ridge regression on product rating, channel and audience (and how much is spent). Validated on whole campaigns held out (GroupKFold): R² = {o.model_r2_holdout.toFixed(2)}. A ranking signal, not a forecast, so new ideas start with a {cfg ? inrDay(cfg.optimizer.OPP_TEST_BUDGET) : "small"} test.
                </p>
                <div>
                  <div className="mb-1 flex justify-between text-sm">
                    <span className="text-fog">Share of variation explained on unseen campaigns</span>
                    <span className="font-bold">{pct(o.model_r2_holdout)}</span>
                  </div>
                  <div className="h-2.5 rounded-full bg-slate-2" role="img" aria-label={`R squared ${o.model_r2_holdout.toFixed(2)} out of 1`}>
                    <div className="h-full rounded-full" style={{ width: `${Math.max(1, o.model_r2_holdout * 100)}%`, background: "var(--synapse)" }} />
                  </div>
                  <div className="mt-1 flex justify-between text-xs text-fog">
                    <span>0 (no better than the average)</span>
                    <span>1 (perfect)</span>
                  </div>
                </div>
              </div>
            )}
          </LoadState>
        </Panel>
        <Panel title="Never shown" note="Because the stock isn't there">
          <p className="text-sm">
            {excluded.length ? (
              <>
                <span className="font-semibold">{excluded.join(", ")}</span> {excluded.length === 1 ? "has" : "have"} under {guard} days of stock, so {excluded.length === 1 ? "it is" : "they are"} left out of this list. The engine won&apos;t recommend buying demand it can&apos;t fulfil.
              </>
            ) : (
              <>Every product has at least {guard} days of stock, so none is left out.</>
            )}
          </p>
        </Panel>
      </div>
    </div>
  );
}
