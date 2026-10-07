"use client";

import { channelDisplay } from "@/lib/names";
import { inrDay, pct, ratio } from "@/lib/format";
import { CALLOUTS, type Linked, type PitchRef } from "@/lib/pitch/links";
import type { CalloutId, PitchData } from "@/lib/pitch/data";
import { usePitchStore } from "@/lib/pitch/store";
import { cn } from "@/lib/utils";

export const TINT: Record<CalloutId, string> = {
  perception: "var(--region-ingest)",
  reasoning: "var(--region-diagnose)",
  prediction: "var(--synapse)",
  decision: "var(--region-decide)",
  memory: "var(--region-learn)",
};

/** Where each card sits around the brain on wide screens (the card overlays the canvas margin). */
const POS: Record<CalloutId, string> = {
  perception: "min-[1200px]:left-3 min-[1200px]:top-[17%]",
  reasoning: "min-[1200px]:left-1/2 min-[1200px]:top-3 min-[1200px]:-translate-x-1/2",
  decision: "min-[1200px]:right-3 min-[1200px]:top-[17%]",
  prediction: "min-[1200px]:right-3 min-[1200px]:bottom-3",
  memory: "min-[1200px]:left-3 min-[1200px]:bottom-3",
};

function content(id: CalloutId, d: PitchData): { key: string; fact: string } {
  const x = d.derived;
  switch (id) {
    case "perception": {
      const over = x.overReport.map((o, i) => (i === 0 ? `${o.label.replace(/ Ads$/, "")} over-reports ${pct(o.pct)}` : `${o.label.replace(/ Ads$/, "")} ${pct(o.pct)}`)).join(", ");
      return { key: `${x.sourceCount} sources live`, fact: `Data trust ${pct(x.dataTrust)}${over ? `; ${over}` : "; every platform matches the store"}` };
    }
    case "reasoning":
      return { key: `${x.signals} signals`, fact: `${x.topAnomaly ? `Biggest: ${x.topAnomalyLabel} (${inrDay(x.topAnomaly.profit_impact)}); ` : ""}${x.found === null ? "" : `${x.found} of ${x.expected} planted problems found`}` };
    case "prediction": {
      const o = x.bestOpp;
      return { key: `${x.ideas} untested ideas scored`, fact: o ? `Best: ${o.sku_name} on ${channelDisplay(o.channel)}, predicted POAS ${ratio(o.predicted_poas)}; model R² ${x.r2?.toFixed(2)} on held-out campaigns` : "No untested idea scored yet" };
    }
    case "decision":
      return { key: `${x.pending} decisions, up to ${inrDay(x.upside)}`, fact: `${x.needsApproval} need approval, ${x.auto} run automatically, ${x.blocked} blocked` };
    case "memory":
      return { key: `Forecast error ${pct(x.mape)}`, fact: `Calibration ×${x.factor?.toFixed(2) ?? "—"}, win-rate ${pct(x.winRate)}, ${x.outcomes} outcomes measured` };
  }
}

interface Props {
  data: PitchData;
  linked: Linked | null;
  /** the callout the shared player is pulsing right now */
  active: CalloutId | null;
  focused: CalloutId | null;
  onFocus: (r: PitchRef) => void;
}

export default function Callouts({ data, linked, active, focused, onFocus }: Props) {
  const setHover = usePitchStore((s) => s.setHover);
  return (
    <>
      {CALLOUTS.map((c) => {
        const k = content(c.id, data);
        const on = active === c.id || focused === c.id || !!linked?.callouts.has(c.id);
        const dim = linked && !linked.callouts.has(c.id) && focused !== c.id;
        return (
          <button
            key={c.id}
            data-pitch={`callout:${c.id}`}
            data-keep
            aria-label={`${c.label}: ${c.does}. ${k.key}. ${k.fact}`}
            onPointerEnter={() => setHover({ kind: "callout", id: c.id })}
            onPointerLeave={() => setHover(null)}
            onFocus={() => setHover({ kind: "callout", id: c.id })}
            onBlur={() => setHover(null)}
            onClick={() => onFocus({ kind: "callout", id: c.id })}
            style={{ borderLeftColor: on ? TINT[c.id] : undefined, borderLeftWidth: on ? 3 : 1 }}
            className={cn(
              "panel z-20 w-full p-2.5 text-left transition-opacity duration-150 hover:border-fog min-[1200px]:absolute min-[1200px]:w-[172px]",
              POS[c.id],
              dim && "opacity-55",
            )}
          >
            <div className="text-sm font-bold">{c.label}</div>
            <div className="text-xs text-fog">{c.does}</div>
            <div className="mt-1 text-lg leading-tight font-bold">{k.key}</div>
            <p className="mt-0.5 line-clamp-4 text-xs leading-snug text-fog">{k.fact}</p>
          </button>
        );
      })}
    </>
  );
}
