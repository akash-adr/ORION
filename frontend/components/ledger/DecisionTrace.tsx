"use client";

import { CircleCheck, CircleX, Info, Lock, TriangleAlert } from "lucide-react";
import Link from "next/link";
import { ConfidenceMeter, CurveChart, Waterfall } from "@/components/charts";
import CampaignName from "@/components/CampaignName";
import { BOUND_LABEL, boundReasons, changePct, guardrailChecks, outcomeFor, rawImpact } from "@/lib/decision";
import { inr, inrDay, num, pct, ratio } from "@/lib/format";
import { actionTypeDisplay, anomalyEntity, channelDisplay, kindDisplay, zMeaning } from "@/lib/names";
import { useAnomalies, useCampaigns, useCurves, useDiagnosis, useLearning, useMetaConfig } from "@/lib/queries";
import type { Anomaly, Decision } from "@/lib/types";
import { cn } from "@/lib/utils";

function Step({ n, title, children }: { n: number; title: string; children: React.ReactNode }) {
  return (
    <li className="group/step relative grid grid-cols-[28px_minmax(0,1fr)] gap-x-3 pb-5 last:pb-0">
      <span className="absolute top-7 bottom-0 left-[13px] w-px bg-line group-last/step:hidden" aria-hidden />
      <span className="z-10 grid size-7 place-items-center rounded-full border border-line bg-slate-2 text-sm font-bold">{n}</span>
      <div className="min-w-0 pt-0.5">
        <h4 className="text-sm font-bold">{title}</h4>
        <div className="mt-1.5 text-sm">{children}</div>
      </div>
    </li>
  );
}

const Chip = ({ children, className }: { children: React.ReactNode; className?: string }) => (
  <span className={cn("inline-flex items-center gap-1 rounded-full border border-line px-2 py-px text-xs", className)}>{children}</span>
);

function SignalStep({ d, anomaly }: { d: Decision; anomaly: Anomaly | undefined }) {
  if (anomaly) {
    const dir = anomaly.change_pct < 0 ? "fell" : "rose";
    return (
      <div className="grid gap-1.5">
        <div>
          <span className="font-semibold">{kindDisplay(anomaly.kind)}</span>, {anomalyEntity(anomaly.label)}: {anomaly.metric.replace(/_/g, " ")} {dir} {pct(Math.abs(anomaly.change_pct), 0)} against the baseline.
        </div>
        <div className="text-fog">
          {anomaly.z !== 0 ? `Statistic z = ${anomaly.z.toFixed(1).replace("-", "−")}, ${zMeaning(anomaly.z)}.` : `Found by comparing sources, not by a statistical test.`} Severity {anomaly.severity}.
        </div>
        <Link href={`/diagnosis?anomaly=${anomaly.id}`} className="w-fit font-semibold text-synapse-fg underline-offset-2 hover:underline">
          Open diagnosis
        </Link>
      </div>
    );
  }
  const type = d.action.type;
  return <span className="text-fog">{type === "launch_test" ? "From the opportunity model: an untested combination with a high predicted return." : "From the optimizer: a budget plan for the current objective, not a single anomaly."}</span>;
}

function CauseStep({ d }: { d: Decision }) {
  const diag = useDiagnosis(d.anomaly_id);
  const rc = diag.data?.root_cause;
  return (
    <div className="grid gap-3">
      <p className="narrative">{d.cause}</p>
      {d.anomaly_id && diag.isPending && <div className="h-24 animate-pulse rounded-lg bg-slate-2" />}
      {rc && rc.factors.length > 0 && (
        <div className="rounded-lg border border-line p-3">
          <div className="mb-1 text-xs text-fog">What moved profit, per day</div>
          <Waterfall factors={rc.factors.map((f) => ({ name: f.name, impact: f.impact }))} summary={`Profit changed by ${inrDay(rc.total_change)}.`} />
        </div>
      )}
    </div>
  );
}

function PlanStep({ d }: { d: Decision }) {
  const cfg = useMetaConfig().data;
  const campaigns = useCampaigns().data ?? [];
  const curves = useCurves().data ?? [];
  const a = d.action as Record<string, unknown> & Decision["action"];
  const byId = new Map(campaigns.map((c) => [c.campaign_id, c]));
  const launch = a.launch as { sku_id: string; channel: string; audience: string; daily_budget: number; predicted_poas: number; predicted_conv_per_1k: number } | undefined;
  const creative = a.creative_refresh as { current_creative: string; suggested: string } | undefined;
  const price = a.price_review as { price_from: number; price_to: number; causal: { effect_per_day: number; ci_low: number; ci_high: number; units_change_pct: number } } | undefined;
  const fix = a.settings as { channel: string; conversion_source: string; reason: string } | undefined;
  const shown = d.action.changes.slice(0, 3);
  return (
    <div className="grid gap-3">
      {d.action.changes.length > 0 && (
        <div className="overflow-x-auto">
          <table className="tbl">
            <thead>
              <tr>
                <th>Campaign</th>
                <th className="num">Now</th>
                <th className="num">Planned</th>
                <th className="num">Change</th>
                <th>Why it stopped there</th>
              </tr>
            </thead>
            <tbody>
              {d.action.changes.map((c) => {
                const p = changePct(c);
                const chips = boundReasons(c, cfg, byId.get(c.campaign_id));
                return (
                  <tr key={c.campaign_id}>
                    <td>
                      <CampaignName name={c.name} channel={c.channel} />
                    </td>
                    <td className="num">{inrDay(c.from_budget)}</td>
                    <td className="num font-semibold">{inrDay(c.to_budget)}</td>
                    <td className={cn("num font-semibold", p < 0 ? "tone-loss" : "tone-gain")}>{p < 0 ? "↓" : "↑"} {pct(Math.abs(p))}</td>
                    <td>
                      <span className="flex flex-wrap gap-1">
                        {chips.map((r) => (
                          <Chip key={r}>
                            {r === "stock" && <Lock className="size-3" aria-hidden />}
                            {BOUND_LABEL[r]}
                          </Chip>
                        ))}
                        {!chips.length && <span className="text-fog">Within limits</span>}
                                              </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {launch && (
        <dl className="grid grid-cols-2 gap-x-6 gap-y-2 min-[700px]:grid-cols-4">
          <div><dt className="text-fog">Product</dt><dd className="font-semibold">{byId.size ? [...byId.values()].find((c) => c.sku_id === launch.sku_id)?.campaign_name.split("·")[1]?.trim() ?? launch.sku_id : launch.sku_id}</dd></div>
          <div><dt className="text-fog">Channel and audience</dt><dd className="font-semibold">{channelDisplay(launch.channel)}, {launch.audience}</dd></div>
          <div><dt className="text-fog">Test budget</dt><dd className="font-semibold">{inrDay(launch.daily_budget)}</dd></div>
          <div><dt className="text-fog">Predicted profit on spend</dt><dd className="font-semibold">{ratio(launch.predicted_poas)}, {num(launch.predicted_conv_per_1k, 1)} orders per ₹1,000 of ad spend</dd></div>
        </dl>
      )}
      {creative && (
        <p>
          Swap the tired creative <span className="font-semibold">{creative.current_creative}</span> for a <span className="font-semibold">{creative.suggested}</span>, and trim the budget while the audience recovers.
        </p>
      )}
      {price && (
        <p>
          Review the price move from <span className="font-semibold">{inr(price.price_from)}</span> to <span className="font-semibold">{inr(price.price_to)}</span>. Units are {pct(Math.abs(price.causal.units_change_pct))} {price.causal.units_change_pct < 0 ? "lower" : "higher"} than they would have been; the margin effect is {inrDay(price.causal.effect_per_day)} with a 95% range of {inr(price.causal.ci_low)} to {inr(price.causal.ci_high)} over the period.
        </p>
      )}
      {fix && (
        <p>
          Optimise {channelDisplay(fix.channel)} on <span className="font-semibold">{fix.conversion_source.replace(/_/g, " ")}</span> conversions. {fix.reason.charAt(0).toUpperCase() + fix.reason.slice(1)}.
        </p>
      )}
      {shown.length > 0 && (
        <div className="grid gap-3 min-[1000px]:grid-cols-2">
          {shown.map((c) => {
            const cv = curves.find((x) => x.campaign_id === c.campaign_id);
            if (!cv) return null;
            return (
              <div key={c.campaign_id} className="rounded-lg border border-line p-3">
                <div className="mb-1 text-xs text-fog">{c.name.split("·").slice(1).join(", ").trim()}: profit against daily spend</div>
                <CurveChart points={cv.points} current={c.from_budget} planned={c.to_budget} optimal={cv.optimal_spend} height={190} summary={`Profit curve for ${c.name}: now ${inrDay(c.from_budget)}, planned ${inrDay(c.to_budget)}.`} />
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

const ICON = { pass: CircleCheck, fail: CircleX, exception: TriangleAlert, info: Info };
const TONE = { pass: "tone-gain", fail: "tone-loss", exception: "tone-risk", info: "text-fog" };
const WORD = { pass: "Passed", fail: "Not met", exception: "Exception", info: "For your approval" };

function GuardrailsStep({ d }: { d: Decision }) {
  const cfg = useMetaConfig().data;
  const campaigns = useCampaigns().data;
  if (!cfg || !campaigns) return <div className="h-16 animate-pulse rounded-lg bg-slate-2" />;
  return (
    <ul className="grid gap-2">
      {guardrailChecks(d, cfg, campaigns).map((c) => {
        const Icon = ICON[c.state];
        return (
          <li key={c.label} className="flex items-start gap-2">
            <Icon className={cn("mt-0.5 size-4 shrink-0", TONE[c.state])} aria-label={WORD[c.state]} />
            <div>
              <span className="font-semibold">{c.label}</span>
              {c.detail && <div className="text-fog">{c.detail}</div>}
            </div>
          </li>
        );
      })}
    </ul>
  );
}

function ConfidenceStep({ d, anomaly }: { d: Decision; anomaly: Anomaly | undefined }) {
  const cfg = useMetaConfig().data;
  const curves = useCurves().data ?? [];
  const learning = useLearning().data;
  const unc = d.action.changes.map((c) => curves.find((x) => x.campaign_id === c.campaign_id)?.uncertainty).filter((v): v is number => v !== undefined);
  const meanUnc = unc.length ? unc.reduce((a, b) => a + b, 0) / unc.length : null;
  return (
    <div className="grid gap-2">
      <ConfidenceMeter value={d.confidence} min={cfg?.guardrails.CONFIDENCE_MIN ?? 0.45} max={cfg?.guardrails.CONFIDENCE_MAX ?? 0.95} />
      <ul className="grid gap-1 text-fog">
        <li>
          <span className="text-bone">Signal strength:</span> {anomaly && anomaly.z !== 0 ? `|z| = ${Math.abs(anomaly.z).toFixed(1)}, ${zMeaning(anomaly.z)}` : "no statistical signal"}
        </li>
        <li>
          <span className="text-bone">Curve uncertainty:</span> {meanUnc === null ? "no budget curve involved" : `${pct(meanUnc)} on average across the changed campaigns`}
        </li>
        <li>
          <span className="text-bone">Past forecast error:</span> {learning?.calibration.mape == null ? "not enough measured outcomes yet" : `${pct(learning.calibration.mape)} over the last ${learning.calibration.n} outcomes`}
        </li>
      </ul>
      <p className="flex items-center gap-1.5 text-xs text-fog">
        <Info className="size-3.5" aria-hidden />
        Confidence is computed, not typed.
      </p>
    </div>
  );
}

function ImpactStep({ d }: { d: Decision }) {
  const raw = rawImpact(d);
  return (
    <div className="grid gap-1">
      <div className="flex flex-wrap items-baseline gap-x-6 gap-y-1">
        <span><span className="text-fog">Model output</span> <span className="font-semibold">{inrDay(raw)}</span></span>
        <span><span className="text-fog">Calibrated</span> <span className="font-semibold tone-gain">{inrDay(d.expected_profit_delta)}</span></span>
        <span><span className="text-fog">Factor</span> <span className="font-semibold">×{d.calibration_factor.toFixed(2)}</span></span>
      </div>
      <p className="text-fog">The model output is scaled by how accurate past predictions turned out to be.</p>
    </div>
  );
}

function OutcomeStep({ d }: { d: Decision }) {
  const learning = useLearning().data;
  const o = outcomeFor(d.id, learning?.outcomes);
  if (d.status === "pending") return <span className="text-fog">Measured after approval.</span>;
  if (d.status === "rejected") return <span className="text-fog">Rejected. Nothing was sent to the ad platforms.</span>;
  if (!o) return <span className="text-fog">{d.status === "rolled_back" ? "Rolled back; budgets are restored." : "No outcome measured yet."}</span>;
  return (
    <div className="grid gap-1">
      <div>
        Predicted <span className="font-semibold">{inrDay(o.predicted)}</span>, actual <span className="font-semibold">{inrDay(o.actual)}</span>
        {o.error_pct !== null && <>, {pct(Math.abs(o.error_pct))} {o.error_pct >= 0 ? "above" : "below"} the prediction</>}.
      </div>
      <div className="flex flex-wrap items-center gap-2 text-fog">
        <Chip>Simulated</Chip>
        <span className="narrative text-fog">{o.note}</span>
      </div>
      {d.status === "rolled_back" && <div className="text-fog">Later rolled back; budgets are restored.</div>}
    </div>
  );
}

/** The seven-step reasoning behind one decision: a real sequence, so the steps are numbered. */
export default function DecisionTrace({ d }: { d: Decision }) {
  const anomalies = useAnomalies().data;
  const anomaly = d.anomaly_id ? anomalies?.find((a) => a.id === d.anomaly_id) : undefined;
  return (
    <ol className="grid" aria-label={`Decision trace for ${actionTypeDisplay(d.action.type)}`}>
      <Step n={1} title="Signal"><SignalStep d={d} anomaly={anomaly} /></Step>
      <Step n={2} title="Cause"><CauseStep d={d} /></Step>
      <Step n={3} title="Plan"><PlanStep d={d} /></Step>
      <Step n={4} title="Guardrails"><GuardrailsStep d={d} /></Step>
      <Step n={5} title="Confidence"><ConfidenceStep d={d} anomaly={anomaly} /></Step>
      <Step n={6} title="Expected impact"><ImpactStep d={d} /></Step>
      <Step n={7} title="Outcome"><OutcomeStep d={d} /></Step>
    </ol>
  );
}
