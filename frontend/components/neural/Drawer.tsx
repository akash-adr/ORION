"use client";

import { X } from "lucide-react";
import Link from "next/link";
import CampaignName from "@/components/CampaignName";
import { CurveChart, Waterfall } from "@/components/charts";
import { HeadroomChip, StatusChip } from "@/components/chips";
import DecisionRow from "@/components/ledger/DecisionRow";
import Money from "@/components/Money";
import { LoadState } from "@/components/Panel";
import { findLaunchDecision } from "@/lib/launch";
import { inr, inrDay, num, pct, ratio } from "@/lib/format";
import type { MapPick } from "@/lib/brain/types";
import { kindDisplay } from "@/lib/names";
import { useBrainSnapshot, useCurves, useDiagnosis, useOpportunities, useRecommendations } from "@/lib/queries";
import type { BrainNode, Decision } from "@/lib/types";
import { useState } from "react";

function Decisions({ list }: { list: Decision[] }) {
  const [open, setOpen] = useState<string | null>(null);
  if (!list.length) return <p className="text-sm text-fog">No decision involves this right now.</p>;
  return (
    <ul className="overflow-hidden rounded-lg border border-line">
      {list.map((d) => (
        <DecisionRow key={d.id} d={d} open={open === d.id} onToggle={() => setOpen((o) => (o === d.id ? null : d.id))} />
      ))}
    </ul>
  );
}

const Section = ({ title, children }: { title: string; children: React.ReactNode }) => (
  <section className="mt-5">
    <h3 className="mb-2 text-sm font-bold">{title}</h3>
    {children}
  </section>
);

function NeuronBody({ n }: { n: BrainNode }) {
  const diag = useDiagnosis(n.anomaly_id);
  const curves = useCurves().data;
  const recs = useRecommendations();
  const curve = n.entity_type === "campaign" ? curves?.find((c) => c.campaign_id === n.entity_id) : undefined;
  const planned = n.planned_change_pct === null ? null : n.current_spend * (1 + n.planned_change_pct);
  return (
    <>
      <div className="flex flex-wrap items-center gap-2">
        {n.entity_type === "campaign" ? <CampaignName name={n.label} channel={n.channel} /> : <span className="text-base font-bold">{n.label}</span>}
        <HeadroomChip h={n.headroom} />
      </div>
      <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
        <div><dt className="text-fog">Ad spend</dt><dd className="font-semibold">{inrDay(n.spend_7d)}</dd></div>
        <div><dt className="text-fog">Profit</dt><dd><Money v={n.profit_7d} /></dd></div>
        <div><dt className="text-fog">Profit on spend</dt><dd className="font-semibold">{ratio(n.poas_7d)}</dd></div>
        <div><dt className="text-fog">Stock cover</dt><dd className="font-semibold">{n.days_cover === null ? "—" : `${num(n.days_cover, 1)} days`}</dd></div>
      </dl>
      <Section title="Why">
        <p className="narrative">{n.why ?? "Nothing unusual here. The engine is watching it and has no signal."}</p>
      </Section>
      {n.is_alerting && n.anomaly_id && (
        <Section title={`What moved profit (${kindDisplay(n.alert_kind)})`}>
          <LoadState q={diag} what="the cause" height={140}>
            {(d) => (
              <>
                <Waterfall factors={d.root_cause.factors.map((f) => ({ name: f.name, impact: f.impact }))} summary={`Profit changed by ${inrDay(d.root_cause.total_change)}.`} />
                <Link href={`/diagnosis?anomaly=${n.anomaly_id}`} className="mt-1 inline-block text-sm font-semibold text-synapse-fg underline-offset-2 hover:underline">
                  Open diagnosis
                </Link>
              </>
            )}
          </LoadState>
        </Section>
      )}
      {curve && (
        <Section title="Profit against daily spend">
          <CurveChart points={curve.points} current={n.current_spend} planned={planned} optimal={curve.optimal_spend} saturation={curve.saturation_spend} height={200} summary={`Profit curve for ${n.label}.`} />
        </Section>
      )}
      <Section title="Decisions about this">
        <LoadState q={recs} what="the decisions" height={80}>
          {(r) => <Decisions list={[...r.pending, ...r.history].filter((d) => d.action.changes.some((c) => c.campaign_id === n.entity_id) || d.targets.some((t) => t.id === n.entity_id))} />}
        </LoadState>
      </Section>
      <p className="mt-4 flex flex-wrap gap-4 text-sm font-semibold">
        <Link href={`/performance?tab=${n.entity_type === "campaign" ? "campaigns" : "products"}${n.entity_type === "campaign" && n.channel ? `&channel=${n.channel}` : ""}`} className="text-synapse-fg underline-offset-2 hover:underline">
          See it in Performance
        </Link>
      </p>
    </>
  );
}

/** The right-hand panel for whatever was clicked on the map. */
export default function Drawer({ pick, onClose }: { pick: MapPick; onClose: () => void }) {
  const snap = useBrainSnapshot().data;
  const opps = useOpportunities().data;
  const recs = useRecommendations().data;
  const title = pick.kind === "neuron" ? (pick.node.entity_type === "campaign" ? "Campaign" : "Product") : pick.kind === "cluster" ? "Channel" : pick.kind === "source" ? "Data source" : "Untested idea";
  return (
    <aside aria-label={`${title} details`} className="panel min-w-0 self-start p-4 min-[1200px]:sticky min-[1200px]:top-4 min-[1200px]:max-h-[calc(100vh-2rem)] min-[1200px]:overflow-y-auto">
      <div className="mb-3 flex items-center justify-between gap-2">
        <h2 className="text-base font-bold">{title}</h2>
        <button onClick={onClose} aria-label="Close details" className="rounded p-1 text-fog hover:text-bone">
          <X className="size-4" />
        </button>
      </div>
      {pick.kind === "neuron" && <NeuronBody n={pick.node} />}
      {pick.kind === "cluster" && (
        <>
          <div className="text-base font-bold">{pick.cluster.label}</div>
          {pick.cluster.alert && <p className="mt-1 text-sm tone-risk">{pick.cluster.alert.message}</p>}
          <Section title="Campaigns on this channel">
            <ul className="grid gap-2 text-sm">
              {(snap?.nodes ?? []).filter((n) => n.cluster === pick.cluster.id).map((n) => (
                <li key={n.entity_id} className="flex flex-wrap items-center justify-between gap-2">
                  {n.entity_type === "campaign" ? <CampaignName name={n.label} channel={n.channel} /> : <span className="font-semibold">{n.label}</span>}
                  <Money v={n.profit_7d} />
                </li>
              ))}
            </ul>
          </Section>
          <p className="mt-4 text-sm font-semibold">
            <Link href={`/performance?tab=campaigns&channel=${pick.cluster.id}`} className="text-synapse-fg underline-offset-2 hover:underline">
              See the channel in Performance
            </Link>
          </p>
        </>
      )}
      {pick.kind === "source" && (
        <>
          <div className="text-base font-bold">{pick.source.label}</div>
          <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
            <div><dt className="text-fog">Status</dt><dd className="font-semibold">{pick.source.status === "warn" ? "Needs attention" : "Healthy"}</dd></div>
            <div><dt className="text-fog">Trust</dt><dd className="font-semibold">{pct(pick.source.trust_score)}</dd></div>
            <div><dt className="text-fog">Over-reporting</dt><dd className="font-semibold">{pick.source.inflation_pct && pick.source.inflation_pct >= 0.005 ? pct(pick.source.inflation_pct) : "None"}</dd></div>
            <div><dt className="text-fog">Store-verified</dt><dd className="font-semibold">{pick.source.verified ? "Yes" : "No"}</dd></div>
          </dl>
          {pick.source.alert && <p className="mt-3 text-sm text-fog">{pick.source.alert.message}</p>}
          <p className="mt-4 text-sm font-semibold">
            <Link href="/data" className="text-synapse-fg underline-offset-2 hover:underline">
              See it in Data truth
            </Link>
          </p>
        </>
      )}
      {pick.kind === "ghost" && (() => {
        const o = opps?.opportunities.find((x) => x.label === pick.ghost.id);
        const d = recs ? findLaunchDecision([...recs.pending, ...recs.history], pick.ghost) : undefined;
        return (
          <>
            <div className="text-base font-bold">{pick.ghost.id}</div>
            <div className="mt-1">{pick.ghost.launched ? <StatusChip tone="gain">Test running</StatusChip> : <StatusChip tone="muted">Predicted, not run</StatusChip>}</div>
            {o && (
              <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
                <div><dt className="text-fog">Rank</dt><dd className="font-semibold">{o.rank}</dd></div>
                <div><dt className="text-fog">Predicted profit on spend</dt><dd className="font-semibold">{ratio(o.predicted_poas)}</dd></div>
                <div><dt className="text-fog">Orders per ₹1,000 of ads</dt><dd className="font-semibold">{num(o.predicted_conv_per_1k, 1)}</dd></div>
                <div><dt className="text-fog">Test budget</dt><dd className="font-semibold">{inr(o.test_budget)}/day</dd></div>
              </dl>
            )}
            <Section title="Launch decision">{d ? <Decisions list={[d]} /> : <p className="text-sm text-fog">No launch decision exists yet. Run the loop now to look again.</p>}</Section>
            <p className="mt-4 text-sm font-semibold">
              <Link href="/opportunities" className="text-synapse-fg underline-offset-2 hover:underline">
                See all opportunities
              </Link>
            </p>
          </>
        );
      })()}
    </aside>
  );
}
