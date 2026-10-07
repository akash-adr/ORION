"use client";

import { usePathname } from "next/navigation";
import { useState, useSyncExternalStore } from "react";
import { useUiStore } from "@/lib/ui-store";
import Intro from "@/components/intro/Intro";
import OfflineBanner from "./OfflineBanner";
import Rail from "./Rail";
import Toaster from "./Toaster";
import TopBar from "./TopBar";

const INTRO_KEY = "mm-intro-shown";

const noop = () => () => {};
const readSeen = () => {
  try {
    return sessionStorage.getItem(INTRO_KEY) === "1";
  } catch {
    return false; // storage unavailable: treat as not seen
  }
};
const readReduced = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;
// null on the server and during hydration, so the first paint is a plain cover (no flash of dashboard before the intro)
const serverNull = () => null;

export default function AppShell({ children }: { children: React.ReactNode }) {
  const seen = useSyncExternalStore<boolean | null>(noop, readSeen, serverNull);
  const reduced = useSyncExternalStore<boolean | null>(noop, readReduced, serverNull);
  const [finished, setFinished] = useState(false);
  const pathname = usePathname();
  const presenterOn = useUiStore((s) => s.presenter);
  const presenting = presenterOn && pathname === "/pitch";
  const phase = seen === null || reduced === null ? "checking" : seen || reduced || finished ? "done" : "intro";

  const introDone = () => {
    try {
      sessionStorage.setItem(INTRO_KEY, "1");
    } catch {
      /* ignore */
    }
    setFinished(true);
  };

  return (
    <div className={presenting ? "min-h-screen" : "min-h-screen min-[1000px]:grid min-[1000px]:grid-cols-[72px_minmax(0,1fr)] min-[1200px]:grid-cols-[236px_minmax(0,1fr)]"}>
      {!presenting && <Rail />}
      <div className="flex min-w-0 flex-col">
        <OfflineBanner />
        {!presenting && <TopBar />}
        <main className={presenting ? "min-w-0 flex-1 px-4 py-4" : "min-w-0 flex-1 px-4 py-6 min-[1000px]:px-6 min-[1200px]:px-8"}>{children}</main>
      </div>
      <Toaster />
      {phase === "checking" && <div className="fixed inset-0 z-[100] bg-ink" aria-hidden />}
      {phase === "intro" && <Intro onDone={introDone} />}
    </div>
  );
}
