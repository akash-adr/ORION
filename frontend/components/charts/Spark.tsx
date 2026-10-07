"use client";

import { linePath, scaleLinear } from "./util";

interface Props {
  values: (number | null)[];
  width?: number;
  height?: number;
  color?: string;
  /** Written description, e.g. "Profit over the last 45 days, down 12%". */
  label: string;
}

/** Tiny trend line with a dot on the latest value. */
export default function Spark({ values, width = 96, height = 28, color = "var(--synapse)", label }: Props) {
  const nums = values.filter((v): v is number => v !== null && Number.isFinite(v));
  if (nums.length < 2) return <svg width={width} height={height} role="img" aria-label={label} />;
  const lo = Math.min(...nums);
  const hi = Math.max(...nums);
  const sy = scaleLinear(lo, hi === lo ? lo + 1 : hi, height - 3, 3);
  const xs = values.map((_, i) => 3 + (i * (width - 6)) / (values.length - 1));
  const ys = values.map((v) => (v === null ? null : sy(v)));
  const lastI = values.length - 1 - [...values].reverse().findIndex((v) => v !== null);
  return (
    <svg width={width} height={height} role="img" aria-label={label} className="block">
      <path d={linePath(xs, ys)} fill="none" stroke={color} strokeWidth="1.75" strokeLinejoin="round" strokeLinecap="round" />
      {ys[lastI] !== null && <circle cx={xs[lastI]} cy={ys[lastI] as number} r="2.5" fill={color} />}
    </svg>
  );
}
