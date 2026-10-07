import { inr, inrDay, num, pct, ratio } from "@/lib/format";
import { key } from "@/lib/brain/layout";
import { channelDisplay, parseDecisionTitle } from "@/lib/names";
import type { BrainRegion } from "@/lib/types";
import type { CalloutId, PitchData } from "./data";
import type { LoopStepId, PitchRef } from "./links";

/** Which side panels stay at full strength during a step. Everything else dims to 0.45. */
export type Panel = "inputs" | "actions" | "loop";
/** Extra content the caption card draws under the text. */
export type StepExtra = "waterfall" | "approve" | "outcome" | "ask" | "summary" | null;

export interface Caption {
  headline: string;
  body: string;
  /** set when the step had to show a neighbouring fact because its own data is missing */
  fallback?: string;
}

export interface BrainPlan {
  region: BrainRegion | null;
  /** overlay key to centre the camera on (wins over region only when region is null) */
  focusKey?: string | null;
  /** overlay keys / neuron ids to ring */
  targets: string[];
  /** ring these one by one (step 2) */
  sequence?: string[];
}

export interface StepDef {
  id: string;
  /** short label for the step dots */
  title: string;
  /** what the hover/focus links light up (null: nothing in particular, the whole page stays lit) */
  ref: PitchRef | null;
  panels: Panel[];
  extra: StepExtra;
  /** ingest lines draw their particles */
  particles?: boolean;
  /** loop steps to light (the last step lights them in sequence instead) */
  loop: LoopStepId[];
  caption: (d: PitchData) => Caption;
  notes: (d: PitchData) => string;
  brain: (d: PitchData) => BrainPlan;
  /** autoplay seconds */
  seconds?: number;
}

export const DEFAULT_SECONDS = 9;
const cut = (s: string) => s.replace(/ Ads$/, "");
const ch = (id: string) => channelDisplay(id);

/** Alerting neurons, biggest effect on profit first. */
export function alertingNodes(d: PitchData) {
  const impact = new Map(d.anomalies.map((a) => [a.id, Math.abs(a.profit_impact)]));
  return d.nodes
    .filter((n) => n.is_alerting)
    .sort((a, b) => (impact.get(b.anomaly_id ?? "") ?? 0) - (impact.get(a.anomaly_id ?? "") ?? 0));
}

/** The stock-locked product: the engine's own "spend can't rise" case. */
export function lockedProduct(d: PitchData) {
  const guard = d.cfg?.detection.STOCK_COVER_RISK_DAYS ?? 7;
  const sku = d.nodes.find((n) => n.entity_type === "sku" && n.days_cover !== null && n.days_cover < guard);
  return sku ?? null;
}

/** The latest measured outcome (the learning loop's most recent check). */
export function latestOutcome(d: PitchData) {
  return [...(d.learning?.outcomes ?? [])].filter((o) => o.actual !== null).sort((a, b) => (a.measured_at < b.measured_at ? 1 : -1))[0] ?? null;
}

/** First and last rolling forecast error. */
export function mapeTrend(d: PitchData): { first: number | null; last: number | null } {
  const c = (d.learning?.accuracy_curve ?? []).filter((p) => p.rolling_mape !== null);
  return { first: c[0]?.rolling_mape ?? null, last: c[c.length - 1]?.rolling_mape ?? null };
}

const reasonWhy = (d: PitchData) => {
  const dx = d.why.diagnosis;
  const f = dx ? [...dx.root_cause.factors].sort((a, b) => Math.abs(b.impact) - Math.abs(a.impact))[0] : null;
  return { dx, f };
};

const priceProduct = (d: PitchData) => {
  const c = d.price.causal;
  if (!c) return null;
  return d.nodes.find((n) => n.entity_id === c.treated_sku)?.label ?? c.treated_sku;
};

export const STEPS: StepDef[] = [
  {
    id: "overview",
    title: "Overview",
    ref: null,
    panels: ["inputs", "actions", "loop"],
    extra: null,
    loop: [],
    caption: (d) => {
      const profit = d.kpis?.profit.value ?? null;
      const poas = d.kpis?.poas.value ?? null;
      return {
        headline: "Margin Mind runs your ad spend like a brain.",
        body: `Profit today is ${inr(profit)} a day, and every rupee of ads returns ${ratio(poas)} in profit. Every number on this screen is computed live.`,
      };
    },
    notes: (d) => `Open with the one number that matters: profit is ${inr(d.kpis?.profit.value ?? null)}/day. Say that the brain on screen is the engine itself, not a picture of it.`,
    brain: () => ({ region: null, targets: [] }),
  },
  {
    id: "perception",
    title: "Perception",
    ref: { kind: "callout", id: "perception" },
    panels: ["inputs", "loop"],
    extra: null,
    particles: true,
    loop: ["ingest"],
    caption: (d) => {
      const o = d.derived.overReport;
      const claims = o.length ? o.map((x) => `${cut(x.label)} claims ${pct(x.pct)} more than the store verified`).join(", ") : "Every platform matches the store";
      return {
        headline: "It reads every source, then checks them against the store.",
        body: `${d.derived.sourceCount} sources are live. ${claims}. Data trust is ${pct(d.derived.dataTrust)}.`,
        fallback: o.length ? undefined : "No platform over-reports right now",
      };
    },
    notes: (d) => {
      const m = d.derived.overReport[0];
      const row = m ? (d.q.recon.data ?? []).find((r) => r.channel === m.channel) : null;
      return row ? `Point at ${m.label}: the platform says ROAS ${ratio(row.roas_platform)}, the store says ${ratio(row.roas_true)}. Every decision uses the store's number.` : "Point at the source list: nine feeds, each with a trust score. Every decision uses the store-verified number.";
    },
    brain: (d) => ({ region: "ingest", targets: d.derived.overReport.map((o) => key.source(d.snapshot?.sources.find((s) => s.label === o.label)?.id ?? "")).filter((k) => k !== "s:") }),
  },
  {
    id: "reasoning",
    title: "Reasoning",
    ref: { kind: "callout", id: "reasoning" },
    panels: ["loop"],
    extra: null,
    loop: ["detect"],
    caption: (d) => {
      const x = d.derived;
      const top = x.topAnomaly ? `${x.topAnomalyLabel} at ${inrDay(x.topAnomaly.profit_impact)}` : null;
      const gain = x.topGain ? `, and ${x.topGainLabel} is rising` : "";
      return {
        headline: "It notices what changed, good and bad.",
        body: `${x.signals} signals this week. ${top ? `The biggest is ${top}${gain}.` : "None is moving profit."} ${x.found === null ? "" : `${x.found} of ${x.expected} planted problems found.`}`.trim(),
        fallback: top ? undefined : "No signal is moving profit right now",
      };
    },
    notes: (d) => `${d.derived.signals} signals, ranked by profit effect. ${d.derived.topAnomaly ? `The top one costs ${inrDay(Math.abs(d.derived.topAnomaly.profit_impact))}.` : ""} Watch the pulses visit the alerting neurons one by one.`,
    brain: (d) => {
      const seq = alertingNodes(d).slice(0, 4).map((n) => key.neuron(n.entity_id));
      return { region: "diagnose", targets: seq, sequence: seq };
    },
  },
  {
    id: "why",
    title: "Why",
    ref: { kind: "callout", id: "reasoning" },
    panels: ["loop"],
    extra: "waterfall",
    loop: ["diagnose"],
    seconds: 11,
    caption: (d) => {
      const { dx, f } = reasonWhy(d);
      const c = d.price.causal;
      const product = priceProduct(d);
      const causal = c && product ? ` The ${product} price rise cut units ${pct(Math.abs(c.units_change_pct))} versus what would have happened anyway.` : "";
      if (!dx || !f) {
        const a = d.derived.topAnomaly;
        return { headline: "And it explains why, to the rupee.", body: a ? `${d.derived.topAnomalyLabel} moved profit by ${inrDay(a.profit_impact)}.${causal}` : "No cause breakdown is available yet.", fallback: "No cost anomaly with a cause breakdown" };
      }
      return {
        headline: "And it explains why, to the rupee.",
        body: `${f.name} explains ${pct(f.pct)} of the ${inrDay(dx.root_cause.total_change)} change.${causal}`,
      };
    },
    notes: (d) => {
      const { dx, f } = reasonWhy(d);
      return dx && f ? `The bars add up exactly to ${inrDay(dx.root_cause.total_change)}. ${f.name} is the longest bar, so that is where to act.` : "Every factor is a bar; together they equal the change, to the rupee.";
    },
    brain: (d) => {
      const a = d.why.anomaly;
      const k = !a ? null : a.entity_type === "channel" ? key.cluster(a.entity_id) : key.neuron(a.entity_id);
      return { region: null, focusKey: k, targets: k ? [k] : [] };
    },
  },
  {
    id: "prediction",
    title: "Prediction",
    ref: { kind: "callout", id: "prediction" },
    panels: ["loop"],
    extra: null,
    loop: ["predict"],
    caption: (d) => {
      const o = d.derived.bestOpp;
      const x = d.derived;
      const grow = `${x.scaleCount} campaign${x.scaleCount === 1 ? "" : "s"} can grow profitably, ${x.cutCount} ${x.cutCount === 1 ? "is" : "are"} past saturation.`;
      return {
        headline: "It forecasts before spending a rupee.",
        body: o ? `Best untested idea: ${o.sku_name} on ${ch(o.channel)}, predicted POAS ${ratio(o.predicted_poas)}. ${grow} The model's R² is ${x.r2?.toFixed(2)} on held-out campaigns, so new ideas start as small tests.` : `${grow} No untested idea is scored yet.`,
        fallback: o ? undefined : "No untested idea scored",
      };
    },
    notes: (d) => {
      const o = d.derived.bestOpp;
      return o ? `${o.sku_name} on ${ch(o.channel)} has never run, yet the model scores it ${ratio(o.predicted_poas)}. It is honest about its limits: R² ${d.derived.r2?.toFixed(2)}, so it only risks ${inrDay(o.test_budget)}.` : "Untested ideas appear as dashed neurons; each is scored before any money moves.";
    },
    brain: (d) => {
      const g = d.snapshot?.ghosts[0];
      return { region: null, focusKey: g ? key.ghost(g.id) : null, targets: [...(d.snapshot?.ghosts ?? []).map((x) => key.ghost(x.id)), ...d.nodes.filter((n) => n.entity_type === "campaign" && n.headroom === "scale").map((n) => key.neuron(n.entity_id))] };
    },
  },
  {
    id: "decision",
    title: "Decision",
    ref: { kind: "callout", id: "decision" },
    panels: ["actions", "loop"],
    extra: null,
    loop: ["decide"],
    caption: (d) => {
      const r = d.derived.topRec;
      const sku = lockedProduct(d);
      const lock = sku ? ` ${sku.label} is locked: spend can't rise with ${num(sku.days_cover)} days of stock.` : "";
      const now = d.snapshot?.headline.current_profit ?? null;
      const planned = d.snapshot?.headline.planned_profit ?? null;
      if (!r) {
        return { headline: "It turns that into decisions with guardrails.", body: `No decision is waiting.${lock} Profit is ${inr(now)}/day.`, fallback: "No decision waiting" };
      }
      const t = parseDecisionTitle(r.title);
      return {
        headline: "It turns that into decisions with guardrails.",
        body: `Top decision: ${t.action}${t.subject ? ` ${t.subject}` : ""} at ${inrDay(r.expected_profit_delta)}, ${pct(r.confidence)} confident.${lock} Profit goes from ${inr(now)}/day to ${inr(planned)}/day if the plan is followed.`,
      };
    },
    notes: (d) => `Every decision carries a risk, a confidence and a guardrail check. ${d.derived.blocked} are blocked outright; ${d.derived.needsApproval} wait for a person.`,
    brain: (d) => ({ region: "decide", targets: d.nodes.filter((n) => n.stock_locked).map((n) => key.neuron(n.entity_id)) }),
  },
  {
    id: "action",
    title: "Action",
    ref: { kind: "callout", id: "decision" },
    panels: ["actions", "loop"],
    extra: "approve",
    loop: ["execute"],
    seconds: 11,
    caption: (d) => {
      const x = d.derived;
      const mode = (d.settings?.autonomy ?? "supervised").replace(/^./, (c) => c.toUpperCase());
      return {
        headline: "Small moves run automatically; big ones wait for you.",
        body: `Autonomy is ${mode}. ${x.needsApproval} decision${x.needsApproval === 1 ? "" : "s"} waiting for approval, ${x.auto} run${x.auto === 1 ? "s" : ""} automatically. Every action is logged and reversible.`,
      };
    },
    notes: (d) => `Mode is ${d.settings?.autonomy ?? "supervised"}. Say that nothing big moves without a person, and that a rollback is one click in the audit log.`,
    brain: () => ({ region: "decide", targets: [] }),
  },
  {
    id: "memory",
    title: "Memory",
    ref: { kind: "callout", id: "memory" },
    panels: ["loop"],
    extra: "outcome",
    loop: ["learn"],
    caption: (d) => {
      const { first, last } = mapeTrend(d);
      const o = latestOutcome(d);
      const x = d.derived;
      const trend = first !== null && last !== null ? `Forecast error went from ${pct(first)} to ${pct(last)}.` : `Forecast error is ${pct(x.mape)}.`;
      return {
        headline: "It checks what actually happened and recalibrates.",
        body: `${trend} Calibration is ×${x.factor?.toFixed(2) ?? "—"}, win-rate ${pct(x.winRate)}.${o ? ` Latest outcome: predicted ${inrDay(o.predicted)}, measured ${inrDay(o.actual)} (simulated in this demo).` : ""}`,
        fallback: o ? undefined : "No measured outcome yet",
      };
    },
    notes: (d) => `The outcomes are simulated in this demo and we say so. What matters: the engine compares its forecast to the result and corrects itself (factor ×${d.derived.factor?.toFixed(2) ?? "—"}).`,
    brain: () => ({ region: "learn", targets: [] }),
  },
  {
    id: "close",
    title: "Close",
    ref: null,
    panels: ["inputs", "actions", "loop"],
    extra: "summary",
    loop: [],
    caption: () => ({ headline: "Calm tool, smart engine.", body: "One engine, five stages, every number traceable. Ask it anything:" }),
    notes: () => "Finish by asking it a question live. The answer comes with the evidence, and the brain lights up what it used.",
    brain: () => ({ region: null, targets: [] }),
  },
];

export const STEP_COUNT = STEPS.length;

/** One line per stage, each with its key number (the close step). */
export function summaryLines(d: PitchData): { id: CalloutId; label: string; line: string }[] {
  const x = d.derived;
  return [
    { id: "perception", label: "Perception", line: `${x.sourceCount} sources, data trust ${pct(x.dataTrust)}` },
    { id: "reasoning", label: "Reasoning", line: `${x.signals} signals, ${x.found === null ? "—" : `${x.found} of ${x.expected}`} planted problems found` },
    { id: "prediction", label: "Prediction", line: `${x.ideas} ideas scored${x.bestOpp ? `, best ${ratio(x.bestOpp.predicted_poas)}` : ""}` },
    { id: "decision", label: "Decision", line: `${x.pending} decisions, up to ${inrDay(x.upside)}` },
    { id: "memory", label: "Memory", line: `forecast error ${pct(x.mape)}, ×${x.factor?.toFixed(2) ?? "—"}` },
  ];
}

export const ASK_CHIPS = ["Where should we scale?", "Is our ROAS real?"];
