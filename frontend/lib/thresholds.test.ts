import { describe, expect, it } from "vitest";
import { describeThresholds } from "./thresholds";
import cfg from "./__samples__/meta-config.json";
import type { MetaConfig } from "./types";

const groups = describeThresholds(cfg as MetaConfig);
const row = (k: string) => groups.flatMap((g) => g.rows).find((r) => r.key === k)!;

describe("thresholds panel", () => {
  it("covers every group the spec lists", () => {
    expect(groups.map((g) => g.id)).toEqual(["detection", "guardrails", "optimizer", "learning", "loop"]);
  });
  it("writes the detection rule from the live numbers", () => {
    expect(row("Z_THRESHOLD").explain).toBe("A change must be both statistically strong (z ≥ 2.5) and at least 15% to raise a signal.");
  });
  it("formats guardrail values", () => {
    expect(row("DAILY_CHANGE_CAP").value).toBe("±50%");
    expect(row("AUTO_APPLY_MAX_SHIFT").value).toBe("10%");
    expect(row("RISK_HIGH_IMPACT").value).toBe("> ₹40.0k/day");
    expect(row("CONFIDENCE").value).toBe("45% to 95%");
    expect(row("STOCK_SPEND_CAP_MULT").explain).toContain("under 7 days");
  });
  it("uses every config number", () => {
    const text = JSON.stringify(groups);
    for (const v of ["7 days", "21 days", "60 days", "5%", "₹5.0k", "8 outcomes", "0.6×", "1.2×", "5 minutes"]) expect(text).toContain(v);
  });
});
