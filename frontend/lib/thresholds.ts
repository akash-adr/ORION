import { inr, pct } from "./format";
import type { MetaConfig } from "./types";

export interface ThresholdRow {
  key: string;
  label: string;
  /** the value as shown, with its unit */
  value: string;
  /** one plain sentence, written from the live numbers */
  explain: string;
}
export interface ThresholdGroup {
  id: "detection" | "guardrails" | "optimizer" | "learning" | "loop";
  title: string;
  rows: ThresholdRow[];
}

const days = (n: number) => `${n} ${n === 1 ? "day" : "days"}`;

/** Turns /meta/config into labelled groups with a one-line explanation per setting. Every number comes from the config. */
export function describeThresholds(c: MetaConfig): ThresholdGroup[] {
  const d = c.detection;
  const g = c.guardrails;
  const o = c.optimizer;
  const l = c.learning;
  return [
    {
      id: "detection",
      title: "Detection",
      rows: [
        { key: "Z_THRESHOLD", label: "Statistical strength", value: `z ≥ ${d.Z_THRESHOLD}`, explain: `A change must be both statistically strong (z ≥ ${d.Z_THRESHOLD}) and at least ${pct(d.MIN_PCT_CHANGE)} to raise a signal.` },
        { key: "MIN_PCT_CHANGE", label: "Minimum change", value: pct(d.MIN_PCT_CHANGE), explain: "Smaller moves are ignored, even when they are statistically unusual." },
        { key: "RECENT_DAYS", label: "Recent window", value: days(d.RECENT_DAYS), explain: `The last ${days(d.RECENT_DAYS)} are compared with the baseline.` },
        { key: "BASELINE_DAYS", label: "Baseline window", value: days(d.BASELINE_DAYS), explain: `The ${days(d.BASELINE_DAYS)} before that define what normal looks like.` },
        { key: "STOCK_COVER_RISK_DAYS", label: "Stock risk", value: days(d.STOCK_COVER_RISK_DAYS), explain: `A product with fewer than ${days(d.STOCK_COVER_RISK_DAYS)} of stock is flagged as a stockout risk.` },
        { key: "SKU_RECENT_DAYS", label: "Product recent window", value: days(d.SKU_RECENT_DAYS), explain: `Product conversion checks compare the last ${days(d.SKU_RECENT_DAYS)} with the ${days(d.SKU_BASELINE_DAYS)} before, because shopper behaviour moves slowly.` },
      ],
    },
    {
      id: "guardrails",
      title: "Guardrails",
      rows: [
        { key: "AUTO_APPLY_MAX_SHIFT", label: "Auto-apply limit", value: pct(g.AUTO_APPLY_MAX_SHIFT), explain: `In autonomous mode only budget shifts under ${pct(g.AUTO_APPLY_MAX_SHIFT)} apply without your approval, and only at low risk.` },
        { key: "DAILY_CHANGE_CAP", label: "Daily change cap", value: `±${pct(g.DAILY_CHANGE_CAP)}`, explain: `No campaign budget changes by more than ${pct(g.DAILY_CHANGE_CAP)} in one day.` },
        { key: "STOCK_SPEND_CAP_MULT", label: "Stock spend cap", value: pct(g.STOCK_SPEND_CAP_MULT), explain: `Campaigns on products under ${days(d.STOCK_COVER_RISK_DAYS)} of stock are held to ${pct(g.STOCK_SPEND_CAP_MULT)} of current spend and can't increase.` },
        { key: "RISK_HIGH_SHIFT", label: "High risk: shift", value: `> ${pct(g.RISK_HIGH_SHIFT)}`, explain: `A budget shift above ${pct(g.RISK_HIGH_SHIFT)} counts as high risk.` },
        { key: "RISK_HIGH_IMPACT", label: "High risk: impact", value: `> ${inr(g.RISK_HIGH_IMPACT)}/day`, explain: `A profit effect above ${inr(g.RISK_HIGH_IMPACT)} a day, either way, counts as high risk.` },
        { key: "RISK_MEDIUM_SHIFT", label: "Medium risk: shift", value: `> ${pct(g.RISK_MEDIUM_SHIFT)}`, explain: `A budget shift above ${pct(g.RISK_MEDIUM_SHIFT)} is at least medium risk.` },
        { key: "CONFIDENCE", label: "Confidence range", value: `${pct(g.CONFIDENCE_MIN)} to ${pct(g.CONFIDENCE_MAX)}`, explain: `No recommendation is ever less than ${pct(g.CONFIDENCE_MIN)} or more than ${pct(g.CONFIDENCE_MAX)} confident. The engine never claims certainty.` },
      ],
    },
    {
      id: "optimizer",
      title: "Optimizer",
      rows: [
        { key: "OVERSTOCK_COVER_DAYS", label: "Overstock", value: days(o.OVERSTOCK_COVER_DAYS), explain: `A product with more than ${days(o.OVERSTOCK_COVER_DAYS)} of stock can receive extra budget when the objective is to clear stock.` },
        { key: "LAUNCH_TEST_RESERVE", label: "Launch reserve", value: pct(o.LAUNCH_TEST_RESERVE), explain: `Launching a product reserves ${pct(o.LAUNCH_TEST_RESERVE)} of the budget for tests of new combinations.` },
        { key: "OPP_TEST_BUDGET", label: "Test budget", value: `${inr(o.OPP_TEST_BUDGET)}/day`, explain: `Untested combinations are scored as if given ${inr(o.OPP_TEST_BUDGET)} a day, and real tests start at that size.` },
      ],
    },
    {
      id: "learning",
      title: "Learning",
      rows: [
        { key: "CALIBRATION_WINDOW", label: "Calibration window", value: `${l.CALIBRATION_WINDOW} outcomes`, explain: `Predictions are corrected using the last ${l.CALIBRATION_WINDOW} measured outcomes.` },
        { key: "CALIBRATION_RANGE", label: "Calibration range", value: `${l.CALIBRATION_MIN}× to ${l.CALIBRATION_MAX}×`, explain: `The correction factor never leaves ${l.CALIBRATION_MIN}× to ${l.CALIBRATION_MAX}×, so one bad outcome can't swing the engine.` },
      ],
    },
    {
      id: "loop",
      title: "Loop",
      rows: [{ key: "REFRESH_MINUTES", label: "Run interval", value: `${c.loop.REFRESH_MINUTES} minutes`, explain: `The engine runs the whole loop (ingest, detect, diagnose, optimize, decide, learn) every ${c.loop.REFRESH_MINUTES} minutes. All money is in ${c.currency}.` }],
    },
  ];
}
