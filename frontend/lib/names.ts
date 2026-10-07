import type { ActionType, AnomalyKind, Autonomy, BrainRegion, Channel, Objective } from "./types";

const CHANNEL_NAMES: Record<string, string> = {
  meta: "Meta",
  google: "Google",
  amazon: "Amazon",
  tiktok: "TikTok",
  programmatic: "Programmatic",
};

/** "tiktok" → "TikTok" (never "Tiktok"). Unknown ids are capitalised. */
export function channelDisplay(id: string | null | undefined): string {
  if (!id) return "—";
  const key = id.toLowerCase();
  return CHANNEL_NAMES[key] ?? key.charAt(0).toUpperCase() + key.slice(1);
}

export function channelId(display: string): Channel | string {
  const key = display.trim().toLowerCase();
  return key in CHANNEL_NAMES ? (key as Channel) : key;
}

export interface CampaignParts {
  /** channel id, e.g. "tiktok" */
  channel: string;
  channelName: string;
  product: string;
  audience: string;
}

/** "Meta · Summer Sneakers · broad" → { channel: "meta", channelName: "Meta", product: "Summer Sneakers", audience: "broad" }. */
export function parseCampaignName(name: string): CampaignParts {
  const [c = "", ...rest] = name.split("·").map((s) => s.trim());
  const audience = rest.length > 1 ? (rest[rest.length - 1] ?? "") : "";
  const product = rest.length > 1 ? rest.slice(0, -1).join(" · ") : (rest[0] ?? "");
  const channel = channelId(c) as string;
  return { channel, channelName: channelDisplay(channel), product, audience };
}

const KINDS: Record<string, string> = {
  creative_fatigue: "Creative fatigue",
  cpc_spike: "CPC spike",
  positive_spike: "Positive spike",
  stockout_risk: "Stockout risk",
  conversion_drop: "Conversion drop",
  metric_shift: "Metric shift",
  attribution_inflation: "Attribution inflation",
};
export function kindDisplay(kind: AnomalyKind | null | undefined): string {
  if (!kind) return "—";
  return KINDS[kind] ?? kind.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
}

const ACTIONS: Record<string, string> = {
  bid_cap: "Cap bids",
  budget_cut: "Cut budget",
  creative_refresh: "Refresh creative",
  data_fix: "Fix data",
  inventory_protect: "Protect stock",
  launch_test: "Launch a test",
  price_review: "Review price",
  scale_up: "Scale up",
};
export function actionTypeDisplay(type: ActionType | null | undefined): string {
  if (!type) return "—";
  return ACTIONS[type] ?? type.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
}

/** The engine's anomaly label is "Kind · entity…"; return only the entity part ("Meta · Summer Sneakers · broad"). */
export function anomalyEntity(label: string): string {
  const i = label.indexOf("·");
  return i === -1 ? label : label.slice(i + 1).trim();
}

export const OBJECTIVE_LABELS: Record<Objective, string> = {
  max_profit: "Max profit",
  revenue_target: "Grow revenue",
  clear_inventory: "Clear stock",
  launch_sku: "Launch a product",
};

export const AUTONOMY_LABELS: Record<Autonomy, { label: string; hint: string }> = {
  advisory: { label: "Advisory", hint: "The engine recommends only. Nothing is sent to the ad platforms." },
  supervised: { label: "Supervised", hint: "You approve every change before it is sent to the ad platforms." },
  autonomous: { label: "Autonomous", hint: "Low-risk changes within the guardrails apply on their own. Everything else waits for you." },
};

export const REGION_LABELS: Record<BrainRegion, string> = {
  ingest: "Ingest",
  diagnose: "Diagnose",
  decide: "Decide",
  learn: "Learn",
};

/** Factor names are a fixed M4 contract; each maps to one colour token (see globals.css --factor-*). */
export type FactorKey = "budget" | "auction" | "creative" | "conversion" | "price" | "traffic" | "site";
const FACTOR_KEYS: Record<string, FactorKey> = {
  "Budget change": "budget",
  "Auction cost (CPM/CPC)": "auction",
  "Click-through / creative": "creative",
  "Conversion rate": "conversion",
  "Price / unit margin": "price",
  "Traffic (sessions)": "traffic",
  "Site conversion rate": "site",
};
export function factorKey(name: string): FactorKey | null {
  return FACTOR_KEYS[name] ?? null;
}
/** CSS colour for a factor bar; unknown factors fall back to the muted text colour. */
export function factorColor(name: string): string {
  const k = factorKey(name);
  return k ? `var(--factor-${k})` : "var(--fog)";
}

/** Funnel stage ids from the GA4 source → readable labels. */
export function stageDisplay(stage: string): string {
  const map: Record<string, string> = {
    pdp_views: "Product page views",
    add_to_cart: "Added to cart",
    checkout: "Reached checkout",
    purchase: "Purchased",
    purchases: "Purchased",
    orders: "Purchased",
    sessions: "Sessions",
  };
  return map[stage] ?? stage.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
}
