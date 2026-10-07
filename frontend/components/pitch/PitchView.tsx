"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import LiveBrain from "@/components/brain/live/LiveBrain";
import Drawer from "@/components/neural/Drawer";
import HoverCard from "@/components/neural/HoverCard";
import { LoadState } from "@/components/Panel";
import { key } from "@/lib/brain/layout";
import { useBrainPlayer } from "@/lib/brain/store";
import type { Anchors, MapPick } from "@/lib/brain/types";
import { useBrainEventPlayer } from "@/lib/brain/usePlayer";
import { type CalloutId, usePitchData } from "@/lib/pitch/data";
import { CALLOUTS, CALLOUT_OF_STEP, eventActionType, eventStage, linkedTo, type PitchRef } from "@/lib/pitch/links";
import { usePitchStore } from "@/lib/pitch/store";
import { cn } from "@/lib/utils";
import ActionsColumn from "./ActionsColumn";
import Callouts, { TINT } from "./Callouts";
import Connectors, { type ConnLine } from "./Connectors";
import DetailSheet from "./DetailSheet";
import Headline from "./Headline";
import InputsColumn from "./InputsColumn";
import LoopStrip from "./LoopStrip";

const calloutOf = (r: PitchRef | null): CalloutId | null => (!r ? null : r.kind === "callout" ? r.id : r.kind === "action" ? "decision" : r.kind === "loop" ? CALLOUT_OF_STEP[r.id] : r.kind === "source" ? "perception" : null);

export default function PitchView() {
  const data = usePitchData();
  const hover = usePitchStore((s) => s.hover);
  const focus = usePitchStore((s) => s.focus);
  const setFocus = usePitchStore((s) => s.setFocus);
  const current = useBrainPlayer((s) => s.current);
  const [pick, setPick] = useState<MapPick | null>(null);
  const [hoverCard, setHoverCard] = useState<{ p: MapPick; x: number; y: number } | null>(null);
  const [tab, setTab] = useState<"inputs" | "actions">("inputs");
  const [fullscreen, setFullscreen] = useState(false);
  const [canvasH, setCanvasH] = useState(520);
  const root = useRef<HTMLDivElement>(null);
  const box = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLDivElement>(null);
  const anchors = useRef<Anchors | null>(null);
  useBrainEventPlayer(true);

  useEffect(() => {
    const el = canvas.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setCanvasH(Math.max(320, Math.round(e.contentRect.height))));
    ro.observe(el);
    return () => ro.disconnect();
  }, [data.ready]);
  useEffect(() => {
    const on = () => setFullscreen(document.fullscreenElement === root.current);
    document.addEventListener("fullscreenchange", on);
    return () => document.removeEventListener("fullscreenchange", on);
  }, []);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (usePitchStore.getState().focus || pick) {
        usePitchStore.getState().setFocus(null);
        setPick(null);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [pick]);
  useEffect(() => {
    // a click anywhere that is not a pitch element, a control or the sheet leaves focus mode
    const onDown = (e: PointerEvent) => {
      if (!usePitchStore.getState().focus) return;
      if (!(e.target as HTMLElement).closest("[data-keep],[data-pitch],aside,button,a,input,select,[role=button]")) usePitchStore.getState().setFocus(null);
    };
    document.addEventListener("pointerdown", onDown);
    return () => document.removeEventListener("pointerdown", onDown);
  }, []);
  useEffect(() => () => usePitchStore.setState({ hover: null, focus: null }), []);

  const snap = data.snapshot;
  const ctx = useMemo(
    () => ({
      sourceChannel: (id: string) => snap?.sources.find((s) => s.id === id)?.channel ?? null,
      campaignsOfChannel: (ch: string) => (snap?.nodes ?? []).filter((n) => n.entity_type === "campaign" && n.channel === ch).map((n) => n.entity_id),
      ghostKeys: (snap?.ghosts ?? []).map((g) => key.ghost(g.id)),
      scaleCampaigns: (snap?.nodes ?? []).filter((n) => n.entity_type === "campaign" && n.headroom === "scale").map((n) => n.entity_id),
      groups: data.derived.groups,
    }),
    [snap, data.derived.groups],
  );
  const ref = hover ?? focus;
  const linked = useMemo(() => linkedTo(ref, ctx), [ref, ctx]);
  const stage = current ? eventStage(current) : null;
  const focusedCallout = calloutOf(focus);

  // The action group an event is about, so its line pulses.
  const eventGroup = useMemo(() => {
    if (!current || stage?.callout !== "decision") return null;
    const p = current.payload as { action_type?: string; rec_id?: string };
    const dec = [...(data.q.recs.data?.recommendations ?? [])].find((d) => d.id === (p.rec_id ?? current.ref_id));
    const type = eventActionType(current) ?? dec?.action.type ?? null;
    return type ? (data.derived.groups.find((g) => g.decisions.some((d) => d.action.type === type))?.id ?? null) : null;
  }, [current, stage, data.q.recs.data, data.derived.groups]);

  const lines: ConnLine[] = useMemo(() => {
    const out: ConnLine[] = [];
    const ingest = stage?.callout === "perception";
    for (const s of data.q.sources.data ?? []) out.push({ id: `src-${s.source_id}`, a: `source:${s.source_id}`, b: "callout:perception", color: TINT.perception, active: ingest || !!linked?.sources.has(s.source_id), particles: ingest });
    for (const g of data.derived.groups) out.push({ id: `act-${g.id}`, a: "callout:decision", b: `action:${g.id}`, color: TINT.decision, active: !!linked?.actions.has(g.id) || eventGroup === g.id });
    for (const c of CALLOUTS) out.push({ id: `br-${c.id}`, a: `callout:${c.id}`, b: `anchor:${c.region ?? "ghost"}`, color: TINT[c.id], active: stage?.callout === c.id || !!linked?.callouts.has(c.id) || focusedCallout === c.id });
    return out;
  }, [data.q.sources.data, data.derived.groups, linked, stage, eventGroup, focusedCallout]);

  const focusRegion = focusedCallout ? (CALLOUTS.find((c) => c.id === focusedCallout)?.region ?? null) : null;
  const focusKey = focusedCallout === "prediction" && snap?.ghosts[0] ? key.ghost(snap.ghosts[0].id) : null;
  const tint = [...(linked?.regions ?? []), ...(stage ? [stage.region] : [])];
  const onFocus = (r: PitchRef) => {
    setPick(null);
    setFocus(r);
  };

  const toggleFullscreen = () => {
    if (document.fullscreenElement) void document.exitFullscreen();
    else void root.current?.requestFullscreen();
  };

  if (data.offline && !data.ready) return <p className="text-sm tone-loss" role="alert">The engine isn&apos;t reachable. Start the backend, then retry.</p>;

  return (
    <div ref={root} className={cn("relative grid min-h-0 gap-4 bg-ink min-[1200px]:h-[calc(100vh-7.5rem)] min-[1200px]:grid-rows-[auto_minmax(0,1fr)_auto]", fullscreen && "h-screen overflow-auto p-6")}>
      <Headline data={data} fullscreen={fullscreen} onFullscreen={toggleFullscreen} />

      <div role="tablist" aria-label="Inputs and actions" className="inline-flex w-fit rounded-lg border border-line bg-slate p-0.5 min-[1200px]:hidden">
        {(["inputs", "actions"] as const).map((t) => (
          <button key={t} role="tab" aria-selected={tab === t} onClick={() => setTab(t)} className={cn("rounded-md px-4 py-1.5 text-sm font-semibold", tab === t ? "bg-primary text-primary-foreground" : "text-fog")}>
            {t === "inputs" ? "Inputs" : "Actions"}
          </button>
        ))}
      </div>

      <div className="grid min-h-0 gap-4 min-[1200px]:grid-cols-[minmax(250px,19%)_minmax(0,1fr)_minmax(262px,21%)]">
        <div className={cn("min-h-0 max-[1199px]:order-2", tab !== "inputs" && "max-[1199px]:hidden")}>
          <LoadState q={data.q.sources} what="the inputs" height={300}>{() => <InputsColumn data={data} linked={linked} onFocus={onFocus} />}</LoadState>
        </div>

        <section ref={box} aria-label="The live brain" onPointerDown={(e) => focus && !(e.target as HTMLElement).closest("[data-keep],[role=button],aside") && setFocus(null)} className="dark-capsule relative min-h-0 overflow-hidden rounded-[14px] border max-[1199px]:order-1">
          <div ref={canvas} className="relative h-[440px] min-[1200px]:absolute min-[1200px]:inset-0 min-[1200px]:h-auto">
            <LoadState q={data.q.snap} what="the brain" height={440}>
              {(s) => (
                <LiveBrain
                  snapshot={s}
                  variant="full"
                  maxDots={9000}
                  height={canvasH}
                  sway
                  swayAmp={0.26}
                  focusRegion={focusRegion}
                  focusKey={focusKey}
                  tintRegions={tint}
                  dimOthers={!!focus}
                  highlightTargets={linked?.targets}
                  onAnchorsProjected={(a) => (anchors.current = a)}
                  onHover={(p, at) => setHoverCard(p && at ? { p, x: at.x, y: at.y } : null)}
                  onPick={(p) => {
                    setFocus(null);
                    setPick(p);
                  }}
                />
              )}
            </LoadState>
          </div>
          <div className="grid gap-2 p-3 min-[1200px]:contents">
            <Callouts data={data} linked={linked} active={stage?.callout ?? null} focused={focusedCallout} onFocus={onFocus} />
          </div>
          {focusedCallout && !pick && <DetailSheet id={focusedCallout} data={data} onClose={() => setFocus(null)} />}
          {pick && (
            <div data-keep className="absolute top-0 right-0 bottom-0 z-30 w-[min(380px,100%)] overflow-y-auto bg-ink">
              <Drawer pick={pick} onClose={() => setPick(null)} />
            </div>
          )}
          {hoverCard && <HoverCard pick={hoverCard.p} at={hoverCard} />}
        </section>

        <div className={cn("min-h-0 max-[1199px]:order-2", tab !== "actions" && "max-[1199px]:hidden")}>
          <LoadState q={data.q.recs} what="the actions" height={300}>{() => <ActionsColumn data={data} linked={linked} onFocus={onFocus} activeType={current && stage?.callout === "decision" ? (eventActionType(current) ?? null) : null} />}</LoadState>
        </div>
      </div>

      <LoopStrip data={data} linked={linked} active={stage?.step ?? null} onFocus={onFocus} />
      <div className="max-[1199px]:hidden">
        <Connectors container={root} canvas={canvas} anchors={anchors} lines={lines} />
      </div>
    </div>
  );
}
