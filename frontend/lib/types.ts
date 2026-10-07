/**
 * API types for the Margin Mind engine (M9 backend). Written from the REAL responses saved in lib/__samples__/.
 * Money is Indian rupees (INR). Dates are "YYYY-MM-DD"; timestamps are naive IST "YYYY-MM-DDTHH:MM:SS".
 * Any numeric field can be null when the engine could not compute it (NaN/Infinity never reach the wire).
 * Fractions are 0–1 (0.25 = 25%), never already multiplied by 100.
 */

/**
 * GET /kpis?period=7 — the last `period` days vs the `period` days before them, anchored on the last data date.
 *
 * PER-DAY VALUES (₹/day, the daily average over the period; NOT period totals):
 *   spend.value, revenue.value, profit.value
 * RATIOS (Σ ÷ Σ over the period, dimensionless):
 *   poas.value (gross margin ÷ spend), roas_true.value (store revenue ÷ spend), roas_platform.value (platform-claimed revenue ÷ spend)
 * `.change` on every block is a FRACTION vs the previous period (-0.49 = down 49%).
 * COUNT: stock_at_risk.value (SKUs under the cover guard).
 * FRACTION: data_trust (spend-weighted source trust, 0–1).
 * DATE / TIMESTAMP: as_of (last data date), last_synced (last source sync).
 * To show a period TOTAL multiply a per-day value by period_days; always label the unit (/day, last 7 days).
 */
export interface Kpi {
  value: number | null;
  change: number | null;
}
export interface Kpis {
  spend: Kpi;
  revenue: Kpi;
  profit: Kpi;
  poas: Kpi;
  roas_true: Kpi;
  roas_platform: Kpi;
  period_days: number;
  stock_at_risk: { value: number; skus: { sku_id: string; name: string; days_cover: number }[] };
  as_of: string;
  last_synced: string;
  data_trust: number | null;
}

/** GET /trend?days=45 — daily totals over all campaigns, ₹ per DAY (not averages). poas = Σ gross margin ÷ Σ spend that day. */
export interface TrendPoint {
  date: string;
  spend: number;
  revenue: number;
  platform_revenue: number;
  profit: number;
  poas: number | null;
}

export type Channel = "meta" | "google" | "amazon" | "tiktok" | "programmatic";

/** GET /channels — last 7 days; spend / revenue / profit are ₹/day averages. */
export interface ChannelRow {
  channel: Channel;
  name: string;
  spend: number;
  revenue: number;
  profit: number;
  poas: number | null;
  roas_true: number | null;
  roas_platform: number | null;
  trust_score: number;
  inflation_pct: number;
}

/** Where the next rupee goes: scale (headroom), hold, cut (past saturation), locked (stock guard). */
export type Headroom = "scale" | "hold" | "cut" | "locked" | null;

/** GET /campaigns — spend_7d / spend_28d / profit_7d are ₹/day averages over that window. campaign_name is "Channel · Product · audience". */
export interface CampaignRow {
  campaign_id: string;
  channel: Channel;
  sku_id: string;
  audience: string;
  spend_7d: number;
  spend_28d: number;
  poas_7d: number | null;
  poas_28d: number | null;
  ctr_7d: number | null;
  cvr_7d: number | null;
  cpm_7d: number | null;
  freq_7d: number | null;
  profit_7d: number;
  campaign_name: string;
  channel_name: string;
  current_spend: number;
  marginal_poas: number | null;
  optimal_spend: number;
  saturation_spend: number;
  uncertainty: number;
  days_cover: number;
  headroom: Headroom;
}

export interface BrainAlert {
  target_id: string;
  target_type: "neuron" | "cluster" | "source" | string;
  anomaly_ids: string[];
  top_kind: AnomalyKind;
  top_severity: Severity;
  direction: "loss" | "gain" | string;
  profit_impact: number;
  stock_locked: boolean;
  message: string;
}

export type SourceStatus = "ok" | "warn";

/** GET /sources */
export interface SourceRow {
  source_id: string;
  label: string;
  kind: "ad_platform" | "store" | "erp" | "analytics" | "pricing";
  connector: string;
  file: string;
  rows: number;
  min_date: string;
  max_date: string;
  last_synced: string;
  status: SourceStatus;
  trust_score: number;
  inflation_pct: number;
  detail: string;
  verified: boolean;
  alert: BrainAlert | null;
}

export interface DataQualityRow {
  check: string;
  status: "pass" | "warn";
  affected_rows: number;
  detail: string;
  action: string;
}

export interface ReconciliationRow {
  channel: Channel;
  platform_conversions: number;
  store_orders: number;
  platform_revenue: number;
  true_revenue: number;
  spend: number;
  inflation_pct: number;
  roas_platform: number;
  roas_true: number;
  trust_score: number;
  last_synced: string;
}

export type Severity = "high" | "medium" | "low";
export type AnomalyKind =
  | "creative_fatigue"
  | "cpc_spike"
  | "positive_spike"
  | "stockout_risk"
  | "conversion_drop"
  | "metric_shift"
  | "attribution_inflation"
  | string;

export interface AnomalyWindow {
  recent_start: string;
  recent_end: string;
  baseline_start: string;
  baseline_end: string;
}

/** GET /anomalies. detail varies by kind (see the optional fields). profit_impact is ₹/day (negative = loss). change_pct is a fraction. */
export interface Anomaly {
  id: string;
  kind: AnomalyKind;
  entity_type: "campaign" | "sku" | "channel" | "source" | string;
  entity_id: string;
  label: string;
  metric: string;
  baseline: number;
  recent: number;
  change_pct: number;
  z: number;
  profit_impact: number;
  severity: Severity;
  detail: {
    related: string[];
    direction: "loss" | "gain" | string;
    window: AnomalyWindow;
    campaigns?: string[];
    frequency_baseline?: number;
    frequency_recent?: number;
    freq_change?: number;
    creative_id?: string;
    cpm_change?: number;
    ctr_change?: number;
    days_cover?: number;
    spend_per_day?: number;
    on_hand?: number;
    inbound?: number;
    atc_rate_change?: number;
    price_start?: number;
    price_end?: number;
    price_change?: number;
    event_id?: string;
    test?: string;
    [k: string]: unknown;
  };
}

/** One bar of the M4 waterfall. impact is ₹/day (signed); pct is the share of the total movement (fraction of |total|). */
export interface Factor {
  name: string;
  impact: number;
  pct: number;
}

/** GA4 funnel step (campaign / SKU anomalies). */
export interface FunnelStage {
  stage: string;
  from: string;
  baseline_rate: number;
  recent_rate: number;
  change_pct: number;
  baseline_count_per_day: number;
  recent_count_per_day: number;
  is_biggest_drop: boolean;
}
/** A funnel entry for channel-level anomalies (cpc_spike): which campaigns moved. */
export interface CampaignMove {
  campaign_id: string;
  campaign_name: string;
  baseline_profit: number;
  recent_profit: number;
  change: number;
  top_factor: string;
}

export interface RootCause {
  anomaly_id: string;
  entity_id: string;
  /** ₹/day change in the headline metric (the waterfall's net). */
  total_change: number;
  factors: Factor[];
  /** null for attribution anomalies (no factors and no funnel; they are explained by the reconciliation) */
  funnel: (FunnelStage | CampaignMove)[] | null;
  narrative: string;
}

/** GET /causal/{id} (synthetic control). ci_low / ci_high bound `total_effect` (₹ over n_post days), NOT effect_per_day. */
export interface CausalResult {
  event_id: string;
  description: string;
  effect_per_day: number;
  total_effect: number;
  ci_low: number;
  ci_high: number;
  series: { date: string; actual: number; counterfactual: number; is_post: boolean }[];
  units_change_pct: number;
  n_post: number;
  controls: string[];
  treated_sku: string;
  ci_includes_zero: boolean;
}

/** Evidence rows differ by kind: campaigns have spend/profit/ctr/cpc/frequency; SKUs have sessions/site_cvr/units/days_cover/unit_price. */
export type EvidenceRow = { date: string } & Record<string, number | string | null>;
export interface Diagnosis {
  anomaly: Anomaly;
  root_cause: RootCause;
  evidence: { daily: EvidenceRow[]; causal: CausalResult | null; related: unknown[] };
}

export type ActionType =
  | "bid_cap"
  | "budget_cut"
  | "creative_refresh"
  | "data_fix"
  | "inventory_protect"
  | "launch_test"
  | "price_review"
  | "scale_up"
  | string;

export interface BudgetChange {
  campaign_id: string;
  name: string;
  channel: Channel;
  /** ₹/day */
  from_budget: number;
  to_budget: number;
}
export interface BrainTarget {
  type: "neuron" | "cluster" | "source" | "ghost" | string;
  id: string;
}
export interface DecisionAction {
  type: ActionType;
  changes: BudgetChange[];
  targets: BrainTarget[];
  notes: string[];
  related: unknown[];
  [k: string]: unknown;
}
export type DecisionStatus = "pending" | "executed" | "rejected" | "rolled_back" | string;
export type Risk = "high" | "medium" | "low";

export interface ApiCall {
  platform: string;
  endpoint: string;
  method: string;
  daily_budget?: number;
  status: string;
  ts: string;
  [k: string]: unknown;
}

/** A Decision Inbox item. expected_profit_delta is ₹/day; confidence is 0.45–0.95 (fraction); calibration_factor scales predictions. */
export interface Decision {
  id: string;
  title: string;
  issue: string;
  /** Engine narrative (render in the serif). */
  cause: string;
  action: DecisionAction;
  expected_profit_delta: number;
  expected_profit_delta_fmt: string;
  confidence: number;
  risk: Risk;
  requires_approval: boolean;
  blocked: boolean;
  priority: number;
  evidence: string[];
  anomaly_id: string | null;
  status: DecisionStatus;
  calibration_factor: number;
  targets: BrainTarget[];
  /** Present once acted on. */
  executed_at?: string;
  approver?: string;
  updated_at?: string;
  block_reason?: string;
}

export interface RecommendationsSummary {
  pending: number;
  executed: number;
  rejected: number;
  rolled_back: number;
  total_expected_profit_delta: number;
  needs_approval: number;
  auto_eligible: number;
  blocked: number;
  plan_profit_delta: number | null;
}
/** GET /recommendations. `recommendations` = every decision; `pending` = those awaiting action; `history` = executed / rejected / rolled back. */
export interface Recommendations {
  objective: Objective;
  preview: boolean;
  summary: RecommendationsSummary;
  recommendations: Decision[];
  pending: Decision[];
  history: Decision[];
  calibration_factor: number;
}

export interface AuditEntry {
  ts: string;
  decision_id: string;
  title: string;
  action: "execute" | "reject" | "rollback" | string;
  approver: "user" | "autopilot" | string;
  api_calls?: ApiCall[];
  rollback?: { type: string; campaign_id: string; channel: Channel; budget: number }[];
  expected_profit_delta?: number;
  confidence?: number;
  [k: string]: unknown;
}

/** Result of approve / reject / rollback. Blocked or duplicate actions are `{ ok: false, reason }` (HTTP 200, not an error). */
export type ActionResult<T extends object = object> = ({ ok: true } & T) | { ok: false; reason: string };
export type ApproveResult = ActionResult<{ api_calls: ApiCall[]; decision: Decision; outcome: Outcome | null }>;
export type RollbackResult = ActionResult<{ api_calls: ApiCall[] }>;
export type RejectResult = ActionResult;

export interface CurvePoint {
  spend: number;
  gross_margin: number;
  profit: number;
  marginal_poas: number;
}
/** GET /curves — per campaign Hill response curve y = f(spend); all ₹/day. */
export interface Curve {
  campaign_id: string;
  name: string;
  channel: Channel;
  sku_id: string;
  audience: string;
  a: number;
  b: number;
  current_spend: number;
  marginal_poas: number | null;
  headroom: Headroom;
  optimal_spend: number;
  saturation_spend: number;
  uncertainty: number;
  days_cover: number;
  points: CurvePoint[];
}

export interface Opportunity {
  rank: number;
  sku_id: string;
  sku_name: string;
  channel: Channel;
  audience: string;
  cluster: string;
  predicted_conv_per_1k: number;
  predicted_poas: number;
  unit_margin: number;
  stock_days: number;
  stock_factor: number;
  score: number;
  /** ₹/day */
  test_budget: number;
  is_ghost: boolean;
  label: string;
  scored_at: string;
  launched: boolean;
  test_campaign_id: string | null;
}
export interface Opportunities {
  model_r2_holdout: number;
  opportunities: Opportunity[];
}

/** One measured outcome. predicted / actual are ₹/day; error_pct is a fraction; ALWAYS simulated in this demo (fixed seed). */
export interface Outcome {
  decision_id: string;
  title: string;
  date: string;
  predicted: number;
  actual: number | null;
  error_pct: number | null;
  simulated: boolean;
  seeded: boolean;
  action_type: ActionType;
  campaigns: string[];
  synapses: string[];
  synapse_deltas: Record<string, number>;
  measurable: boolean;
  /** Engine note (render in the serif). */
  note: string;
  measured_at: string;
}
export interface Learning {
  outcomes: Outcome[];
  accuracy_curve: { index: number; date: string; decision_id: string; rolling_mape: number | null }[];
  cumulative_profit: { date: string; cumulative: number }[];
  calibration: { factor: number; mape: number | null; win_rate: number | null; n: number };
  /** keys are "CMP-01->SKU-A" */
  synapse_strength: Record<string, number>;
  kpis: { forecast_error: number | null; calibration_factor: number; win_rate: number | null; measured_count: number; total_measured_profit: number };
  simulated_note: string;
}

export type Autonomy = "advisory" | "supervised" | "autonomous";
export type Objective = "max_profit" | "revenue_target" | "clear_inventory" | "launch_sku";
export interface Settings {
  autonomy: Autonomy;
  objective: Objective;
  autonomy_modes: Autonomy[];
  objectives: Objective[];
  refresh_minutes: number;
  demo_mode: boolean;
  agent: { claude_available: boolean };
  last_refresh_at: string | null;
  /** null when the background loop is not running */
  next_refresh_at: string | null;
}

/** GET /meta/config — read-only thresholds (fractions are 0–1, money in ₹/day). */
export interface MetaConfig {
  detection: {
    RECENT_DAYS: number;
    BASELINE_DAYS: number;
    Z_THRESHOLD: number;
    MIN_PCT_CHANGE: number;
    STOCK_COVER_RISK_DAYS: number;
    SKU_RECENT_DAYS: number;
    SKU_BASELINE_DAYS: number;
  };
  guardrails: {
    AUTO_APPLY_MAX_SHIFT: number;
    DAILY_CHANGE_CAP: number;
    STOCK_SPEND_CAP_MULT: number;
    RISK_HIGH_SHIFT: number;
    RISK_HIGH_IMPACT: number;
    RISK_MEDIUM_SHIFT: number;
    CONFIDENCE_MIN: number;
    CONFIDENCE_MAX: number;
  };
  optimizer: { OVERSTOCK_COVER_DAYS: number; LAUNCH_TEST_RESERVE: number; OPP_TEST_BUDGET: number };
  learning: { CALIBRATION_WINDOW: number; CALIBRATION_MIN: number; CALIBRATION_MAX: number };
  loop: { REFRESH_MINUTES: number };
  currency: string;
}

export type LoopStepName = "ingest" | "detect" | "diagnose" | "optimize" | "decide" | "learn";
export interface LoopStep {
  ok: boolean;
  duration_ms: number;
  events?: number;
  error?: string;
}
/** POST /refresh result; GET /loop/last returns the same plus `at` (null if the loop never ran). */
export interface RefreshResult {
  ok: boolean;
  steps: Record<LoopStepName, LoopStep>;
  auto_applied: string[];
  outcomes_measured: number;
  events_logged: number;
  duration_ms: number;
}
export type LoopLast = (RefreshResult & { at: string }) | null;

export type BrainRegion = "ingest" | "diagnose" | "decide" | "learn";
export type BrainEventType = "ingest" | "anomaly" | "diagnosis" | "recommendation" | "approval" | "rejection" | "rollback" | "auto_apply" | "outcome";
export interface BrainEvent {
  id: string;
  ts: string;
  type: BrainEventType;
  region: BrainRegion;
  path: string[];
  entity_id: string | null;
  ref_id: string | null;
  severity: Severity;
  message: string;
  payload: Record<string, unknown> & { replay?: boolean };
}
export interface BrainEvents {
  events: BrainEvent[];
  last_id: string | null;
}
export type BrainMode = "idle" | "ingesting" | "thinking" | "deciding" | "learning" | string;
export interface BrainState {
  mode: BrainMode;
  active_region: BrainRegion | null;
  last_event_id: string | null;
  counts: { anomalies: number; pending_decisions: number; outcomes: number };
}

export type Health = "good" | "weak" | "losing";
/** One neuron: a campaign (entity_type "campaign") or a SKU ("sku"). spend / profit are ₹/day over 7 days; change_pct is a fraction. */
export interface BrainNode {
  entity_id: string;
  entity_type: "campaign" | "sku" | string;
  label: string;
  cluster: string;
  channel: Channel | null;
  sku_id: string;
  spend_7d: number;
  poas_7d: number | null;
  profit_7d: number;
  change_pct: number | null;
  health: Health;
  size: number;
  roas_platform_7d: number | null;
  roas_true_7d: number | null;
  trust_score: number | null;
  days_cover: number | null;
  is_alerting: boolean;
  anomaly_id: string | null;
  anomaly_ids: string[];
  alert_kind: AnomalyKind | null;
  alert_severity: Severity | null;
  alert_direction: string | null;
  stock_locked: boolean;
  alert_message: string | null;
  headroom: Headroom;
  marginal_poas: number | null;
  /** fraction the current objective's plan would change this campaign's budget by */
  planned_change_pct: number | null;
  current_spend: number;
  why: string | null;
}
export interface BrainSource {
  id: string;
  label: string;
  kind: string;
  channel: string;
  status: SourceStatus | null;
  trust_score: number | null;
  inflation_pct: number | null;
  verified: boolean;
  alert: BrainAlert | null;
}
export interface BrainCluster {
  id: string;
  label: string;
  alert: BrainAlert | null;
}
export interface BrainGhost {
  id: string;
  sku_id: string;
  channel: Channel;
  cluster: string;
  audience: string;
  predicted_poas: number;
  score: number;
  launched: boolean;
  test_campaign_id: string | null;
}
export interface BrainSynapse {
  source: string;
  target: string;
  kind: string;
  strength: number;
  test?: boolean;
}
export interface DetectionQuality {
  expected: number;
  found: number;
  missed: string[];
  recall: number;
  precision: number;
  extra_alerts: { id: string; kind: string; entity_id: string; label: string }[];
  knock_on: { id: string; kind: string; entity_id: string; label: string; reason: string; scenario: string; related: string[] }[];
  false_alarms: unknown[];
  per_scenario: Record<string, { found: boolean; anomaly_id: string; anomaly_ids: string[]; label: string }>;
  evaluated_at: string;
}
/** GET /brain/snapshot — everything the map renders. headline money is ₹/day. */
export interface BrainSnapshot {
  as_of: string;
  objective: Objective;
  autonomy: Autonomy;
  nodes: BrainNode[];
  clusters: BrainCluster[];
  sources: BrainSource[];
  ghosts: BrainGhost[];
  synapses: BrainSynapse[];
  headline: {
    current_profit: number | null;
    planned_profit: number | null;
    profit_delta: number | null;
    data_trust: number | null;
    detection_quality: DetectionQuality | null;
    calibration: Learning["calibration"] | null;
  };
  counts: { anomalies: number; pending_decisions: number; executed: number; outcomes: number };
}

export interface AskResult {
  answer: string;
  engine: "claude" | "rules" | string;
  tools_used: { name: string; input: Record<string, unknown> }[];
  highlights: BrainTarget[];
  note: string;
  duration_ms: number;
}

export interface SimTotals {
  spend: number;
  gross_margin: number;
  revenue: number;
  profit: number;
  poas: number | null;
}
/** POST /simulate/channels and POST /simulate. All ₹/day. */
export interface Simulation {
  summary: {
    current: SimTotals;
    simulated: SimTotals;
    profit_delta: number;
    revenue_delta: number;
    spend_delta: number;
    stock_warnings: string[];
  };
  campaigns: {
    campaign_id: string;
    name: string;
    channel: Channel;
    current_spend: number;
    new_spend: number;
    current_profit: number;
    new_profit: number;
    current_gross_margin: number;
    new_gross_margin: number;
    current_revenue: number;
    new_revenue: number;
    marginal_poas_current: number | null;
    marginal_poas_new: number | null;
    stock_warning: boolean;
  }[];
}

/** POST /optimize. plan = {campaign_id: ₹/day}. */
export interface OptimizeResult {
  ok: boolean;
  objective: Objective;
  total_budget: number;
  plan: Record<string, number>;
  summary: {
    current: SimTotals;
    planned: SimTotals;
    profit_delta: number;
    revenue_delta: number;
    spend_delta: number;
  };
  campaigns: {
    campaign_id: string;
    name: string;
    channel: Channel;
    sku_id: string;
    current_spend: number;
    planned_spend: number;
    change_pct: number;
    current_profit: number;
    planned_profit: number;
    marginal_poas_current: number | null;
    marginal_poas_planned: number | null;
    bound_reasons: string[];
    days_cover: number;
    stock_locked: boolean;
  }[];
  solver: { ok: boolean; iterations: number; message: string };
}

export interface BrainManifest {
  version: number;
  seed: number;
  date_range: { start: string; end: string; n_days: number };
  sources: { id: string; label: string; kind: string; channel: string; file: string }[];
  clusters: { id: string; label: string }[];
  neurons: {
    entity_id: string;
    entity_type: string;
    label: string;
    cluster: string;
    channel: Channel | null;
    sku_id: string;
    audience: string | null;
    format: string | null;
    daily_budget: number | null;
    category: string | null;
    margin_pct: number | null;
  }[];
  synapses: { source: string; target: string; kind: string }[];
  stimuli: { event_id: string; date: string; type: string; targets: string[]; direction: string; label: string }[];
  scenario_timeline: {
    scenario: string;
    start_date: string;
    end_date: string;
    entities: string[];
    expected_event_type: string;
    expected_kind: string;
    expected_region: string;
    direction: string;
    detector_module: string;
    headline: string;
    expected_action: string;
  }[];
  replay_order: string[];
  hero_story: { steps: { step: number; scenario: string; focus: string; beat: string }[] };
}

/** Error body of every non-2xx response. */
export interface ErrorBody {
  detail: string;
}
