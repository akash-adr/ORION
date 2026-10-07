"use client";

import { LineChart } from "@/components/charts";
import PageHeader from "@/components/PageHeader";
import { EmptyState, LoadState, Panel } from "@/components/Panel";
import { dateShort, inr, inrDay, pct, timeShort } from "@/lib/format";
import { actionTypeDisplay } from "@/lib/names";
import { useAudit, useLearning } from "@/lib/queries";

export default function LearningPage() {
  const l = useLearning();
  const a = useAudit();
  return (
    <div className="grid gap-5">
      <PageHeader title="Learning and audit">How accurate the engine&apos;s predictions have been, and every change it has sent.</PageHeader>
      <Panel title="Forecast error" note="Rolling average miss, lower is better">
        <LoadState q={l} what="the learning history" height={260}>
          {(d) => (
            <>
              <LineChart
                x={d.accuracy_curve.map((p) => p.date)}
                xFormat={(x) => dateShort(x)}
                series={[{ id: "mape", label: "Forecast error", color: "var(--synapse)", data: d.accuracy_curve.map((p) => p.rolling_mape) }]}
                format={(v) => pct(v)}
                summary={`Rolling forecast error over ${d.accuracy_curve.length} measured decisions, latest ${pct(d.accuracy_curve[d.accuracy_curve.length - 1]?.rolling_mape ?? null)}.`}
              />
              <p className="mt-2 text-sm text-fog">{d.simulated_note}</p>
            </>
          )}
        </LoadState>
      </Panel>
      <Panel title="Measured outcomes" note="Predicted against actual profit per day">
        <LoadState q={l} what="the outcomes" height={200}>
          {(d) => (
            <ul className="divide-y divide-line">
              {[...d.outcomes].reverse().slice(0, 6).map((o) => (
                <li key={o.decision_id + o.measured_at} className="py-3 first:pt-0">
                  <div className="flex flex-wrap items-baseline justify-between gap-x-4">
                    <span className="font-semibold">{o.title}</span>
                    <span className="text-sm text-fog">
                      {actionTypeDisplay(o.action_type)}, {dateShort(o.date)}
                    </span>
                  </div>
                  <div className="mt-0.5 text-sm">
                    Predicted {inrDay(o.predicted)}, actual {inrDay(o.actual)}
                    {o.error_pct !== null && Math.abs(o.error_pct) >= 0.005 && <>, {pct(Math.abs(o.error_pct))} {o.error_pct > 0 ? "above" : "below"} the prediction</>}
                  </div>
                  <p className="narrative mt-1 text-fog">{o.note}</p>
                </li>
              ))}
            </ul>
          )}
        </LoadState>
      </Panel>
      <Panel title="Audit trail" note="Every change sent to an ad platform">
        <LoadState q={a} what="the audit trail" height={120}>
          {(rows) =>
            rows.length === 0 ? (
              <EmptyState title="Nothing has been sent yet" hint="Approve a decision and it will be recorded here with a way to roll it back." />
            ) : (
              <table className="tbl">
                <thead>
                  <tr>
                    <th>When</th>
                    <th>Decision</th>
                    <th>Action</th>
                    <th>By</th>
                    <th className="num">Expected</th>
                  </tr>
                </thead>
                <tbody>
                  {[...rows].reverse().map((r, i) => (
                    <tr key={i}>
                      <td className="whitespace-nowrap">{dateShort(r.ts)}, {timeShort(r.ts)}</td>
                      <td>{r.title}</td>
                      <td className="capitalize">{r.action}</td>
                      <td>{r.approver === "autopilot" ? "Autopilot" : "You"}</td>
                      <td className="num">{inr(r.expected_profit_delta ?? null)}/day</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )
          }
        </LoadState>
      </Panel>
    </div>
  );
}
