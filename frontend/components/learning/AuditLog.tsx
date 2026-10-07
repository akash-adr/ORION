"use client";

import { ChevronRight, CircleCheck, CircleX, LoaderCircle, Undo2, Zap } from "lucide-react";
import { Fragment, useState } from "react";
import { EmptyState, LoadState, Panel } from "@/components/Panel";
import { ApiError } from "@/lib/api";
import { dateShort, inr, pct, timeShort } from "@/lib/format";
import { useAudit, useRecommendations, useRollback } from "@/lib/queries";
import { useUiStore } from "@/lib/ui-store";
import type { AuditEntry } from "@/lib/types";
import { cn } from "@/lib/utils";

const ACTION = {
  execute: { label: "Executed", Icon: CircleCheck, cls: "tone-gain" },
  reject: { label: "Rejected", Icon: CircleX, cls: "text-fog" },
  rollback: { label: "Rolled back", Icon: Undo2, cls: "tone-risk" },
} as const;

function RollbackButton({ id }: { id: string }) {
  const rollback = useRollback();
  const toast = useUiStore((s) => s.toast);
  return (
    <button
      onClick={(e) => {
        e.stopPropagation();
        rollback.mutate(id, {
          onSuccess: (r) => (r.ok ? toast("gain", `Rolled back · ${r.api_calls.length} ${r.api_calls.length === 1 ? "budget" : "budgets"} restored`) : toast("risk", "Not rolled back", r.reason)),
          onError: (err) => toast("loss", "Roll back did not go through", err instanceof ApiError ? err.detail : undefined),
        });
      }}
      disabled={rollback.isPending}
      className="inline-flex h-7 items-center gap-1.5 rounded-lg border border-line px-2.5 text-sm font-semibold hover:bg-slate-2 disabled:opacity-60"
    >
      {rollback.isPending ? <LoaderCircle className="size-3.5 animate-spin" aria-hidden /> : <Undo2 className="size-3.5" aria-hidden />}
      Roll back
    </button>
  );
}

export default function AuditLog() {
  const q = useAudit();
  const recs = useRecommendations().data;
  const [open, setOpen] = useState<string | null>(null);
  return (
    <Panel title="Audit log" note="Every change the engine sent, newest first">
      <LoadState q={q} what="the audit log" height={160}>
        {(rows) => {
          if (!rows.length) return <EmptyState title="Nothing has been sent yet" hint="Approve a decision on the Command page and it is recorded here, with a way to roll it back." />;
          // the API already returns the newest entry first
          const entries = rows.map((r, i) => ({ r, i }));
          const executed = new Set((recs?.recommendations ?? []).filter((d) => d.status === "executed").map((d) => d.id));
          const latestExec = new Map<string, number>();
          rows.forEach((r, i) => r.action === "execute" && !latestExec.has(r.decision_id) && latestExec.set(r.decision_id, i));
          return (
            <div className="overflow-x-auto">
              <table className="tbl min-w-[880px]">
                <thead>
                  <tr>
                    <th className="w-8" aria-label="Details" />
                    <th>When</th>
                    <th>Action</th>
                    <th>Decision</th>
                    <th>By</th>
                    <th className="num">Expected</th>
                    <th className="num">Confidence</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {entries.map(({ r, i }) => {
                    const a = ACTION[r.action as keyof typeof ACTION] ?? ACTION.execute;
                    const key = `${r.decision_id}-${i}`;
                    const calls = r.api_calls ?? [];
                    const isOpen = open === key;
                    const canRollBack = r.action === "execute" && latestExec.get(r.decision_id) === i && executed.has(r.decision_id);
                    return (
                      <Fragment key={key}>
                        <tr className={cn(calls.length && "cursor-pointer hover:bg-slate-2/60")} onClick={() => calls.length && setOpen(isOpen ? null : key)}>
                          <td className="!pr-0">
                            {calls.length > 0 && (
                              <button aria-expanded={isOpen} aria-label={isOpen ? "Hide API calls" : "Show API calls"} onClick={(e) => (e.stopPropagation(), setOpen(isOpen ? null : key))} className="rounded p-1 text-fog hover:text-bone">
                                <ChevronRight className={cn("size-4 transition-transform duration-200", isOpen && "rotate-90")} aria-hidden />
                              </button>
                            )}
                          </td>
                          <td className="whitespace-nowrap">{dateShort(r.ts)}, {timeShort(r.ts)}</td>
                          <td><span className={cn("inline-flex items-center gap-1 font-semibold", a.cls)}><a.Icon className="size-3.5" aria-hidden />{a.label}</span></td>
                          <td className="font-semibold">{r.title}</td>
                          <td>
                            {r.approver === "autopilot" ? (
                              <span className="inline-flex items-center gap-1 rounded-full border border-line px-2 py-px text-xs font-semibold"><Zap className="size-3 tone-risk" aria-hidden />Autopilot</span>
                            ) : (
                              "You"
                            )}
                          </td>
                          <td className="num">{r.expected_profit_delta == null ? "—" : `${inr(r.expected_profit_delta)}/day`}</td>
                          <td className="num">{r.confidence == null ? "—" : pct(r.confidence)}</td>
                          <td className="num">{canRollBack && <RollbackButton id={r.decision_id} />}</td>
                        </tr>
                        {isOpen && <ApiCalls calls={calls} />}
                      </Fragment>
                    );
                  })}
                </tbody>
              </table>
            </div>
          );
        }}
      </LoadState>
    </Panel>
  );
}

function ApiCalls({ calls }: { calls: NonNullable<AuditEntry["api_calls"]> }) {
  return (
    <tr>
      <td colSpan={8} className="!bg-slate-2/30 !p-3">
        <div className="mb-1 text-xs text-fog">{calls.length} {calls.length === 1 ? "call" : "calls"} sent to the ad platforms</div>
        <ul className="grid gap-1 font-mono text-xs">
          {calls.map((c, i) => {
            const { platform, endpoint, method, status, ts, ...rest } = c;
            return (
              <li key={i} className="flex flex-wrap gap-x-3">
                <span className="font-bold">{method}</span>
                <span>{endpoint}</span>
                <span className="text-fog">{Object.entries(rest).map(([k, v]) => `${k}=${typeof v === "number" ? v : JSON.stringify(v)}`).join(" ")}</span>
                <span className={status === "OK" ? "tone-gain" : "tone-loss"}>{status}</span>
                <span className="text-fog">{platform}, {timeShort(ts)}</span>
              </li>
            );
          })}
        </ul>
      </td>
    </tr>
  );
}
