"use client";

import { LoadState, Panel } from "@/components/Panel";
import DataGrid, { type Col } from "@/components/DataGrid";
import { dateShort, inrDay, pct } from "@/lib/format";
import { actionTypeDisplay } from "@/lib/names";
import { useLearning } from "@/lib/queries";
import type { Outcome } from "@/lib/types";
import { cn } from "@/lib/utils";

const Tag = ({ children }: { children: React.ReactNode }) => <span className="inline-flex rounded-full border border-line px-2 py-px text-xs whitespace-nowrap text-fog">{children}</span>;

export default function OutcomesTable() {
  const q = useLearning();
  return (
    <Panel title="Predicted against actual" note="Newest first. Money is per day">
      <LoadState q={q} what="the outcomes" height={300}>
        {(l) => {
          const rows = [...l.outcomes].sort((a, b) => b.measured_at.localeCompare(a.measured_at));
          const cols: Col<Outcome>[] = [
            { id: "title", label: "Decision", sticky: true, sort: (o) => o.title, cell: (o) => (<span><span className="font-semibold">{o.title}</span><span className="block text-xs text-fog">{actionTypeDisplay(o.action_type)}</span></span>) },
            { id: "date", label: "Date", sort: (o) => o.measured_at, cell: (o) => dateShort(o.date) },
            { id: "pred", label: "Predicted", sub: "per day", align: "right", sort: (o) => o.predicted, cell: (o) => inrDay(o.predicted) },
            { id: "act", label: "Actual", sub: "per day", align: "right", sort: (o) => o.actual, cell: (o) => <span className="font-semibold">{inrDay(o.actual)}</span> },
            {
              id: "err",
              label: "Error",
              hint: "How far actual was from the prediction. Above means better than predicted.",
              align: "right",
              sort: (o) => o.error_pct,
              cell: (o) => (o.error_pct === null ? <span className="text-fog">—</span> : <span className={cn("font-semibold", o.error_pct < -0.005 ? "tone-loss" : o.error_pct > 0.005 ? "tone-gain" : "")}>{o.error_pct < -0.005 ? "↓ −" : o.error_pct > 0.005 ? "↑ +" : ""}{pct(Math.abs(o.error_pct))}</span>),
            },
            {
              id: "tags",
              label: "Tags",
              cell: (o) => (
                <span className="flex flex-wrap gap-1">
                  {o.seeded && <Tag>Seeded history</Tag>}
                  {o.simulated && <Tag>Simulated</Tag>}
                  {!o.measurable && <Tag>Not measured in ₹</Tag>}
                </span>
              ),
            },
          ];
          return <DataGrid rows={rows} cols={cols} rowKey={(o) => o.decision_id + o.measured_at} defaultSort={{ id: "date", dir: "desc" }} ariaLabel="Predicted against actual outcomes" />;
        }}
      </LoadState>
    </Panel>
  );
}
