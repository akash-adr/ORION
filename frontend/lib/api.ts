import type {
  ActionResult,
  Anomaly,
  ApproveResult,
  AskResult,
  AuditEntry,
  BrainEvents,
  BrainManifest,
  BrainSnapshot,
  BrainState,
  CampaignRow,
  CausalResult,
  ChannelRow,
  Curve,
  DataQualityRow,
  Diagnosis,
  Health,
  Kpis,
  Learning,
  LoopLast,
  MetaConfig,
  Objective,
  Autonomy,
  Opportunities,
  OptimizeResult,
  ReconciliationRow,
  Recommendations,
  RefreshResult,
  RejectResult,
  RollbackResult,
  Settings,
  Simulation,
  SourceRow,
  TrendPoint,
} from "./types";

export const API_URL = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");
const TIMEOUT_MS = 15_000;

/** A non-2xx answer, a timeout (status 408) or an unreachable engine (status 0). */
export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: string,
  ) {
    super(detail);
    this.name = "ApiError";
  }
  get unreachable() {
    return this.status === 0 || this.status === 408;
  }
}

// Connectivity is reported to the shell (offline banner) without coupling the client to React.
type Listener = (online: boolean) => void;
const listeners = new Set<Listener>();
let online = true;
export function onConnectivity(cb: Listener): () => void {
  listeners.add(cb);
  return () => listeners.delete(cb);
}
function setOnline(next: boolean) {
  if (next === online) return;
  online = next;
  listeners.forEach((l) => l(next));
}

async function request<T>(method: "GET" | "POST", path: string, body?: unknown): Promise<T> {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), TIMEOUT_MS);
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      method,
      headers: body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: ctl.signal,
      cache: "no-store",
    });
  } catch (e) {
    const timedOut = e instanceof DOMException && e.name === "AbortError";
    setOnline(false);
    throw new ApiError(timedOut ? 408 : 0, timedOut ? "The engine took too long to answer." : "The engine isn't reachable.");
  } finally {
    clearTimeout(timer);
  }
  setOnline(true);
  let data: unknown = null;
  try {
    data = await res.json();
  } catch {
    /* empty or non-JSON body */
  }
  if (!res.ok) {
    const detail =
      data && typeof data === "object" && "detail" in data
        ? typeof (data as { detail: unknown }).detail === "string"
          ? (data as { detail: string }).detail
          : "The request was not valid."
        : `The engine answered ${res.status}.`;
    throw new ApiError(res.status, detail);
  }
  return data as T;
}

const get = <T,>(path: string) => request<T>("GET", path);
const post = <T,>(path: string, body: unknown = {}) => request<T>("POST", path, body);
const qs = (params: Record<string, string | number | null | undefined>) => {
  const s = Object.entries(params)
    .filter(([, v]) => v !== null && v !== undefined)
    .map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`)
    .join("&");
  return s ? `?${s}` : "";
};

export const api = {
  health: () => get<{ ok: boolean; version: string }>("/health"),
  // KPIs & data
  kpis: (period = 7) => get<Kpis>(`/kpis${qs({ period })}`),
  trend: (days = 45) => get<TrendPoint[]>(`/trend${qs({ days })}`),
  channels: () => get<ChannelRow[]>("/channels"),
  campaigns: () => get<CampaignRow[]>("/campaigns"),
  sources: () => get<SourceRow[]>("/sources"),
  dataQuality: () => get<DataQualityRow[]>("/data-quality"),
  // detection & diagnosis
  anomalies: () => get<Anomaly[]>("/anomalies"),
  diagnosis: (anomalyId: string) => get<Diagnosis>(`/anomalies/${encodeURIComponent(anomalyId)}/diagnosis`),
  causal: (eventId: string) => get<CausalResult>(`/causal/${encodeURIComponent(eventId)}`),
  reconciliation: () => get<ReconciliationRow[]>("/reconciliation"),
  // decisions
  recommendations: (objective?: Objective) => get<Recommendations>(`/recommendations${qs({ objective })}`),
  approve: (id: string) => post<ApproveResult>(`/decisions/${encodeURIComponent(id)}/approve`),
  reject: (id: string) => post<RejectResult>(`/decisions/${encodeURIComponent(id)}/reject`),
  rollback: (id: string) => post<RollbackResult>(`/decisions/${encodeURIComponent(id)}/rollback`),
  audit: () => get<AuditEntry[]>("/audit"),
  // optimizer
  optimize: (body: { objective?: Objective; total_budget?: number | null } = {}) => post<OptimizeResult>("/optimize", body),
  simulate: (plan: Record<string, number>) => post<Simulation>("/simulate", { plan }),
  simulateChannels: (multipliers: Record<string, number>) => post<Simulation>("/simulate/channels", { multipliers }),
  curves: () => get<Curve[]>("/curves"),
  opportunities: () => get<Opportunities>("/opportunities"),
  // learning
  learning: () => get<Learning>("/learning"),
  // brain
  brainManifest: () => get<BrainManifest>("/brain/manifest"),
  brainSnapshot: () => get<BrainSnapshot>("/brain/snapshot"),
  brainEvents: (since?: string | null, limit = 100) => get<BrainEvents>(`/brain/events${qs({ since, limit })}`),
  brainState: () => get<BrainState>("/brain/state"),
  brainReplay: () => post<{ ok: boolean; events_queued: number; first_id: string; last_id: string }>("/brain/replay"),
  // settings, agent, loop
  settings: () => get<Settings>("/settings"),
  updateSettings: (body: { autonomy?: Autonomy; objective?: Objective }) => post<Settings>("/settings", body),
  metaConfig: () => get<MetaConfig>("/meta/config"),
  ask: (question: string) => post<AskResult>("/ask", { question }),
  refresh: () => post<RefreshResult>("/refresh"),
  loopLast: () => get<LoopLast>("/loop/last"),
  demoReset: () => post<ActionResult<object> & Partial<RefreshResult>>("/demo/reset"),
};

export type { Health };
