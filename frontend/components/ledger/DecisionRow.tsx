"use client";

import { Boxes, ChevronRight, Gavel, Info, LoaderCircle, Lock, Palette, Rocket, Tag, TrendingDown, TrendingUp, TriangleAlert, Wrench, Zap, type LucideIcon } from "lucide-react";
import CampaignName from "@/components/CampaignName";
import { STATUS_LABEL } from "@/lib/decision";
import { inr, pct } from "@/lib/format";
import { actionTypeDisplay, parseDecisionTitle } from "@/lib/names";
import type { Decision } from "@/lib/types";
import { cn } from "@/lib/utils";
import DecisionTrace from "./DecisionTrace";
import { useDecisionActions } from "./useDecisionActions";

const ICONS: Record<string, LucideIcon> = {
  inventory_protect: Boxes,
  creative_refresh: Palette,
  price_review: Tag,
  budget_cut: TrendingDown,
  bid_cap: Gavel,
  launch_test: Rocket,
  scale_up: TrendingUp,
  data_fix: Wrench,
};

const Chip = ({ children, className, title }: { children: React.ReactNode; className?: string; title?: string }) => (
  <span title={title} className={cn("inline-flex items-center gap-1 rounded-full border border-line px-2 py-px text-xs whitespace-nowrap", className)}>
    {children}
  </span>
);

interface Props {
  d: Decision;
  open: boolean;
  onToggle: () => void;
}

/** One ledger row: collapsed summary with actions; expands into the decision trace. */
export default function DecisionRow({ d, open, onToggle }: Props) {
  const act = useDecisionActions(d);
  const Icon = ICONS[d.action.type] ?? Wrench;
  const title = parseDecisionTitle(d.title);
  const handled = d.status !== "pending";
  const gain = d.expected_profit_delta >= 0;
  const bodyId = `trace-${d.id}`;

  return (
    <li className={cn("border-b border-line last:border-b-0", open && "bg-slate-2/40")}>
      <div className="grid items-start gap-x-4 gap-y-2 px-4 py-3 min-[1200px]:grid-cols-[minmax(0,1fr)_auto]">
        <button onClick={onToggle} aria-expanded={open} aria-controls={bodyId} className="flex min-w-0 items-start gap-3 rounded-lg text-left">
          <span className="mt-0.5 grid size-8 shrink-0 place-items-center rounded-lg border border-line bg-slate-2" aria-hidden>
            <Icon className="size-4 text-synapse-fg" />
          </span>
          <span className="min-w-0 flex-1">
            <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
              <ChevronRight className={cn("size-4 shrink-0 text-fog transition-transform duration-200", open && "rotate-90")} aria-hidden />
              <span className="font-bold">{title.action}</span>
              {title.campaign && <CampaignName name={`${title.campaign.channelName} · ${title.campaign.product} · ${title.campaign.audience}`} />}
              {title.subject && <span className="text-fog">{title.subject}</span>}
            </span>
            <span className="mt-1.5 flex flex-wrap items-center gap-1.5">
              <Chip className="text-fog">{actionTypeDisplay(d.action.type)}</Chip>
              {d.risk === "high" && (
                <Chip className="font-semibold tone-risk">
                  <TriangleAlert className="size-3" aria-hidden />
                  High risk
                </Chip>
              )}
              {d.risk === "medium" && <Chip className="tone-risk">Medium risk</Chip>}
              {d.risk === "low" && <Chip className="text-fog">Low risk</Chip>}
              <Chip>{pct(d.confidence)} confident</Chip>
              {!handled && (d.requires_approval ? <Chip>Needs approval</Chip> : (
                <Chip>
                  <Zap className="size-3" aria-hidden />
                  Runs automatically
                </Chip>
              ))}
              {d.blocked && (
                <Chip className="font-semibold tone-loss">
                  <Lock className="size-3" aria-hidden />
                  Blocked
                </Chip>
              )}
              {handled && <Chip className={cn("font-semibold", d.status === "executed" ? "tone-gain" : "text-fog")}>{STATUS_LABEL[d.status] ?? d.status}</Chip>}
            </span>
            {d.action.notes[0] && (
              <span className="mt-2 flex items-start gap-1.5 rounded-lg border border-line bg-slate px-2.5 py-1.5 text-sm text-fog">
                <Info className="mt-0.5 size-3.5 shrink-0 text-fog" aria-hidden />
                {d.action.notes[0]}
              </span>
            )}
          </span>
        </button>

        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 min-[1200px]:flex-col min-[1200px]:items-end min-[1200px]:gap-2">
          <div className="min-[1200px]:text-right">
            <div className={cn("text-base font-bold whitespace-nowrap", gain ? "tone-gain" : "tone-loss")}>
              {gain ? "↑" : "↓"} {inr(Math.abs(d.expected_profit_delta))}
              <span className="ml-1 text-sm font-semibold text-fog">/day</span>
            </div>
            {Math.abs(d.calibration_factor - 1) >= 0.005 && <div className="text-xs text-fog">calibrated ×{d.calibration_factor.toFixed(2)}</div>}
          </div>
          <div className="flex items-center gap-2">
            {!handled && (
              <>
                <button
                  onClick={act.approve}
                  disabled={act.busy || act.advisory || d.blocked}
                  className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-primary px-3 text-sm font-semibold text-primary-foreground hover:bg-primary/85 disabled:opacity-50"
                >
                  {act.pending.approve && <LoaderCircle className="size-3.5 animate-spin" aria-hidden />}
                  Approve
                </button>
                <button onClick={act.reject} disabled={act.busy} className="inline-flex h-8 items-center rounded-lg border border-line px-3 text-sm font-semibold hover:bg-slate-2 disabled:opacity-50">
                  Reject
                </button>
              </>
            )}
            {d.status === "executed" && (
              <button onClick={act.rollback} disabled={act.busy} className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-line px-3 text-sm font-semibold hover:bg-slate-2 disabled:opacity-50">
                {act.pending.rollback && <LoaderCircle className="size-3.5 animate-spin" aria-hidden />}
                Roll back
              </button>
            )}
          </div>
          {!handled && (act.advisory || d.blocked) && (
            <div className="max-w-[240px] text-xs text-fog min-[1200px]:text-right">
              {act.advisory ? "Advisory mode never executes decisions." : "Blocked by a hard guardrail, so it can't be approved."}
            </div>
          )}
        </div>
      </div>
      {open && (
        <div id={bodyId} className="px-4 pt-1 pb-5 min-[1200px]:pl-[60px]">
          <DecisionTrace d={d} />
        </div>
      )}
    </li>
  );
}

