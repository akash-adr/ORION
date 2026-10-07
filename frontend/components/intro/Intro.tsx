"use client";

import { AnimatePresence, animate, motion, useMotionValue } from "framer-motion";
import { useEffect, useRef, useState } from "react";
import BrainCanvas from "@/components/brain/BrainCanvas";
import { useBrainSnapshot, useKpis } from "@/lib/queries";

const STEPS = ["Ingesting", "Reconciling", "Detecting", "Diagnosing", "Deciding", "Learning"] as const;
const STEP_MS = 700;
const MAX_MS = 7000;
const INK = "#0F1724";

/** The intro background must match the page ink in the current theme only at start; the intro is always dark. */
export default function Intro({ onDone }: { onDone: () => void }) {
  const [step, setStep] = useState(0);
  const [assembling, setAssembling] = useState(false);
  const [target, setTarget] = useState<{ x: number; y: number } | null>(null);
  const scroll = useMotionValue(0);
  const startedAt = useRef(0);
  const wrap = useRef<HTMLDivElement>(null);
  const finished = useRef(false);
  const kpis = useKpis(7);
  const snap = useBrainSnapshot();
  const loaded = kpis.isSuccess && snap.isSuccess;

  const finish = () => {
    if (finished.current) return;
    finished.current = true;
    // Where the brain lands: the Engine map panel on the dashboard (crossfade if it is not on this page).
    const el = document.querySelector("[data-engine-map]");
    const box = wrap.current?.getBoundingClientRect();
    if (el && box) {
      // The rig shrinks the brain and re-centres it in the canvas (scrollProgress 0 → 1); we only move the canvas so that
      // centre lands on the Engine map panel.
      const r = el.getBoundingClientRect();
      setTarget({ x: r.left + r.width / 2 - (box.left + box.width / 2), y: r.top + r.height / 2 - (box.top + box.height / 2) });
    }
    animate(scroll, 1, { duration: 0.8, ease: [0.4, 0, 0.2, 1] });
    setAssembling(true);
    setTimeout(onDone, 900);
  };

  useEffect(() => {
    startedAt.current = performance.now();
    const tick = setInterval(() => setStep((s) => Math.min(STEPS.length - 1, s + 1)), STEP_MS);
    const cap = setTimeout(finish, MAX_MS);
    const skip = () => finish();
    window.addEventListener("keydown", skip);
    window.addEventListener("pointerdown", skip);
    return () => {
      clearInterval(tick);
      clearTimeout(cap);
      window.removeEventListener("keydown", skip);
      window.removeEventListener("pointerdown", skip);
    };
    // finish is stable for the lifetime of the intro
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Done as soon as the real data is in and every stage label has been shown once.
  useEffect(() => {
    if (loaded && step === STEPS.length - 1) {
      const t = setTimeout(finish, 500);
      return () => clearTimeout(t);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loaded, step]);

  return (
    <motion.div className="fixed inset-0 z-[100]" aria-label="Profit Pilot is loading" role="status" style={{ pointerEvents: assembling ? "none" : "auto" }}>
      <motion.div className="absolute inset-0" style={{ background: INK }} animate={{ opacity: assembling ? 0 : 1 }} transition={{ duration: 0.7, delay: 0.1 }} />

      <motion.div
        ref={wrap}
        className="absolute inset-0"
        animate={assembling && target ? { x: target.x, y: target.y, opacity: 1 } : assembling ? { opacity: 0 } : { opacity: 1 }}
        transition={{ duration: 0.8, ease: [0.4, 0, 0.2, 1] }}
      >
        <BrainCanvas scrollProgress={scroll} background={INK} />
      </motion.div>

      <motion.div className="relative flex h-full max-w-[640px] flex-col justify-center px-8 min-[1200px]:px-16" animate={{ opacity: assembling ? 0 : 1 }} transition={{ duration: 0.35 }}>
        <div className="mb-8 flex items-center gap-2.5">
          <span className="grid size-8 place-items-center rounded-lg bg-[#3FC7E0] text-base font-extrabold text-[#08202a]" aria-hidden>
            P
          </span>
          <span className="text-xl font-extrabold tracking-tight text-[#E8ECF4]">Profit Pilot</span>
        </div>
        <h1 className="text-[40px] leading-[1.08] font-extrabold tracking-[-0.03em] text-[#E8ECF4]">The decision engine behind your ad spend</h1>
        <div className="mt-8 flex items-center gap-3 text-base text-[#8B97B0]" aria-live="polite">
          <span className="relative h-5 min-w-[120px] overflow-hidden">
            <AnimatePresence mode="wait" initial={false}>
              <motion.span key={step} className="absolute inset-0 font-semibold text-[#3FC7E0]" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }} transition={{ duration: 0.18 }}>
                {STEPS[step]}
              </motion.span>
            </AnimatePresence>
          </span>
          <span className="flex gap-1.5" aria-hidden>
            {STEPS.map((_, i) => (
              <span key={i} className="size-1.5 rounded-full" style={{ background: i <= step ? "#3FC7E0" : "#26324D" }} />
            ))}
          </span>
        </div>
        <p className="mt-10 text-sm text-[#8B97B0]">Press any key to skip.</p>
      </motion.div>
    </motion.div>
  );
}
