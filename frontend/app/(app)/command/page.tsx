"use client";

import { ArrowUp, Lock, TriangleAlert } from "lucide-react";
import Link from "next/link";
import { ConfidenceMeter, LineChart } from "@/components/charts";
import PnlStrip from "@/components/command/PnlStrip";
import PageHeader from "@/components/PageHeader";
import { EmptyState, LoadState, Panel } from "@/components/Panel";
import { dateShort, inr, inrDay } from "@/lib/format";
import { actionTypeDisplay } from "@/lib/names";
import { useBrainSnapshot, useMetaConfig, useRecommendations, useTrend } from "@/lib/queries";

function EngineMap() {
  const q = useBrainSnapshot();
  return (
    <Panel title="Engine map" note="The live map arrives with the neural view" data-engine-map className="min-h-[300px]">
      <LoadState q={q} what="the engine map" height={220}>
        {(s) => {
          const health = (h: string) => s.nodes.filter((n) => n.health === h).length;
          const rows: [string, number][] = [
            ["Neurons", s.nodes.length],
            ["Synapses", s.synapses.length],
            ["Data sources", s.sources.length],
            ["Ghost opportunities", s.ghosts.length],
            ["Alerting now", s.nodes.filter((n) => n.is_alerting).length],
          ];
          return (
            <dl className="grid grid-cols-2 gap-x-6 gap-y-3 text-sm">
              {rows.map(([k, v]) => (
                <div key={k}>
                  <dt className="text-fog">{k}</dt>
                  <dd className="text-xl font-bold">{v}</dd>
                </div>
              ))}
              <div className="col-span-2 border-t border-line pt-3 text-fog">
                {health("good")} healthy, {health("weak")} weak, {health("losing")} losing money
              </div>
            </dl>
          );
        }}
      </LoadState>
    </Panel>
  );
}

function TrendPanel() {
  const q = useTrend(45);
  return (
    <Panel title="Profit and spend each day" note="Last 45 days, per day">
      <LoadState q={q} what="the trend" height={260}>
        {(t) => (
          <LineChart
            x={t.map((p) => p.date)}
            xFormat={(d) => dateShort(d)}
            series={[
              { id: "profit", label: "Profit", color: "var(--synapse)", data: t.map((p) => p.profit), area: true },
              { id: "spend", label: "Ad spend", color: "var(--fog)", data: t.map((p) => p.spend), dashed: true },
            ]}
            summary={`Daily profit and ad spend for the last ${t.length} days. Latest profit ${inrDay(t[t.length - 1]?.profit)}, latest spend ${inrDay(t[t.length - 1]?.spend)}.`}
          />
        )}
      </LoadState>
    </Panel>
  );
}

function DecisionPreview() {
  const q = useRecommendations();
  const cfg = useMetaConfig();
  return (
    <Panel title="Decisions waiting" note="Highest value first">
      <LoadState q={q} what="the decisions" height={200}>
        {(r) => {
          const top = [...r.pending].sort((a, b) => b.priority - a.priority).slice(0, 4);
          if (!top.length) return <EmptyState title="No decisions waiting" hint="Run the loop now to check for new ones." />;
          const min = cfg.data?.guardrails.CONFIDENCE_MIN ?? 0.45;
          const max = cfg.data?.guardrails.CONFIDENCE_MAX ?? 0.95;
          return (
            <ul className="divide-y divide-line">
              {top.map((d) => (
                <li key={d.id} className="grid gap-x-6 gap-y-2 py-3 first:pt-0 min-[1000px]:grid-cols-[1fr_auto]">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-semibold">{d.title}</span>
                      <span className="rounded-full border border-line px-2 py-px text-xs text-fog">{actionTypeDisplay(d.action.type)}</span>
                      {d.risk === "high" && (
                        <span className="inline-flex items-center gap-1 rounded-full border border-line px-2 py-px text-xs font-semibold tone-risk">
                          <TriangleAlert className="size-3" aria-hidden />
                          High risk
                        </span>
                      )}
                      {d.blocked && (
                        <span className="inline-flex items-center gap-1 rounded-full border border-line px-2 py-px text-xs font-semibold tone-loss">
                          <Lock className="size-3" aria-hidden />
                          Blocked
                        </span>
                      )}
                    </div>
                    <p className="narrative mt-1 line-clamp-2 text-fog">{d.cause}</p>
                  </div>
                  <div className="flex items-center gap-4 min-[1000px]:flex-col min-[1000px]:items-end min-[1000px]:gap-1.5">
                    <span className="inline-flex items-center gap-1 text-base font-bold tone-gain">
                      <ArrowUp className="size-4" aria-hidden />
                      {inr(d.expected_profit_delta)}/day
                    </span>
                    <ConfidenceMeter value={d.confidence} min={min} max={max} />
                  </div>
                </li>
              ))}
            </ul>
          );
        }}
      </LoadState>
      <p className="mt-3 text-sm text-fog">
        Approving, rejecting and rolling back arrive with the full decision ledger. Past actions are in the{" "}
        <Link href="/learning" className="font-semibold text-synapse-fg underline-offset-2 hover:underline">
          audit trail
        </Link>
        .
      </p>
    </Panel>
  );
}

export default function CommandPage() {
  return (
    <div className="grid gap-5">
      <PageHeader title="Command">What changed, what the engine recommends, and the proof one click away.</PageHeader>
      <PnlStrip />
      <div className="grid gap-5 min-[1200px]:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
        <EngineMap />
        <TrendPanel />
      </div>
      <DecisionPreview />
    </div>
  );
}
