"use client";

import { ArrowRight, LoaderCircle, Play, Rewind, Search } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState, useSyncExternalStore } from "react";
import LiveBrain from "@/components/brain/live/LiveBrain";
import DevPanel from "@/components/brain/DevPanel";
import { LoadState } from "@/components/Panel";
import { useRunLoop } from "@/components/shell/useRunLoop";
import { ApiError, api } from "@/lib/api";
import { key } from "@/lib/brain/layout";
import { useBrainPlayer } from "@/lib/brain/store";
import type { MapPick } from "@/lib/brain/types";
import { useBrainEventPlayer } from "@/lib/brain/usePlayer";
import { inr, pct } from "@/lib/format";
import { useBrainSnapshot } from "@/lib/queries";
import { useUiStore } from "@/lib/ui-store";
import type { BrainSnapshot } from "@/lib/types";
import Drawer from "./Drawer";
import HoverCard from "./HoverCard";
import Legend from "./Legend";
import PulseFeed from "./PulseFeed";

const viewportH = () => window.innerHeight;
const subResize = (cb: () => void) => {
  window.addEventListener("resize", cb);
  return () => window.removeEventListener("resize", cb);
};

/** URL form of a pick: plain id for neurons, prefixed for the rest. The URL is the single source of truth for what is focused. */
const toParam = (p: MapPick) => (p.kind === "neuron" ? p.node.entity_id : p.kind === "cluster" ? key.cluster(p.cluster.id) : p.kind === "source" ? key.source(p.source.id) : key.ghost(p.ghost.id));
function fromParam(s: BrainSnapshot, v: string | null): MapPick | null {
  if (!v) return null;
  if (v.startsWith("c:")) {
    const c = s.clusters.find((x) => x.id === v.slice(2));
    return c ? { kind: "cluster", cluster: c } : null;
  }
  if (v.startsWith("s:")) {
    const c = s.sources.find((x) => x.id === v.slice(2));
    return c ? { kind: "source", source: c } : null;
  }
  if (v.startsWith("g:")) {
    const c = s.ghosts.find((x) => x.id === v.slice(2));
    return c ? { kind: "ghost", ghost: c } : null;
  }
  const n = s.nodes.find((x) => x.entity_id === v);
  return n ? { kind: "neuron", node: n } : null;
}
const focusKeyOf = (p: MapPick | null) => (p ? (p.kind === "neuron" ? key.neuron(p.node.entity_id) : toParam(p)) : null);

function Headline({ s }: { s: BrainSnapshot }) {
  const h = s.headline;
  const dq = h.detection_quality;
  const delta = h.profit_delta;
  const item = (label: string, value: React.ReactNode, sub?: string, wide = false) => (
    <div className={`bg-slate px-4 py-3 ${wide ? "col-span-2 min-[1200px]:col-span-1" : ""}`}>
      <div className="text-sm text-fog">{label}</div>
      <div className="mt-0.5 text-xl font-bold whitespace-nowrap">{value}</div>
      {sub && <div className="text-xs text-fog">{sub}</div>}
    </div>
  );
  return (
    <section aria-label="The engine at a glance" className="panel overflow-hidden">
      <div className="grid grid-cols-2 gap-px bg-line min-[700px]:grid-cols-3 min-[1200px]:grid-cols-5">
        {item(
          "Profit now and planned",
          <>
            {inr(h.current_profit)} <ArrowRight className="inline size-4 text-fog" aria-label="to" /> {inr(h.planned_profit)}
          </>,
          delta === null ? undefined : `${delta >= 0 ? "+" : "−"}${inr(Math.abs(delta))} a day, ${s.objective.replace(/_/g, " ")} plan`,
        )}
        {item("Data trust", pct(h.data_trust), "Weighted by ad spend")}
        {item("Planted problems found", dq ? `${dq.found} of ${dq.expected}` : "—", dq ? `Recall ${pct(dq.recall)}` : undefined)}
        {item("Calibration factor", h.calibration?.factor == null ? "—" : `×${h.calibration.factor.toFixed(2)}`, h.calibration ? `Over the last ${h.calibration.n} outcomes` : undefined)}
        {item("Decisions waiting", s.counts.pending_decisions, `${s.counts.executed} already acted on`)}
      </div>
    </section>
  );
}

function Body() {
  const router = useRouter();
  const params = useSearchParams();
  const snapQ = useBrainSnapshot();
  const toast = useUiStore((st) => st.toast);
  const { run, running } = useRunLoop();
  const replay = useBrainPlayer((st) => st.replay);
  const caption = useBrainPlayer((st) => st.caption);
  const [hover, setHover] = useState<{ p: MapPick; x: number; y: number } | null>(null);
  const [legend, setLegend] = useState(true);
  const [search, setSearch] = useState("");
  const [replaying, setReplaying] = useState(false);
  const vh = useSyncExternalStore(subResize, viewportH, () => 800);
  const height = Math.max(480, Math.min(760, vh - 300));
  useBrainEventPlayer(true);

  const focusParam = params.get("focus");
  const snap = snapQ.data;
  const picked = snap ? fromParam(snap, focusParam) : null;
  const go = (value: string | null) => router.replace(value ? `/neural?focus=${encodeURIComponent(value)}` : "/neural", { scroll: false });

  // Esc closes the drawer.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && focusParam && go(null);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // go is stable enough: it only closes over router
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusParam]);

  // Asking something elsewhere highlights nodes; here the first one is focused straight away.
  const asked = useUiStore((st) => st.highlights);
  const askedFirst = asked.find((h) => h.type === "neuron")?.id;
  useEffect(() => {
    if (askedFirst && snap?.nodes.some((n) => n.entity_id === askedFirst) && params.get("focus") !== askedFirst) router.replace(`/neural?focus=${encodeURIComponent(askedFirst)}`, { scroll: false });
    // only when a new answer arrives
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [askedFirst]);

  const progress = replay && replay.done < replay.total ? replay : null;
  const startReplay = async () => {
    setReplaying(true);
    try {
      const r = await api.brainReplay();
      useBrainPlayer.getState().beginReplay(r.first_id, r.events_queued);
      toast("info", `Replaying the last 7 days · ${r.events_queued} events queued`);
    } catch (e) {
      toast("loss", "Could not start the replay", e instanceof ApiError ? e.detail : "Check that the backend is running.");
    } finally {
      setReplaying(false);
    }
  };
  const known = new Set((snap?.nodes ?? []).map((n) => n.entity_id));
  const find = (q: string) => snap?.nodes.find((n) => n.label.toLowerCase() === q.toLowerCase() || n.entity_id.toLowerCase() === q.toLowerCase());

  return (
    <div className="grid gap-5">
      <div className="flex flex-wrap items-center gap-3">
        <button onClick={startReplay} disabled={replaying || !!progress} className="inline-flex h-9 items-center gap-1.5 rounded-lg bg-primary px-3.5 text-sm font-semibold text-primary-foreground hover:bg-primary/85 disabled:opacity-60">
          {replaying || progress ? <LoaderCircle className="size-4 animate-spin" aria-hidden /> : <Rewind className="size-4" aria-hidden />}
          {progress ? `Replaying ${progress.done} of ${progress.total}` : "Replay the last 7 days"}
        </button>
        <button onClick={run} disabled={running} className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-line px-3.5 text-sm font-semibold hover:bg-slate-2 disabled:opacity-60">
          {running ? <LoaderCircle className="size-4 animate-spin" aria-hidden /> : <Play className="size-4" aria-hidden />}
          Run the loop now
        </button>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            const n = find(search);
            if (n) {
              go(n.entity_id);
              setSearch("");
            }
          }}
          className="flex h-9 items-center gap-2 rounded-lg border border-line bg-slate-2 px-2.5 focus-within:outline focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-synapse"
        >
          <Search className="size-4 text-fog" aria-hidden />
          <input
            list="neural-focus-list"
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              const n = find(e.target.value);
              if (n) {
                go(n.entity_id);
                setSearch("");
              }
            }}
            placeholder="Focus a product or campaign"
            aria-label="Focus a product or campaign"
            className="w-56 bg-transparent text-sm outline-none placeholder:text-fog"
          />
          <datalist id="neural-focus-list">{(snap?.nodes ?? []).map((n) => <option key={n.entity_id} value={n.label} />)}</datalist>
        </form>
        <label className="ml-auto inline-flex items-center gap-2 text-sm text-fog">
          <input type="checkbox" checked={legend} onChange={(e) => setLegend(e.target.checked)} className="size-4 accent-[var(--synapse)]" />
          Show the legend
        </label>
      </div>

      <LoadState q={snapQ} what="the neural map" height={140}>{(s) => <Headline s={s} />}</LoadState>

      <div className={`grid items-start gap-5 ${picked ? "min-[1200px]:grid-cols-[minmax(0,1fr)_380px]" : "min-[1200px]:grid-cols-[280px_minmax(0,1fr)]"}`}>
        {/* with the drawer open the map needs the width, so the feed and legend drop below it */}
        <div className={`order-2 grid gap-5 ${picked ? "min-[1200px]:order-3 min-[1200px]:col-span-2 min-[1200px]:grid-cols-2" : "min-[1200px]:order-1"}`}>
          <PulseFeed knownIds={known} onFocus={(id) => go(id)} />
          {legend && <Legend />}
        </div>
        <section aria-label="Neural map" className="dark-capsule order-1 min-w-0 rounded-[14px] border p-3 min-[1200px]:order-1">
          <LoadState q={snapQ} what="the neural map" height={height}>
            {(s) => (
              <>
                <LiveBrain snapshot={s} variant="full" maxDots={9000} height={height} focusKey={focusKeyOf(picked)} sway={!picked} onHover={(p, at) => setHover(p && at ? { p, x: at.x, y: at.y } : null)} onPick={(p) => go(toParam(p))} />
                <div className="mt-2 flex items-center gap-2 border-t border-line pt-2 text-sm" aria-live="polite">
                  <span className="size-2 shrink-0 rounded-full bg-synapse" aria-hidden />
                  <span className={caption ? "" : "text-fog"}>{caption ?? "Waiting for the next engine event."}</span>
                  {picked && <button onClick={() => go(null)} className="ml-auto rounded-lg border border-line px-2.5 py-1 text-xs font-semibold hover:bg-slate-2">Back to the overview</button>}
                </div>
              </>
            )}
          </LoadState>
          {hover && <HoverCard pick={hover.p} at={hover} />}
        </section>
        {picked && (
          <div className="order-1 min-[1200px]:order-2">
            <Drawer pick={picked} onClose={() => go(null)} />
          </div>
        )}
      </div>
      {params.get("dev") === "1" && <DevPanel />}
    </div>
  );
}

export default function NeuralView() {
  return (
    <Suspense fallback={null}>
      <Body />
    </Suspense>
  );
}
