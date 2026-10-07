"use client";

import { create } from "zustand";
import type { BrainEvent, BrainRegion } from "@/lib/types";

export type PulseTone = "loss" | "gain" | "risk" | "synapse";
export interface Pulse {
  id: string;
  /** region names the pulse travels through, in order, then the targets */
  path: BrainRegion[] | string[];
  targets: string[];
  tone: PulseTone;
  strong: boolean;
  startedAt: number;
  duration: number;
}

export type PlayerMode = "idle" | "ingesting" | "diagnosing" | "deciding" | "learning";

const MODE_OF: Record<string, PlayerMode> = {
  ingest: "ingesting",
  anomaly: "diagnosing",
  diagnosis: "diagnosing",
  recommendation: "deciding",
  approval: "deciding",
  rejection: "deciding",
  rollback: "deciding",
  auto_apply: "deciding",
  outcome: "learning",
};

export function pulseTone(e: BrainEvent): PulseTone {
  const p = e.payload as Record<string, unknown>;
  switch (e.type) {
    case "ingest":
      return "synapse";
    case "anomaly":
    case "diagnosis":
      return p.direction === "gain" ? "gain" : "loss";
    case "recommendation":
      return p.blocked ? "risk" : "synapse";
    case "approval":
    case "auto_apply":
    case "outcome":
      return "gain";
    default:
      return "risk"; // rejection, rollback
  }
}

/** Every entity an event is about: its own entity, the payload targets (ids or {type,id}), and any related campaigns. */
export function eventTargets(e: BrainEvent): string[] {
  const p = e.payload as Record<string, unknown>;
  const ids = new Set<string>();
  if (e.entity_id) ids.add(e.entity_id);
  for (const key of ["targets", "campaigns"]) {
    const v = p[key];
    if (Array.isArray(v)) for (const x of v) ids.add(typeof x === "string" ? x : (x as { id?: string })?.id ?? "");
  }
  ids.delete("");
  return [...ids];
}

interface BrainPlayer {
  /** id of the newest event already queued or played (the polling cursor) */
  cursor: string | null;
  queue: BrainEvent[];
  /** newest first, at most 20 */
  feed: BrainEvent[];
  mode: PlayerMode;
  caption: string | null;
  pulses: Pulse[];
  /** entity id → performance.now() until which it is highlighted */
  highlightUntil: Record<string, number>;
  /** replay progress */
  replay: { total: number; done: number } | null;
  /** id of the first replayed event; a player that mounts after the replay was requested starts from here, not from "now" */
  replayFrom: string | null;

  setCursor: (id: string | null) => void;
  enqueue: (events: BrainEvent[]) => void;
  playNext: () => BrainEvent | null;
  setMode: (m: PlayerMode) => void;
  /** a replay was just requested: remember where it starts and show progress */
  beginReplay: (firstId: string, total: number) => void;
  clearReplay: () => void;
}

let pulseSeq = 0;

export const useBrainPlayer = create<BrainPlayer>((set, get) => ({
  cursor: null,
  queue: [],
  feed: [],
  mode: "idle",
  caption: null,
  pulses: [],
  highlightUntil: {},
  replay: null,
  replayFrom: null,

  setCursor: (cursor) => set({ cursor }),
  enqueue: (events) => {
    if (!events.length) return;
    const seen = new Set(get().queue.map((e) => e.id));
    const fresh = events.filter((e) => !seen.has(e.id));
    set({ queue: [...get().queue, ...fresh], cursor: events[events.length - 1].id });
  },
  playNext: () => {
    const { queue, replay } = get();
    const e = queue[0];
    if (!e) return null;
    const now = performance.now();
    const strong = e.severity === "high";
    const duration = strong ? 1600 : 1100;
    const pulse: Pulse = { id: `p${++pulseSeq}`, path: e.path, targets: eventTargets(e), tone: pulseTone(e), strong, startedAt: now, duration };
    const until = { ...get().highlightUntil };
    for (const t of pulse.targets) until[t] = now + duration + 1400;
    set({
      queue: queue.slice(1),
      feed: [e, ...get().feed].slice(0, 20),
      caption: e.message,
      mode: MODE_OF[e.type] ?? "idle",
      pulses: [...get().pulses.filter((p) => now - p.startedAt < p.duration), pulse],
      highlightUntil: until,
      replay: replay ? { ...replay, done: Math.min(replay.total, replay.done + 1) } : null,
    });
    return e;
  },
  setMode: (mode) => set({ mode }),
  beginReplay: (firstId, total) => set({ replay: { total, done: 0 }, replayFrom: firstId }),
  clearReplay: () => set({ replay: null, replayFrom: null }),
}));
