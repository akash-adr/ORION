"use client";

import { CircleCheck, CircleX, TriangleAlert } from "lucide-react";
import { LoadState, Panel } from "@/components/Panel";
import { num } from "@/lib/format";
import { useDataQuality } from "@/lib/queries";

const humanize = (s: string) => s.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());

/** Plain wording for the one check whose action text is an internal module note. */
const ACTION_COPY: Record<string, string> = {
  reconciliation_gap: "Raised an attribution alert and recommended server-side conversion tracking.",
};

export default function QualitySection() {
  const q = useDataQuality();
  return (
    <Panel title="Data quality checks" note="Run on every ingest">
      <LoadState q={q} what="the checks" height={260}>
        {(rows) => {
          const warn = rows.filter((r) => r.status !== "pass").length;
          return (
            <>
              <p className="mb-3 text-sm text-fog">
                {rows.length - warn} of {rows.length} passed{warn ? `, ${warn} ${warn === 1 ? "needs" : "need"} a look` : ""}.
              </p>
              <table className="tbl">
                <thead>
                  <tr>
                    <th>Check</th>
                    <th>Result</th>
                    <th className="num">Rows affected</th>
                    <th>Detail</th>
                    <th>Action taken</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => {
                    const fail = (r.status as string) === "fail";
                    const pass = r.status === "pass";
                    return (
                      <tr key={r.check}>
                        <td className="font-semibold">{humanize(r.check)}</td>
                        <td>
                          {pass ? (
                            <span className="inline-flex items-center gap-1 tone-gain"><CircleCheck className="size-3.5" aria-hidden />Passed</span>
                          ) : fail ? (
                            <span className="inline-flex items-center gap-1 font-semibold tone-loss"><CircleX className="size-3.5" aria-hidden />Failed</span>
                          ) : (
                            <span className="inline-flex items-center gap-1 font-semibold tone-risk"><TriangleAlert className="size-3.5" aria-hidden />Warning</span>
                          )}
                        </td>
                        <td className="num">{num(r.affected_rows)}</td>
                        <td className="text-fog">{r.detail}</td>
                        <td className="text-fog">{r.action === "none" ? "No action needed" : (ACTION_COPY[r.check] ?? r.action)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </>
          );
        }}
      </LoadState>
    </Panel>
  );
}
