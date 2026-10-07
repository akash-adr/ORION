"use client";

import { Panel } from "@/components/Panel";
import { PairBars, Waterfall } from "@/components/charts";
import { inr, inrDay, num, pct, ratio } from "@/lib/format";
import { channelDisplay, factorColor } from "@/lib/names";
import { useReconciliation } from "@/lib/queries";
import type { Diagnosis } from "@/lib/types";

/** Sections 2 and 3: the waterfall (or, for attribution, the reconciliation explainer) and the factor table beneath it. */
export default function FactorSection({ d }: { d: Diagnosis }) {
  const rec = useReconciliation().data;
  const a = d.anomaly;
  const rc = d.root_cause;
  const metric = a.entity_type === "sku" ? "gross margin" : "profit";

  if (a.kind === "attribution_inflation") {
    const row = rec?.find((r) => r.channel === a.entity_id);
    const name = channelDisplay(a.entity_id);
    return (
      <Panel title={`Why ${name}'s numbers can't be trusted`} note="Last 7 days">
        {row ? (
          <>
            <PairBars
              aLabel="Platform says"
              bLabel="Verified in the store"
              format={(v) => ratio(v)}
              items={[{ label: name, a: row.roas_platform, b: row.roas_true, note: `Platform overstates by ${pct(row.inflation_pct)}` }]}
              summary={`${name} claims a return on ad spend of ${ratio(row.roas_platform)}; the store verified ${ratio(row.roas_true)}.`}
            />
            <dl className="mt-3 grid grid-cols-2 gap-x-6 gap-y-3 text-sm min-[1000px]:grid-cols-4">
              <div><dt className="text-fog">Conversions claimed</dt><dd className="font-semibold">{num(row.platform_conversions)}</dd></div>
              <div><dt className="text-fog">Real store orders</dt><dd className="font-semibold">{num(row.store_orders)}</dd></div>
              <div><dt className="text-fog">Revenue claimed</dt><dd className="font-semibold">{inr(row.platform_revenue)}</dd></div>
              <div><dt className="text-fog">Revenue verified</dt><dd className="font-semibold">{inr(row.true_revenue)}</dd></div>
            </dl>
            <p className="mt-3 text-sm text-fog">Every decision uses the store-verified number. Optimising on the platform&apos;s number would over-fund this channel.</p>
          </>
        ) : (
          <p className="text-sm text-fog">Loading the reconciliation.</p>
        )}
      </Panel>
    );
  }

  const unit = rc.total_change;
  return (
    <>
      <Panel title={`What moved daily ${metric}`} note="Change per day, by cause">
        <Waterfall
          factors={rc.factors.map((f) => ({ name: f.name, impact: f.impact }))}
          netLabel={`Net change in ${metric}`}
          summary={`Daily ${metric} changed by ${inrDay(unit)}. ${rc.factors.map((f) => `${f.name} ${inrDay(f.impact)}`).join(", ")}.`}
        />
        <p className="mt-2 text-sm text-fog">Bars add up exactly to the net change.</p>
      </Panel>
      <Panel title="Factors in numbers" note="Per day, last 7 days against the baseline">
        <table className="tbl">
          <thead>
            <tr>
              <th>Factor</th>
              <th className="num">Change per day</th>
              <th className="num">Share of the movement</th>
              <th>Effect</th>
            </tr>
          </thead>
          <tbody>
            {rc.factors.map((f) => (
              <tr key={f.name}>
                <td>
                  <span className="inline-flex items-center gap-2">
                    <span className="size-2.5 rounded-sm" style={{ background: factorColor(f.name) }} aria-hidden />
                    {f.name}
                  </span>
                </td>
                <td className={`num font-semibold ${f.impact === 0 ? "" : f.impact < 0 ? "tone-loss" : "tone-gain"}`}>{f.impact === 0 ? "₹0" : `${f.impact < 0 ? "↓" : "↑"} ${inr(Math.abs(f.impact))}`}</td>
                <td className="num">{pct(f.pct)}</td>
                <td>{f.impact === 0 ? <span className="text-fog">No effect</span> : f.impact < 0 ? `Lowered ${metric}` : `Raised ${metric}`}</td>
              </tr>
            ))}
            <tr>
              <td className="font-bold">Net change</td>
              <td className={`num font-bold ${unit < 0 ? "tone-loss" : "tone-gain"}`}>{unit < 0 ? "↓" : "↑"} {inr(Math.abs(unit))}</td>
              <td />
              <td />
            </tr>
          </tbody>
        </table>
      </Panel>
    </>
  );
}
