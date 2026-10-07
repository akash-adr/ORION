"use client";

import { LineChart, type ChartEvent, type LineSeries } from "@/components/charts";
import { Panel } from "@/components/Panel";
import { indexTo100 } from "@/lib/diagnosis";
import { dateShort, inr, num, pct } from "@/lib/format";
import { useBrainManifest, useMetaConfig } from "@/lib/queries";
import type { Anomaly, Diagnosis } from "@/lib/types";

interface ChartSpec {
  title: string;
  note: string;
  series: LineSeries[];
  format: (v: number | null) => string;
  thresholds?: { value: number; label: string }[];
  events: ChartEvent[];
  summary: string;
}

const col = (rows: Diagnosis["evidence"]["daily"], k: string) => rows.map((r) => (typeof r[k] === "number" ? (r[k] as number) : null));

/** Section 4: the evidence behind the diagnosis, chosen by the kind of anomaly. Every series is read from evidence.daily. */
export default function EvidenceCharts({ d }: { d: Diagnosis }) {
  const manifest = useBrainManifest().data;
  const cfg = useMetaConfig().data;
  const a: Anomaly = d.anomaly;
  const rows = d.evidence.daily;
  if (!rows.length || a.kind === "attribution_inflation") return null;
  const dates = rows.map((r) => r.date);
  const w = a.detail.window;
  const last = dates[dates.length - 1];
  const band = [{ from: w.recent_start < dates[0] ? dates[0] : w.recent_start, to: w.recent_end > last ? last : w.recent_end, label: "Recent window" }];
  const stimulus = (type?: string, eventId?: string) => manifest?.stimuli.find((s) => (eventId ? s.event_id === eventId : s.type === type));
  const mark = (s: ReturnType<typeof stimulus>): ChartEvent[] => (s && dates.includes(s.date) ? [{ x: s.date, label: s.label }] : []);
  const ci = (v: number | null) => (v === null ? "—" : v.toFixed(0));

  const charts: ChartSpec[] = [];
  const idx = (k: string) => indexTo100(col(rows, k), dates, w.baseline_start, w.baseline_end);

  switch (a.kind) {
    case "creative_fatigue":
      charts.push({
        title: "Click-through rate and ad frequency",
        note: "Indexed to 100 at the baseline average",
        series: [
          { id: "ctr", label: "Click-through rate", color: "var(--factor-creative)", data: idx("ctr") },
          { id: "freq", label: "Frequency", color: "var(--risk)", data: idx("frequency"), dashed: true },
        ],
        format: ci,
        events: [],
        summary: `Click-through rate and frequency, indexed to 100. Frequency rose from ${a.detail.frequency_baseline?.toFixed(1)} to ${a.detail.frequency_recent?.toFixed(1)} while click-through fell ${pct(Math.abs(a.change_pct))}.`,
      });
      break;
    case "cpc_spike":
    case "metric_shift": {
      const ev = mark(stimulus("competitor"));
      charts.push({
        title: "Cost per click",
        note: "₹ per click, per day",
        series: [{ id: "cpc", label: "Cost per click", color: "var(--factor-auction)", data: col(rows, "cpc") }],
        format: (v) => (v === null ? "—" : `₹${v.toFixed(1)}`),
        events: ev,
        summary: `Daily cost per click over ${rows.length} days; it jumped in the recent window.`,
      });
      charts.push({
        title: "Profit",
        note: "₹ per day",
        series: [{ id: "profit", label: "Profit", color: "var(--synapse)", data: col(rows, "profit"), area: true }],
        format: inr,
        events: ev,
        summary: `Daily profit over ${rows.length} days.`,
      });
      break;
    }
    case "stockout_risk":
      charts.push({
        title: "Days of stock left",
        note: "Against the stock guard",
        series: [{ id: "cover", label: "Days of cover", color: "var(--synapse)", data: col(rows, "days_cover") }],
        format: (v) => (v === null ? "—" : `${v.toFixed(1)} d`),
        thresholds: cfg ? [{ value: cfg.detection.STOCK_COVER_RISK_DAYS, label: `Guard: ${cfg.detection.STOCK_COVER_RISK_DAYS} days` }] : [],
        events: [],
        summary: `Days of stock cover over ${rows.length} days, falling to ${a.recent.toFixed(1)} against a guard of ${cfg?.detection.STOCK_COVER_RISK_DAYS ?? "—"} days.`,
      });
      charts.push({
        title: "Units sold",
        note: "Per day",
        series: [{ id: "units", label: "Units", color: "var(--factor-traffic)", data: col(rows, "units") }],
        format: (v) => (v === null ? "—" : num(v)),
        events: [],
        summary: "Units sold each day.",
      });
      break;
    case "conversion_drop": {
      const ev = mark(a.detail.event_id ? stimulus(undefined, a.detail.event_id) : undefined);
      charts.push({
        title: "Site conversion rate",
        note: "Sessions that bought, per day",
        series: [{ id: "cvr", label: "Site conversion rate", color: "var(--factor-site)", data: col(rows, "site_cvr") }],
        format: (v) => (v === null ? "—" : pct(v, 2)),
        events: ev,
        summary: `Site conversion rate over ${rows.length} days, down ${pct(Math.abs(a.change_pct))} in the recent window.`,
      });
      charts.push({
        title: "Units sold",
        note: "Per day",
        series: [{ id: "units", label: "Units", color: "var(--factor-traffic)", data: col(rows, "units") }],
        format: (v) => (v === null ? "—" : num(v)),
        events: ev,
        summary: "Units sold each day.",
      });
      break;
    }
    case "positive_spike":
      charts.push({
        title: "Click-through rate",
        note: "Per day",
        series: [{ id: "ctr", label: "Click-through rate", color: "var(--factor-creative)", data: col(rows, "ctr") }],
        format: (v) => (v === null ? "—" : pct(v, 2)),
        events: mark(stimulus("creative_launch")),
        summary: `Click-through rate over ${rows.length} days; it rose after the new creative launched.`,
      });
      charts.push({
        title: "Profit",
        note: "₹ per day",
        series: [{ id: "profit", label: "Profit", color: "var(--synapse)", data: col(rows, "profit"), area: true }],
        format: inr,
        events: mark(stimulus("creative_launch")),
        summary: "Daily profit over the same days.",
      });
      break;
    default:
      break;
  }
  if (!charts.length) return null;
  return (
    <Panel title="The evidence" note={`Last ${rows.length} days; the shaded area is the window being tested`}>
      <div className="grid gap-5 min-[1200px]:grid-cols-2">
        {charts.map((c) => (
          <div key={c.title}>
            <div className="mb-1 flex flex-wrap items-baseline justify-between gap-2">
              <h3 className="text-sm font-bold">{c.title}</h3>
              <span className="text-xs text-fog">{c.note}</span>
            </div>
            <LineChart x={dates} xFormat={dateShort} series={c.series} format={c.format} bands={band} events={c.events} thresholds={c.thresholds} height={210} summary={c.summary} />
          </div>
        ))}
      </div>
    </Panel>
  );
}
