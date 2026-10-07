"use client";

import { useSyncExternalStore } from "react";

const noop = () => () => {};
/** false while the server HTML is being hydrated (and on the server), true afterwards. */
export function useHydrated(): boolean {
  return useSyncExternalStore(noop, () => true, () => false);
}
