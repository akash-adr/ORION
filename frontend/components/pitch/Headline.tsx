"use client";

import { Expand, LoaderCircle, Minimize, Play, Presentation, Rewind } from "lucide-react";
import { useState } from "react";
import { useRunLoop } from "@/components/shell/useRunLoop";
import { ApiError, api } from "@/lib/api";
import { useBrainPlayer } from "@/lib/brain/store";
import { inr, inrDay, pct } from "@/lib/format";
import type { PitchData } from "@/lib/pitch/data";
import { useUiStore } from "@/lib/ui-store";

const Fact = ({ label, children }: { label: string; children: React.ReactNode }) => (
  <div className="min-w-0">
    <div className="text-xs text-fog">{label}</div>
    <div className="text-base font-bold whitespace-nowrap">{children}</div>
  </div>
);

interface Props {
  data: PitchData;
  fullscreen: boolean;
  onFullscreen: () => void;
  /** wired by the walkthrough */
  onStart?: () => void;
  walking?: boolean;
}

export default function Headline({ data, fullscreen, onFullscreen, onStart, walking }: Props) {
  const toast = useUiStore((s) => s.toast);
  const { run, running } = useRunLoop();
  const replay = useBrainPlayer((s) => s.replay);
  const [replaying, setReplaying] = useState(false);
  const d = data.derived;
  const profit = data.kpis?.profit.value ?? null;
  const planned = data.snapshot?.headline.planned_profit ?? null;
  const delta = data.snapshot?.headline.profit_delta ?? null;
  const progress = replay && replay.done < replay.total ? replay : null;

  const startReplay = async () => {
    setReplaying(true);
    try {
      const r = await api.brainReplay();
      useBrainPlayer.getState().beginReplay(r.first_id, r.events_queued);
      toast("info", `Replaying the last 7 days · ${r.events_queued} events queued`);
    } catch (e) {
      toast("loss", "Could not start the replay", e instanceof ApiError ? e.detail : "Check that the backend is running.");
    } finally {
      setReplaying(false);
    }
  };
  const btn = "inline-flex h-9 items-center gap-1.5 rounded-lg border border-line px-3 text-sm font-semibold hover:bg-slate-2 disabled:opacity-60";

  return (
    <header className="grid gap-2">
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
        <h1 className="text-[28px] leading-tight font-extrabold tracking-tight">How Margin Mind thinks</h1>
        <div className="flex flex-wrap items-center gap-2">
          <button onClick={onStart} disabled={!onStart || !data.ready} title={onStart ? undefined : "Coming next"} className="inline-flex h-9 items-center gap-1.5 rounded-lg bg-primary px-3.5 text-sm font-semibold text-primary-foreground hover:bg-primary/85 disabled:opacity-60">
            <Presentation className="size-4" aria-hidden />
            {walking ? "Restart walkthrough" : "Start walkthrough"}
          </button>
          <button onClick={startReplay} disabled={replaying || !!progress} className={btn}>
            {replaying || progress ? <LoaderCircle className="size-4 animate-spin" aria-hidden /> : <Rewind className="size-4" aria-hidden />}
            {progress ? `Replaying ${progress.done} of ${progress.total}` : "Replay the last 7 days"}
          </button>
          <button onClick={run} disabled={running} className={btn}>
            {running ? <LoaderCircle className="size-4 animate-spin" aria-hidden /> : <Play className="size-4" aria-hidden />}
            Run the loop now
          </button>
          <button onClick={onFullscreen} className={btn}>
            {fullscreen ? <Minimize className="size-4" aria-hidden /> : <Expand className="size-4" aria-hidden />}
            {fullscreen ? "Exit full screen" : "Full screen"}
          </button>
        </div>
      </div>
      <div className="flex flex-wrap items-end gap-x-8 gap-y-1">
        <p className="text-sm text-fog">Live engine: every number below is computed right now.</p>
        <Fact label="Profit today, per day">
          <span className={profit !== null && profit < 0 ? "tone-loss" : ""}>{inr(profit)}</span> <span className="text-fog">to</span> {inr(planned)}
          {delta !== null && <span className="ml-1.5 text-sm font-semibold tone-gain">{delta >= 0 ? "+" : "\u2212"}{inrDay(Math.abs(delta))} planned</span>}
        </Fact>
        <Fact label="Data trust">{pct(d.dataTrust)}</Fact>
        <Fact label="Planted problems found">{d.found === null ? "—" : `${d.found} of ${d.expected}`}</Fact>
        <Fact label="Forecast calibration">{d.factor === null ? "—" : `×${d.factor.toFixed(2)}`}</Fact>
      </div>
    </header>
  );
}
