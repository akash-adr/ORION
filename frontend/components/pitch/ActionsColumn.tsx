"use client";

import { Boxes, Gavel, Lock, Palette, Rocket, Tag, Wrench, type LucideIcon } from "lucide-react";
import Link from "next/link";
import CampaignName from "@/components/CampaignName";
import { ConfidenceMeter } from "@/components/charts";
import { inr, inrDay } from "@/lib/format";
import { parseDecisionTitle } from "@/lib/names";
import type { PitchData } from "@/lib/pitch/data";
import type { ActionGroupId } from "@/lib/pitch/data";
import type { Linked, PitchRef } from "@/lib/pitch/links";
import { usePitchStore } from "@/lib/pitch/store";
import { cn } from "@/lib/utils";

const ICON: Record<ActionGroupId, LucideIcon> = { protect: Boxes, creative: Palette, rebalance: Gavel, price: Tag, launch: Rocket, data: Wrench };

function TopRecommendation({ data }: { data: PitchData }) {
  const d = data.derived.topRec;
  const cfg = data.cfg;
  if (!d) return <p className="text-sm text-fog">No decision is waiting. Run the loop now to look again.</p>;
  const t = parseDecisionTitle(d.title);
  return (
    <div className="rounded-lg border border-line p-2.5" data-pitch="top-recommendation">
      <div className="text-xs text-fog">Top recommendation</div>
      <div className="mt-0.5 flex flex-wrap items-center gap-x-2 text-sm">
        <span className="font-bold">{t.action}</span>
        {t.campaign && <CampaignName name={`${t.campaign.channelName} · ${t.campaign.product} · ${t.campaign.audience}`} />}
        {t.subject && <span className="text-fog">{t.subject}</span>}
      </div>
      <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="text-base font-bold tone-gain">{"\u2191"} {inrDay(d.expected_profit_delta)}</span>
        <ConfidenceMeter value={d.confidence} min={cfg?.guardrails.CONFIDENCE_MIN ?? 0.45} max={cfg?.guardrails.CONFIDENCE_MAX ?? 0.95} />
      </div>
      <div className="mt-1 flex flex-wrap gap-1.5 text-xs">
        <span className="rounded-full border border-line px-2 py-px">{d.risk === "high" ? "High risk" : d.risk === "medium" ? "Medium risk" : "Low risk"}</span>
        <span className="rounded-full border border-line px-2 py-px">{d.requires_approval ? "Needs approval" : "Runs automatically"}</span>
        {d.blocked && (
          <span className="inline-flex items-center gap-1 rounded-full border border-line px-2 py-px font-semibold tone-loss">
            <Lock className="size-3" aria-hidden />
            Blocked by a guardrail
          </span>
        )}
      </div>
      <div className="mt-1.5 flex gap-1.5">
        {d.anomaly_id && (
          <Link href={`/diagnosis?anomaly=${d.anomaly_id}`} className="inline-flex h-7 items-center rounded-lg border border-line px-2.5 text-sm font-semibold hover:bg-slate-2">
            Why?
          </Link>
        )}
        <Link href={`/command?decision=${encodeURIComponent(d.id)}`} className="inline-flex h-7 items-center rounded-lg bg-primary px-2.5 text-sm font-semibold text-primary-foreground hover:bg-primary/85">
          Open decision
        </Link>
      </div>
    </div>
  );
}

export default function ActionsColumn({ data, linked, onFocus, activeType }: { data: PitchData; linked: Linked | null; onFocus: (r: PitchRef) => void; activeType: string | null }) {
  const setHover = usePitchStore((s) => s.setHover);
  const groups = data.derived.groups;
  return (
    <section aria-label="Actions" className={cn("panel flex h-full min-h-0 flex-col overflow-hidden p-3 transition-opacity duration-150", linked && linked.actions.size === 0 && !linked.callouts.has("decision") && "opacity-55")}>
      <h2 className="mb-2 flex items-baseline justify-between text-base font-bold">
        Actions <span className="text-xs font-normal text-fog">Expected per day</span>
      </h2>
      <ul className="grid gap-0.5">
        {groups.map((g) => {
          const Icon = ICON[g.id];
          const dim = linked && linked.actions.size > 0 && !linked.actions.has(g.id);
          const live = activeType !== null && g.decisions.some((d) => d.action.type === activeType);
          const parts = [g.waiting ? `${g.waiting} waiting approval` : null, g.automatic ? `${g.automatic} run automatically` : null, g.executed ? `${g.executed} executed` : null].filter(Boolean);
          return (
            <li key={g.id}>
              <button
                data-pitch={`action:${g.id}`}
                onPointerEnter={() => setHover({ kind: "action", id: g.id })}
                onPointerLeave={() => setHover(null)}
                onFocus={() => setHover({ kind: "action", id: g.id })}
                onBlur={() => setHover(null)}
                onClick={() => onFocus({ kind: "action", id: g.id })}
                className={cn("grid w-full grid-cols-[16px_minmax(0,1fr)] items-start gap-x-2 rounded-lg border border-transparent px-2 py-0.5 text-left text-sm hover:border-line hover:bg-slate-2", (linked?.actions.has(g.id) || live) && "border-line bg-slate-2", dim && "opacity-55")}
              >
                <Icon className="mt-0.5 size-4 text-fog" aria-hidden />
                <span className="min-w-0">
                  <span className="flex items-baseline justify-between gap-2">
                    <span className="flex min-w-0 items-center gap-1.5 font-semibold">
                      <span>{g.label}</span>
                      {g.blocked && <Lock className="size-3 shrink-0 tone-risk" aria-label="Blocked" />}
                    </span>
                    <span className={cn("shrink-0 text-sm font-bold whitespace-nowrap", g.total >= 0 ? "tone-gain" : "tone-loss")}>{g.count ? <>{g.total >= 0 ? "\u2191" : "\u2193"} {inr(Math.abs(g.total))}</> : <span className="font-normal text-fog">—</span>}</span>
                  </span>
                  <span className="block text-xs text-fog">{parts.length ? parts.join(", ") : "Nothing yet"}</span>
                </span>
              </button>
            </li>
          );
        })}
      </ul>
      <div className="mt-2 min-h-0 flex-1 overflow-y-auto">
        <TopRecommendation data={data} />
      </div>
    </section>
  );
}
