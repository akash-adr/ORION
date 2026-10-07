import { ArrowDown, ArrowUp } from "lucide-react";
import { inr } from "@/lib/format";
import { cn } from "@/lib/utils";

/** A signed ₹ amount with an arrow and tone, so the sign never rests on colour alone. */
export default function Money({ v, unit = "/day", className }: { v: number | null | undefined; unit?: string; className?: string }) {
  if (v === null || v === undefined || !Number.isFinite(v)) return <span className="text-fog">—</span>;
  if (Math.abs(v) < 0.5) return <span className={className}>₹0{unit}</span>;
  const Icon = v < 0 ? ArrowDown : ArrowUp;
  return (
    <span className={cn("inline-flex items-center gap-0.5 font-semibold whitespace-nowrap", v < 0 ? "tone-loss" : "tone-gain", className)}>
      <Icon className="size-3.5" aria-hidden />
      {v < 0 ? "\u2212" : ""}
      {inr(Math.abs(v))}
      <span className="font-normal text-fog">{unit}</span>
    </span>
  );
}
