"use client";

import { ArrowDown, ArrowUp, RotateCcw, TriangleAlert, Zap } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Panel, LoadState } from "@/components/Panel";
import { ApiError } from "@/lib/api";
import { inr, inrDay, pct, ratio } from "@/lib/format";
import { channelDisplay, parseCampaignName } from "@/lib/names";
import { simulateChannels, useCampaigns, useChannels } from "@/lib/queries";
import type { Simulation } from "@/lib/types";
import { cn } from "@/lib/utils";

const DEBOUNCE_MS = 250;

function Delta({ v, unit = "", neutral }: { v: number | null; unit?: string; neutral?: boolean }) {
  if (v === null || Math.abs(v) < 0.5) return <span className="text-fog">No change</span>;
  const Icon = v < 0 ? ArrowDown : ArrowUp;
  return (
    <span className={cn("inline-flex items-center gap-0.5 font-semibold whitespace-nowrap", neutral ? "" : v < 0 ? "tone-loss" : "tone-gain")}>
      <Icon className="size-3.5" aria-hidden />
      {v < 0 ? "−" : ""}
      {inr(Math.abs(v))}
      {unit}
    </span>
  );
}

export default function WhatIf() {
  const channels = useChannels();
  const campaigns = useCampaigns().data ?? [];
  const [pctBy, setPctBy] = useState<Record<string, number>>({});
  const [result, setResult] = useState<{ sim: Simulation; ms: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const seq = useRef(0);

  const rows = channels.data ?? [];
  const value = (c: string) => pctBy[c] ?? 100;
  const changed = rows.some((r) => value(r.channel) !== 100);

  // Debounced round trip: only the latest request may update the screen.
  useEffect(() => {
    if (!rows.length) return;
    const multipliers = Object.fromEntries(rows.map((r) => [r.channel, value(r.channel) / 100]));
    const id = ++seq.current;
    const t = setTimeout(async () => {
      const t0 = performance.now();
      try {
        const sim = await simulateChannels(multipliers);
        if (id === seq.current) {
          setResult({ sim, ms: performance.now() - t0 });
          setError(null);
        }
      } catch (e) {
        if (id === seq.current) setError(e instanceof ApiError ? e.detail : "The simulation did not run.");
      }
    }, id === 1 ? 0 : DEBOUNCE_MS);
    return () => clearTimeout(t);
    // value() reads pctBy; rows identity is stable per fetch
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pctBy, channels.data]);

  const s = result?.sim.summary;
  // "Today" for a channel = the sum of its campaigns' current daily budgets, the same basis the simulator itself uses.
  const todayBy = new Map<string, number>();
  for (const c of result?.sim.campaigns ?? []) todayBy.set(c.channel, (todayBy.get(c.channel) ?? 0) + c.current_spend);
  const warned = (s?.stock_warnings ?? []).map((id) => campaigns.find((c) => c.campaign_id === id)).filter((c): c is NonNullable<typeof c> => !!c);
  const tone = !s ? "" : s.profit_delta < -0.5 ? "tone-loss" : s.profit_delta > 0.5 ? "tone-gain" : "";

  return (
    <Panel title="What if" note="Move each channel's daily spend and see profit change, per day">
      <LoadState q={channels} what="the channels" height={260}>
        {(chs) => (
          <div className="grid gap-6 min-[1200px]:grid-cols-[minmax(0,5fr)_minmax(0,6fr)]">
            <div className="grid content-start gap-4">
              {chs.map((c) => {
                const v = value(c.channel);
                return (
                  <div key={c.channel}>
                    <div className="flex items-baseline justify-between gap-2 text-sm">
                      <label htmlFor={`sl-${c.channel}`} className="font-semibold">
                        {channelDisplay(c.channel)}
                      </label>
                      <span className="text-fog">
                        <span className="font-bold text-bone">{v}%</span> of today: {inrDay((todayBy.get(c.channel) ?? c.spend) * (v / 100))}
                      </span>
                    </div>
                    <input
                      id={`sl-${c.channel}`}
                      type="range"
                      min={0}
                      max={200}
                      step={5}
                      value={v}
                      onChange={(e) => setPctBy((cur) => ({ ...cur, [c.channel]: Number(e.target.value) }))}
                      aria-valuetext={`${v}% of today's spend`}
                      className="mt-1.5 h-2 w-full cursor-pointer accent-[var(--synapse)]"
                    />
                  </div>
                );
              })}
              <button onClick={() => setPctBy({})} disabled={!changed} className="inline-flex h-8 w-fit items-center gap-1.5 rounded-lg border border-line px-3 text-sm font-semibold hover:bg-slate-2 disabled:opacity-50">
                <RotateCcw className="size-3.5" aria-hidden />
                Reset sliders
              </button>
            </div>

            <div aria-live="polite">
              {error && <p className="text-sm tone-loss" role="alert">{error} Check that the backend is running, then move a slider.</p>}
              {s && (
                <>
                  <div className="text-sm text-fog">Profit per day with this spend</div>
                  <div className={cn("t-hero mt-1 whitespace-nowrap", tone)}>
                    {Math.abs(s.profit_delta) < 0.5 ? "₹0" : <>{s.profit_delta < 0 ? "↓ −" : "↑ +"}{inr(Math.abs(s.profit_delta))}</>}
                    <span className="ml-1.5 text-sm font-semibold text-fog">/day</span>
                  </div>
                  <table className="tbl mt-4">
                    <thead>
                      <tr>
                        <th />
                        <th className="num">Now</th>
                        <th className="num">Simulated</th>
                        <th className="num">Change</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr><td>Ad spend</td><td className="num">{inrDay(s.current.spend)}</td><td className="num font-semibold">{inrDay(s.simulated.spend)}</td><td className="num"><Delta v={s.spend_delta} neutral /></td></tr>
                      <tr><td>Revenue</td><td className="num">{inrDay(s.current.revenue)}</td><td className="num font-semibold">{inrDay(s.simulated.revenue)}</td><td className="num"><Delta v={s.revenue_delta} /></td></tr>
                      <tr><td>Profit</td><td className="num">{inrDay(s.current.profit)}</td><td className="num font-semibold">{inrDay(s.simulated.profit)}</td><td className="num"><Delta v={s.profit_delta} /></td></tr>
                      <tr><td>Profit on spend</td><td className="num">{ratio(s.current.poas)}</td><td className="num font-semibold">{ratio(s.simulated.poas)}</td><td className="num">{s.current.poas != null && s.simulated.poas != null ? <span className={cn("font-semibold", s.simulated.poas < s.current.poas - 0.005 ? "tone-loss" : s.simulated.poas > s.current.poas + 0.005 ? "tone-gain" : "text-fog")}>{Math.abs(s.simulated.poas - s.current.poas) < 0.005 ? "No change" : `${s.simulated.poas < s.current.poas ? "↓" : "↑"} ${Math.abs(s.simulated.poas - s.current.poas).toFixed(2)}×`}</span> : "—"}</td></tr>
                    </tbody>
                  </table>
                  {warned.length > 0 && (
                    <div className="mt-4 flex items-start gap-2 rounded-lg border border-line bg-slate-2/50 p-3 text-sm" role="alert">
                      <TriangleAlert className="mt-0.5 size-4 shrink-0 tone-risk" aria-hidden />
                      <div>
                        <div className="font-semibold">Stock warning</div>
                        <ul className="mt-0.5 text-fog">
                          {warned.map((c) => {
                            const p = parseCampaignName(c.campaign_name);
                            return (
                              <li key={c.campaign_id}>
                                {p.channelName} {p.product} ({p.audience}): only {c.days_cover.toFixed(1)} days of {p.product} stock left, so more spend would outrun supply.
                              </li>
                            );
                          })}
                        </ul>
                      </div>
                    </div>
                  )}
                  {result && (
                    <p className="mt-3 inline-flex items-center gap-1 text-xs text-fog">
                      <Zap className="size-3" aria-hidden />
                      Simulated in {Math.max(1, Math.round(result.ms))} ms
                      {s && changed ? `, ${pct(Math.abs(s.spend_delta) / Math.max(1, s.current.spend), 0)} ${s.spend_delta < 0 ? "less" : "more"} spend in total` : ""}
                    </p>
                  )}
                </>
              )}
            </div>
          </div>
        )}
      </LoadState>
    </Panel>
  );
}
