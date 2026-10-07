"use client";

import dynamic from "next/dynamic";
import { useSyncExternalStore } from "react";
import type { BrainSceneProps } from "./BrainScene";

// three.js needs `window`/WebGL, so the canvas is client-only.
const BrainScene = dynamic(() => import("./BrainScene"), { ssr: false });

const QUERY = "(max-width: 767px)";
const subscribe = (cb: () => void) => {
  const mq = window.matchMedia(QUERY);
  mq.addEventListener("change", cb);
  return () => mq.removeEventListener("change", cb);
};

/** Renders the WebGL brain on desktop and a static image below 768px. */
export default function BrainCanvas(props: BrainSceneProps) {
  const isMobile = useSyncExternalStore(
    subscribe,
    () => window.matchMedia(QUERY).matches,
    () => null,
  );

  if (isMobile === null) return null;
  if (isMobile) {
    return (
      <div className="absolute inset-0 flex items-center justify-center">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src="/brain-fallback.svg" alt="Particle brain" className="w-[90%] max-w-md opacity-90" />
      </div>
    );
  }
  return <BrainScene {...props} />;
}

