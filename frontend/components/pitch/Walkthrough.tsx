"use client";

import { ChevronLeft, ChevronRight, LoaderCircle, Pause, Play, ShieldCheck, StickyNote, X } from "lucide-react";
import { useEffect, useState } from "react";
import { LineChart, Spark, Waterfall } from "@/components/charts";
import { useDecisionActions } from "@/components/ledger/useDecisionActions";
import { dateShort, inrDay, pct } from "@/lib/format";
import type { PitchData } from "@/lib/pitch/data";
import { usePitchPlayer } from "@/lib/pitch/player";
import { ASK_CHIPS, STEPS, STEP_COUNT, mapeTrend, summaryLines } from "@/lib/pitch/steps";
import type { Decision } from "@/lib/types";
import { useUiStore } from "@/lib/ui-store";
import { cn } from "@/lib/utils";
import { TINT } from "./Callouts";

/** The cause bars for the step "Why": the biggest two, with the rest folded into one so the bars still add up exactly. */
function whyFactors(d: PitchData) {
  const fs = [...(d.why.diagnosis?.root_cause.factors ?? [])].sort((a, b) => Math.abs(b.impact) - Math.abs(a.impact));
  if (fs.length <= 3) return fs.map((f) => ({ name: f.name, impact: f.impact }));
  const rest = fs.slice(2).reduce((a, f) => a + f.impact, 0);
  return [...fs.slice(0, 2).map((f) => ({ name: f.name, impact: f.impact })), { name: "Other factors", impact: rest }];
}

function WhyCharts({ d }: { d: PitchData }) {
  const dx = d.why.diagnosis;
  const c = d.price.causal;
  if (!dx && !c) return null;
  const post = c?.series.filter((s) => s.is_post) ?? [];
  return (
    <div className={cn("mt-2 grid gap-3", dx && c && "min-[1700px]:grid-cols-2")}>
      {dx && (
        <div data-pitch="waterfall" aria-label="Why: cost bars">
          <Waterfall factors={whyFactors(d)} netLabel="Net change in profit" summary={`Daily profit changed by ${inrDay(dx.root_cause.total_change)}. ${whyFactors(d).map((f) => `${f.name} ${inrDay(f.impact)}`).join(", ")}.`} />
        </div>
      )}
      {c && (
        <div data-pitch="causal-chart" className="hidden min-[1700px]:block">
          <LineChart
            x={c.series.map((s) => s.date)}
            xFormat={dateShort}
            series={[
              { id: "actual", label: "Actual conversion rate", color: "var(--synapse)", data: c.series.map((s) => s.actual) },
              { id: "cf", label: "Without the change", color: "var(--fog)", dashed: true, data: c.series.map((s) => s.counterfactual) },
            ]}
            bands={post.length ? [{ from: post[0].date, to: post[post.length - 1].date, label: "After the change" }] : []}
            format={(v) => (v === null ? "—" : pct(v, 2))}
            height={150}
            summary={`Site conversion rate for ${c.treated_sku}, actual against what a synthetic control predicts. Units ${c.units_change_pct < 0 ? "fell" : "rose"} ${pct(Math.abs(c.units_change_pct))} against the control.`}
          />
        </div>
      )}
    </div>
  );
}

function ApproveBlock({ decision }: { decision: Decision }) {
  const act = useDecisionActions(decision);
  const setApproved = usePitchPlayer((s) => s.setApproved);
  const [confirm, setConfirm] = useState(false);
  const blocked = decision.blocked;
  if (act.advisory) return <p className="mt-2 text-sm text-fog">Advisory mode never executes decisions, so there is nothing to approve here.</p>;
  if (blocked) return <p className="mt-2 text-sm text-fog">The top decision is blocked by a guardrail, so it can&apos;t be approved. Skip ahead.</p>;
  const go = () => {
    setConfirm(false);
    act.approveWith((r) => setApproved({ decisionId: decision.id, title: decision.title, calls: r.calls, noun: r.noun, outcome: r.outcome }));
  };
  return (
    <div className="relative mt-2">
      <button data-pitch="approve" onClick={() => setConfirm(true)} disabled={act.busy} className="inline-flex h-9 items-center gap-1.5 rounded-lg bg-primary px-3.5 text-sm font-semibold text-primary-foreground hover:bg-primary/85 disabled:opacity-60">
        {act.pending.approve ? <LoaderCircle className="size-4 animate-spin" aria-hidden /> : <ShieldCheck className="size-4" aria-hidden />}
        Approve top decision
      </button>
      {confirm && (
        <div role="alertdialog" aria-label="Confirm approval" className="float-layer absolute bottom-11 left-0 z-40 w-[min(340px,100%)] rounded-lg border border-line p-3 text-sm shadow-lg">
          <p>This executes the decision with mock ad-platform API calls. Reset the demo afterwards.</p>
          <div className="mt-2 flex gap-2">
            <button autoFocus onClick={go} className="inline-flex h-8 items-center rounded-lg bg-primary px-3 text-sm font-semibold text-primary-foreground hover:bg-primary/85">
              Approve
            </button>
            <button onClick={() => setConfirm(false)} className="inline-flex h-8 items-center rounded-lg border border-line px-3 text-sm font-semibold hover:bg-slate-2">
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

interface Props {
  data: PitchData;
  capRef: React.Ref<HTMLDivElement>;
  /** the pointer is over the caption: autoplay holds */
  onHold: (h: boolean) => void;
  /** the Ask bar was asked something (presenter mode opens its small Ask popover) */
  onAsk: () => void;
}

export default function Walkthrough({ data, capRef, onHold, onAsk }: Props) {
  const { index, playing, notes, approved, next, prev, goTo, exit, togglePlay, toggleNotes } = usePitchPlayer();
  const requestAsk = useUiStore((s) => s.requestAsk);
  // the card can unmount under the pointer (Esc, Exit): never leave autoplay held
  useEffect(() => () => onHold(false), [onHold]);
  const step = STEPS[index];
  const cap = step.caption(data);
  const tint = step.ref?.kind === "callout" ? TINT[step.ref.id] : "var(--synapse)";
  const topRec = data.derived.topRec;

  // The step after an approval says what was sent, and what came back, instead of repeating the old plan.
  let headline = cap.headline;
  let body = cap.body;
  if (step.id === "action" && approved) {
    const o = approved.outcome ?? (() => {
      const m = data.learning?.outcomes.find((x) => x.decision_id === approved.decisionId && x.actual !== null);
      return m ? { predicted: m.predicted, actual: m.actual as number } : null;
    })();
    headline = `Approved: ${approved.noun} sent.`;
    body = `${approved.title}. ${o ? `Predicted ${inrDay(o.predicted)}, measured ${inrDay(o.actual)} (simulated in this demo).` : "The outcome is measured after the change has run."} It is logged, and one click rolls it back.`;
  }
  const trend = mapeTrend(data);
  const lines = step.extra === "summary" ? summaryLines(data) : null;

  return (
    <div
      ref={capRef}
      data-keep
      data-pitch="caption"
      role="region"
      aria-label="Walkthrough"
      onPointerEnter={() => onHold(true)}
      onPointerLeave={() => onHold(false)}
      style={{ borderTop: `3px solid ${tint}` }}
      className="float-layer z-[25] w-full rounded-xl p-3 min-[1200px]:absolute min-[1200px]:z-[25] min-[1200px]:bottom-3 min-[1200px]:left-1/2 min-[1200px]:w-[min(620px,calc(100%-24px))] min-[1700px]:w-[min(880px,calc(100%-24px))] min-[1200px]:-translate-x-1/2 max-[1199px]:order-3"
    >
      <div className="flex items-center justify-between text-xs text-fog">
        <span data-pitch="step-counter" className="font-semibold">
          {index + 1} of {STEP_COUNT}
        </span>
        <button onClick={toggleNotes} aria-pressed={notes} title="Speaker notes (N)" className={cn("inline-flex items-center gap-1 rounded px-1.5 py-0.5 hover:text-bone", notes && "text-synapse-fg")}>
          <StickyNote className="size-3.5" aria-hidden />
          Notes
        </button>
      </div>
      <div aria-live="polite">
        <h2 data-pitch="caption-headline" className="mt-1 text-[20px] leading-tight font-extrabold">
          {headline}
        </h2>
        <p data-pitch="caption-body" className="narrative mt-1.5 text-[16px] leading-[1.6]">
          {body}
        </p>
      </div>
      {cap.fallback && <p className="sr-only">Showing the closest available fact: {cap.fallback}.</p>}

      {step.extra === "waterfall" && <WhyCharts d={data} />}
      {step.extra === "approve" && !approved && topRec && <ApproveBlock key={topRec.id} decision={topRec} />}
      {step.extra === "outcome" && trend.first !== null && (
        <div className="mt-2 flex items-center gap-3 text-sm text-fog">
          <Spark values={(data.learning?.accuracy_curve ?? []).map((p) => p.rolling_mape)} width={200} height={32} label="Rolling forecast error over the measured outcomes" />
          <span>Rolling forecast error</span>
        </div>
      )}
      {lines && (
        <div className="mt-2 grid gap-1">
          <ul className="grid gap-0.5 text-sm">
            {lines.map((l) => (
              <li key={l.id} className="flex gap-2">
                <span className="flex w-28 shrink-0 items-center gap-1.5 font-semibold">
                  <span className="size-2 rounded-full" style={{ background: TINT[l.id] }} aria-hidden />
                  {l.label}
                </span>
                <span>{l.line}</span>
              </li>
            ))}
          </ul>
          <div className="mt-1 flex flex-wrap gap-2">
            {ASK_CHIPS.map((q) => (
              <button
                key={q}
                data-pitch="ask-chip"
                onClick={() => {
                  requestAsk(q);
                  onAsk();
                }}
                className="rounded-full border border-line px-3 py-1 text-sm font-semibold hover:bg-slate-2"
              >
                {q}
              </button>
            ))}
          </div>
        </div>
      )}

      {notes && (
        <div data-pitch="notes" className="mt-2 rounded-lg border border-line bg-slate-2 p-2.5 text-sm">
          <div className="text-xs font-semibold text-fog">Speaker notes</div>
          {step.notes(data)}
        </div>
      )}

      <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-1" role="group" aria-label="Steps">
          {STEPS.map((s, i) => (
            <button
              key={s.id}
              onClick={() => goTo(i)}
              aria-label={`Go to step ${i + 1}: ${s.title}`}
              aria-current={i === index ? "step" : undefined}
              title={s.title}
              className="grid size-5 place-items-center rounded-full"
            >
              <span className={cn("block rounded-full transition-all", i === index ? "h-2.5 w-5 bg-primary" : i < index ? "size-2 bg-fog" : "size-2 bg-line")} />
            </button>
          ))}
        </div>
        <div className="flex items-center gap-1.5">
          <button onClick={prev} disabled={index === 0} className="inline-flex h-8 items-center gap-1 rounded-lg border border-line px-2.5 text-sm font-semibold hover:bg-slate-2 disabled:opacity-40">
            <ChevronLeft className="size-4" aria-hidden />
            Back
          </button>
          <button onClick={next} disabled={index === STEP_COUNT - 1} className="inline-flex h-8 items-center gap-1 rounded-lg bg-primary px-3 text-sm font-semibold text-primary-foreground hover:bg-primary/85 disabled:opacity-40">
            Next
            <ChevronRight className="size-4" aria-hidden />
          </button>
          <button onClick={togglePlay} aria-label={playing ? "Pause autoplay" : "Play autoplay"} title="Play / pause (P)" className="inline-flex h-8 items-center gap-1 rounded-lg border border-line px-2.5 text-sm font-semibold hover:bg-slate-2">
            {playing ? <Pause className="size-4" aria-hidden /> : <Play className="size-4" aria-hidden />}
            {playing ? "Pause" : "Play"}
          </button>
          <button onClick={exit} className="inline-flex h-8 items-center gap-1 rounded-lg border border-line px-2.5 text-sm font-semibold hover:bg-slate-2">
            <X className="size-4" aria-hidden />
            Exit
          </button>
        </div>
      </div>
    </div>
  );
}
