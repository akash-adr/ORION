"use client";

import { useBrainStore, type BrainState } from "./store";

const STATES: BrainState[] = ["idle", "ingesting", "anomaly", "deciding", "learning"];

/** TEMPORARY: demo controls for triggering brain states. Remove once the backend drives state. */
export default function DevPanel() {
  const current = useBrainStore((s) => s.brainState);
  const set = useBrainStore((s) => s.setBrainState);
  return (
    <div className="fixed bottom-4 left-4 z-50 w-40 rounded-xl border border-white/10 bg-black/60 p-2 backdrop-blur-md">
      <div className="mb-1.5 px-1 font-mono text-[10px] uppercase tracking-widest text-white/40">dev · brain state</div>
      <div className="flex flex-col gap-1">
        {STATES.map((s) => (
          <button
            key={s}
            onClick={() => set(s)}
            className={`rounded-md px-2 py-1 text-left font-mono text-xs transition-colors ${
              current === s ? "bg-white/15 text-white" : "text-white/60 hover:bg-white/10"
            }`}
          >
            {s}
          </button>
        ))}
      </div>
    </div>
  );
}

