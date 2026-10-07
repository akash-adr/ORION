"use client";

import { LoadState, Panel } from "@/components/Panel";
import { useMetaConfig } from "@/lib/queries";
import { describeThresholds } from "@/lib/thresholds";

export default function ThresholdsSection() {
  const q = useMetaConfig();
  return (
    <Panel title="Guardrails and thresholds" note="Read-only. These are the engine's own settings">
      <LoadState q={q} what="the thresholds" height={320}>
        {(cfg) => (
          <div className="grid gap-6 min-[1200px]:grid-cols-2">
            {describeThresholds(cfg).map((g) => (
              <section key={g.id} aria-labelledby={`thr-${g.id}`}>
                <h3 id={`thr-${g.id}`} className="mb-2 border-b border-line pb-1.5 text-sm font-bold">
                  {g.title}
                </h3>
                <dl className="grid gap-3">
                  {g.rows.map((r) => (
                    <div key={r.key} className="grid grid-cols-[minmax(0,1fr)_auto] gap-x-4">
                      <dt className="text-sm font-semibold">{r.label}</dt>
                      <dd className="text-right text-sm font-bold whitespace-nowrap">{r.value}</dd>
                      <p className="col-span-2 mt-0.5 text-sm text-fog">{r.explain}</p>
                    </div>
                  ))}
                </dl>
              </section>
            ))}
          </div>
        )}
      </LoadState>
    </Panel>
  );
}
