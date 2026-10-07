"use client";

import { useEffect, useRef } from "react";
import { REGION_META } from "./regions";
import { useBrainStore } from "./store";

/** Cursor-following label for the hovered region. */
export default function BrainTooltip() {
  const hovered = useBrainStore((s) => s.hoveredRegion);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const move = (e: PointerEvent) => {
      if (ref.current) ref.current.style.transform = `translate(${e.clientX + 16}px, ${e.clientY + 16}px)`;
    };
    window.addEventListener("pointermove", move);
    return () => window.removeEventListener("pointermove", move);
  }, []);

  const meta = hovered ? REGION_META[hovered] : null;
  return (
    <div
      ref={ref}
      className="pointer-events-none fixed left-0 top-0 z-50 transition-opacity duration-150"
      style={{ opacity: meta ? 1 : 0 }}
    >
      {meta && (
        <div
          className="rounded-lg border bg-black/70 px-3 py-2 backdrop-blur-md"
          style={{ borderColor: `${meta.color}66` }}
        >
          <div className="flex items-center gap-2 font-mono text-xs font-semibold tracking-widest" style={{ color: meta.color }}>
            <span className="h-2 w-2 rounded-full" style={{ background: meta.color, boxShadow: `0 0 8px ${meta.color}` }} />
            {meta.label}
          </div>
          <div className="mt-0.5 text-[11px] text-white/60">{meta.description}</div>
        </div>
      )}
    </div>
  );
}

