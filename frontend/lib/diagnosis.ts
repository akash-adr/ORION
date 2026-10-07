import type { FunnelStageView } from "@/components/charts/FunnelBars";
import { stageDisplay } from "./names";
import type { CampaignMove, FunnelStage } from "./types";

const isStage = (x: FunnelStage | CampaignMove): x is FunnelStage => "stage" in x;

/** GA4 funnel stages for the chart; null when the funnel is a list of campaign moves (channel-level anomalies). */
export function funnelStages(funnel: (FunnelStage | CampaignMove)[] | null): FunnelStageView[] | null {
  const stages = (funnel ?? []).filter(isStage);
  if (!stages.length) return null;
  const first = stages[0];
  const sessions = first.recent_rate ? first.recent_count_per_day / first.recent_rate : 0;
  return [
    { label: stageDisplay(first.from), count: sessions, rate: null },
    ...stages.map((s) => ({ label: stageDisplay(s.stage), count: s.recent_count_per_day, rate: s.recent_rate, baselineRate: s.baseline_rate, biggestDrop: s.is_biggest_drop && s.change_pct < -0.005 })),
  ];
}

export function campaignMoves(funnel: (FunnelStage | CampaignMove)[] | null): CampaignMove[] {
  return (funnel ?? []).filter((x): x is CampaignMove => !isStage(x));
}

/** Raw funnel steps (baseline vs recent step rates) for the table. */
export function funnelSteps(funnel: (FunnelStage | CampaignMove)[] | null): FunnelStage[] {
  return (funnel ?? []).filter(isStage);
}

/** Index a series to 100 at the mean of the baseline window. */
export function indexTo100(values: (number | null)[], dates: string[], from: string | null | undefined, to: string | null | undefined): (number | null)[] {
  const base = values.filter((v, i): v is number => v !== null && !!from && !!to && dates[i] >= from && dates[i] <= to);
  const mean = base.length ? base.reduce((a, b) => a + b, 0) / base.length : null;
  return values.map((v) => (v === null || !mean ? null : (v / mean) * 100));
}
