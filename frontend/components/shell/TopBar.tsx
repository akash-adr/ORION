"use client";

import { useState } from "react";
import { ApiError } from "@/lib/api";
import { dateShort, pct, timeShort } from "@/lib/format";
import { useKpis, useSettings, useUpdateSettings } from "@/lib/queries";
import { AUTONOMY_LABELS, OBJECTIVE_LABELS } from "@/lib/names";
import { useUiStore } from "@/lib/ui-store";
import type { Autonomy, Objective } from "@/lib/types";
import { cn } from "@/lib/utils";
import AskBar from "./AskBar";

function Status({ label, value }: { label: string; value: string }) {
  return (
    <div className="px-3 first:pl-0 last:pr-0">
      <div className="text-xs text-fog">{label}</div>
      <div className="text-sm font-semibold whitespace-nowrap">{value}</div>
    </div>
  );
}

function AutonomyControl() {
  const { data: settings } = useSettings();
  const update = useUpdateSettings();
  const toast = useUiStore((s) => s.toast);
  const [hint, setHint] = useState<Autonomy | null>(null);
  const modes = settings?.autonomy_modes ?? (["advisory", "supervised", "autonomous"] as Autonomy[]);
  const current = settings?.autonomy;
  const pick = (a: Autonomy) => {
    if (a === current) return;
    update.mutate(
      { autonomy: a },
      {
        onSuccess: () => toast("gain", `Autonomy set to ${AUTONOMY_LABELS[a].label.toLowerCase()}`, AUTONOMY_LABELS[a].hint),
        onError: (e) => toast("loss", "Autonomy did not change", e instanceof ApiError ? e.detail : undefined),
      },
    );
  };
  return (
    <div className="relative" onPointerLeave={() => setHint(null)}>
      <div role="radiogroup" aria-label="Autonomy" className="flex rounded-lg border border-line bg-slate-2 p-0.5">
        {modes.map((m) => (
          <button
            key={m}
            role="radio"
            aria-checked={current === m}
            onClick={() => pick(m)}
            onPointerEnter={() => setHint(m)}
            onFocus={() => setHint(m)}
            onBlur={() => setHint(null)}
            disabled={!settings || update.isPending}
            className={cn("rounded-md px-3 py-1.5 text-sm font-semibold transition-colors", current === m ? "bg-synapse text-primary-foreground" : "text-fog hover:text-bone")}
          >
            {AUTONOMY_LABELS[m].label}
          </button>
        ))}
      </div>
      {hint && (
        <div role="tooltip" className="float-layer absolute top-full right-0 z-40 mt-2 w-72 p-3 text-sm">
          <span className="font-semibold">{AUTONOMY_LABELS[hint].label}.</span> {AUTONOMY_LABELS[hint].hint}
        </div>
      )}
    </div>
  );
}

function ObjectiveSelect() {
  const { data: settings } = useSettings();
  const update = useUpdateSettings();
  const toast = useUiStore((s) => s.toast);
  const options = settings?.objectives ?? (Object.keys(OBJECTIVE_LABELS) as Objective[]);
  return (
    <label className="flex items-center gap-2 text-sm text-fog">
      Objective
      <select
        value={settings?.objective ?? ""}
        disabled={!settings || update.isPending}
        onChange={(e) => {
          const objective = e.target.value as Objective;
          update.mutate(
            { objective },
            {
              onSuccess: () => toast("gain", `Objective set to ${OBJECTIVE_LABELS[objective].toLowerCase()}`, "The plan and the decision inbox were rebuilt."),
              onError: (err) => toast("loss", "Objective did not change", err instanceof ApiError ? err.detail : undefined),
            },
          );
        }}
        className="h-9 rounded-lg border border-line bg-slate-2 px-2.5 text-sm font-semibold text-bone"
      >
        {!settings && <option value="">Loading</option>}
        {options.map((o) => (
          <option key={o} value={o}>
            {OBJECTIVE_LABELS[o]}
          </option>
        ))}
      </select>
    </label>
  );
}

export default function TopBar() {
  const { data: kpis } = useKpis(7);
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-3 border-b border-line bg-ink px-4 py-3 min-[1000px]:px-6 min-[1200px]:px-8">
      <AskBar />
      <div className="flex divide-x divide-line" aria-label="Data status" role="group">
        <Status label="Data through" value={kpis ? dateShort(kpis.as_of) : "—"} />
        <Status label="Synced" value={kpis ? timeShort(kpis.last_synced) : "—"} />
        <Status label="Data trust" value={kpis ? pct(kpis.data_trust) : "—"} />
      </div>
      <ObjectiveSelect />
      <AutonomyControl />
      {/* Brain status orb: a static dot until the live orb is built in part 5. */}
      <span role="img" aria-label="Brain status" className="size-3 shrink-0 rounded-full border-2 border-synapse bg-synapse/40" />
    </div>
  );
}
