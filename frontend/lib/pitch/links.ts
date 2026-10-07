import type { BrainEvent, BrainRegion } from "@/lib/types";
import { key } from "@/lib/brain/layout";
import type { ActionGroup, CalloutId } from "./data";

/** What the Pitch page can point at. */
export type PitchRef = { kind: "source"; id: string } | { kind: "callout"; id: CalloutId } | { kind: "action"; id: string } | { kind: "loop"; id: LoopStepId };
export type LoopStepId = "ingest" | "detect" | "diagnose" | "predict" | "decide" | "execute" | "learn";

export const LOOP_STEPS: { id: LoopStepId; label: string }[] = [
  { id: "ingest", label: "Ingest" },
  { id: "detect", label: "Detect" },
  { id: "diagnose", label: "Diagnose" },
  { id: "predict", label: "Predict" },
  { id: "decide", label: "Decide" },
  { id: "execute", label: "Execute" },
  { id: "learn", label: "Learn" },
];

export const CALLOUTS: { id: CalloutId; label: string; region: BrainRegion | null; does: string; full: string }[] = [
  { id: "perception", label: "Perception", region: "ingest", does: "Ingest and reconcile", full: "/data" },
  { id: "reasoning", label: "Reasoning", region: "diagnose", does: "Detect and diagnose", full: "/diagnosis" },
  { id: "prediction", label: "Prediction", region: null, does: "Forecast before spending", full: "/opportunities" },
  { id: "decision", label: "Decision", region: "decide", does: "Optimise and decide", full: "/command" },
  { id: "memory", label: "Memory", region: "learn", does: "Learn from outcomes", full: "/learning" },
];

const REGION_OF_CALLOUT: Record<CalloutId, BrainRegion | null> = { perception: "ingest", reasoning: "diagnose", prediction: null, decision: "decide", memory: "learn" };
const REGION_OF_STEP: Record<LoopStepId, BrainRegion | null> = { ingest: "ingest", detect: "diagnose", diagnose: "diagnose", predict: null, decide: "decide", execute: "decide", learn: "learn" };
export const CALLOUT_OF_STEP: Record<LoopStepId, CalloutId> = { ingest: "perception", detect: "reasoning", diagnose: "reasoning", predict: "prediction", decide: "decision", execute: "decision", learn: "memory" };

/** The callout and loop step an engine event belongs to (so the page lights up in sync with the player). */
export function eventStage(e: BrainEvent): { callout: CalloutId; step: LoopStepId; region: BrainRegion } {
  const launch = (e.payload as { action_type?: string }).action_type === "launch_test";
  switch (e.type) {
    case "ingest":
      return { callout: "perception", step: "ingest", region: "ingest" };
    case "anomaly":
      return { callout: "reasoning", step: "detect", region: "diagnose" };
    case "diagnosis":
      return { callout: "reasoning", step: "diagnose", region: "diagnose" };
    case "recommendation":
      return launch ? { callout: "prediction", step: "predict", region: "decide" } : { callout: "decision", step: "decide", region: "decide" };
    case "outcome":
      return { callout: "memory", step: "learn", region: "learn" };
    default: // approval, rejection, rollback, auto_apply
      return { callout: "decision", step: "execute", region: "decide" };
  }
}

/** Which decision-type group an event is about, so that row's line can pulse. */
export function eventActionType(e: BrainEvent): string | null {
  return ((e.payload as { action_type?: string }).action_type as string | undefined) ?? null;
}

export interface Linked {
  regions: BrainRegion[];
  /** neuron ids and overlay keys to ring on the brain */
  targets: string[];
  callouts: Set<string>;
  sources: Set<string>;
  actions: Set<string>;
  steps: Set<string>;
}

interface Ctx {
  sourceChannel: (sourceId: string) => string | null;
  campaignsOfChannel: (channel: string) => string[];
  ghostKeys: string[];
  scaleCampaigns: string[];
  groups: ActionGroup[];
}

/** Everything linked to one hovered or focused thing: what to ring on the brain and what to keep at full strength. */
export function linkedTo(ref: PitchRef | null, c: Ctx): Linked | null {
  if (!ref) return null;
  const out: Linked = { regions: [], targets: [], callouts: new Set(), sources: new Set(), actions: new Set(), steps: new Set() };
  switch (ref.kind) {
    case "source": {
      const ch = c.sourceChannel(ref.id);
      out.regions = ["ingest"];
      out.sources.add(ref.id);
      out.callouts.add("perception");
      out.targets = [key.source(ref.id), ...(ch ? c.campaignsOfChannel(ch) : [])];
      break;
    }
    case "callout": {
      const r = REGION_OF_CALLOUT[ref.id];
      out.callouts.add(ref.id);
      if (r) out.regions = [r];
      if (ref.id === "prediction") out.targets = [...c.ghostKeys, ...c.scaleCampaigns];
      if (ref.id === "perception") ["meta_ads", "google_ads"].forEach((s) => out.sources.add(s));
      if (ref.id === "decision") c.groups.forEach((g) => out.actions.add(g.id));
      for (const s of LOOP_STEPS) if (CALLOUT_OF_STEP[s.id] === ref.id) out.steps.add(s.id);
      break;
    }
    case "action": {
      const g = c.groups.find((x) => x.id === ref.id);
      out.regions = ["decide"];
      out.actions.add(ref.id);
      out.callouts.add("decision");
      out.targets = g?.targets ?? [];
      break;
    }
    case "loop": {
      const r = REGION_OF_STEP[ref.id];
      if (r) out.regions = [r];
      out.steps.add(ref.id);
      out.callouts.add(CALLOUT_OF_STEP[ref.id]);
      if (ref.id === "predict") out.targets = [...c.ghostKeys, ...c.scaleCampaigns];
      break;
    }
  }
  return out;
}
