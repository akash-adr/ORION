"use client";

import { Info, Lock } from "lucide-react";
import { useState } from "react";
import CampaignName from "@/components/CampaignName";
import DataGrid, { type Col } from "@/components/DataGrid";
import { LoadState, Panel } from "@/components/Panel";
import { OPTIMIZER_REASON } from "@/lib/decision";
import { inr, inrDay, pct, ratio } from "@/lib/format";
import { OBJECTIVE_LABELS, parseCampaignName } from "@/lib/names";
import { useMetaConfig, useOptimize, useSettings } from "@/lib/queries";
import type { Objective, OptimizeResult } from "@/lib/types";
import { cn } from "@/lib/utils";

type Move = OptimizeResult["campaigns"][number];

const Chip = ({ children }: { children: React.ReactNode }) => <span className="inline-flex items-center gap-1 rounded-full border border-line px-2 py-px text-xs whitespace-nowrap">{children}</span>;

function productsOf(list: Move[]): string {
  const names = [...new Set(list.map((c) => parseCampaignName(c.name).product))];
  return names.length <= 1 ? (names[0] ?? "") : `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
}

/** Plain, honest notes about what this objective does, written from the plan's own numbers. */
function notes(objective: Objective, r: OptimizeResult, cfg: ReturnType<typeof useMetaConfig>["data"]): string[] {
  const out: string[] = [];
  const locked = r.campaigns.filter((c) => c.stock_locked);
  const boosted = r.campaigns.filter((c) => c.bound_reasons.includes("overstock_boost"));
  if (objective === "max_profit") out.push("Moves spend toward campaigns where the next ₹1 earns more than ₹1, inside the guardrails below.");
  if (objective === "revenue_target") {
    out.push("Grow revenue chases sales, not profit, so profit can stay flat or fall.");
    if (r.summary.revenue_delta <= 0.5 && locked.length) out.push(`Revenue does not grow here: protecting ${productsOf(locked)} stock limits revenue growth.`);
    else if (r.summary.revenue_delta <= 0.5) out.push("Revenue does not grow here: the budget is already spread as widely as the guardrails allow.");
  }
  if (objective === "clear_inventory") out.push(boosted.length ? `Gives extra budget to ${productsOf(boosted)}, which have more than ${cfg?.optimizer.OVERSTOCK_COVER_DAYS ?? "—"} days of stock.` : "No product is overstocked enough to boost right now.");
  if (objective === "launch_sku" && cfg) out.push(`Reserves ${pct(cfg.optimizer.LAUNCH_TEST_RESERVE)} of the budget, ${inrDay(r.total_budget * cfg.optimizer.LAUNCH_TEST_RESERVE)}, for tests of new combinations.`);
  if (locked.length && objective !== "revenue_target") out.push(`${productsOf(locked)} cannot receive more spend because of the stock guard.`);
  return out;
}

export default function OptimizerPanel() {
  const settings = useSettings().data;
  const cfg = useMetaConfig().data;
  const [picked, setPicked] = useState<Objective | null>(null);
  const objective = picked ?? settings?.objective;
  const q = useOptimize(objective);
  const objectives = settings?.objectives ?? (Object.keys(OBJECTIVE_LABELS) as Objective[]);
  return (
    <Panel title="Optimizer" note="The best spend plan for an objective, per day. A preview: nothing is sent">
      <div role="tablist" aria-label="Objective" className="mb-4 inline-flex flex-wrap rounded-lg border border-line bg-slate-2 p-0.5">
        {objectives.map((o) => (
          <button key={o} role="tab" aria-selected={objective === o} onClick={() => setPicked(o)} className={cn("rounded-md px-3.5 py-1.5 text-sm font-semibold transition-colors", objective === o ? "bg-synapse text-primary-foreground" : "text-fog hover:text-bone")}>
            {OBJECTIVE_LABELS[o]}
          </button>
        ))}
      </div>
      <LoadState q={q} what="the plan" height={420}>
        {(r) => {
          const sm = r.summary;
          const moves = [...r.campaigns].sort((a, b) => Math.abs(b.planned_spend - b.current_spend) - Math.abs(a.planned_spend - a.current_spend)).slice(0, 8);
          const cols: Col<Move>[] = [
            { id: "name", label: "Campaign", sticky: true, cell: (c) => <CampaignName name={c.name} channel={c.channel} className="flex-nowrap" /> },
            { id: "now", label: "Now", sub: "per day", align: "right", cell: (c) => inrDay(c.current_spend) },
            { id: "plan", label: "Planned", sub: "per day", align: "right", cell: (c) => <span className="font-semibold">{inrDay(c.planned_spend)}</span> },
            { id: "chg", label: "Change", align: "right", cell: (c) => (Math.abs(c.change_pct) < 0.005 ? <span className="text-fog">None</span> : <span className={cn("font-semibold", c.change_pct < 0 ? "tone-loss" : "tone-gain")}>{c.change_pct < 0 ? "↓" : "↑"} {pct(Math.abs(c.change_pct))}</span>) },
            {
              id: "why",
              label: "Why it stopped there",
              cell: (c) => (
                <span className="flex flex-wrap gap-1">
                  {c.bound_reasons.map((b) => (
                    <Chip key={b}>
                      {b === "stock_guard" && <Lock className="size-3 tone-risk" aria-label="Locked by the stock guard" />}
                      {OPTIMIZER_REASON[b] ?? b}
                    </Chip>
                  ))}
                  {!c.bound_reasons.length && <span className="text-fog">Within limits</span>}
                </span>
              ),
            },
          ];
          const tone = sm.profit_delta < -0.5 ? "tone-loss" : sm.profit_delta > 0.5 ? "tone-gain" : "";
          return (
            <div className="grid gap-6">
              <div className="grid gap-6 min-[1200px]:grid-cols-[minmax(0,5fr)_minmax(0,6fr)]">
                <div>
                  <div className="text-sm text-fog">Profit per day under this plan</div>
                  <div className={cn("t-hero mt-1 whitespace-nowrap", tone)}>
                    {Math.abs(sm.profit_delta) < 0.5 ? "₹0" : <>{sm.profit_delta < 0 ? "↓ −" : "↑ +"}{inr(Math.abs(sm.profit_delta))}</>}
                    <span className="ml-1.5 text-sm font-semibold text-fog">/day</span>
                  </div>
                  <ul className="mt-3 grid gap-1.5 text-sm text-fog">
                    {notes(r.objective, r, cfg).map((n) => (
                      <li key={n} className="flex items-start gap-1.5">
                        <Info className="mt-0.5 size-3.5 shrink-0 text-fog" aria-hidden />
                        {n}
                      </li>
                    ))}
                  </ul>
                </div>
                <table className="tbl self-start">
                  <thead>
                    <tr>
                      <th />
                      <th className="num">Now</th>
                      <th className="num">Planned</th>
                      <th className="num">Change</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(
                      [
                        ["Ad spend", sm.current.spend, sm.planned.spend, sm.spend_delta, true],
                        ["Revenue", sm.current.revenue, sm.planned.revenue, sm.revenue_delta, false],
                        ["Profit", sm.current.profit, sm.planned.profit, sm.profit_delta, false],
                      ] as [string, number, number, number, boolean][]
                    ).map(([label, a, b, d, neutral]) => (
                      <tr key={label}>
                        <td>{label}</td>
                        <td className="num">{inrDay(a)}</td>
                        <td className="num font-semibold">{inrDay(b)}</td>
                        <td className={cn("num font-semibold", neutral || Math.abs(d) < 0.5 ? "" : d < 0 ? "tone-loss" : "tone-gain")}>{Math.abs(d) < 0.5 ? <span className="font-normal text-fog">No change</span> : `${d < 0 ? "↓ −" : "↑ "}${inr(Math.abs(d))}`}</td>
                      </tr>
                    ))}
                    <tr>
                      <td>Profit on spend</td>
                      <td className="num">{ratio(sm.current.poas)}</td>
                      <td className="num font-semibold">{ratio(sm.planned.poas)}</td>
                      <td className="num text-fog">{sm.current.poas != null && sm.planned.poas != null ? `${(sm.planned.poas - sm.current.poas >= 0 ? "+" : "−") + Math.abs(sm.planned.poas - sm.current.poas).toFixed(2)}×` : "—"}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
              <div>
                <h3 className="mb-2 text-sm font-bold">Biggest moves</h3>
                <DataGrid rows={moves} cols={cols} rowKey={(c) => c.campaign_id} ariaLabel="Biggest budget moves in the plan" maxHeight="none" />
              </div>
              {cfg && (
                <div>
                  <h3 className="mb-1 text-sm font-bold">Limits the plan stays inside</h3>
                  <ul className="grid gap-1 text-sm text-fog min-[1000px]:grid-cols-2">
                    <li>No campaign changes by more than ±{pct(cfg.guardrails.DAILY_CHANGE_CAP)} in a day.</li>
                    <li>Total budget stays at {inrDay(r.total_budget)}.</li>
                    <li>
                      Products under {cfg.detection.STOCK_COVER_RISK_DAYS} days of stock are held to {pct(cfg.guardrails.STOCK_SPEND_CAP_MULT)} of current spend and can&apos;t grow.
                    </li>
                    <li>Solver {r.solver.ok ? "converged" : "did not converge"} in {r.solver.iterations} iterations.</li>
                  </ul>
                </div>
              )}
            </div>
          );
        }}
      </LoadState>
    </Panel>
  );
}
