"use client";

import { ArrowDown, ArrowUp, ChevronRight } from "lucide-react";
import { Fragment, useMemo, useState } from "react";
import { useWidth } from "@/components/charts/util";
import { cn } from "@/lib/utils";

export interface Col<T> {
  id: string;
  label: string;
  /** shown under the label, e.g. "per day" */
  sub?: string;
  align?: "left" | "right";
  /** sort key; omit for an unsortable column */
  sort?: (r: T) => number | string | null | undefined;
  cell: (r: T) => React.ReactNode;
  /** the first column stays in view while scrolling sideways */
  sticky?: boolean;
  /** explanation shown on hover and read by screen readers */
  hint?: string;
}

interface Props<T> {
  rows: T[];
  cols: Col<T>[];
  rowKey: (r: T) => string;
  defaultSort?: { id: string; dir: "asc" | "desc" };
  /** renders the expanded detail of a row; adds a chevron column */
  expand?: (r: T) => React.ReactNode;
  onRowClick?: (r: T) => void;
  ariaLabel: string;
  /** the sticky header needs a scroll container with a height */
  maxHeight?: string;
  empty?: React.ReactNode;
}

/** A real table: click a header to sort (twice to reverse), sticky header, right-aligned numbers, optional expanding rows. */
export default function DataGrid<T>({ rows, cols, rowKey, defaultSort, expand, onRowClick, ariaLabel, maxHeight = "min(72vh, 760px)", empty }: Props<T>) {
  const [sort, setSort] = useState(defaultSort ?? null);
  const [open, setOpen] = useState<string | null>(null);
  const [box, boxW] = useWidth<HTMLDivElement>();

  const sorted = useMemo(() => {
    if (!sort) return rows;
    const col = cols.find((c) => c.id === sort.id);
    if (!col?.sort) return rows;
    const get = col.sort;
    const dir = sort.dir === "asc" ? 1 : -1;
    return [...rows].sort((a, b) => {
      const x = get(a);
      const y = get(b);
      if (x == null && y == null) return 0;
      if (x == null) return 1; // missing values always last
      if (y == null) return -1;
      return (typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y))) * dir;
    });
  }, [rows, cols, sort]);

  const click = (c: Col<T>) => {
    if (!c.sort) return;
    setSort((cur) => (cur?.id === c.id ? { id: c.id, dir: cur.dir === "asc" ? "desc" : "asc" } : { id: c.id, dir: c.align === "right" ? "desc" : "asc" }));
  };

  if (!rows.length && empty) return <>{empty}</>;
  return (
    <div ref={box} className="overflow-auto" style={{ maxHeight }}>
      <table className="tbl min-w-full" aria-label={ariaLabel}>
        <thead>
          <tr>
            {expand && <th className="sticky top-0 z-20 w-8 bg-slate" aria-label="Details" />}
            {cols.map((c, i) => {
              const active = sort?.id === c.id;
              return (
                <th
                  key={c.id}
                  scope="col"
                  aria-sort={active ? (sort!.dir === "asc" ? "ascending" : "descending") : c.sort ? "none" : undefined}
                  title={c.hint}
                  className={cn("sticky top-0 z-10 bg-slate", c.align === "right" && "text-right", c.sticky && i === 0 && "left-0 z-30")}
                >
                  {c.sort ? (
                    <button onClick={() => click(c)} className={cn("inline-flex flex-col items-start rounded text-left font-semibold hover:text-bone", c.align === "right" && "items-end text-right", active ? "text-bone" : "text-fog")}>
                      <span className="inline-flex items-center gap-1">
                        {c.label}
                        {active && (sort!.dir === "asc" ? <ArrowUp className="size-3" aria-hidden /> : <ArrowDown className="size-3" aria-hidden />)}
                      </span>
                      {c.sub && <span className="text-xs font-normal text-fog">{c.sub}</span>}
                    </button>
                  ) : (
                    <span className="inline-flex flex-col">
                      {c.label}
                      {c.sub && <span className="text-xs font-normal text-fog">{c.sub}</span>}
                    </span>
                  )}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {sorted.map((r) => {
            const key = rowKey(r);
            const isOpen = open === key;
            return (
              <Fragment key={key}>
                <tr
                  onClick={() => (expand ? setOpen(isOpen ? null : key) : onRowClick?.(r))}
                  className={cn("group", (expand || onRowClick) && "cursor-pointer hover:bg-slate-2/60", isOpen && "bg-slate-2/60")}
                >
                  {expand && (
                    <td className="w-8 !pr-0">
                      <button aria-expanded={isOpen} aria-label={isOpen ? "Hide details" : "Show details"} onClick={(e) => (e.stopPropagation(), setOpen(isOpen ? null : key))} className="rounded p-1 text-fog hover:text-bone">
                        <ChevronRight className={cn("size-4 transition-transform duration-200", isOpen && "rotate-90")} aria-hidden />
                      </button>
                    </td>
                  )}
                  {cols.map((c, i) => (
                    <td key={c.id} className={cn(c.align === "right" && "num", c.sticky && i === 0 && "sticky left-0 z-[5] min-w-[240px] whitespace-nowrap bg-slate group-hover:bg-slate-2", isOpen && c.sticky && i === 0 && "bg-slate-2")}>
                      {c.cell(r)}
                    </td>
                  ))}
                </tr>
                {isOpen && expand && (
                  <tr>
                    <td colSpan={cols.length + 1} className="!border-b !bg-slate-2/30 !p-4">
                      {/* pinned to the visible width, so a wide table never pushes the detail off-screen */}
                      <div className="sticky left-0" style={{ width: Math.max(280, boxW - 32) }}>
                        {expand(r)}
                      </div>
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
