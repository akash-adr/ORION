"use client";

import { LineChart } from "@/components/charts";
import { LoadState, Panel } from "@/components/Panel";
import { dateShort, inr, pct } from "@/lib/format";
import { useLearning } from "@/lib/queries";

export default function LearningCharts() {
  const q = useLearning();
  return (
    <div className="grid gap-5 min-[1200px]:grid-cols-2">
      <Panel title="Forecast error over time" note="Rolling average miss, lower is better">
        <LoadState q={q} what="the forecast error" height={280}>
          {(l) => {
            const pts = l.accuracy_curve;
            const first = pts.find((p) => p.rolling_mape !== null);
            const last = [...pts].reverse().find((p) => p.rolling_mape !== null);
            const better = first && last && last.rolling_mape! < first.rolling_mape!;
            return (
              <>
                <LineChart
                  x={pts.map((p) => p.date)}
                  xFormat={dateShort}
                  series={[{ id: "mape", label: "Forecast error", color: "var(--synapse)", data: pts.map((p) => p.rolling_mape) }]}
                  format={(v) => pct(v)}
                  events={[...(first ? [{ x: first.date, label: `Start ${pct(first.rolling_mape)}` }] : []), ...(last && last !== first ? [{ x: last.date, label: `Now ${pct(last.rolling_mape)}` }] : [])]}
                  height={240}
                  summary={`Rolling forecast error over ${pts.length} measured decisions, from ${pct(first?.rolling_mape ?? null)} to ${pct(last?.rolling_mape ?? null)}.`}
                />
                {first && last && first !== last && (
                  <p className="mt-2 text-sm text-fog">
                    {better ? "The engine is getting more accurate" : "The engine is getting less accurate"}: the average miss went from {pct(first.rolling_mape)} to {pct(last.rolling_mape)}.
                  </p>
                )}
              </>
            );
          }}
        </LoadState>
      </Panel>
      <Panel title="Measured profit, adding up" note="Per day, across measured outcomes">
        <LoadState q={q} what="the measured profit" height={280}>
          {(l) => {
            const c = l.cumulative_profit;
            return (
              <LineChart
                x={c.map((p) => p.date)}
                xFormat={dateShort}
                series={[{ id: "cum", label: "Cumulative profit", color: "var(--gain)", data: c.map((p) => p.cumulative), area: true }]}
                format={inr}
                height={240}
                summary={`Cumulative measured profit per day across ${c.length} outcomes, ending at ${inr(c[c.length - 1]?.cumulative ?? null)}.`}
              />
            );
          }}
        </LoadState>
      </Panel>
    </div>
  );
}
