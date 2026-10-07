"use client";

import { RefreshCw } from "lucide-react";
import type { UseQueryResult } from "@tanstack/react-query";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

export function Panel({ title, note, children, className, ...rest }: { title?: string; note?: string; children: React.ReactNode; className?: string } & React.HTMLAttributes<HTMLElement>) {
  return (
    <section className={cn("panel min-w-0 p-4 min-[1200px]:p-5", className)} {...rest}>
      {title && (
        <div className="mb-3 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
          <h2 className="text-base font-bold">{title}</h2>
          {note && <span className="text-sm text-fog">{note}</span>}
        </div>
      )}
      {children}
    </section>
  );
}

/** Skeleton while loading, a plain-language error with a retry, otherwise the children. */
export function LoadState<T>({ q, what, height = 160, children }: { q: UseQueryResult<T>; what: string; height?: number; children: (data: T) => React.ReactNode }) {
  if (q.isPending) return <Skeleton className="w-full rounded-lg bg-slate-2" style={{ height }} />;
  if (q.isError || q.data === undefined)
    return (
      <div className="flex flex-wrap items-center gap-3 text-sm" role="alert">
        <span className="tone-loss font-semibold">Couldn&apos;t load {what}.</span>
        <span className="text-fog">Check that the backend is running, then retry.</span>
        <button onClick={() => q.refetch()} className="inline-flex items-center gap-1.5 rounded-lg border border-line px-2.5 py-1 font-semibold hover:bg-slate-2">
          <RefreshCw className="size-3.5" aria-hidden />
          Retry
        </button>
      </div>
    );
  return <>{children(q.data)}</>;
}

export function EmptyState({ title, hint, action }: { title: string; hint: string; action?: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-dashed border-line px-4 py-8 text-center">
      <p className="font-semibold">{title}</p>
      <p className="mt-1 text-sm text-fog">{hint}</p>
      {action && <div className="mt-3">{action}</div>}
    </div>
  );
}
