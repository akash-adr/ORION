"use client";

import { Info } from "lucide-react";
import { LoadState } from "@/components/Panel";
import { inr, pct } from "@/lib/format";
import { useLearning, useMetaConfig } from "@/lib/queries";
import { cn } from "@/lib/utils";

function Cell({ label, value, children, valueTone }: { label: string; value: string; children: React.ReactNode; valueTone?: "gain" | "loss" }) {
  return (
    <div className="bg-slate px-4 py-4 min-[1200px]:px-5">
      <div className="text-sm font-semibold">{label}</div>
      <div className={cn("t-kpi mt-2", valueTone === "gain" && "tone-gain", valueTone === "loss" && "tone-loss")}>{value}</div>
      <div className="mt-1.5 text-sm text-fog">{children}</div>
    </div>
  );
}

/** The learning KPIs as one strip, with the standing honesty note about simulated outcomes. */
export default function LearningKpis() {
  const q = useLearning();
  const cfg = useMetaConfig().data;
  return (
    <div className="grid gap-3">
      <LoadState q={q} what="the learning numbers" height={120}>
        {(l) => {
          const k = l.kpis;
          const w = cfg?.learning.CALIBRATION_WINDOW ?? l.calibration.n;
          return (
            <section aria-label="Learning at a glance" className="panel overflow-hidden">
              <div className="grid grid-cols-2 gap-px bg-line min-[1000px]:grid-cols-4">
                <Cell label="Forecast error" value={pct(k.forecast_error)}>
                  Average miss over the last {w} outcomes. Lower is better.
                </Cell>
                <Cell label="Calibration factor" value={k.calibration_factor === null ? "—" : `×${k.calibration_factor.toFixed(2)}`}>
                  Every predicted ₹ is multiplied by this, so a hopeful engine promises less.
                </Cell>
                <Cell label="Win rate" value={pct(k.win_rate)}>
                  Share of the last {w} outcomes that earned a profit.
                </Cell>
                <Cell label="Measured profit" value={inr(k.total_measured_profit)} valueTone={k.total_measured_profit >= 0 ? "gain" : "loss"}>
                  Across {k.measured_count} measured outcomes, per day.
                </Cell>
              </div>
            </section>
          );
        }}
      </LoadState>
      <p className="flex items-start gap-1.5 text-sm text-fog">
        <Info className="mt-0.5 size-3.5 shrink-0" aria-hidden />
        Outcomes in this demo are simulated with a fixed seed. In production they&apos;re measured against a holdout or synthetic control after 7 days.
      </p>
    </div>
  );
}
