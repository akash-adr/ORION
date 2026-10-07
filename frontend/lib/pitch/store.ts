"use client";

import { create } from "zustand";
import type { PitchRef } from "./links";

interface PitchStore {
  /** what the pointer is over (links highlight everything related) */
  hover: PitchRef | null;
  setHover: (r: PitchRef | null) => void;
  /** focus mode: the camera is on a region and a detail sheet is open */
  focus: PitchRef | null;
  setFocus: (r: PitchRef | null) => void;
}

export const usePitchStore = create<PitchStore>((set) => ({
  hover: null,
  setHover: (hover) => set({ hover }),
  focus: null,
  setFocus: (focus) => set({ focus }),
}));
