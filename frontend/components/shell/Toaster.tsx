"use client";

import { CircleAlert, CircleCheck, Info, TriangleAlert, X } from "lucide-react";
import { useUiStore, type ToastTone } from "@/lib/ui-store";

const ICON: Record<ToastTone, typeof Info> = { gain: CircleCheck, loss: CircleAlert, risk: TriangleAlert, info: Info };
const COLOR: Record<ToastTone, string> = { gain: "tone-gain", loss: "tone-loss", risk: "tone-risk", info: "text-synapse-fg" };

export default function Toaster() {
  const toasts = useUiStore((s) => s.toasts);
  const dismiss = useUiStore((s) => s.dismissToast);
  return (
    <div className="pointer-events-none fixed right-4 bottom-4 z-[60] flex w-[min(380px,calc(100vw-2rem))] flex-col gap-2" role="region" aria-label="Notifications" aria-live="polite">
      {toasts.map((t) => {
        const Icon = ICON[t.tone];
        return (
          <div key={t.id} className="float-layer pointer-events-auto flex items-start gap-2.5 p-3 text-sm" role={t.tone === "loss" ? "alert" : "status"}>
            <Icon className={`mt-0.5 size-4 shrink-0 ${COLOR[t.tone]}`} aria-hidden />
            <div className="min-w-0 flex-1">
              <div className="font-semibold">{t.message}</div>
              {t.detail && <div className="mt-0.5 text-fog">{t.detail}</div>}
            </div>
            <button onClick={() => dismiss(t.id)} aria-label="Dismiss notification" className="rounded p-0.5 text-fog hover:text-bone">
              <X className="size-4" />
            </button>
          </div>
        );
      })}
    </div>
  );
}
