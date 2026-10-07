import type { FunnelStageView } from "@/components/charts/FunnelBars";
import { stageDisplay } from "./names";
import type { CampaignMove, FunnelStage } from "./types";

const isStage = (x: FunnelStage | CampaignMove): x is FunnelStage => "stage" in x;

/** GA4 funnel stages for the chart; null when the funnel is a list of campaign moves (channel-level anomalies). */
export function funnelStages(funnel: (FunnelStage | CampaignMove)[]): FunnelStageView[] | null {
  const stages = funnel.filter(isStage);
  if (!stages.length) return null;
  const first = stages[0];
  const sessions = first.recent_rate ? first.recent_count_per_day / first.recent_rate : 0;
  return [
    { label: stageDisplay(first.from), count: sessions, rate: null },
    ...stages.map((s) => ({ label: stageDisplay(s.stage), count: s.recent_count_per_day, rate: s.recent_rate, baselineRate: s.baseline_rate, biggestDrop: s.is_biggest_drop })),
  ];
}

export function campaignMoves(funnel: (FunnelStage | CampaignMove)[]): CampaignMove[] {
  return funnel.filter((x): x is CampaignMove => !isStage(x));
}
