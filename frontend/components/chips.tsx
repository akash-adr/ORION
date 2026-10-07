import { Lock, Minus, TrendingDown, TrendingUp, TriangleAlert } from "lucide-react";
import Link from "next/link";
import KindIcon from "@/components/KindIcon";
import { kindDisplay } from "@/lib/names";
import type { AnomalyKind, Headroom, Severity } from "@/lib/types";
import { cn } from "@/lib/utils";

const base = "inline-flex items-center gap-1 rounded-full border border-line px-2 py-px text-xs font-semibold whitespace-nowrap";

/** Where the next rupee should go: Scale (room to grow), Hold, Cut (past saturation) or Locked (stock guard). */
export function HeadroomChip({ h }: { h: Headroom | undefined }) {
  if (!h) return <span className="text-fog">—</span>;
  const m = {
    scale: { label: "Scale", Icon: TrendingUp, cls: "tone-gain" },
    hold: { label: "Hold", Icon: Minus, cls: "text-fog" },
    cut: { label: "Cut", Icon: TrendingDown, cls: "tone-loss" },
    locked: { label: "Locked", Icon: Lock, cls: "tone-risk" },
  }[h];
  return (
    <span className={cn(base, m.cls)} title={h === "locked" ? "Spend can't increase: the product is under the stock guard" : undefined}>
      <m.Icon className="size-3" aria-hidden />
      {m.label}
    </span>
  );
}

/** An open anomaly on this entity, linking to its diagnosis. */
export function AlertChip({ kind, anomalyId, severity }: { kind: AnomalyKind | null; anomalyId: string | null; severity?: Severity | null }) {
  if (!kind || !anomalyId) return <span className="text-fog">None</span>;
  return (
    <Link href={`/diagnosis?anomaly=${anomalyId}`} onClick={(e) => e.stopPropagation()} className={cn(base, "hover:border-synapse", severity === "high" ? "tone-risk" : "text-bone")}>
      {severity === "high" ? <TriangleAlert className="size-3" aria-hidden /> : <KindIcon kind={kind} className="size-3" />}
      {kindDisplay(kind)}
    </Link>
  );
}

export function StatusChip({ tone, icon: Icon, children }: { tone: "gain" | "risk" | "loss" | "muted"; icon?: React.ComponentType<{ className?: string; "aria-hidden"?: boolean }>; children: React.ReactNode }) {
  const cls = { gain: "tone-gain", risk: "tone-risk", loss: "tone-loss", muted: "text-fog" }[tone];
  return (
    <span className={cn(base, cls)}>
      {Icon && <Icon className="size-3" aria-hidden />}
      {children}
    </span>
  );
}
