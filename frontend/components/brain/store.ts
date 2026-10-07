import { create } from "zustand";
import type { Region } from "./regions";

export type BrainState = "idle" | "ingesting" | "anomaly" | "deciding" | "learning";

interface BrainStore {
  brainState: BrainState;
  /** performance.now()/1000 at the moment the state was (re)triggered. */
  stateStartedAt: number;
  hoveredRegion: Region | null;
  selectedRegion: Region | null;
  setBrainState: (s: BrainState) => void;
  setHoveredRegion: (r: Region | null) => void;
  setSelectedRegion: (r: Region | null) => void;
}

export const useBrainStore = create<BrainStore>((set) => ({
  brainState: "idle",
  stateStartedAt: 0,
  hoveredRegion: null,
  selectedRegion: null,
  setBrainState: (brainState) =>
    set({ brainState, stateStartedAt: performance.now() / 1000 }),
  setHoveredRegion: (hoveredRegion) => set({ hoveredRegion }),
  setSelectedRegion: (selectedRegion) => set({ selectedRegion }),
}));

