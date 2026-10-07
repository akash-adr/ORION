"use client";

import { ApiError } from "@/lib/api";
import { inrDay } from "@/lib/format";
import { useApprove, useReject, useRollback, useSettings } from "@/lib/queries";
import { useUiStore } from "@/lib/ui-store";
import type { Decision } from "@/lib/types";

const noun = (d: Decision, n: number) => {
  const base = d.action.changes.length ? "budget change" : d.action.type === "launch_test" ? "campaign launch" : "platform setting";
  return `${n} ${base}${n === 1 ? "" : "s"}`;
};

/** Approve / reject / roll back one decision, with the engine's wording in the toast. */
export function useDecisionActions(d: Decision) {
  const toast = useUiStore((s) => s.toast);
  const approve = useApprove();
  const reject = useReject();
  const rollback = useRollback();
  const { data: settings } = useSettings();
  const advisory = settings?.autonomy === "advisory";
  const fail = (what: string) => (e: unknown) => toast("loss", `${what} did not go through`, `${e instanceof ApiError ? e.detail : "Something went wrong."} Check the backend and try again.`);

  const doApprove = (done?: (r: { calls: number; noun: string; outcome: { predicted: number; actual: number } | null }) => void) =>
    approve.mutate(d.id, {
      onSuccess: (r) => {
        if (!r.ok) return toast("risk", "Not approved", r.reason);
        const o = r.outcome;
        toast("gain", `Approved · ${noun(d, r.api_calls.length)} sent to ad APIs`, o && o.actual != null && o.predicted !== 0 ? `Predicted ${inrDay(o.predicted)}, measured ${inrDay(o.actual)} (simulated).` : undefined);
        done?.({ calls: r.api_calls.length, noun: noun(d, r.api_calls.length), outcome: o && o.actual != null ? { predicted: o.predicted, actual: o.actual } : null });
      },
      onError: fail("Approval"),
    });

  return {
    advisory,
    busy: approve.isPending || reject.isPending || rollback.isPending,
    pending: { approve: approve.isPending, reject: reject.isPending, rollback: rollback.isPending },
    approve: () => doApprove(),
    /** Approve, then tell the caller what was sent (the Pitch walkthrough shows it in its caption). */
    approveWith: (done: (r: { calls: number; noun: string; outcome: { predicted: number; actual: number } | null }) => void) => doApprove(done),
    reject: () =>
      reject.mutate(d.id, {
        onSuccess: (r) => (r.ok ? toast("gain", "Rejected · nothing was sent to the ad platforms") : toast("risk", "Not rejected", r.reason)),
        onError: fail("Rejection"),
      }),
    rollback: () =>
      rollback.mutate(d.id, {
        onSuccess: (r) => (r.ok ? toast("gain", `Rolled back · ${noun(d, r.api_calls.length)} restored`) : toast("risk", "Not rolled back", r.reason)),
        onError: fail("Roll back"),
      }),
  };
}
