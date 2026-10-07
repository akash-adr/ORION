"use client";

import { Link2 } from "lucide-react";
import Link from "next/link";
import AnomalyName from "@/components/AnomalyName";
import { EmptyState, LoadState, Panel } from "@/components/Panel";
import { inr, pct } from "@/lib/format";
import { kindIcon } from "@/lib/kinds";
import { kindDisplay } from "@/lib/names";
import { useAnomalies, useBrainSnapshot } from "@/lib/queries";
import type { Anomaly } from "@/lib/types";
import { cn } from "@/lib/utils";

const cause = (a: Anomaly, all: Anomaly[]): Anomaly | undefined => {
  const ref = a.detail.related?.[0];
  if (!ref) return undefined;
  const [kind, entity] = ref.split(":");
  return all.find((x) => x.kind === kind && x.entity_id === entity);
};

export default function Signals() {
  const q = useAnomalies();
  const snap = useBrainSnapshot().data;
  const dq = snap?.headline.detection_quality;
  return (
    <Panel title="Signals" note="Ranked by profit effect, per day">
      <LoadState q={q} what="the signals" height={220}>
        {(all) => {
          if (!all.length) return <EmptyState title="No signals right now" hint="Run the loop now to check again." />;
          const ranked = [...all].sort((a, b) => Math.abs(b.profit_impact) - Math.abs(a.profit_impact));
          return (
            <>
              <ul className="divide-y divide-line">
                {ranked.map((a) => {
                  const Icon = kindIcon(a.kind);
                  const none = Math.abs(a.profit_impact) < 0.5;
                  const gain = a.profit_impact > 0;
                  const c = cause(a, all);
                  return (
                    <li key={a.id}>
                      <Link href={`/diagnosis?anomaly=${a.id}`} className="grid grid-cols-[28px_minmax(0,1fr)_auto] items-start gap-x-3 gap-y-0.5 rounded-lg py-2.5 hover:bg-slate-2/60">
                        <span className="mt-0.5 grid size-7 place-items-center rounded-lg border border-line bg-slate-2" aria-hidden>
                          <Icon className="size-3.5 text-fog" />
                        </span>
                        <span className="min-w-0">
                          <AnomalyName a={a} className="text-sm" />
                          <span className="mt-0.5 block text-sm text-fog">
                            {kindDisplay(a.kind)}
                            {a.change_pct !== 0 && <>, {a.change_pct < 0 ? "−" : "+"}{pct(Math.abs(a.change_pct))} on {a.metric.replace(/_/g, " ")}</>}
                          </span>
                          {c && (
                            <span className="mt-0.5 flex items-center gap-1 text-xs text-fog">
                              <Link2 className="size-3" aria-hidden />
                              Linked to {kindDisplay(c.kind).toLowerCase()}
                            </span>
                          )}
                        </span>
                        <span className="text-right">
                          {none ? (
                            <span className="text-sm text-fog">No profit effect</span>
                          ) : (
                            <span className={cn("text-sm font-bold whitespace-nowrap", gain ? "tone-gain" : "tone-loss")}>
                              {gain ? "↑" : "↓"} {inr(Math.abs(a.profit_impact))}
                              <span className="font-semibold text-fog">/day</span>
                            </span>
                          )}
                          <span className="block text-xs text-fog">{a.severity} severity</span>
                        </span>
                      </Link>
                    </li>
                  );
                })}
              </ul>
              {dq && (
                <p className="mt-3 border-t border-line pt-3 text-sm text-fog">
                  {dq.found} of {dq.expected} planted problems detected.
                </p>
              )}
            </>
          );
        }}
      </LoadState>
    </Panel>
  );
}
