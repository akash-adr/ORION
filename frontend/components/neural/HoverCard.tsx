"use client";

import { Lock } from "lucide-react";
import CampaignName from "@/components/CampaignName";
import { HeadroomChip } from "@/components/chips";
import { inrDay, pct, ratio } from "@/lib/format";
import type { MapPick } from "@/lib/brain/types";

const HEALTH_WORD: Record<string, string> = { good: "Healthy", weak: "Weak", losing: "Losing money" };

/** The card that follows the pointer over any item on the map. Always dark, like the canvas it sits on. */
export default function HoverCard({ pick, at }: { pick: MapPick; at: { x: number; y: number } }) {
  const left = Math.min(at.x + 14, (typeof window === "undefined" ? 0 : window.innerWidth) - 290);
  const top = at.y + 14;
  return (
    <div role="tooltip" className="float-layer dark-capsule pointer-events-none fixed z-50 w-72 p-3 text-sm" style={{ left, top }}>
      {pick.kind === "neuron" && (
        <>
          <div className="mb-1">{pick.node.entity_type === "campaign" ? <CampaignName name={pick.node.label} channel={pick.node.channel} /> : <span className="font-bold">{pick.node.label}</span>}</div>
          <dl className="grid grid-cols-2 gap-x-3 gap-y-0.5">
            <dt className="text-fog">Ad spend</dt>
            <dd className="font-semibold">{inrDay(pick.node.spend_7d)}</dd>
            <dt className="text-fog">Profit on spend</dt>
            <dd className="font-semibold">{ratio(pick.node.poas_7d)}</dd>
            {pick.node.roas_true_7d !== null && (
              <>
                <dt className="text-fog">Verified vs claimed ROAS</dt>
                <dd className="font-semibold">
                  {ratio(pick.node.roas_true_7d)} vs {ratio(pick.node.roas_platform_7d)}
                </dd>
              </>
            )}
            {pick.node.trust_score !== null && (
              <>
                <dt className="text-fog">Data trust</dt>
                <dd className="font-semibold">{pct(pick.node.trust_score)}</dd>
              </>
            )}
            {pick.node.days_cover !== null && (
              <>
                <dt className="text-fog">Stock cover</dt>
                <dd className="font-semibold">{pick.node.days_cover.toFixed(1)} days</dd>
              </>
            )}
            <dt className="text-fog">Health</dt>
            <dd className="font-semibold">{HEALTH_WORD[pick.node.health] ?? pick.node.health}</dd>
            {pick.node.planned_change_pct !== null && (
              <>
                <dt className="text-fog">Planned change</dt>
                <dd className="font-semibold">{pick.node.planned_change_pct < 0 ? "↓ " : "↑ "}{pct(Math.abs(pick.node.planned_change_pct))}</dd>
              </>
            )}
          </dl>
          <div className="mt-1.5 flex items-center gap-2">
            <HeadroomChip h={pick.node.headroom} />
            {pick.node.stock_locked && (
              <span className="inline-flex items-center gap-1 text-xs tone-risk">
                <Lock className="size-3" aria-hidden />
                Locked by the stock guard
              </span>
            )}
          </div>
          {pick.node.why && <p className="narrative mt-2 !text-[13px] text-fog">{pick.node.why}</p>}
          <div className="mt-1.5 text-xs text-fog">Last 7 days, per day. Click for details.</div>
        </>
      )}
      {pick.kind === "cluster" && (
        <>
          <div className="font-bold">{pick.cluster.label}</div>
          <p className="mt-1 text-fog">{pick.cluster.alert ? pick.cluster.alert.message : "No alert on this channel."}</p>
          <div className="mt-1.5 text-xs text-fog">Click for the channel&apos;s campaigns.</div>
        </>
      )}
      {pick.kind === "source" && (
        <>
          <div className="font-bold">{pick.source.label}</div>
          <p className="mt-1 text-fog">
            {pick.source.status === "warn" ? `Needs attention. Trust ${pct(pick.source.trust_score)}.` : "Healthy."}
            {pick.source.verified ? " Store-verified." : ""}
          </p>
          <div className="mt-1.5 text-xs text-fog">Click for its row in Data truth.</div>
        </>
      )}
      {pick.kind === "ghost" && (
        <>
          <div className="font-bold">{pick.ghost.launched ? "Test running" : "Untested idea"}</div>
          <p className="mt-1 text-fog">{pick.ghost.id}</p>
          <p className="mt-1">Predicted profit on spend {ratio(pick.ghost.predicted_poas)}</p>
          <div className="mt-1.5 text-xs text-fog">Click for the details and the launch decision.</div>
        </>
      )}
    </div>
  );
}
