import { describe, expect, it } from "vitest";
import { boundReasons, changePct, guardrailChecks, rawImpact } from "./decision";
import { parseDecisionTitle, zMeaning } from "./names";
import cfg from "./__samples__/meta-config.json";
import campaigns from "./__samples__/campaigns.json";
import recs from "./__samples__/recommendations.json";
import type { CampaignRow, Decision, MetaConfig } from "./types";

const C = cfg as MetaConfig;
const camps = campaigns as unknown as CampaignRow[];
const decisions = recs.pending as unknown as Decision[];
const byType = (t: string) => decisions.find((d) => d.action.type === t)!;

describe("decision helpers", () => {
  it("computes change percentages from the budgets", () => {
    const c = byType("inventory_protect").action.changes[0];
    expect(changePct(c)).toBeCloseTo(-0.6, 2);
  });
  it("explains a stock-guard cut as the stock guard, not the daily cap", () => {
    const d = byType("inventory_protect");
    const c = d.action.changes[0];
    expect(boundReasons(c, C, camps.find((x) => x.campaign_id === c.campaign_id))).toEqual(["stock"]);
  });
  it("explains a 50% cut on a healthy product as the daily cap", () => {
    const d = byType("creative_refresh");
    const c = d.action.changes[0];
    expect(boundReasons(c, C, camps.find((x) => x.campaign_id === c.campaign_id))).toEqual(["cap"]);
  });
  it("marks the stock-guard cut as an exception to the daily cap, not a failure", () => {
    const checks = guardrailChecks(byType("inventory_protect"), C, camps);
    expect(checks[0].state).toBe("exception");
    expect(checks[1].state).toBe("pass");
    expect(checks[2].state).toBe("info");
    expect(checks[3].state).toBe("pass");
    expect(checks[0].label).toBe("Change within ±50% per day");
    expect(checks[1].label).toBe("No spend increase on products under 7 days of stock");
  });
  it("passes a low-risk launch test for automatic apply", () => {
    expect(guardrailChecks(byType("launch_test"), C, camps)[2].state).toBe("pass");
  });
  it("recovers the raw model output from the calibrated impact", () => {
    const d = { ...byType("scale_up"), expected_profit_delta: 1010, calibration_factor: 1.01 } as Decision;
    expect(rawImpact(d)).toBeCloseTo(1000);
  });
});

describe("decision titles and statistics", () => {
  it("splits a campaign title into action and parts", () => {
    const t = parseDecisionTitle("Refresh creative & trim budget · Meta · Summer Sneakers · broad");
    expect(t.action).toBe("Refresh creative & trim budget");
    expect(t.campaign).toMatchObject({ channelName: "Meta", product: "Summer Sneakers", audience: "broad" });
  });
  it("keeps a free-text subject without a campaign", () => {
    const t = parseDecisionTitle("Protect stock · cut ads on Running Pro by 60%");
    expect(t).toMatchObject({ action: "Protect stock", subject: "cut ads on Running Pro by 60%", campaign: null });
  });
  it("describes z-scores in plain words", () => {
    expect(zMeaning(-6.9)).toBe("far outside normal variation");
    expect(zMeaning(28.3)).toBe("far outside normal variation");
    expect(zMeaning(-2.6)).toBe("outside normal variation");
    expect(zMeaning(0)).toContain("sources");
    expect(zMeaning(null)).toBe("no statistical signal");
  });
});
