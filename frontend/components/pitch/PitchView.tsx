"use client";

import { useSearchParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import LiveBrain from "@/components/brain/live/LiveBrain";
import Drawer from "@/components/neural/Drawer";
import HoverCard from "@/components/neural/HoverCard";
import { LoadState } from "@/components/Panel";
import AskBar from "@/components/shell/AskBar";
import { key } from "@/lib/brain/layout";
import { useBrainPlayer } from "@/lib/brain/store";
import type { Anchors, MapPick } from "@/lib/brain/types";
import { useBrainEventPlayer } from "@/lib/brain/usePlayer";
import { type CalloutId, usePitchData } from "@/lib/pitch/data";
import { CALLOUTS, CALLOUT_OF_STEP, LOOP_STEPS, eventActionType, eventStage, linkedTo, type PitchRef } from "@/lib/pitch/links";
import { usePitchPlayer, useAutoplay } from "@/lib/pitch/player";
import { STEPS } from "@/lib/pitch/steps";
import { usePitchStore } from "@/lib/pitch/store";
import { useUiStore } from "@/lib/ui-store";
import { cn } from "@/lib/utils";
import ActionsColumn from "./ActionsColumn";
import Callouts, { TINT } from "./Callouts";
import Connectors, { type ConnLine } from "./Connectors";
import DetailSheet from "./DetailSheet";
import Headline from "./Headline";
import InputsColumn from "./InputsColumn";
import LoopStrip from "./LoopStrip";
import Walkthrough from "./Walkthrough";

const calloutOf = (r: PitchRef | null): CalloutId | null => (!r ? null : r.kind === "callout" ? r.id : r.kind === "action" ? "decision" : r.kind === "loop" ? CALLOUT_OF_STEP[r.id] : r.kind === "source" ? "perception" : null);

const reducedSub = (cb: () => void) => {
  const m = window.matchMedia("(prefers-reduced-motion: reduce)");
  m.addEventListener("change", cb);
  return () => m.removeEventListener("change", cb);
};
const reducedNow = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/** Counts 0..n-1 on a timer while mounted (state lives in the parent via onTick, so it resets when this unmounts). */
function Ticker({ ms, n, loop, onTick }: { ms: number; n: number; loop: boolean; onTick: (i: number) => void }) {
  useEffect(() => {
    let i = 0;
    const id = setInterval(() => {
      i = loop ? (i + 1) % n : Math.min(i + 1, n);
      onTick(i);
    }, ms);
    return () => {
      clearInterval(id);
      onTick(-1);
    };
  }, [ms, n, loop, onTick]);
  return null;
}

const isTyping = (t: EventTarget | null) => {
  const el = t as HTMLElement | null;
  return !!el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.tagName === "SELECT" || el.isContentEditable);
};

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
  const [held, setHeld] = useState(false);
  const [capH, setCapH] = useState(0);
  const [seq, setSeq] = useState(-1);
  const [closeIdx, setCloseIdx] = useState(-1);
  const [askOpen, setAskOpen] = useState(false);
  const presenter = useUiStore((s) => s.presenter);
  const setPresenter = useUiStore((s) => s.setPresenter);
  const highlights = useUiStore((s) => s.highlights);
  const reduced = useSyncExternalStore(reducedSub, reducedNow, () => false);
  const walking = usePitchPlayer((s) => s.active);
  const stepIdx = usePitchPlayer((s) => s.index);
  const step = walking ? STEPS[stepIdx] : null;
  const params = useSearchParams();
  const capEl = useRef<HTMLDivElement | null>(null);
  const deepLinked = useRef(false);
  const leavePresenter = () => {
    setPresenter(false);
    if (document.fullscreenElement) void document.exitFullscreen();
  };
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
      if (isTyping(e.target) || e.metaKey || e.ctrlKey || e.altKey) return;
      const pl = usePitchPlayer.getState();
      if (e.key === "Escape") {
        if (usePitchStore.getState().focus || pick) {
          usePitchStore.getState().setFocus(null);
          setPick(null);
        } else if (pl.active) pl.exit();
        else if (useUiStore.getState().presenter) leavePresenter();
        return;
      }
      if (!pl.active) return;
      const onButton = (e.target as HTMLElement | null)?.closest("button,a,[role=tab]");
      if (e.key === "ArrowRight" || (e.key === " " && !onButton)) pl.next();
      else if (e.key === "ArrowLeft") pl.prev();
      else if (e.key === "p" || e.key === "P") pl.togglePlay();
      else if (e.key === "n" || e.key === "N") pl.toggleNotes();
      else if (/^[1-9]$/.test(e.key)) pl.goTo(Number(e.key) - 1);
      else return;
      e.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
  useEffect(
    () => () => {
      // leaving /pitch mid-walkthrough: stop the player and give the shell back
      usePitchStore.setState({ hover: null, focus: null });
      usePitchPlayer.getState().exit();
      useUiStore.getState().setPresenter(false);
      if (document.fullscreenElement) void document.exitFullscreen();
    },
    [],
  );
  useEffect(() => {
    const on = () => !document.fullscreenElement && useUiStore.getState().presenter && useUiStore.getState().setPresenter(false);
    document.addEventListener("fullscreenchange", on);
    return () => document.removeEventListener("fullscreenchange", on);
  }, []);
  useEffect(() => {
    const el = capEl.current;
    if (!walking || !el) return;
    const ro = new ResizeObserver(([e]) => setCapH(Math.round(e.contentRect.height + 28)));
    ro.observe(el);
    return () => ro.disconnect();
  }, [walking, data.ready]);
  // /pitch?step=3 opens the walkthrough there (paused, so a linked page is deterministic)
  const stepParam = params.get("step");
  useEffect(() => {
    if (deepLinked.current || !data.ready || stepParam === null) return;
    const n = Number(stepParam);
    if (!Number.isInteger(n)) return;
    deepLinked.current = true;
    usePitchPlayer.getState().start(n, false);
  }, [data.ready, stepParam]);
  useAutoplay(held);

  const togglePresenter = () => {
    if (useUiStore.getState().presenter) return leavePresenter();
    setPresenter(true);
    void document.documentElement.requestFullscreen?.().catch(() => undefined);
  };
  const startWalk = () => usePitchPlayer.getState().start(0, !reduced);

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
  const interacting = !!hover || !!focus;
  const ref = hover ?? focus ?? step?.ref ?? null;
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
    const ingest = stage?.callout === "perception" || !!step?.particles;
    for (const s of data.q.sources.data ?? []) out.push({ id: `src-${s.source_id}`, a: `source:${s.source_id}`, b: "callout:perception", color: TINT.perception, active: ingest || !!linked?.sources.has(s.source_id), particles: ingest });
    for (const g of data.derived.groups) out.push({ id: `act-${g.id}`, a: "callout:decision", b: `action:${g.id}`, color: TINT.decision, active: !!linked?.actions.has(g.id) || eventGroup === g.id });
    for (const c of CALLOUTS) out.push({ id: `br-${c.id}`, a: `callout:${c.id}`, b: `anchor:${c.region ?? "ghost"}`, color: TINT[c.id], active: stage?.callout === c.id || !!linked?.callouts.has(c.id) || focusedCallout === c.id });
    return out;
  }, [data.q.sources.data, data.derived.groups, linked, stage, eventGroup, focusedCallout, step]);

  const plan = useMemo(() => (step ? step.brain(data) : null), [step, data]);
  const askedKey = step?.id === "close" && highlights[0]?.type === "neuron" ? key.neuron(highlights[0].id) : null;
  const sequence = plan?.sequence ?? null;
  const seqTargets = sequence?.length ? (reduced ? sequence : [sequence[Math.max(0, seq) % sequence.length]]) : null;
  const stepTargets = seqTargets ?? plan?.targets ?? [];
  const highlightTargets = !interacting && step && stepTargets.length ? stepTargets : linked?.targets;
  const focusRegion = focusedCallout ? (CALLOUTS.find((c) => c.id === focusedCallout)?.region ?? null) : (plan?.region ?? null);
  const focusKey = focusedCallout === "prediction" && snap?.ghosts[0] ? key.ghost(snap.ghosts[0].id) : focusedCallout ? null : (askedKey ?? (!focusRegion ? (plan?.focusKey ?? null) : null));
  const tint = [...(linked?.regions ?? []), ...(stage ? [stage.region] : [])];
  const dimPanel = (p: "inputs" | "actions" | "loop") => !!step && !interacting && !step.panels.includes(p);
  const loopActive = stage?.step ?? (step ? (step.id === "close" ? (reduced ? "learn" : (LOOP_STEPS[closeIdx]?.id ?? null)) : (step.loop[0] ?? null)) : null);
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
    <div
      ref={root}
      style={{ "--cap": walking ? `${capH}px` : "0px" } as React.CSSProperties}
      className={cn("relative grid min-h-0 gap-4 bg-ink", presenter ? "min-[1200px]:h-[calc(100vh-2rem)]" : "min-[1200px]:h-[calc(100vh-7.5rem)]", "min-[1200px]:grid-rows-[auto_minmax(0,1fr)_auto]", fullscreen && "h-screen overflow-auto p-6")}
    >
      <Headline data={data} fullscreen={fullscreen} onFullscreen={toggleFullscreen} onStart={startWalk} walking={walking} presenting={presenter} onPresenter={togglePresenter} />

      <div role="tablist" aria-label="Inputs and actions" className="inline-flex w-fit rounded-lg border border-line bg-slate p-0.5 min-[1200px]:hidden">
        {(["inputs", "actions"] as const).map((t) => (
          <button key={t} role="tab" aria-selected={tab === t} onClick={() => setTab(t)} className={cn("rounded-md px-4 py-1.5 text-sm font-semibold", tab === t ? "bg-primary text-primary-foreground" : "text-fog")}>
            {t === "inputs" ? "Inputs" : "Actions"}
          </button>
        ))}
      </div>

      <div className="grid min-h-0 gap-4 min-[1200px]:grid-cols-[minmax(250px,19%)_minmax(0,1fr)_minmax(262px,21%)]">
        <div data-dim={dimPanel("inputs") || undefined} className={cn("min-h-0 transition-opacity duration-200 max-[1199px]:order-2", tab !== "inputs" && "max-[1199px]:hidden", dimPanel("inputs") && "opacity-45")}>
          <LoadState q={data.q.sources} what="the inputs" height={300}>{() => <InputsColumn data={data} linked={linked} onFocus={onFocus} />}</LoadState>
        </div>

        <section ref={box} aria-label="The live brain" onPointerDown={(e) => focus && !(e.target as HTMLElement).closest("[data-keep],[role=button],aside") && setFocus(null)} className="dark-capsule relative flex min-h-0 flex-col overflow-hidden rounded-[14px] border max-[1199px]:order-1">
          <div ref={canvas} className="relative h-[440px] min-[1200px]:absolute min-[1200px]:inset-x-0 min-[1200px]:top-0 min-[1200px]:bottom-[var(--cap)] min-[1200px]:h-auto">
            <LoadState q={data.q.snap} what="the brain" height={440}>
              {(s) => (
                <LiveBrain
                  snapshot={s}
                  variant="full"
                  maxDots={9000}
                  height={canvasH}
                  sway={!reduced}
                  swayAmp={0.26}
                  focusRegion={focusRegion}
                  focusKey={focusKey}
                  tintRegions={tint}
                  dimOthers={!!focus || (!!step && !interacting && stepTargets.length > 0)}
                  highlightTargets={highlightTargets}
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
          <div className={cn("grid gap-2 p-3", walking ? "pointer-events-none min-[1200px]:absolute min-[1200px]:inset-x-0 min-[1200px]:top-0 min-[1200px]:flex min-[1200px]:items-start min-[1200px]:gap-1.5 min-[1200px]:p-2" : "min-[1200px]:contents")}>
            <Callouts data={data} linked={linked} active={stage?.callout ?? null} focused={focusedCallout} onFocus={onFocus} compact={walking} />
          </div>
          {walking && (
            <Walkthrough data={data} capRef={capEl} onHold={setHeld} onAsk={() => presenter && setAskOpen(true)} />
          )}
          {focusedCallout && !pick && <DetailSheet id={focusedCallout} data={data} onClose={() => setFocus(null)} />}
          {pick && (
            <div data-keep className="absolute top-0 right-0 bottom-0 z-30 w-[min(380px,100%)] overflow-y-auto bg-ink">
              <Drawer pick={pick} onClose={() => setPick(null)} />
            </div>
          )}
          {hoverCard && <HoverCard pick={hoverCard.p} at={hoverCard} />}
        </section>

        <div data-dim={dimPanel("actions") || undefined} className={cn("min-h-0 transition-opacity duration-200 max-[1199px]:order-2", tab !== "actions" && "max-[1199px]:hidden", dimPanel("actions") && "opacity-45")}>
          <LoadState q={data.q.recs} what="the actions" height={300}>{() => <ActionsColumn data={data} linked={linked} onFocus={onFocus} activeType={current && stage?.callout === "decision" ? (eventActionType(current) ?? null) : null} />}</LoadState>
        </div>
      </div>

      <div data-dim={dimPanel("loop") || undefined} className={cn("transition-opacity duration-200", dimPanel("loop") && "opacity-45")}>
        <LoopStrip data={data} linked={step && !interacting && linked ? { ...linked, steps: new Set<string>(step.loop) } : linked} active={loopActive} onFocus={onFocus} />
      </div>
      <div className="max-[1199px]:hidden">
        <Connectors container={root} canvas={canvas} anchors={anchors} lines={lines} />
      </div>
      {sequence && sequence.length > 1 && !reduced && <Ticker ms={1300} n={sequence.length} loop onTick={setSeq} />}
      {step?.id === "close" && !reduced && <Ticker ms={450} n={LOOP_STEPS.length} loop={false} onTick={setCloseIdx} />}
      {presenter && (
        <>
          <button onClick={() => setAskOpen((v) => !v)} aria-expanded={askOpen} className="fixed top-3 right-3 z-50 inline-flex h-8 items-center gap-1.5 rounded-lg border border-line bg-slate px-3 text-sm font-semibold hover:bg-slate-2">
            Ask
          </button>
          {askOpen && (
            <div className="fixed top-14 right-3 z-50 w-[min(440px,calc(100vw-24px))]">
              <AskBar />
            </div>
          )}
        </>
      )}
    </div>
  );
}
