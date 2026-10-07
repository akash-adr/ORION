"use client";

import { CircleCheck, CircleX } from "lucide-react";
import { dateShort, pct, timeShort } from "@/lib/format";
import type { PitchData } from "@/lib/pitch/data";
import { LOOP_STEPS, type Linked, type LoopStepId, type PitchRef } from "@/lib/pitch/links";
import { usePitchStore } from "@/lib/pitch/store";
import { cn } from "@/lib/utils";

function figure(id: LoopStepId, d: PitchData): string {
  const x = d.derived;
  const ev = (n: string) => d.loop?.steps?.[n as keyof NonNullable<typeof d.loop>["steps"]]?.events;
  switch (id) {
    case "ingest":
      return `${x.sourceCount} sources${ev("ingest") !== undefined ? `, ${ev("ingest")} events` : ""}`;
    case "detect":
      return `${x.signals} signals`;
    case "diagnose":
      return `${x.signals} diagnosed${x.found !== null ? `, ${x.found} of ${x.expected} planted found` : ""}`;
    case "predict":
      return `${x.curveCount} curves, ${x.ideas} ideas`;
    case "decide":
      return `${x.pending} decisions`;
    case "execute":
      return `${x.executed} executed${d.loop ? `, ${d.loop.auto_applied.length} automatic` : ""}`;
    case "learn":
      return `${x.outcomes} outcomes, error ${pct(x.mape)}`;
  }
}
const STEP_KEY: Partial<Record<LoopStepId, string>> = { ingest: "ingest", detect: "detect", diagnose: "diagnose", predict: "optimize", decide: "decide", learn: "learn" };

export default function LoopStrip({ data, linked, active, onFocus }: { data: PitchData; linked: Linked | null; active: LoopStepId | null; onFocus: (r: PitchRef) => void }) {
  const setHover = usePitchStore((s) => s.setHover);
  const loop = data.loop;
  return (
    <section aria-label="The loop" className="panel p-3">
      <ol className="grid gap-2 min-[1200px]:grid-cols-[repeat(7,minmax(0,1fr))_auto] min-[1200px]:items-stretch">
        {LOOP_STEPS.map((s, i) => {
          const st = loop?.steps?.[STEP_KEY[s.id] as keyof NonNullable<typeof loop>["steps"]];
          const on = active === s.id || !!linked?.steps.has(s.id);
          const dim = linked && !linked.steps.has(s.id) && active !== s.id;
          return (
            <li key={s.id} className="min-w-0">
                <button
                  data-pitch={`loop:${s.id}`}
                  onPointerEnter={() => setHover({ kind: "loop", id: s.id })}
                  onPointerLeave={() => setHover(null)}
                  onFocus={() => setHover({ kind: "loop", id: s.id })}
                  onBlur={() => setHover(null)}
                  onClick={() => onFocus({ kind: "loop", id: s.id })}
                  className={cn("h-full w-full rounded-lg border border-line px-3 py-2 text-left transition-opacity duration-150 hover:border-fog", on && "border-fog bg-slate-2", dim && "opacity-55")}
                >
                  <span className="flex items-center gap-1.5 text-sm font-bold">
                    <span className="grid size-5 shrink-0 place-items-center rounded-full border border-line text-xs">{i + 1}</span>
                    {s.label}
                    {st && (st.ok ? <CircleCheck className="ml-auto size-3.5 tone-gain" aria-label="Succeeded" /> : <CircleX className="ml-auto size-3.5 tone-loss" aria-label="Failed" />)}
                  </span>
                  <span className="mt-1 block text-[13px] leading-snug text-fog">{figure(s.id, data)}</span>
                </button>
            </li>
          );
        })}
        <li className="flex min-w-0 flex-col justify-center px-2 text-sm">
          {loop ? (
            <>
              <span className="font-semibold">Last run {timeShort(loop.at)}</span>
              <span className="text-xs text-fog">
                {dateShort(loop.at)}, {(loop.duration_ms / 1000).toFixed(1)} s
              </span>
            </>
          ) : (
            <span className="text-fog">The loop hasn&apos;t run yet</span>
          )}
        </li>
      </ol>
    </section>
  );
}
