"use client";

import { LoaderCircle, Search, Send, X } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { ApiError } from "@/lib/api";
import { parseCampaignName } from "@/lib/names";
import { useAsk, useBrainSnapshot } from "@/lib/queries";
import { useUiStore } from "@/lib/ui-store";
import type { AskResult, BrainTarget } from "@/lib/types";

const SUGGESTIONS = ["Why did Summer Sneakers drop?", "Where should we scale?", "Is our ROAS real?", "What if Google +20%?", "Today's brief"];

function engineLabel(engine: string): string {
  if (engine === "claude") return "Claude";
  if (engine === "rules") return "Rules engine";
  return "Fallback";
}

export default function AskBar() {
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const [asked, setAsked] = useState<string | null>(null);
  const box = useRef<HTMLDivElement>(null);
  const ask = useAsk();
  const { data: snap } = useBrainSnapshot();
  const setHighlights = useUiStore((s) => s.setHighlights);
  const highlights = useUiStore((s) => s.highlights);
  const result: AskResult | undefined = ask.data;

  useEffect(() => {
    if (!open) return;
    const away = (e: PointerEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", away);
    return () => document.removeEventListener("pointerdown", away);
  }, [open]);

  const submit = (text: string) => {
    const question = text.trim();
    if (!question || ask.isPending) return;
    setQ(question);
    setAsked(question);
    setOpen(true);
    ask.mutate(question, { onSuccess: (r) => setHighlights(r.highlights) });
  };

  const label = (t: BrainTarget): string => {
    if (t.type === "neuron") {
      const n = snap?.nodes.find((x) => x.entity_id === t.id);
      if (!n) return t.id;
      if (n.entity_type !== "campaign") return n.label;
      const p = parseCampaignName(n.label);
      return `${p.channelName} ${p.product}, ${p.audience}`;
    }
    if (t.type === "cluster") return snap?.clusters.find((c) => c.id === t.id)?.label ?? t.id;
    if (t.type === "source") return snap?.sources.find((s) => s.id === t.id)?.label ?? t.id;
    return t.id;
  };

  const showPanel = open && (ask.isPending || result || ask.isError || !asked);
  const err = ask.error instanceof ApiError ? ask.error.detail : "The question did not go through.";

  return (
    <div ref={box} className="relative min-w-[240px] flex-1">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          submit(q);
        }}
        className="flex items-center gap-2 rounded-lg border border-line bg-slate-2 px-3 focus-within:outline focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-synapse"
        role="search"
      >
        <Search className="size-4 shrink-0 text-fog" aria-hidden />
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onFocus={() => setOpen(true)}
          onKeyDown={(e) => e.key === "Escape" && setOpen(false)}
          placeholder="Ask the engine anything about your spend"
          aria-label="Ask the engine"
          className="h-9 min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-fog"
        />
        <button type="submit" disabled={!q.trim() || ask.isPending} aria-label="Send question" className="rounded p-1 text-synapse-fg hover:bg-slate disabled:text-fog">
          {ask.isPending ? <LoaderCircle className="size-4 animate-spin" aria-hidden /> : <Send className="size-4" aria-hidden />}
        </button>
      </form>

      {showPanel && (
        <div className="float-layer absolute top-full left-0 z-40 mt-2 w-[min(680px,calc(100vw-2rem))] p-4">
          {!asked && (
            <>
              <p className="mb-2 text-sm text-fog">Try one of these.</p>
              <div className="flex flex-wrap gap-2">
                {SUGGESTIONS.map((s) => (
                  <button key={s} onClick={() => submit(s)} className="rounded-full border border-line bg-slate-2 px-3 py-1.5 text-sm hover:border-synapse">
                    {s}
                  </button>
                ))}
              </div>
            </>
          )}
          {asked && (
            <div>
              <div className="flex items-start justify-between gap-3">
                <p className="text-sm font-semibold">{asked}</p>
                <button onClick={() => setOpen(false)} aria-label="Close answer" className="rounded p-0.5 text-fog hover:text-bone">
                  <X className="size-4" />
                </button>
              </div>
              {ask.isPending && <p className="mt-3 text-sm text-fog">The engine is reading its tools.</p>}
              {ask.isError && <p className="mt-3 text-sm tone-loss">{err} Check that the backend is running, then ask again.</p>}
              {result && (
                <>
                  <p className="narrative mt-3">{result.answer}</p>
                  {result.highlights.length > 0 && (
                    <div className="mt-3 flex flex-wrap items-center gap-2">
                      <span className="text-sm text-fog">Highlighted on the brain</span>
                      {result.highlights.find((t) => t.type === "neuron") && (
                        <Link href={`/neural?focus=${encodeURIComponent(result.highlights.find((t) => t.type === "neuron")!.id)}`} onClick={() => setOpen(false)} className="rounded-full bg-primary px-2.5 py-0.5 text-sm font-semibold text-primary-foreground hover:bg-primary/85">
                          Show in neural view
                        </Link>
                      )}
                      {result.highlights.map((t) => (
                        <button
                          key={`${t.type}:${t.id}`}
                          data-highlight={t.id}
                          onClick={() => setHighlights(highlights.some((h) => h.id === t.id) ? highlights.filter((h) => h.id !== t.id) : [...highlights, t])}
                          aria-pressed={highlights.some((h) => h.id === t.id)}
                          className="rounded-full border border-line px-2.5 py-0.5 text-sm hover:border-synapse aria-pressed:border-synapse aria-pressed:bg-slate-2"
                        >
                          {label(t)}
                        </button>
                      ))}
                    </div>
                  )}
                  <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-line pt-3 text-xs text-fog">
                    <span className="rounded-full border border-line px-2 py-px font-semibold text-bone">{engineLabel(result.engine)}</span>
                    <span>Every number comes from an engine tool call.</span>
                    <span>{result.tools_used.length} {result.tools_used.length === 1 ? "tool" : "tools"} used</span>
                  </div>
                </>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
