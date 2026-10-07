"use client";

import { ArrowDown, ArrowUp, TriangleAlert } from "lucide-react";
import Link from "next/link";
import AnomalyName from "@/components/AnomalyName";
import { Panel } from "@/components/Panel";
import { dateShort, inr, num, pct } from "@/lib/format";
import { anomalyEntity, kindDisplay, parseCampaignName, zMeaning } from "@/lib/names";
import type { Anomaly, Diagnosis } from "@/lib/types";

function metricValue(metric: string, v: number): string {
  if (/ctr|cvr/.test(metric)) return pct(v, 2);
  if (metric === "days_cover") return `${v.toFixed(1)} days`;
  if (metric === "platform_vs_store") return `${num(v)} conversions`;
  if (metric === "cpc") return `₹${v.toFixed(2)}`;
  return inr(v);
}

/** "Google, Summer Sneakers" for a campaign anomaly; the entity name otherwise. */
function shortEntity(a: Anomaly): string {
  const e = anomalyEntity(a.label);
  if (a.entity_type !== "campaign") return e;
  const p = parseCampaignName(e);
  return `${p.channelName}, ${p.product}`;
}

const Fact = ({ label, children }: { label: string; children: React.ReactNode }) => (
  <div>
    <dt className="text-sm text-fog">{label}</dt>
    <dd className="mt-0.5 text-sm font-semibold">{children}</dd>
  </div>
);

/** Section 1: what happened, in numbers and in the engine's words. */
export default function Brief({ d, all }: { d: Diagnosis; all: Anomaly[] }) {
  const a = d.anomaly;
  const w = a.detail.window;
  const resolve = (ref: string) => {
    const [kind, entity] = ref.split(":");
    return all.find((x) => x.kind === kind && x.entity_id === entity);
  };
  const causes = (a.detail.related ?? []).map(resolve).filter((x): x is Anomaly => !!x);
  const effects = all.filter((x) => x.id !== a.id && (x.detail.related ?? []).some((r) => resolve(r)?.id === a.id));
  const loss = a.profit_impact < 0;
  const DirIcon = a.change_pct < 0 ? ArrowDown : ArrowUp;
  return (
    <Panel title={kindDisplay(a.kind)} note={`${a.id}`}>
      <div className="mb-3">
        <AnomalyName a={a} />
      </div>
      <dl className="grid grid-cols-2 gap-x-6 gap-y-3 min-[1200px]:grid-cols-4">
        <Fact label="What changed">
          <span className="inline-flex items-center gap-1">
            <DirIcon className="size-3.5" aria-hidden />
            {a.metric.replace(/_/g, " ")} {a.change_pct < 0 ? "−" : "+"}
            {pct(Math.abs(a.change_pct))}
          </span>
          <span className="block font-normal text-fog">
            {metricValue(a.metric, a.baseline)} to {metricValue(a.metric, a.recent)}
          </span>
        </Fact>
        <Fact label="Statistic">
          {a.z !== 0 ? <>z = {a.z.toFixed(1).replace("-", "−")}</> : "No statistical test"}
          <span className="block font-normal text-fog">{a.z !== 0 ? zMeaning(a.z) : "Platform and store conversions were compared directly."}</span>
        </Fact>
        <Fact label="Severity and direction">
          <span className="inline-flex items-center gap-1">
            {a.severity === "high" && <TriangleAlert className="size-3.5 tone-risk" aria-hidden />}
            {a.severity.charAt(0).toUpperCase() + a.severity.slice(1)}
          </span>
          <span className={`block font-normal ${loss ? "tone-loss" : "tone-gain"}`}>{loss ? "Costing" : "Earning"} {inr(Math.abs(a.profit_impact))} a day</span>
        </Fact>
        <Fact label="Compared windows">
          Recent {dateShort(w.recent_start)} to {dateShort(w.recent_end)}
          <span className="block font-normal text-fog">{w.baseline_start ? `Baseline ${dateShort(w.baseline_start)} to ${dateShort(w.baseline_end)}` : "No baseline window"}</span>
        </Fact>
      </dl>
      <p className="narrative mt-4">{d.root_cause.narrative}</p>
      {(causes.length > 0 || effects.length > 0) && (
        <div className="mt-4 flex flex-wrap items-center gap-2 text-sm">
          {causes.length > 0 && <span className="text-fog">Linked to</span>}
          {causes.map((c) => (
            <Link key={c.id} href={`/diagnosis?anomaly=${c.id}`} className="rounded-full border border-line px-2.5 py-0.5 font-semibold hover:border-synapse">
              {kindDisplay(c.kind)}, {shortEntity(c)}
            </Link>
          ))}
          {effects.length > 0 && <span className="text-fog">Knock-on effects</span>}
          {effects.map((c) => (
            <Link key={c.id} href={`/diagnosis?anomaly=${c.id}`} className="rounded-full border border-line px-2.5 py-0.5 font-semibold hover:border-synapse">
              {kindDisplay(c.kind)}, {shortEntity(c)}
            </Link>
          ))}
        </div>
      )}
    </Panel>
  );
}
