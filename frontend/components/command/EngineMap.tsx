"use client";

import { ArrowUpRight, Lock } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import CampaignName from "@/components/CampaignName";
import LiveBrain from "@/components/brain/live/LiveBrain";
import { LoadState } from "@/components/Panel";
import { useBrainPlayer } from "@/lib/brain/store";
import { useBrainEventPlayer } from "@/lib/brain/usePlayer";
import { inrDay, ratio } from "@/lib/format";
import { useBrainSnapshot } from "@/lib/queries";
import type { BrainNode } from "@/lib/types";

const HEALTH_WORD: Record<string, string> = { good: "Healthy", weak: "Weak", losing: "Losing money" };

function Counter({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <div className="text-xs text-fog">{label}</div>
      <div className="text-xl font-bold">{value}</div>
    </div>
  );
}

/** The compact live brain: the one bold element on /command. Always a dark capsule. */
export default function EngineMap() {
  const q = useBrainSnapshot();
  const router = useRouter();
  const caption = useBrainPlayer((s) => s.caption);
  const mode = useBrainPlayer((s) => s.mode);
  const [hover, setHover] = useState<{ n: BrainNode; x: number; y: number } | null>(null);
  useBrainEventPlayer(true);

  return (
    <section data-engine-map aria-label="Engine map" className="dark-capsule relative overflow-hidden rounded-[14px] border p-4 min-[1200px]:p-5">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="text-base font-bold">Engine map</h2>
          <p className="text-sm text-fog">Every dot is a campaign or product; colour is health, size is spend.</p>
        </div>
        <Link href="/neural" className="inline-flex h-8 items-center gap-1 rounded-lg border border-line px-3 text-sm font-semibold hover:bg-slate-2">
          Open neural view
          <ArrowUpRight className="size-3.5" aria-hidden />
        </Link>
      </div>
      <LoadState q={q} what="the engine map" height={300}>
        {(s) => (
          <>
            <LiveBrain snapshot={s} maxDots={3600} height={300} onHover={(p, at) => setHover(p?.kind === "neuron" && at ? { n: p.node, x: at.x, y: at.y } : null)} onPick={(p) => p.kind === "neuron" && router.push(`/neural?focus=${encodeURIComponent(p.node.entity_id)}`)} />
            <div className="mt-2 flex items-center gap-2 border-t border-line pt-3 text-sm" aria-live="polite">
              <span className={`size-2 shrink-0 rounded-full ${mode === "idle" ? "bg-fog" : "bg-synapse"}`} aria-hidden />
              <span className={mode === "idle" ? "text-fog" : ""}>{caption ?? "Waiting for the next engine event."}</span>
            </div>
            <div className="mt-3 grid grid-cols-3 gap-4">
              <Counter label="Signals" value={s.counts.anomalies} />
              <Counter label="Decisions waiting" value={s.counts.pending_decisions} />
              <Counter label="Outcomes measured" value={s.counts.outcomes} />
            </div>
          </>
        )}
      </LoadState>
      {hover && (
        <div role="tooltip" className="float-layer pointer-events-none fixed z-50 w-64 p-3 text-sm" style={{ left: Math.min(hover.x + 14, (typeof window === "undefined" ? 0 : window.innerWidth) - 280), top: hover.y + 14, background: "#18233a", color: "#e8ecf4", borderColor: "#26324d" }}>
          <div className="mb-1">{hover.n.entity_type === "campaign" ? <CampaignName name={hover.n.label} channel={hover.n.channel} /> : <span className="font-bold">{hover.n.label}</span>}</div>
          <dl className="grid grid-cols-2 gap-x-3 gap-y-0.5">
            <dt className="text-fog">Spend</dt>
            <dd className="font-semibold">{inrDay(hover.n.spend_7d)}</dd>
            <dt className="text-fog">Profit on spend</dt>
            <dd className="font-semibold">{ratio(hover.n.poas_7d)}</dd>
            <dt className="text-fog">Health</dt>
            <dd className="font-semibold">{HEALTH_WORD[hover.n.health] ?? hover.n.health}</dd>
          </dl>
          {hover.n.stock_locked && (
            <div className="mt-1 flex items-center gap-1 text-xs" style={{ color: "#f2a93b" }}>
              <Lock className="size-3" aria-hidden />
              Spend locked by the stock guard
            </div>
          )}
          {hover.n.why && <p className="narrative mt-1.5 !text-[13px] text-fog">{hover.n.why}</p>}
          <div className="mt-1.5 text-xs text-fog">Last 7 days, per day. Click to open in the neural view.</div>
        </div>
      )}
    </section>
  );
}
