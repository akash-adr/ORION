"use client";

import { ChevronDown } from "lucide-react";
import { useState } from "react";
import { EmptyState, LoadState, Panel } from "@/components/Panel";
import { inr } from "@/lib/format";
import { useRecommendations } from "@/lib/queries";
import { cn } from "@/lib/utils";
import DecisionRow from "./DecisionRow";

export default function DecisionLedger() {
  const q = useRecommendations();
  const [open, setOpen] = useState<string | null>(null);
  const [showHandled, setShowHandled] = useState(false);
  const toggle = (id: string) => setOpen((cur) => (cur === id ? null : id));
  return (
    <Panel className="p-0 min-[1200px]:p-0" aria-label="Decisions">
      <LoadState q={q} what="the decisions" height={420}>
        {(r) => {
          const pending = [...r.pending].sort((a, b) => b.priority - a.priority);
          const s = r.summary;
          return (
            <div>
              <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1 border-b border-line px-4 py-4">
                <div>
                  <h2 className="text-base font-bold">Decisions</h2>
                  <p className="text-sm text-fog">
                    {s.pending} waiting, {s.needs_approval} need approval, {s.auto_eligible} run automatically, {s.blocked} blocked
                  </p>
                </div>
                <div className="text-right">
                  <div className="text-sm text-fog">Expected upside if all approved</div>
                  <div className="text-base font-bold tone-gain">
                    {"↑"} {inr(s.total_expected_profit_delta)}
                    <span className="ml-1 text-sm font-semibold text-fog">/day</span>
                  </div>
                </div>
              </div>
              {pending.length === 0 ? (
                <div className="p-4">
                  <EmptyState title="No decisions waiting" hint="Run the loop now to look for new signals." />
                </div>
              ) : (
                <ul>
                  {pending.map((d) => (
                    <DecisionRow key={d.id} d={d} open={open === d.id} onToggle={() => toggle(d.id)} />
                  ))}
                </ul>
              )}
              {r.history.length > 0 && (
                <div className="border-t border-line">
                  <button onClick={() => setShowHandled((v) => !v)} aria-expanded={showHandled} className="flex w-full items-center gap-2 px-4 py-3 text-left text-sm font-semibold hover:bg-slate-2/50">
                    <ChevronDown className={cn("size-4 text-fog transition-transform duration-200", !showHandled && "-rotate-90")} aria-hidden />
                    Handled ({r.history.length})
                    <span className="font-normal text-fog">approved {s.executed}, rejected {s.rejected}, rolled back {s.rolled_back}</span>
                  </button>
                  {showHandled && (
                    <ul>
                      {r.history.map((d) => (
                        <DecisionRow key={d.id} d={d} open={open === d.id} onToggle={() => toggle(d.id)} />
                      ))}
                    </ul>
                  )}
                </div>
              )}
            </div>
          );
        }}
      </LoadState>
    </Panel>
  );
}
