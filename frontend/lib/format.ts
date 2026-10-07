/**
 * Number formatting. inr() must match backend `format_inr` (backend/core/metrics.py) exactly:
 * crores "₹1.20Cr", lakhs "₹1.23L", thousands "₹12.3k", below 1000 "₹850"; negatives "-₹12.3k"; null / NaN → "—".
 */
export const MINUS = "−"; // true minus sign, used for percentages and deltas
const DASH = "—";

type Maybe = number | null | undefined;

function finite(v: Maybe): v is number {
  return typeof v === "number" && Number.isFinite(v);
}

/** Python-style round-half-even is not needed here: toFixed matches Python's f"{x:.1f}" for the values we show. */
export function inr(v: Maybe): string {
  if (!finite(v)) return DASH;
  const sign = v < 0 ? "-" : "";
  const a = Math.abs(v);
  let body: string;
  if (a >= 1e7) body = `${(a / 1e7).toFixed(2)}Cr`;
  else if (a >= 1e5) body = `${(a / 1e5).toFixed(2)}L`;
  else if (a >= 1e3) body = `${(a / 1e3).toFixed(1)}k`;
  else body = a.toFixed(0);
  return `${sign}₹${body}`;
}

/** ₹ per day, e.g. "₹12.3k/day". */
export function inrDay(v: Maybe): string {
  const s = inr(v);
  return s === DASH ? s : `${s}/day`;
}

/** Signed ₹ with an explicit plus: "+₹12.3k". Zero stays unsigned. */
export function inrSigned(v: Maybe): string {
  if (!finite(v)) return DASH;
  return v > 0 ? `+${inr(v)}` : inr(v);
}

/** A fraction as a percentage: pct(0.254) → "25%", pct(-0.05, 1, true) → "−5.0%", pct(0.05, 0, true) → "+5%". */
export function pct(fraction: Maybe, digits = 0, signed = false): string {
  if (!finite(fraction)) return DASH;
  const body = `${Math.abs(fraction * 100).toFixed(digits)}%`;
  if (fraction < 0 && Number(body.slice(0, -1)) !== 0) return `${MINUS}${body}`;
  return signed && Number(body.slice(0, -1)) !== 0 ? `+${body}` : body;
}

/** Plain number with grouping, e.g. num(1234.5, 1) → "1,234.5". */
export function num(v: Maybe, digits = 0): string {
  if (!finite(v)) return DASH;
  const s = Math.abs(v).toLocaleString("en-IN", { minimumFractionDigits: digits, maximumFractionDigits: digits });
  return v < 0 && Number(s.replace(/,/g, "")) !== 0 ? `${MINUS}${s}` : s;
}

/** A ratio like ROAS / POAS: "2.05×". */
export function ratio(v: Maybe, digits = 2): string {
  return finite(v) ? `${v.toFixed(digits)}×` : DASH;
}

export type Tone = "gain" | "loss" | "muted";
/** Tone of a signed value. Pass `invert` for metrics where down is good (cost per click). */
export function tone(v: Maybe, invert = false): Tone {
  if (!finite(v) || v === 0) return "muted";
  return (v > 0) !== invert ? "gain" : "loss";
}

/** "2026-10-06" → "6 Oct" (or "6 Oct 2026"). */
export function dateShort(iso: string | null | undefined, withYear = false): string {
  if (!iso) return DASH;
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  if (!y || !m || !d) return DASH;
  const mon = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][m - 1];
  return withYear ? `${d} ${mon} ${y}` : `${d} ${mon}`;
}

/** "2026-10-07T14:54:39" → "2:54 pm" (the engine's naive IST timestamps, shown as-is). */
export function timeShort(ts: string | null | undefined): string {
  if (!ts || ts.length < 16) return DASH;
  const h = Number(ts.slice(11, 13));
  const mm = ts.slice(14, 16);
  return `${h % 12 || 12}:${mm} ${h >= 12 ? "pm" : "am"}`;
}
