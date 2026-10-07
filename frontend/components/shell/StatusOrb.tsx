"use client";

import Link from "next/link";
import { useBrainState } from "@/lib/queries";
import { timeShort } from "@/lib/format";

const RING: Record<string, { color: string; word: string }> = {
  idle: { color: "var(--fog)", word: "Idle" },
  ingesting: { color: "var(--region-ingest)", word: "Ingesting data" },
  diagnosing: { color: "var(--region-diagnose)", word: "Diagnosing" },
  thinking: { color: "var(--region-diagnose)", word: "Diagnosing" },
  deciding: { color: "var(--region-decide)", word: "Deciding" },
  learning: { color: "var(--region-learn)", word: "Learning" },
};

/** A small brain glyph in the top bar. Its ring colour follows the engine's mode (/brain/state) and it pulses only while the engine is working. */
export default function StatusOrb() {
  const q = useBrainState();
  const mode = q.data?.state.mode ?? "idle";
  const ring = RING[mode] ?? RING.idle;
  const active = mode !== "idle";
  const latest = q.data?.latest;
  const tip = latest ? `${ring.word}. ${latest.message} (${timeShort(latest.ts)})` : `${ring.word}. No engine events yet.`;
  return (
    <Link href="/neural" title={tip} aria-label={`Brain status: ${tip}. Open the neural view`} className="group relative grid size-9 shrink-0 place-items-center rounded-full">
      <svg width="34" height="34" viewBox="0 0 34 34" aria-hidden className={active ? "animate-pulse" : undefined}>
        <circle cx="17" cy="17" r="15" fill="none" stroke={ring.color} strokeWidth="2" strokeOpacity={active ? 1 : 0.55} />
        {/* two lobes and a centre line: a brain, in outline */}
        <path d="M17 9.5c-2.2-2-6-1.2-7 1.6-1.9.3-3 2.2-2.4 4 -.9 1.4-.6 3.4.8 4.4.1 2 2 3.4 3.9 3 .8 1 2.2 1.3 3.3.6" fill="none" stroke="var(--bone)" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
        <path d="M17 9.5c2.2-2 6-1.2 7 1.6 1.9.3 3 2.2 2.4 4 .9 1.4.6 3.4-.8 4.4-.1 2-2 3.4-3.9 3-.8 1-2.2 1.3-3.3.6" fill="none" stroke="var(--bone)" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
        <path d="M17 9.5v15.4" stroke="var(--bone)" strokeWidth="1.2" strokeOpacity="0.6" />
      </svg>
      <span className="sr-only">{tip}</span>
    </Link>
  );
}
