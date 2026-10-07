import { channelDisplay } from "@/lib/names";

export default function ChannelBadge({ channel }: { channel: string }) {
  return <span className="rounded-full border border-line bg-slate-2 px-2 py-px text-xs font-semibold">{channelDisplay(channel)}</span>;
}
