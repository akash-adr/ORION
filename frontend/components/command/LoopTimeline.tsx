"use client";

import { CircleCheck, CircleX, LoaderCircle, Play } from "lucide-react";
import { useEffect, useState } from "react";
import { EmptyState, LoadState, Panel } from "@/components/Panel";
import { useRunLoop } from "@/components/shell/useRunLoop";
import { timeShort } from "@/lib/format";
import { useLoopLast, useSettings } from "@/lib/queries";
import type { LoopStepName } from "@/lib/types";
import { cn } from "@/lib/utils";

const STEPS: { key: LoopStepName; label: string; what: string }[] = [
  { key: "ingest", label: "Ingest", what: "Clean and reconcile data" },
  { key: "detect", label: "Detect", what: "Look for anomalies" },
  { key: "diagnose", label: "Diagnose", what: "Find the cause" },
  { key: "optimize", label: "Optimize", what: "Plan the budget" },
  { key: "decide", label: "Decide", what: "Build the decisions" },
  { key: "learn", label: "Learn", what: "Measure outcomes" },
];

function useCountdown(target: string | null | undefined): string | null {
  const [now, setNow] = useState<number | null>(null);
  useEffect(() => {
    const tick = () => setNow(Date.now());
    const first = setTimeout(tick, 0);
    const id = setInterval(tick, 1000);
    return () => {
      clearTimeout(first);
      clearInterval(id);
    };
  }, []);
  if (!target || now === null) return null;
  // The engine's timestamps are naive IST; compare in the same frame by reading them as local wall-clock.
  const t = new Date(target).getTime();
  // "now" in IST wall-clock terms
  const ist = new Date(new Date(now).toLocaleString("en-US", { timeZone: "Asia/Kolkata" })).getTime();
  const s = Math.max(0, Math.round((t - ist) / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

export default function LoopTimeline() {
  const q = useLoopLast();
  const settings = useSettings().data;
  const { run, running } = useRunLoop();
  const countdown = useCountdown(settings?.next_refresh_at);
  return (
    <Panel title="The loop" note={settings ? `Runs every ${settings.refresh_minutes} minutes` : undefined}>
      <LoadState q={q} what="the loop" height={120}>
        {(last) => {
          const runBtn = (
            <button onClick={run} disabled={running} className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-synapse px-3 text-sm font-semibold text-primary-foreground hover:bg-synapse/85 disabled:opacity-60">
              {running ? <LoaderCircle className="size-3.5 animate-spin" aria-hidden /> : <Play className="size-3.5" aria-hidden />}
              Run the loop now
            </button>
          );
          if (!last) return <EmptyState title="The loop hasn't run yet" hint="Run it now to watch the engine work." action={runBtn} />;
          return (
            <div className="grid gap-4">
              <ol className="grid gap-px overflow-hidden rounded-lg border border-line bg-line min-[700px]:grid-cols-3 min-[1200px]:grid-cols-6">
                {STEPS.map((s, i) => {
                  const st = last.steps[s.key];
                  const OkIcon = st?.ok ? CircleCheck : CircleX;
                  return (
                    <li key={s.key} className="bg-slate p-3">
                      <div className="flex items-center gap-1.5 text-sm font-bold">
                        <OkIcon className={cn("size-4", st?.ok ? "tone-gain" : "tone-loss")} aria-label={st?.ok ? "Succeeded" : "Failed"} />
                        <span className="text-fog">{i + 1}</span>
                        {s.label}
                      </div>
                      <div className="mt-0.5 text-xs text-fog">{s.what}</div>
                      <div className="mt-1.5 text-sm">
                        {st ? Math.round(st.duration_ms) : "—"} ms
                        <span className="text-fog">{st && st.events !== undefined ? `, ${st.events} ${st.events === 1 ? "event" : "events"}` : ""}</span>
                      </div>
                    </li>
                  );
                })}
              </ol>
              <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-2 text-sm">
                <div className="flex flex-wrap gap-x-5 gap-y-1">
                  <span><span className="text-fog">Last run</span> <span className="font-semibold">{timeShort(last.at)}</span></span>
                  <span><span className="text-fog">Events</span> <span className="font-semibold">{last.events_logged}</span></span>
                  <span><span className="text-fog">Applied automatically</span> <span className="font-semibold">{last.auto_applied.length}</span></span>
                  <span><span className="text-fog">Outcomes measured</span> <span className="font-semibold">{last.outcomes_measured}</span></span>
                  <span><span className="text-fog">Next run in</span> <span className="font-semibold">{countdown ?? "—"}</span></span>
                </div>
                {runBtn}
              </div>
            </div>
          );
        }}
      </LoadState>
    </Panel>
  );
}
