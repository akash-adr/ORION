"use client";

import { LineChart } from "@/components/charts";
import { Panel } from "@/components/Panel";
import { dateShort, inr, inrDay, num, pct } from "@/lib/format";
import { useBrainSnapshot } from "@/lib/queries";
import type { CausalResult } from "@/lib/types";

/** Section 5: did the change cause the drop? Actual against what a synthetic control says would have happened anyway. */
export default function CausalProof({ c }: { c: CausalResult }) {
  const snap = useBrainSnapshot().data;
  const post = c.series.filter((s) => s.is_post);
  const names = c.controls.map((id) => snap?.nodes.find((n) => n.entity_id === id)?.label ?? id);
  const verdict = c.ci_includes_zero
    ? "The 95% range includes zero, so the effect on margin is not proven either way."
    : c.total_effect > 0
      ? "The 95% range is above zero: the change earned margin."
      : "The 95% range is below zero: the change cost margin.";
  return (
    <Panel title="Did the change cause it?" note="Method: synthetic control">
      <LineChart
        x={c.series.map((s) => s.date)}
        xFormat={dateShort}
        series={[
          { id: "actual", label: "Actual conversion rate", color: "var(--synapse)", data: c.series.map((s) => s.actual) },
          { id: "cf", label: "Without the change", color: "var(--fog)", dashed: true, data: c.series.map((s) => s.counterfactual) },
        ]}
        bands={post.length ? [{ from: post[0].date, to: post[post.length - 1].date, label: "After the change" }] : []}
        format={(v) => (v === null ? "—" : pct(v, 2))}
        height={230}
        summary={`Site conversion rate for ${c.treated_sku}, actual against what a synthetic control predicts, with the period after the change shaded. ${c.description}. Units ${c.units_change_pct < 0 ? "fell" : "rose"} ${pct(Math.abs(c.units_change_pct))} against the control. Margin effect ${inrDay(c.effect_per_day)}.`}
      />
      <p className="narrative mt-3">
        {c.description}. Units {c.units_change_pct < 0 ? "fell" : "rose"} {pct(Math.abs(c.units_change_pct))} against what the control predicted. The net effect on margin is {inrDay(c.effect_per_day)}, {inr(c.total_effect)} over {num(c.n_post)} days, with a 95% range of {inr(c.ci_low)} to {inr(c.ci_high)}. {verdict}
      </p>
      <p className="mt-2 text-sm text-fog">Built from {names.length} products that were not touched: {names.join(", ")}.</p>
    </Panel>
  );
}
