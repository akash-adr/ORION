"use client";

import { kindDisplay } from "@/lib/names";
import { useAnomalies, useBrainSnapshot, useCampaigns, useCurves, useDiagnosis, useKpis, useLearning, useLoopLast, useMetaConfig, useOpportunities, useReconciliation, useRecommendations, useSettings, useSources } from "@/lib/queries";
import type { Anomaly, BrainNode, BrainSource, Decision, Opportunity } from "@/lib/types";

export type CalloutId = "perception" | "reasoning" | "prediction" | "decision" | "memory";
export type ActionGroupId = "protect" | "creative" | "rebalance" | "price" | "launch" | "data";

/** The order and wording of the Actions list; each group is a set of decision types. */
export const ACTION_GROUPS: { id: ActionGroupId; label: string; types: string[] }[] = [
  { id: "protect", label: "Protect stock", types: ["inventory_protect"] },
  { id: "creative", label: "Refresh creative", types: ["creative_refresh"] },
  { id: "rebalance", label: "Rebalance budget", types: ["bid_cap", "budget_cut", "scale_up"] },
  { id: "price", label: "Review price", types: ["price_review"] },
  { id: "launch", label: "Launch tests", types: ["launch_test"] },
  { id: "data", label: "Fix data", types: ["data_fix"] },
];

export interface ActionGroup {
  id: ActionGroupId;
  label: string;
  decisions: Decision[];
  /** pending plus executed */
  count: number;
  /** expected profit per day, summed over pending and executed decisions */
  total: number;
  waiting: number;
  automatic: number;
  executed: number;
  blocked: boolean;
  /** neuron ids this group's decisions touch */
  targets: string[];
}

const short = (a: Anomaly) => {
  const e = a.label.includes("·") ? a.label.slice(a.label.indexOf("·") + 1).trim() : a.label;
  const parts = e.split("·").map((x) => x.trim());
  return `${kindDisplay(a.kind)}, ${a.entity_type === "campaign" ? parts.slice(0, 2).join(" ") : e}`;
};

/** Everything the Pitch page shows, derived from the engine's own queries. Nothing here is a constant. */
export function usePitchData() {
  const kpis = useKpis(7);
  const snap = useBrainSnapshot();
  const sources = useSources();
  const recon = useReconciliation();
  const anomalies = useAnomalies();
  const recs = useRecommendations();
  const opps = useOpportunities();
  const learning = useLearning();
  const loop = useLoopLast();
  const cfg = useMetaConfig();
  const settings = useSettings();
  const curves = useCurves();
  const campaigns = useCampaigns();

  // the diagnosis the "Why" step explains (the auction-cost spike if there is one, else the biggest loss with causes) and the price event's causal proof
  const anomalyList = anomalies.data ?? [];
  const whyAnomaly =
    anomalyList.find((a) => a.kind === "cpc_spike") ??
    [...anomalyList].filter((a) => a.profit_impact < 0 && a.kind !== "attribution_inflation" && a.kind !== "stockout_risk").sort((a, b) => a.profit_impact - b.profit_impact)[0] ??
    null;
  const priceAnomaly = anomalyList.find((a) => (a.detail.price_change ?? 0) !== 0) ?? null;
  const whyDx = useDiagnosis(whyAnomaly?.id ?? null);
  // one diagnosis at a time: the engine computes each from shared frames, and two at once can race on the devserver
  const priceDx = useDiagnosis(whyDx.isSuccess || whyDx.isError || !whyAnomaly ? (priceAnomaly?.id ?? null) : null);

  const all = [kpis, snap, sources, recon, anomalies, recs, opps, learning, cfg, settings, curves, campaigns];
  const ready = all.every((q) => q.isSuccess);
  const offline = all.some((q) => q.isError);

  const s = snap.data;
  const adSources: BrainSource[] = (s?.sources ?? []).filter((x) => x.kind === "ad_platform");
  const overReport = adSources.filter((x) => x.status === "warn").map((x) => ({ channel: x.channel, label: x.label, pct: x.inflation_pct ?? 0, trust: x.trust_score }));
  const list = anomalies.data ?? [];
  const topAnomaly = [...list].sort((a, b) => Math.abs(b.profit_impact) - Math.abs(a.profit_impact))[0] ?? null;
  const gains = list.filter((a) => a.profit_impact > 0).sort((a, b) => b.profit_impact - a.profit_impact);
  const dq = s?.headline.detection_quality ?? null;
  const oppList: Opportunity[] = opps.data?.opportunities ?? [];
  const summary = recs.data?.summary;
  const decisions: Decision[] = [...(recs.data?.pending ?? []), ...(recs.data?.history ?? [])];
  const pending = recs.data?.pending ?? [];
  const topRec = [...pending].sort((a, b) => b.priority - a.priority)[0] ?? null;
  const nodes: BrainNode[] = s?.nodes ?? [];
  const campaignNodes = nodes.filter((n) => n.entity_type === "campaign");

  const groups: ActionGroup[] = ACTION_GROUPS.map((g) => {
    const ds = decisions.filter((d) => g.types.includes(d.action.type) && (d.status === "pending" || d.status === "executed"));
    const ids = new Set<string>();
    for (const d of ds) {
      for (const t of d.targets) ids.add(t.id);
      for (const c of d.action.changes) ids.add(c.campaign_id);
    }
    return {
      id: g.id,
      label: g.label,
      decisions: ds,
      count: ds.length,
      total: ds.reduce((a, d) => a + d.expected_profit_delta, 0),
      waiting: ds.filter((d) => d.status === "pending" && d.requires_approval).length,
      automatic: ds.filter((d) => d.status === "pending" && !d.requires_approval).length,
      executed: ds.filter((d) => d.status === "executed").length,
      blocked: ds.some((d) => d.blocked),
      targets: [...ids],
    };
  });

  const scaleCount = campaignNodes.filter((n) => n.headroom === "scale").length;
  const cutCount = campaignNodes.filter((n) => n.headroom === "cut").length;
  const lockedCount = campaignNodes.filter((n) => n.headroom === "locked" || n.stock_locked).length;

  return {
    ready,
    offline,
    q: { whyDx, priceDx, kpis, snap, sources, recon, anomalies, recs, opps, learning, loop, cfg, settings, curves, campaigns },
    kpis: kpis.data,
    snapshot: s,
    settings: settings.data,
    cfg: cfg.data,
    learning: learning.data,
    loop: loop.data ?? null,
    opps: oppList,
    anomalies: list,
    nodes,
    why: { anomaly: whyAnomaly, diagnosis: whyDx.data ?? null },
    price: { anomaly: priceAnomaly, causal: priceDx.data?.evidence.causal ?? null },
    derived: {
      sourceCount: sources.data?.length ?? 0,
      overReport,
      dataTrust: s?.headline.data_trust ?? kpis.data?.data_trust ?? null,
      signals: list.length,
      topAnomaly,
      topAnomalyLabel: topAnomaly ? short(topAnomaly) : null,
      topGain: gains[0] ?? null,
      topGainLabel: gains[0] ? short(gains[0]) : null,
      found: dq?.found ?? null,
      expected: dq?.expected ?? null,
      ideas: oppList.length,
      bestOpp: oppList[0] ?? null,
      r2: opps.data?.model_r2_holdout ?? null,
      curveCount: curves.data?.length ?? 0,
      scaleCount,
      cutCount,
      lockedCount,
      pending: summary?.pending ?? 0,
      upside: summary?.total_expected_profit_delta ?? 0,
      needsApproval: summary?.needs_approval ?? 0,
      auto: summary?.auto_eligible ?? 0,
      blocked: summary?.blocked ?? 0,
      executed: summary?.executed ?? 0,
      mape: learning.data?.calibration.mape ?? null,
      factor: learning.data?.calibration.factor ?? null,
      winRate: learning.data?.calibration.win_rate ?? null,
      outcomes: learning.data?.kpis.measured_count ?? 0,
      groups,
      topRec,
    },
  };
}
export type PitchData = ReturnType<typeof usePitchData>;
