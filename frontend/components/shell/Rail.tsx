"use client";

import { Brain, ChartLine, History, LayoutDashboard, LoaderCircle, Lightbulb, Microscope, Moon, Play, RotateCcw, ShieldCheck, SlidersHorizontal, Sun, Rewind } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState } from "react";
import { useDemoReset, useRefresh, useReplay, useSettings } from "@/lib/queries";
import { ApiError } from "@/lib/api";
import { useUiStore } from "@/lib/ui-store";
import { cn } from "@/lib/utils";
import ConfirmDialog from "./ConfirmDialog";

const NAV = [
  { href: "/command", label: "Command", icon: LayoutDashboard },
  { href: "/neural", label: "Neural view", icon: Brain },
  { href: "/diagnosis", label: "Diagnosis", icon: Microscope },
  { href: "/performance", label: "Performance", icon: ChartLine },
  { href: "/data", label: "Data truth", icon: ShieldCheck },
  { href: "/simulator", label: "Simulator", icon: SlidersHorizontal },
  { href: "/opportunities", label: "Opportunities", icon: Lightbulb },
  { href: "/learning", label: "Learning & audit", icon: History },
] as const;

const failure = (e: unknown) => (e instanceof ApiError ? e.detail : "Something went wrong.");

/** Left rail at >= 1000px (icons only below 1200px); a top strip below 1000px. */
export default function Rail() {
  const pathname = usePathname();
  const router = useRouter();
  const toast = useUiStore((s) => s.toast);
  const theme = useUiStore((s) => s.theme);
  const toggleTheme = useUiStore((s) => s.toggleTheme);
  const { data: settings } = useSettings();
  const refresh = useRefresh();
  const replay = useReplay();
  const reset = useDemoReset();
  const [confirmReset, setConfirmReset] = useState(false);

  const runLoop = () =>
    refresh.mutate(undefined, {
      onSuccess: (r) => {
        const failed = Object.entries(r.steps).filter(([, s]) => !s.ok).map(([k]) => k);
        if (failed.length) toast("risk", `Ran the loop · ${failed.join(", ")} failed`, "The other steps finished. Check the engine log, then run the loop again.");
        else toast("gain", `Ran the loop · ${r.events_logged} brain events`, `${r.outcomes_measured} outcomes measured in ${(r.duration_ms / 1000).toFixed(1)} s.`);
      },
      onError: (e) => toast("loss", "The loop did not run", `${failure(e)} Start the backend and try again.`),
    });

  const startReplay = () =>
    replay.mutate(undefined, {
      onSuccess: (r) => {
        toast("info", `Replaying the last 7 days · ${r.events_queued} events queued`);
        router.push("/neural");
      },
      onError: (e) => toast("loss", "Could not start the replay", failure(e)),
    });

  const doReset = () =>
    reset.mutate(undefined, {
      onSuccess: (r) => {
        setConfirmReset(false);
        if (r.ok === false) toast("risk", "Demo reset is switched off", "reason" in r ? String(r.reason) : undefined);
        else toast("gain", "Demo reset · fresh data loaded");
      },
      onError: (e) => {
        setConfirmReset(false);
        toast("loss", "Could not reset the demo", failure(e));
      },
    });

  const btn = "flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-semibold text-bone hover:bg-slate-2 disabled:opacity-60 max-[999px]:px-2.5 min-[1000px]:max-[1199px]:justify-center min-[1000px]:max-[1199px]:px-0";
  const lab = "max-[999px]:sr-only min-[1000px]:max-[1199px]:sr-only";

  return (
    <aside className="flex items-center gap-2 border-b border-line bg-slate px-3 py-2 min-[1000px]:sticky min-[1000px]:top-0 min-[1000px]:h-screen min-[1000px]:flex-col min-[1000px]:items-stretch min-[1000px]:gap-1 min-[1000px]:border-r min-[1000px]:border-b-0 min-[1000px]:p-3 max-[999px]:overflow-x-auto">
      <Link href="/command" className="flex shrink-0 items-center gap-2.5 px-2 py-1.5 min-[1000px]:mb-4 min-[1000px]:max-[1199px]:justify-center min-[1000px]:max-[1199px]:px-0" aria-label="Profit Pilot, home">
        <span className="grid size-7 shrink-0 place-items-center rounded-lg bg-synapse text-[15px] font-extrabold text-primary-foreground" aria-hidden>
          P
        </span>
        <span className={cn("text-base font-extrabold tracking-tight", lab)}>Profit Pilot</span>
      </Link>

      <nav aria-label="Main" className="flex gap-1 min-[1000px]:flex-1 min-[1000px]:flex-col">
        {NAV.map(({ href, label, icon: Icon }) => {
          const active = pathname === href || pathname.startsWith(`${href}/`);
          return (
            <Link
              key={href}
              href={href}
              title={label}
              aria-current={active ? "page" : undefined}
              className={cn(
                "flex shrink-0 items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-semibold whitespace-nowrap transition-colors max-[999px]:px-2.5 min-[1000px]:max-[1199px]:justify-center min-[1000px]:max-[1199px]:px-0",
                active ? "bg-slate-2 text-bone shadow-[inset_2px_0_0_var(--synapse)]" : "text-fog hover:bg-slate-2 hover:text-bone",
              )}
            >
              <Icon className={cn("size-[18px] shrink-0", active && "text-synapse-fg")} aria-hidden />
              <span className={lab}>{label}</span>
            </Link>
          );
        })}
      </nav>

      <div className="flex shrink-0 gap-1 border-line max-[999px]:ml-auto min-[1000px]:flex-col min-[1000px]:border-t min-[1000px]:pt-3">
        <button onClick={runLoop} disabled={refresh.isPending} className={cn(btn, "bg-synapse !text-primary-foreground hover:!bg-synapse/85")} title="Run the loop now">
          {refresh.isPending ? <LoaderCircle className="size-[18px] animate-spin" aria-hidden /> : <Play className="size-[18px]" aria-hidden />}
          <span className={lab}>{refresh.isPending ? "Running the loop" : "Run the loop now"}</span>
        </button>
        <button onClick={startReplay} disabled={replay.isPending} className={btn} title="Replay the last 7 days">
          <Rewind className="size-[18px]" aria-hidden />
          <span className={lab}>Replay the last 7 days</span>
        </button>
        {settings?.demo_mode && (
          <button onClick={() => setConfirmReset(true)} className={cn(btn, "text-xs !font-medium text-fog")} title="Reset demo">
            <RotateCcw className="size-4" aria-hidden />
            <span className={lab}>Reset demo</span>
          </button>
        )}
        <button onClick={toggleTheme} className={cn(btn, "text-xs !font-medium text-fog")} title={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}>
          {theme === "dark" ? <Sun className="size-4" aria-hidden /> : <Moon className="size-4" aria-hidden />}
          <span className={lab}>{theme === "dark" ? "Light theme" : "Dark theme"}</span>
        </button>
      </div>

      <ConfirmDialog
        open={confirmReset}
        onOpenChange={setConfirmReset}
        title="Reset the demo?"
        description="This clears every decision, audit entry and measured outcome, then runs the loop on fresh data. It can't be undone."
        confirmLabel="Reset the demo"
        busy={reset.isPending}
        onConfirm={doReset}
      />
    </aside>
  );
}
