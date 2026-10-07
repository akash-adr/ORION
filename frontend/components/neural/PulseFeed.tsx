"use client";

import { CircleCheck, CircleX, Flag, Lightbulb, Microscope, Database, TriangleAlert, Undo2, Zap, type LucideIcon } from "lucide-react";
import { Panel } from "@/components/Panel";
import { eventTargets, useBrainPlayer } from "@/lib/brain/store";
import { timeShort } from "@/lib/format";
import type { BrainEventType } from "@/lib/types";

const ICON: Record<BrainEventType, LucideIcon> = {
  ingest: Database,
  anomaly: TriangleAlert,
  diagnosis: Microscope,
  recommendation: Lightbulb,
  approval: CircleCheck,
  rejection: CircleX,
  rollback: Undo2,
  auto_apply: Zap,
  outcome: Flag,
};
const LABEL: Record<BrainEventType, string> = { ingest: "Ingest", anomaly: "Signal", diagnosis: "Diagnosis", recommendation: "Decision", approval: "Approved", rejection: "Rejected", rollback: "Rolled back", auto_apply: "Auto-applied", outcome: "Outcome" };

/** The latest 20 events the player has played, newest first. Click one to focus what it was about. */
export default function PulseFeed({ onFocus, knownIds }: { onFocus: (id: string) => void; knownIds: Set<string> }) {
  const feed = useBrainPlayer((s) => s.feed);
  return (
    <Panel title="Live pulses" note="Latest 20 engine events">
      {feed.length === 0 ? (
        <p className="text-sm text-fog">Quiet. Events appear here as the engine works. Replay the last 7 days or run the loop to see some.</p>
      ) : (
        <ol className="grid max-h-[340px] gap-0.5 overflow-y-auto" aria-live="polite" aria-label="Recent engine events">
          {feed.map((e) => {
            const Icon = ICON[e.type];
            const target = eventTargets(e).find((t) => knownIds.has(t));
            return (
              <li key={e.id}>
                <button onClick={() => target && onFocus(target)} disabled={!target} className="grid w-full grid-cols-[18px_minmax(0,1fr)_auto] items-start gap-2 rounded-lg px-2 py-1.5 text-left text-sm hover:bg-slate-2 disabled:cursor-default disabled:hover:bg-transparent">
                  <Icon className="mt-0.5 size-4 text-fog" aria-label={LABEL[e.type]} />
                  <span className="min-w-0">
                    <span className="block line-clamp-2">{e.message}</span>
                    <span className="text-xs text-fog">{LABEL[e.type]}</span>
                  </span>
                  <span className="text-xs whitespace-nowrap text-fog">{timeShort(e.ts)}</span>
                </button>
              </li>
            );
          })}
        </ol>
      )}
    </Panel>
  );
}
