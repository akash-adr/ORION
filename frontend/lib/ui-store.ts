"use client";

import { create } from "zustand";
import type { BrainTarget } from "./types";

export type Theme = "dark" | "light";
export type ToastTone = "gain" | "loss" | "risk" | "info";
export interface Toast {
  id: number;
  tone: ToastTone;
  message: string;
  /** optional detail line */
  detail?: string;
}

interface UiStore {
  /** Not persisted: the only allowed browser storage is the "intro shown" flag. */
  theme: Theme;
  setTheme: (t: Theme) => void;
  toggleTheme: () => void;

  toasts: Toast[];
  toast: (tone: ToastTone, message: string, detail?: string) => void;
  dismissToast: (id: number) => void;

  /** Brain targets the Ask bar wants highlighted (consumed by the brain in part 5). */
  highlights: BrainTarget[];
  setHighlights: (h: BrainTarget[]) => void;

  /** The engine is unreachable (set by the API client). */
  offline: boolean;
  setOffline: (o: boolean) => void;
}

let nextId = 1;

export const useUiStore = create<UiStore>((set, get) => ({
  theme: "dark",
  setTheme: (theme) => set({ theme }),
  toggleTheme: () => set({ theme: get().theme === "dark" ? "light" : "dark" }),

  toasts: [],
  toast: (tone, message, detail) => {
    const id = nextId++;
    set({ toasts: [...get().toasts.slice(-3), { id, tone, message, detail }] });
    setTimeout(() => get().dismissToast(id), tone === "loss" ? 8000 : 5000);
  },
  dismissToast: (id) => set({ toasts: get().toasts.filter((t) => t.id !== id) }),

  highlights: [],
  setHighlights: (highlights) => set({ highlights }),

  offline: false,
  setOffline: (offline) => set({ offline }),
}));
