"use client";

import { ArrowDown, ArrowUp, TriangleAlert } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import AnomalyName from "@/components/AnomalyName";
import Brief from "@/components/diagnosis/Brief";
import CausalProof from "@/components/diagnosis/CausalProof";
import EvidenceCharts from "@/components/diagnosis/EvidenceCharts";
import FactorSection from "@/components/diagnosis/FactorSection";
import FunnelSection from "@/components/diagnosis/FunnelSection";
import DecisionRow from "@/components/ledger/DecisionRow";
import PageHeader from "@/components/PageHeader";
import { EmptyState, LoadState, Panel } from "@/components/Panel";
import { inr } from "@/lib/format";
import { kindIcon } from "@/lib/kinds";
import { kindDisplay } from "@/lib/names";
import { useAnomalies, useDiagnosis, useRecommendations } from "@/lib/queries";
import type { Anomaly } from "@/lib/types";
import { cn } from "@/lib/utils";

function RecommendedAction({ anomalyId }: { anomalyId: string }) {
  const q = useRecommendations();
  const [open, setOpen] = useState(false);
  return (
    <Panel title="Recommended action" className="p-0 min-[1200px]:p-0">
      <LoadState q={q} what="the recommendation" height={100}>
        {(r) => {
          const match = [...r.pending, ...r.history].filter((d) => d.anomaly_id === anomalyId);
          if (!match.length)
            return (
              <div className="p-4">
                <EmptyState title="No decision is waiting for this signal" hint="The engine only recommends a change when it can name one. Run the loop now to check again." />
              </div>
            );
          return (
            <ul>
              {match.map((d) => (
                <DecisionRow key={d.id} d={d} open={open} onToggle={() => setOpen((o) => !o)} />
              ))}
            </ul>
          );
        }}
      </LoadState>
    </Panel>
  );
}

function Detail({ id, all }: { id: string; all: Anomaly[] }) {
  const q = useDiagnosis(id);
  return (
    <LoadState q={q} what="this diagnosis" height={460}>
      {(d) => (
        <div className="grid gap-5">
          <Brief d={d} all={all} />
          <FactorSection d={d} />
          <EvidenceCharts d={d} />
          {d.evidence.causal && <CausalProof c={d.evidence.causal} />}
          <FunnelSection d={d} />
          <RecommendedAction anomalyId={id} />
        </div>
      )}
    </LoadState>
  );
}

function Body() {
  const params = useSearchParams();
  const router = useRouter();
  const list = useAnomalies();
  const chosen = params.get("anomaly");
  return (
    <LoadState q={list} what="the anomalies" height={300}>
      {(all) => {
        const sorted = [...all].sort((a, b) => Math.abs(b.profit_impact) - Math.abs(a.profit_impact));
        const id = chosen && all.some((a) => a.id === chosen) ? chosen : (sorted[0]?.id ?? null);
        if (!id) return <EmptyState title="No anomalies right now" hint="Run the loop now to check again." />;
        return (
          <div className="grid items-start gap-5 min-[1000px]:grid-cols-[300px_minmax(0,1fr)]">
            <nav aria-label="Anomalies" className="panel p-2 min-[1000px]:sticky min-[1000px]:top-4 min-[1000px]:max-h-[calc(100vh-2rem)] min-[1000px]:overflow-y-auto">
              <ul>
                {sorted.map((a) => {
                  const KindIcon = kindIcon(a.kind);
                  const Arrow = a.profit_impact < 0 ? ArrowDown : ArrowUp;
                  const none = Math.abs(a.profit_impact) < 0.5;
                  return (
                    <li key={a.id}>
                      <button
                        onClick={() => router.replace(`/diagnosis?anomaly=${a.id}`, { scroll: false })}
                        aria-current={a.id === id ? "true" : undefined}
                        className={cn("w-full rounded-lg px-3 py-2.5 text-left hover:bg-slate-2", a.id === id && "bg-slate-2 shadow-[inset_2px_0_0_var(--synapse)]")}
                      >
                        <div className="flex items-center justify-between gap-2">
                          <span className="inline-flex items-center gap-1.5 text-sm font-semibold">
                            <KindIcon className="size-3.5 text-fog" aria-hidden />
                            {kindDisplay(a.kind)}
                          </span>
                          {none ? (
                            <span className="text-xs text-fog">No profit effect</span>
                          ) : (
                            <span className={cn("inline-flex items-center gap-0.5 text-sm font-semibold", a.profit_impact < 0 ? "tone-loss" : "tone-gain")}>
                              <Arrow className="size-3.5" aria-hidden />
                              {inr(Math.abs(a.profit_impact))}
                              <span className="text-xs font-normal text-fog">/day</span>
                            </span>
                          )}
                        </div>
                        <div className="mt-1 flex items-center justify-between gap-2">
                          <AnomalyName a={a} className="text-sm" />
                          <span className="inline-flex shrink-0 items-center gap-1 text-xs text-fog">
                            {a.severity === "high" && <TriangleAlert className="size-3 tone-risk" aria-hidden />}
                            {a.severity}
                          </span>
                        </div>
                      </button>
                    </li>
                  );
                })}
              </ul>
            </nav>
            <Detail id={id} all={all} />
          </div>
        );
      }}
    </LoadState>
  );
}

export default function DiagnosisPage() {
  return (
    <div>
      <PageHeader title="Diagnosis">Pick a signal to see what changed, why, and the proof, in order of how much profit it moved.</PageHeader>
      <Suspense fallback={null}>
        <Body />
      </Suspense>
    </div>
  );
}
