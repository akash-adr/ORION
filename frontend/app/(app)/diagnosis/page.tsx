"use client";

import { ArrowDown, ArrowUp, TriangleAlert } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { FunnelBars, LineChart, Waterfall } from "@/components/charts";
import CampaignName from "@/components/CampaignName";
import PageHeader from "@/components/PageHeader";
import { EmptyState, LoadState, Panel } from "@/components/Panel";
import { campaignMoves, funnelStages } from "@/lib/diagnosis";
import { dateShort, inr, inrDay } from "@/lib/format";
import { anomalyEntity, kindDisplay } from "@/lib/names";
import { useAnomalies, useDiagnosis } from "@/lib/queries";
import { cn } from "@/lib/utils";

function Detail({ id }: { id: string }) {
  const q = useDiagnosis(id);
  return (
    <LoadState q={q} what="this diagnosis" height={420}>
      {(d) => {
        const rc = d.root_cause;
        const stages = funnelStages(rc.funnel);
        const moves = campaignMoves(rc.funnel);
        const causal = d.evidence.causal;
        const post = causal?.series.filter((s) => s.is_post) ?? [];
        return (
          <div className="grid gap-5">
            <Panel title={`${kindDisplay(d.anomaly.kind)}: ${anomalyEntity(d.anomaly.label)}`} note={`Profit effect ${inrDay(d.anomaly.profit_impact)}`}>
              <p className="narrative">{rc.narrative}</p>
            </Panel>
            <Panel title="What moved profit" note="Change in profit per day, by cause">
              <Waterfall
                factors={rc.factors.map((f) => ({ name: f.name, impact: f.impact }))}
                summary={`Profit changed by ${inrDay(rc.total_change)}. ${rc.factors.map((f) => `${f.name} ${inrDay(f.impact)}`).join(", ")}.`}
              />
            </Panel>
            {stages && (
              <Panel title="Where shoppers drop off" note="Recent days against the baseline">
                <FunnelBars stages={stages} summary={`Funnel from ${stages[0].label} to ${stages[stages.length - 1].label}.`} />
              </Panel>
            )}
            {moves.length > 0 && (
              <Panel title="Campaigns that moved" note="Profit per day, baseline to recent">
                <table className="tbl">
                  <thead>
                    <tr>
                      <th>Campaign</th>
                      <th className="num">Before</th>
                      <th className="num">Now</th>
                      <th>Main cause</th>
                    </tr>
                  </thead>
                  <tbody>
                    {moves.map((m) => (
                      <tr key={m.campaign_id}>
                        <td>
                          <CampaignName name={m.campaign_name} />
                        </td>
                        <td className="num">{inr(m.baseline_profit)}</td>
                        <td className="num font-semibold">{inr(m.recent_profit)}</td>
                        <td className="text-fog">{m.top_factor}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Panel>
            )}
            {causal && (
              <Panel title="What would have happened anyway" note={`Units ${causal.units_change_pct < 0 ? "fell" : "rose"} against a synthetic control`}>
                <LineChart
                  x={causal.series.map((s) => s.date)}
                  xFormat={(x) => dateShort(x)}
                  series={[
                    { id: "actual", label: "Actual", color: "var(--synapse)", data: causal.series.map((s) => s.actual) },
                    { id: "cf", label: "Without the change", color: "var(--fog)", dashed: true, data: causal.series.map((s) => s.counterfactual) },
                  ]}
                  bands={post.length ? [{ from: post[0].date, to: post[post.length - 1].date, label: "After the change" }] : []}
                  format={(v) => (v === null ? "—" : v.toFixed(0))}
                  summary={`${causal.description}. Effect ${inrDay(causal.effect_per_day)}; the 95% interval ${causal.ci_includes_zero ? "includes" : "excludes"} zero.`}
                />
                <p className="mt-2 text-sm text-fog">
                  {causal.description}. Net effect {inrDay(causal.effect_per_day)}, {inr(causal.total_effect)} over {causal.n_post} days (95% interval {inr(causal.ci_low)} to {inr(causal.ci_high)}).
                </p>
              </Panel>
            )}
          </div>
        );
      }}
    </LoadState>
  );
}

function Body() {
  const params = useSearchParams();
  const router = useRouter();
  const list = useAnomalies();
  const chosen = params.get("anomaly");
  return (
    <LoadState q={list} what="the anomalies" height={300}>
      {(all) => {
        const sorted = [...all].sort((a, b) => Math.abs(b.profit_impact) - Math.abs(a.profit_impact));
        const id = chosen && all.some((a) => a.id === chosen) ? chosen : (sorted[0]?.id ?? null);
        if (!id) return <EmptyState title="No anomalies right now" hint="Run the loop now to check again." />;
        return (
          <div className="grid gap-5 min-[1000px]:grid-cols-[320px_minmax(0,1fr)]">
            <nav aria-label="Anomalies" className="panel self-start p-2">
              <ul>
                {sorted.map((a) => {
                  const Icon = a.profit_impact < 0 ? ArrowDown : ArrowUp;
                  const none = Math.abs(a.profit_impact) < 0.5;
                  return (
                    <li key={a.id}>
                      <button
                        onClick={() => router.replace(`/diagnosis?anomaly=${a.id}`)}
                        aria-current={a.id === id ? "true" : undefined}
                        className={cn("w-full rounded-lg px-3 py-2.5 text-left hover:bg-slate-2", a.id === id && "bg-slate-2 shadow-[inset_2px_0_0_var(--synapse)]")}
                      >
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-sm font-semibold">{kindDisplay(a.kind)}</span>
                          {none ? (
                            <span className="text-sm text-fog">No profit effect</span>
                          ) : (
                            <span className={cn("inline-flex items-center gap-0.5 text-sm font-semibold", a.profit_impact < 0 ? "tone-loss" : "tone-gain")}>
                              <Icon className="size-3.5" aria-hidden />
                              {inr(Math.abs(a.profit_impact))}
                            </span>
                          )}
                        </div>
                        <div className="mt-0.5 flex items-center gap-1.5 text-sm text-fog">
                          {a.severity === "high" && <TriangleAlert className="size-3.5 shrink-0 tone-risk" aria-label="High severity" />}
                          <span className="truncate">{anomalyEntity(a.label)}</span>
                        </div>
                      </button>
                    </li>
                  );
                })}
              </ul>
            </nav>
            <Detail id={id} />
          </div>
        );
      }}
    </LoadState>
  );
}

export default function DiagnosisPage() {
  return (
    <div>
      <PageHeader title="Diagnosis">Pick an alert to see why it happened, in order of how much profit it moved.</PageHeader>
      <Suspense fallback={null}>
        <Body />
      </Suspense>
    </div>
  );
}
