"use client";

import { X } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import AnomalyName from "@/components/AnomalyName";
import { CurveChart, PairBars, Spark } from "@/components/charts";
import DecisionRow from "@/components/ledger/DecisionRow";
import Money from "@/components/Money";
import { channelDisplay, parseCampaignName } from "@/lib/names";
import { inrDay, pct, ratio } from "@/lib/format";
import { CALLOUTS } from "@/lib/pitch/links";
import type { CalloutId, PitchData } from "@/lib/pitch/data";
import { TINT } from "./Callouts";

const Fact = ({ label, value }: { label: string; value: React.ReactNode }) => (
  <div>
    <dt className="text-xs text-fog">{label}</dt>
    <dd className="text-base font-bold">{value}</dd>
  </div>
);
const H = ({ children }: { children: React.ReactNode }) => <h3 className="mt-4 mb-1.5 text-sm font-bold">{children}</h3>;

function Perception({ d }: { d: PitchData }) {
  const rows = d.q.recon.data ?? [];
  const x = d.derived;
  return (
    <>
      <dl className="grid grid-cols-3 gap-3">
        <Fact label="Sources" value={x.sourceCount} />
        <Fact label="Data trust" value={pct(x.dataTrust)} />
        <Fact label="Over-reporting" value={x.overReport.length ? x.overReport.map((o) => `${o.label.replace(/ Ads$/, "")} ${pct(o.pct)}`).join(", ") : "None"} />
      </dl>
      <H>Platform against store, return on ad spend</H>
      <PairBars aLabel="Platform says" bLabel="Verified" format={(v) => ratio(v)} items={rows.map((r) => ({ label: channelDisplay(r.channel), a: r.roas_platform, b: r.roas_true }))} summary="Platform-claimed against store-verified return on ad spend, per channel." />
    </>
  );
}

function Reasoning({ d }: { d: PitchData }) {
  const x = d.derived;
  const top = [...d.anomalies].sort((a, b) => Math.abs(b.profit_impact) - Math.abs(a.profit_impact)).slice(0, 3);
  return (
    <>
      <dl className="grid grid-cols-3 gap-3">
        <Fact label="Signals" value={x.signals} />
        <Fact label="Planted found" value={x.found === null ? "—" : `${x.found} of ${x.expected}`} />
        <Fact label="Rising" value={x.topGain ? inrDay(x.topGain.profit_impact) : "None"} />
      </dl>
      <H>The three biggest, per day</H>
      <ul className="grid gap-2 text-sm">
        {top.map((a) => (
          <li key={a.id} className="flex items-center justify-between gap-2">
            <Link href={`/diagnosis?anomaly=${a.id}`} className="min-w-0 truncate hover:underline">
              <AnomalyName a={a} />
            </Link>
            <Money v={a.profit_impact} />
          </li>
        ))}
      </ul>
    </>
  );
}

function Prediction({ d }: { d: PitchData }) {
  const x = d.derived;
  const curves = d.q.curves.data ?? [];
  const scale = d.nodes.filter((n) => n.headroom === "scale" && n.entity_type === "campaign").map((n) => curves.find((c) => c.campaign_id === n.entity_id)).filter((c): c is NonNullable<typeof c> => !!c).sort((a, b) => (b.marginal_poas ?? 0) - (a.marginal_poas ?? 0))[0];
  return (
    <>
      <dl className="grid grid-cols-3 gap-3">
        <Fact label="Ideas scored" value={x.ideas} />
        <Fact label="Can grow" value={x.scaleCount} />
        <Fact label="Model R²" value={x.r2?.toFixed(2) ?? "—"} />
      </dl>
      <H>The three best untested ideas</H>
      <ol className="grid gap-1.5 text-sm">
        {d.opps.slice(0, 3).map((o) => (
          <li key={o.label} className="flex items-baseline justify-between gap-2">
            <span>
              <span className="mr-1.5 text-fog">{o.rank}</span>
              <span className="font-semibold">{o.sku_name}</span> on {channelDisplay(o.channel)}, {o.audience}
            </span>
            <span className="font-bold">{ratio(o.predicted_poas)}</span>
          </li>
        ))}
      </ol>
      {scale && (
        <>
          <H>Room to grow: {(() => { const p = parseCampaignName(scale.name); return `${p.channelName} ${p.product}`; })()}</H>
          <CurveChart points={scale.points} current={scale.current_spend} optimal={scale.optimal_spend} saturation={scale.saturation_spend} height={170} summary={`Profit curve for ${scale.name}.`} />
        </>
      )}
    </>
  );
}

function Decision({ d }: { d: PitchData }) {
  const x = d.derived;
  const [open, setOpen] = useState<string | null>(null);
  const top = [...(d.q.recs.data?.pending ?? [])].sort((a, b) => b.priority - a.priority).slice(0, 3);
  return (
    <>
      <dl className="grid grid-cols-3 gap-3">
        <Fact label="Waiting" value={x.pending} />
        <Fact label="Upside" value={inrDay(x.upside)} />
        <Fact label="Blocked" value={x.blocked} />
      </dl>
      <H>The top three</H>
      <ul className="overflow-hidden rounded-lg border border-line">
        {top.map((r) => (
          <DecisionRow key={r.id} d={r} open={open === r.id} onToggle={() => setOpen((o) => (o === r.id ? null : r.id))} />
        ))}
      </ul>
    </>
  );
}

function Memory({ d }: { d: PitchData }) {
  const l = d.learning;
  const x = d.derived;
  const latest = l?.outcomes.at(0);
  const curve = l?.accuracy_curve ?? [];
  return (
    <>
      <dl className="grid grid-cols-3 gap-3">
        <Fact label="Forecast error" value={pct(x.mape)} />
        <Fact label="Calibration" value={x.factor === null ? "—" : `×${x.factor.toFixed(2)}`} />
        <Fact label="Win-rate" value={pct(x.winRate)} />
      </dl>
      <H>Rolling forecast error</H>
      <Spark values={curve.map((p) => p.rolling_mape)} width={300} height={40} label={`Rolling forecast error over ${curve.length} outcomes.`} />
      {latest && (
        <>
          <H>Latest outcome</H>
          <p className="text-sm">
            <span className="font-semibold">{latest.title}</span>: predicted {inrDay(latest.predicted)}, actual {inrDay(latest.actual)}. <span className="text-fog">Simulated in this demo.</span>
          </p>
        </>
      )}
    </>
  );
}

export default function DetailSheet({ id, data, onClose }: { id: CalloutId; data: PitchData; onClose: () => void }) {
  const c = CALLOUTS.find((x) => x.id === id)!;
  return (
    <aside data-keep aria-label={`${c.label} details`} className="float-layer absolute top-0 right-0 bottom-0 z-30 flex w-[min(360px,100%)] flex-col overflow-hidden" style={{ borderLeft: `3px solid ${TINT[id]}` }}>
      <div className="flex items-start justify-between gap-2 p-4 pb-2">
        <div>
          <h2 className="text-base font-bold">{c.label}</h2>
          <p className="text-sm text-fog">{c.does}</p>
        </div>
        <button onClick={onClose} aria-label="Close details" className="rounded p-1 text-fog hover:text-bone">
          <X className="size-4" />
        </button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-4 pb-4">
        {id === "perception" && <Perception d={data} />}
        {id === "reasoning" && <Reasoning d={data} />}
        {id === "prediction" && <Prediction d={data} />}
        {id === "decision" && <Decision d={data} />}
        {id === "memory" && <Memory d={data} />}
        <p className="mt-4 text-sm font-semibold">
          <Link href={c.full} className="text-synapse-fg underline-offset-2 hover:underline">
            Open full page
          </Link>
        </p>
      </div>
    </aside>
  );
}
