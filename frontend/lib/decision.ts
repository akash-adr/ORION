import type { BudgetChange, CampaignRow, Decision, MetaConfig, Outcome } from "./types";

export function changePct(c: BudgetChange): number {
  return c.from_budget ? c.to_budget / c.from_budget - 1 : 0;
}

export type BoundReason = "cap" | "stock" | "overstock";
export const BOUND_LABEL: Record<BoundReason, string> = { cap: "Daily change cap", stock: "Stock guard", overstock: "Overstock boost" };

/** Why a change stopped where it did, derived from the numbers and the engine's thresholds. */
export function boundReasons(c: BudgetChange, cfg: MetaConfig | undefined, campaign: CampaignRow | undefined): BoundReason[] {
  if (!cfg) return [];
  const pct = changePct(c);
  const out: BoundReason[] = [];
  const g = cfg.guardrails;
  const lowStock = campaign ? campaign.days_cover < cfg.detection.STOCK_COVER_RISK_DAYS : false;
  if (lowStock && c.to_budget <= c.from_budget * (g.STOCK_SPEND_CAP_MULT + 0.01)) out.push("stock");
  else if (Math.abs(pct) >= g.DAILY_CHANGE_CAP - 0.01) out.push("cap");
  if (campaign && campaign.days_cover > cfg.optimizer.OVERSTOCK_COVER_DAYS && pct > 0) out.push("overstock");
  return out;
}

export type CheckState = "pass" | "fail" | "exception" | "info";
export interface GuardrailCheck {
  label: string;
  state: CheckState;
  detail?: string;
}

/** The four guardrails the executor enforces, evaluated for one decision with the engine's own thresholds. */
export function guardrailChecks(d: Decision, cfg: MetaConfig, campaigns: CampaignRow[]): GuardrailCheck[] {
  const g = cfg.guardrails;
  const guard = cfg.detection.STOCK_COVER_RISK_DAYS;
  const byId = new Map(campaigns.map((c) => [c.campaign_id, c]));
  const changes = d.action.changes;
  const capPct = Math.round(g.DAILY_CHANGE_CAP * 100);
  const overCap = changes.filter((c) => Math.abs(changePct(c)) > g.DAILY_CHANGE_CAP + 0.005);
  const overCapByStock = overCap.filter((c) => (byId.get(c.campaign_id)?.days_cover ?? Infinity) < guard);
  const increases = changes.filter((c) => c.to_budget > c.from_budget && (byId.get(c.campaign_id)?.days_cover ?? Infinity) < guard);
  const maxShift = changes.length ? Math.max(...changes.map((c) => Math.abs(changePct(c)))) : 0;
  const autoShift = Math.round(g.AUTO_APPLY_MAX_SHIFT * 100);

  const cap: GuardrailCheck = { label: `Change within ±${capPct}% per day`, state: "pass" };
  if (!changes.length) cap.detail = "No budget change in this decision.";
  else if (overCap.length && overCap.length === overCapByStock.length) {
    cap.state = "exception";
    cap.detail = `Cut to ${Math.round(g.STOCK_SPEND_CAP_MULT * 100)}% of current spend by the stock guard, which overrides the daily cap.`;
  } else if (overCap.length) {
    cap.state = "fail";
    cap.detail = `${overCap.length} change${overCap.length > 1 ? "s" : ""} beyond the cap.`;
  } else cap.detail = `Largest change ${Math.round(maxShift * 100)}%.`;

  const stock: GuardrailCheck = { label: `No spend increase on products under ${guard} days of stock`, state: increases.length ? "fail" : "pass" };
  if (increases.length) stock.detail = `${increases.length} increase${increases.length > 1 ? "s" : ""} on low-stock products.`;

  const eligible = !d.requires_approval;
  const auto: GuardrailCheck = {
    label: `Auto-apply only if shift < ${autoShift}% and low risk`,
    state: eligible ? "pass" : "info",
    detail: eligible ? "Qualifies to run automatically in autonomous mode." : `Needs your approval (${d.risk} risk${changes.length ? `, largest shift ${Math.round(maxShift * 100)}%` : ""}).`,
  };

  const block: GuardrailCheck = {
    label: "Hard block",
    state: d.blocked ? "fail" : "pass",
    detail: d.blocked ? "Blocked by a hard guardrail. The API does not state which one." : "Not blocked.",
  };
  return [cap, stock, auto, block];
}

/** Decisions store the calibrated impact; the raw model output is that divided by the calibration factor. */
export function rawImpact(d: Decision): number {
  return d.calibration_factor ? d.expected_profit_delta / d.calibration_factor : d.expected_profit_delta;
}

export function outcomeFor(decisionId: string, outcomes: Outcome[] | undefined): Outcome | undefined {
  return outcomes?.filter((o) => o.decision_id === decisionId).at(-1);
}

export const STATUS_LABEL: Record<string, string> = {
  pending: "Waiting",
  executed: "Approved and sent",
  rejected: "Rejected",
  rolled_back: "Rolled back",
};

/** Reason ids the optimizer returns in `bound_reasons`, in plain words. */
export const OPTIMIZER_REASON: Record<string, string> = { change_cap: "Daily change cap", stock_guard: "Stock guard", overstock_boost: "Overstock boost" };
