"use client";

import { CircleCheck, TriangleAlert } from "lucide-react";
import { PairBars } from "@/components/charts";
import PageHeader from "@/components/PageHeader";
import { LoadState, Panel } from "@/components/Panel";
import { dateShort, inr, num, pct, timeShort } from "@/lib/format";
import { channelDisplay } from "@/lib/names";
import { useDataQuality, useReconciliation, useSources } from "@/lib/queries";

const Status = ({ ok, okWord, warnWord }: { ok: boolean; okWord: string; warnWord: string }) =>
  ok ? (
    <span className="inline-flex items-center gap-1 tone-gain">
      <CircleCheck className="size-3.5" aria-hidden />
      {okWord}
    </span>
  ) : (
    <span className="inline-flex items-center gap-1 tone-risk">
      <TriangleAlert className="size-3.5" aria-hidden />
      {warnWord}
    </span>
  );

export default function DataPage() {
  const rec = useReconciliation();
  const src = useSources();
  const dq = useDataQuality();
  return (
    <div className="grid gap-5">
      <PageHeader title="Data truth">Where platform numbers and store numbers disagree, and how far to trust each source.</PageHeader>
      <Panel title="Revenue by channel" note="Last 7 days">
        <LoadState q={rec} what="the reconciliation" height={240}>
          {(rows) => (
            <PairBars
              aLabel="Platform claims"
              bLabel="Store verified"
              format={(v) => inr(v)}
              items={rows.map((r) => ({ label: channelDisplay(r.channel), a: r.platform_revenue, b: r.true_revenue, note: `${num(r.platform_conversions)} claimed, ${num(r.store_orders)} real orders` }))}
              summary="Revenue claimed by each ad platform against revenue verified in the store."
            />
          )}
        </LoadState>
      </Panel>
      <Panel title="Sources" note="Trust is how closely a source matches the store">
        <LoadState q={src} what="the sources" height={260}>
          {(rows) => (
            <div className="overflow-x-auto">
              <table className="tbl">
                <thead>
                  <tr>
                    <th>Source</th>
                    <th>Status</th>
                    <th className="num">Trust</th>
                    <th className="num">Rows</th>
                    <th>Data through</th>
                    <th>Synced</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((s) => (
                    <tr key={s.source_id}>
                      <td className="font-semibold">{s.label}</td>
                      <td>
                        <Status ok={s.status === "ok"} okWord="Healthy" warnWord="Needs a look" />
                      </td>
                      <td className="num">{pct(s.trust_score)}</td>
                      <td className="num">{num(s.rows)}</td>
                      <td>{dateShort(s.max_date)}</td>
                      <td>{timeShort(s.last_synced)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </LoadState>
      </Panel>
      <Panel title="Data quality checks">
        <LoadState q={dq} what="the checks" height={200}>
          {(rows) => (
            <table className="tbl">
              <thead>
                <tr>
                  <th>Check</th>
                  <th>Result</th>
                  <th className="num">Rows affected</th>
                  <th>What the engine did</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.check}>
                    <td className="font-semibold">{r.check}</td>
                    <td>
                      <Status ok={r.status === "pass"} okWord="Passed" warnWord="Warning" />
                    </td>
                    <td className="num">{num(r.affected_rows)}</td>
                    <td className="text-fog">{r.action}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </LoadState>
      </Panel>
    </div>
  );
}
