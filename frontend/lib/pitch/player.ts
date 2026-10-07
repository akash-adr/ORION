"use client";

import { useEffect } from "react";
import { create } from "zustand";
import { DEFAULT_SECONDS, STEP_COUNT, STEPS } from "./steps";
import { usePitchStore } from "./store";

export interface Approved {
  decisionId: string;
  title: string;
  calls: number;
  /** "2 budget changes" */
  noun: string;
  /** predicted → measured, when the outcome came back with the approval */
  outcome: { predicted: number; actual: number } | null;
}

interface PitchPlayer {
  active: boolean;
  index: number;
  playing: boolean;
  /** speaker notes visible */
  notes: boolean;
  /** the Approve in step 6 has been used in this run */
  approved: Approved | null;
  start: (index?: number, autoplay?: boolean) => void;
  exit: () => void;
  next: () => void;
  prev: () => void;
  goTo: (i: number) => void;
  togglePlay: () => void;
  toggleNotes: () => void;
  setApproved: (a: Approved | null) => void;
}

const clamp = (i: number) => Math.max(0, Math.min(STEP_COUNT - 1, i));

export const usePitchPlayer = create<PitchPlayer>((set, get) => ({
  active: false,
  index: 0,
  playing: false,
  notes: false,
  approved: null,
  // a restart forgets the approval, so the new run reads the engine's current state
  start: (index = 0, autoplay = true) => set({ active: true, index: clamp(index), playing: autoplay, approved: null }),
  exit: () => set({ active: false, playing: false, notes: false }),
  next: () => {
    const { index } = get();
    if (index >= STEP_COUNT - 1) set({ playing: false });
    else set({ index: index + 1 });
  },
  prev: () => set({ index: clamp(get().index - 1) }),
  goTo: (i) => set({ index: clamp(i) }),
  togglePlay: () => set({ playing: !get().playing }),
  toggleNotes: () => set({ notes: !get().notes }),
  setApproved: (approved) => set({ approved }),
}));

/**
 * Advances the walkthrough while it plays. It holds (without losing its place) whenever the pointer is over the caption,
 * over something on the page, or a detail sheet is open, and starts the step's countdown again when released.
 */
export function useAutoplay(held: boolean) {
  const active = usePitchPlayer((s) => s.active);
  const playing = usePitchPlayer((s) => s.playing);
  const index = usePitchPlayer((s) => s.index);
  const hover = usePitchStore((s) => s.hover);
  const focus = usePitchStore((s) => s.focus);
  const paused = held || !!hover || !!focus;
  useEffect(() => {
    if (!active || !playing || paused) return;
    const t = setTimeout(() => usePitchPlayer.getState().next(), (STEPS[index].seconds ?? DEFAULT_SECONDS) * 1000);
    return () => clearTimeout(t);
  }, [active, playing, paused, index]);
}
