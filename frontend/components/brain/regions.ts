export type Region = "ingest" | "diagnose" | "decide" | "learn";

/** Array index == value of the `aRegion` vertex attribute. */
export const REGIONS: Region[] = ["ingest", "diagnose", "decide", "learn"];

export const REGION_META: Record<
  Region,
  { index: number; label: string; description: string; color: string }
> = {
  ingest: { index: 0, label: "INGEST", description: "Unify ad & sales data", color: "#3b82f6" },
  diagnose: { index: 1, label: "DIAGNOSE", description: "Detect anomalies & root causes", color: "#a855f7" },
  decide: { index: 2, label: "DECIDE", description: "Choose budget & creative actions", color: "#22c55e" },
  learn: { index: 3, label: "LEARN", description: "Feed outcomes back into the model", color: "#f59e0b" },
};

export const ALERT_COLOR = "#ef4444";
export const BACKGROUND = "#05060a";

