"use client";

import { QueryClient, useMutation, useQuery as useRQ, useQueryClient, type UseQueryOptions, type UseQueryResult } from "@tanstack/react-query";
import { api, ApiError } from "./api";
import { useHydrated } from "./use-hydrated";
import type { Autonomy, Objective } from "./types";

const SECOND = 1000;

/**
 * useQuery that reports "pending" until the page has hydrated. The server renders skeletons; a query that resolves while React
 * is still hydrating a later part of the tree would otherwise render data where the server rendered a skeleton (a hydration mismatch).
 */
function useQuery<T>(options: UseQueryOptions<T, Error, T, readonly unknown[]>): UseQueryResult<T, Error> {
  const hydrated = useHydrated();
  const q = useRQ(options);
  if (hydrated) return q;
  return { ...q, data: undefined, isPending: true, isSuccess: false, isError: false, error: null, status: "pending" } as unknown as UseQueryResult<T, Error>;
}

export const keys = {
  kpis: (period: number) => ["kpis", period] as const,
  trend: (days: number) => ["trend", days] as const,
  channels: ["channels"] as const,
  campaigns: ["campaigns"] as const,
  sources: ["sources"] as const,
  dataQuality: ["data-quality"] as const,
  anomalies: ["anomalies"] as const,
  diagnosis: (id: string) => ["diagnosis", id] as const,
  causal: (id: string) => ["causal", id] as const,
  reconciliation: ["reconciliation"] as const,
  recommendations: (objective?: string) => ["recommendations", objective ?? "current"] as const,
  audit: ["audit"] as const,
  curves: ["curves"] as const,
  opportunities: ["opportunities"] as const,
  learning: ["learning"] as const,
  settings: ["settings"] as const,
  metaConfig: ["meta-config"] as const,
  loopLast: ["loop-last"] as const,
  brainManifest: ["brain-manifest"] as const,
  brainSnapshot: ["brain-snapshot"] as const,
  brainState: ["brain-state"] as const,
  health: ["health"] as const,
};

export function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30 * SECOND,
        refetchOnWindowFocus: false,
        // an unreachable engine is shown by the offline banner; retrying quickly once is enough
        retry: (count, err) => !(err instanceof ApiError && err.status >= 400 && err.status < 500) && count < 1,
        retryDelay: 800,
      },
    },
  });
}

// Reads. Slow-moving engine output gets a longer staleTime; anything an action can change is refetched by invalidateAfterAction.
export const useKpis = (period = 7) => useQuery({ queryKey: keys.kpis(period), queryFn: () => api.kpis(period), staleTime: 30 * SECOND });
export const useTrend = (days = 45) => useQuery({ queryKey: keys.trend(days), queryFn: () => api.trend(days), staleTime: 60 * SECOND });
export const useChannels = () => useQuery({ queryKey: keys.channels, queryFn: api.channels, staleTime: 30 * SECOND });
export const useCampaigns = () => useQuery({ queryKey: keys.campaigns, queryFn: api.campaigns, staleTime: 30 * SECOND });
export const useSources = () => useQuery({ queryKey: keys.sources, queryFn: api.sources, staleTime: 60 * SECOND });
export const useDataQuality = () => useQuery({ queryKey: keys.dataQuality, queryFn: api.dataQuality, staleTime: 60 * SECOND });
export const useAnomalies = () => useQuery({ queryKey: keys.anomalies, queryFn: api.anomalies, staleTime: 30 * SECOND });
export const useDiagnosis = (id: string | null) =>
  useQuery({ queryKey: keys.diagnosis(id ?? ""), queryFn: () => api.diagnosis(id as string), enabled: !!id, staleTime: 5 * 60 * SECOND });
export const useCausal = (id: string | null) =>
  useQuery({ queryKey: keys.causal(id ?? ""), queryFn: () => api.causal(id as string), enabled: !!id, staleTime: 5 * 60 * SECOND });
export const useReconciliation = () => useQuery({ queryKey: keys.reconciliation, queryFn: api.reconciliation, staleTime: 60 * SECOND });
export const useRecommendations = (objective?: Objective) =>
  useQuery({ queryKey: keys.recommendations(objective), queryFn: () => api.recommendations(objective), staleTime: 20 * SECOND });
export const useAudit = () => useQuery({ queryKey: keys.audit, queryFn: api.audit, staleTime: 20 * SECOND });
export const useCurves = () => useQuery({ queryKey: keys.curves, queryFn: api.curves, staleTime: 60 * SECOND });
export const useOpportunities = () => useQuery({ queryKey: keys.opportunities, queryFn: api.opportunities, staleTime: 5 * 60 * SECOND });
export const useLearning = () => useQuery({ queryKey: keys.learning, queryFn: api.learning, staleTime: 30 * SECOND });
export const useSettings = () => useQuery({ queryKey: keys.settings, queryFn: api.settings, staleTime: 10 * SECOND });
export const useMetaConfig = () => useQuery({ queryKey: keys.metaConfig, queryFn: api.metaConfig, staleTime: Infinity });
export const useLoopLast = () => useQuery({ queryKey: keys.loopLast, queryFn: api.loopLast, staleTime: 10 * SECOND });
export const useBrainSnapshot = () => useQuery({ queryKey: keys.brainSnapshot, queryFn: api.brainSnapshot, staleTime: 10 * SECOND });
export const useBrainManifest = () => useQuery({ queryKey: keys.brainManifest, queryFn: api.brainManifest, staleTime: Infinity });

/** Everything an action (approve, refresh, objective change…) can change. */
const AFTER_ACTION = [
  "kpis", "trend", "recommendations", "audit", "learning", "curves", "campaigns", "channels", "sources", "opportunities",
  "brain-snapshot", "loop-last", "anomalies", "settings", "optimize",
] as const;

export function invalidateAfterAction(qc: QueryClient) {
  return Promise.all(AFTER_ACTION.map((k) => qc.invalidateQueries({ queryKey: [k] })));
}

/** Mutations used by the shell; page-level actions (approve, simulate) are added with their pages. */
export function useUpdateSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { autonomy?: Autonomy; objective?: Objective }) => api.updateSettings(body),
    onSuccess: (settings) => {
      qc.setQueryData(keys.settings, settings);
      void invalidateAfterAction(qc);
    },
  });
}
export function useRefresh() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: api.refresh, onSuccess: () => void invalidateAfterAction(qc) });
}
export function useReplay() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: api.brainReplay, onSuccess: () => qc.invalidateQueries({ queryKey: ["brain-snapshot"] }) });
}
export function useDemoReset() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: api.demoReset, onSuccess: () => void invalidateAfterAction(qc) });
}
export function useAsk() {
  return useMutation({ mutationFn: (q: string) => api.ask(q) });
}

/** Approve / reject / roll back. Callers show the toast; every outcome (even {ok:false}) refreshes the engine's views. */
function useDecisionMutation<T>(fn: (id: string) => Promise<T>) {
  const qc = useQueryClient();
  // not awaited: the row that fired the action may unmount once the lists refresh, and its toast callback must still run
  return useMutation({ mutationFn: fn, onSettled: () => void invalidateAfterAction(qc) });
}
export const useApprove = () => useDecisionMutation(api.approve);
export const useReject = () => useDecisionMutation(api.reject);
export const useRollback = () => useDecisionMutation(api.rollback);

/** The optimizer's plan for the current objective (used for each campaign's bound reasons). */
export const useOptimizeKey = () => {
  const { data: settings } = useSettings();
  const objective = settings?.objective;
  return useQuery({ queryKey: ["optimize", objective ?? ""], queryFn: () => api.optimize({ objective }), enabled: !!objective, staleTime: 60 * SECOND });
};
