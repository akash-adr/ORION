"use client";

import { BadgeCheck, CircleCheck, Filter, Megaphone, ShoppingBag, Tag, TriangleAlert, Warehouse, type LucideIcon } from "lucide-react";
import { Fragment } from "react";
import { num, pct } from "@/lib/format";
import type { PitchData } from "@/lib/pitch/data";
import type { Linked, PitchRef } from "@/lib/pitch/links";
import { usePitchStore } from "@/lib/pitch/store";
import type { SourceRow } from "@/lib/types";
import { cn } from "@/lib/utils";

const GROUPS: { kind: SourceRow["kind"]; title: string }[] = [
  { kind: "ad_platform", title: "Ad platforms" },
  { kind: "store", title: "Store orders" },
  { kind: "erp", title: "Inventory (ERP)" },
  { kind: "analytics", title: "GA4 funnel" },
  { kind: "pricing", title: "Pricing" },
];
const ICON: Record<string, LucideIcon> = { ad_platform: Megaphone, store: ShoppingBag, erp: Warehouse, analytics: Filter, pricing: Tag };

export default function InputsColumn({ data, linked, onFocus }: { data: PitchData; linked: Linked | null; onFocus: (r: PitchRef) => void }) {
  const setHover = usePitchStore((s) => s.setHover);
  const rows = data.q.sources.data ?? [];
  const snapSources = new Map((data.snapshot?.sources ?? []).map((s) => [s.id, s]));
  return (
    <section aria-label="Inputs" className={cn("panel flex h-full min-h-0 flex-col overflow-hidden p-3 transition-opacity duration-150", linked && !linked.callouts.has("perception") && linked.sources.size === 0 && "opacity-55")}>
      <h2 className="mb-1.5 text-base font-bold">Inputs</h2>
      <div className="min-h-0 flex-1 overflow-y-auto pr-1">
        {GROUPS.map((g) => {
          const items = rows.filter((r) => r.kind === g.kind);
          if (!items.length) return null;
          return (
            <Fragment key={g.kind}>
              {items.length > 1 && <h3 className="mb-1 text-xs font-semibold text-fog">{g.title}</h3>}
              <ul className="grid gap-0.5">
                {items.map((s) => {
                  const Icon = ICON[s.kind];
                  const bs = snapSources.get(s.source_id);
                  const warn = s.status === "warn";
                  const dim = linked && linked.sources.size > 0 && !linked.sources.has(s.source_id);
                  return (
                    <li key={s.source_id}>
                      <button
                        data-pitch={`source:${s.source_id}`}
                        onPointerEnter={() => setHover({ kind: "source", id: s.source_id })}
                        onPointerLeave={() => setHover(null)}
                        onFocus={() => setHover({ kind: "source", id: s.source_id })}
                        onBlur={() => setHover(null)}
                        onClick={() => onFocus({ kind: "callout", id: "perception" })}
                        className={cn("block w-full rounded-lg border border-transparent px-2 py-1 text-left text-sm hover:border-line hover:bg-slate-2", linked?.sources.has(s.source_id) && "border-line bg-slate-2", dim && "opacity-55")}
                      >
                        <span className="min-w-0">
                          <span className="flex items-center justify-between gap-3">
                            <span className="flex min-w-0 items-center gap-1.5">
                              <Icon className="size-3.5 shrink-0 text-fog" aria-hidden />
                              <span className="font-semibold whitespace-nowrap">{s.label}</span>
                              {s.verified && <BadgeCheck className="size-3.5 shrink-0 tone-gain" aria-label="Store-verified" />}
                            </span>
                            <span className={cn("inline-flex shrink-0 items-center gap-1 text-xs font-semibold", warn ? "tone-risk" : "tone-gain")}>
                              {warn ? <TriangleAlert className="size-3" aria-hidden /> : <CircleCheck className="size-3" aria-hidden />}
                              {warn ? "Check" : "Live"}
                            </span>
                          </span>
                          <span className={cn("block pl-5 text-xs", warn ? "tone-risk" : "text-fog")}>
                            {num(s.rows)} rows
                            {s.kind === "ad_platform" && bs ? `, ${(bs.inflation_pct ?? 0) >= 0.005 ? `${pct(bs.inflation_pct)} over, ` : ""}trust ${pct(bs.trust_score)}` : ""}
                            {s.verified ? ", Store-verified" : ""}
                          </span>
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            </Fragment>
          );
        })}
      </div>
    </section>
  );
}
