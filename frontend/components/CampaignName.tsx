import { channelDisplay, parseCampaignName } from "@/lib/names";
import { cn } from "@/lib/utils";

/** A campaign as structured parts: channel badge + product + audience (muted). Never the raw dotted string. */
export default function CampaignName({ name, channel, className }: { name: string; channel?: string | null; className?: string }) {
  const p = parseCampaignName(name);
  const chan = channel ? channelDisplay(channel) : p.channelName;
  return (
    <span className={cn("inline-flex flex-wrap items-center gap-x-2 gap-y-0.5", className)}>
      <span className="rounded-full border border-line bg-slate-2 px-2 py-px text-xs font-semibold">{chan}</span>
      <span className="font-semibold">{p.product}</span>
      {p.audience && <span className="text-fog">{p.audience}</span>}
    </span>
  );
}
