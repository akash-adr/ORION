"use client";

import { motion, useScroll, useTransform, type Variants } from "framer-motion";
import BrainCanvas from "@/components/brain/BrainCanvas";
import BrainTooltip from "@/components/brain/BrainTooltip";
import DevPanel from "@/components/brain/DevPanel";
import { REGION_META } from "@/components/brain/regions";
import { useBrainStore } from "@/components/brain/store";

const HEADLINE = "The Autonomous Brain Behind Your Ad Spend".split(" ");

const word: Variants = {
  hidden: { opacity: 0, y: 28, filter: "blur(8px)" },
  show: { opacity: 1, y: 0, filter: "blur(0px)", transition: { duration: 0.7, ease: "easeOut" } },
};

// Card slots around the brain: two left, two right.
const CARD_ORDER = ["ingest", "diagnose", "decide", "learn"] as const;

export default function Home() {
  const { scrollYProgress } = useScroll();
  // The page is two screens tall, so progress hits 1 when the dashboard is fully in view.
  const heroOpacity = useTransform(scrollYProgress, [0, 0.45], [1, 0]);
  const heroY = useTransform(scrollYProgress, [0, 0.45], [0, -60]);
  const dashOpacity = useTransform(scrollYProgress, [0.55, 1], [0, 1]);
  const selected = useBrainStore((s) => s.selectedRegion);

  return (
    <main className="relative bg-[#05060a] text-white">
      {/* Fixed brain stage; hero and dashboard content scroll over it. */}
      <div className="fixed inset-0 z-0">
        <BrainCanvas scrollProgress={scrollYProgress} />
      </div>

      <div className="pointer-events-none relative z-10">
        {/* Hero */}
        <section className="flex h-screen items-center px-6 md:px-16">
          <motion.div style={{ opacity: heroOpacity, y: heroY }} className="max-w-xl">
            <motion.p
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ delay: 0.1, duration: 0.8 }}
              className="mb-4 font-mono text-xs uppercase tracking-[0.3em] text-blue-300/80"
            >
              D2C Advertising Intelligence Engine
            </motion.p>
            <motion.h1
              initial="hidden"
              animate="show"
              transition={{ staggerChildren: 0.08, delayChildren: 0.25 }}
              className="text-4xl font-semibold leading-[1.05] tracking-tight md:text-6xl"
            >
              {HEADLINE.map((w, i) => (
                <motion.span key={i} variants={word} className="mr-[0.25em] inline-block">
                  {w}
                </motion.span>
              ))}
            </motion.h1>
            <motion.p
              initial={{ opacity: 0, y: 16 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 1.1, duration: 0.8 }}
              className="mt-6 max-w-md text-base text-white/60 md:text-lg"
            >
              Ingests every channel, diagnoses anomalies in real time, decides where budget should
              move, and learns from every outcome — without waiting for a human.
            </motion.p>
            <motion.button
              initial={{ opacity: 0, y: 16 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 1.4, duration: 0.8 }}
              whileHover={{ scale: 1.04 }}
              whileTap={{ scale: 0.97 }}
              onClick={() => window.scrollTo({ top: window.innerHeight, behavior: "smooth" })}
              className="pointer-events-auto mt-8 rounded-full border border-blue-400/40 bg-blue-500/15 px-7 py-3 text-sm font-medium text-blue-100 shadow-[0_0_30px_-8px_#3b82f6] backdrop-blur-md transition-colors hover:bg-blue-500/25"
            >
              Launch Engine
            </motion.button>
          </motion.div>
        </section>

        {/* Dashboard: brain sits in the empty centre column */}
        <motion.section
          style={{ opacity: dashOpacity }}
          className="grid h-screen grid-cols-1 content-center gap-5 px-6 md:grid-cols-[1fr_minmax(260px,32vw)_1fr] md:grid-rows-[auto_auto] md:gap-y-[22vh] md:px-12"
        >
          {CARD_ORDER.map((r, i) => {
            const meta = REGION_META[r];
            // grid placement: ingest/diagnose left, decide/learn right
            const col = i < 2 ? "md:col-start-1" : "md:col-start-3";
            const row = i % 2 === 0 ? "md:row-start-1" : "md:row-start-2";
            return (
              <div
                key={r}
                className={`${col} ${row} pointer-events-auto rounded-2xl border bg-white/[0.04] p-5 backdrop-blur-xl transition-colors`}
                style={{
                  borderColor: selected === r ? meta.color : "rgba(255,255,255,0.1)",
                  boxShadow: selected === r ? `0 0 40px -12px ${meta.color}` : undefined,
                }}
              >
                <div className="flex items-center gap-2 font-mono text-xs font-semibold tracking-widest" style={{ color: meta.color }}>
                  <span className="h-2 w-2 rounded-full" style={{ background: meta.color }} />
                  {meta.label}
                </div>
                <p className="mt-1 text-xs text-white/50">{meta.description}</p>
                <div className="mt-4 h-24 rounded-xl border border-dashed border-white/10" />
              </div>
            );
          })}
        </motion.section>
      </div>

      <BrainTooltip />
      <DevPanel />
    </main>
  );
}

