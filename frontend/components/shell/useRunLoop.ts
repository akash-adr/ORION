"use client";

import { ApiError } from "@/lib/api";
import { useRefresh } from "@/lib/queries";
import { useUiStore } from "@/lib/ui-store";

/** "Run the loop now": POST /refresh, then a toast with the event count; views refresh through the mutation. */
export function useRunLoop() {
  const toast = useUiStore((s) => s.toast);
  const refresh = useRefresh();
  const run = () =>
    refresh.mutate(undefined, {
      onSuccess: (r) => {
        const failed = Object.entries(r.steps).filter(([, s]) => !s.ok).map(([k]) => k);
        if (failed.length) toast("risk", `Ran the loop · ${failed.join(", ")} failed`, "The other steps finished. Check the engine log, then run the loop again.");
        else toast("gain", `Ran the loop · ${r.events_logged} brain events`, `${r.outcomes_measured} outcomes measured in ${(r.duration_ms / 1000).toFixed(1)} s.`);
      },
      onError: (e) => toast("loss", "The loop did not run", `${e instanceof ApiError ? e.detail : "Something went wrong."} Start the backend and try again.`),
    });
  return { run, running: refresh.isPending };
}
