"use client";

import { useQueryClient } from "@tanstack/react-query";
import { WifiOff } from "lucide-react";
import { useState } from "react";
import { API_URL, api } from "@/lib/api";
import { useUiStore } from "@/lib/ui-store";

function portOf(url: string): string {
  try {
    const u = new URL(url);
    return u.port || (u.protocol === "https:" ? "443" : "80");
  } catch {
    return "8000";
  }
}

export default function OfflineBanner() {
  const offline = useUiStore((s) => s.offline);
  const qc = useQueryClient();
  const [busy, setBusy] = useState(false);
  if (!offline) return null;
  const retry = async () => {
    setBusy(true);
    try {
      await api.health(); // flips the connectivity flag back if the engine answers
      await qc.refetchQueries();
    } catch {
      /* still offline: the banner stays */
    } finally {
      setBusy(false);
    }
  };
  return (
    <div role="alert" className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-line bg-slate-2 px-4 py-2.5 text-sm min-[1000px]:px-6">
      <WifiOff className="size-4 shrink-0 tone-loss" aria-hidden />
      <span className="font-semibold">The engine isn&apos;t reachable on port {portOf(API_URL)}.</span>
      <span className="text-fog">Start the backend, then retry.</span>
      <button onClick={retry} disabled={busy} className="ml-auto rounded-lg border border-line bg-slate px-3 py-1 font-semibold hover:bg-slate-2 disabled:opacity-60">
        {busy ? "Checking" : "Retry"}
      </button>
    </div>
  );
}
