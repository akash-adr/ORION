"use client";

import { LoadState, Panel } from "@/components/Panel";
import CampaignName from "@/components/CampaignName";
import { useBrainSnapshot } from "@/lib/queries";

export default function SynapseMemory() {
  const q = useBrainSnapshot();
  return (
    <Panel title="What the brain remembers" note="The 8 strongest connections from a campaign to its product">
      <LoadState q={q} what="the connections" height={240}>
        {(s) => {
          const label = new Map(s.nodes.map((n) => [n.entity_id, n]));
          const edges = s.synapses.filter((e) => e.source.startsWith("CMP") && label.has(e.source) && label.has(e.target)).sort((a, b) => b.strength - a.strength).slice(0, 8);
          const top = Math.max(1, ...edges.map((e) => e.strength));
          return (
            <>
              <ul className="grid gap-2.5">
                {edges.map((e) => {
                  const c = label.get(e.source)!;
                  const p = label.get(e.target)!;
                  return (
                    <li key={`${e.source}-${e.target}`} className="grid grid-cols-[minmax(0,1fr)_minmax(80px,200px)_48px] items-center gap-3 text-sm">
                      <span className="min-w-0 truncate">
                        <CampaignName name={c.label} channel={c.channel} className="flex-nowrap" /> <span className="text-fog">promotes {p.label}</span>
                      </span>
                      <span className="h-2.5 rounded-full bg-slate-2" role="img" aria-label={`Connection strength ${e.strength.toFixed(2)}`}>
                        <span className="block h-full rounded-full" style={{ width: `${(e.strength / top) * 100}%`, background: "var(--synapse)" }} />
                      </span>
                      <span className="text-right font-semibold">{e.strength.toFixed(2)}</span>
                    </li>
                  );
                })}
              </ul>
              <p className="narrative mt-4">Connections strengthen when decisions deliver what they predicted.</p>
            </>
          );
        }}
      </LoadState>
    </Panel>
  );
}
