import { Activity, Eye, Filter, Gavel, ImageOff, PackageX, Sparkles, type LucideIcon } from "lucide-react";

/** One icon per anomaly kind, shared by Signals, Diagnosis and the neural view. */
export const KIND_ICON: Record<string, LucideIcon> = {
  creative_fatigue: ImageOff,
  cpc_spike: Gavel,
  positive_spike: Sparkles,
  stockout_risk: PackageX,
  conversion_drop: Filter,
  metric_shift: Activity,
  attribution_inflation: Eye,
};
