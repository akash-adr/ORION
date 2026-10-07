import CampaignName from "@/components/CampaignName";
import { anomalyEntity, channelDisplay, parseCampaignName } from "@/lib/names";
import type { Anomaly } from "@/lib/types";

/** The entity an anomaly is about, as structured parts: a campaign (badge + product + audience), a channel, or a product. */
export default function AnomalyName({ a, className }: { a: Anomaly; className?: string }) {
  const entity = anomalyEntity(a.label);
  if (a.entity_type === "campaign") return <CampaignName name={entity} className={className} />;
  if (a.entity_type === "channel") return <span className={className}><span className="rounded-full border border-line bg-slate-2 px-2 py-px text-xs font-semibold">{channelDisplay(a.entity_id)}</span></span>;
  return <span className={`font-semibold ${className ?? ""}`}>{parseCampaignName(entity).product || entity}</span>;
}
