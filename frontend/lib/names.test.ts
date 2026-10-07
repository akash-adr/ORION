import { describe, expect, it } from "vitest";
import { actionTypeDisplay, anomalyEntity, channelDisplay, factorColor, kindDisplay, parseCampaignName } from "./names";

describe("names", () => {
  it("parses campaign names into parts", () => {
    expect(parseCampaignName("Meta · Summer Sneakers · broad")).toEqual({ channel: "meta", channelName: "Meta", product: "Summer Sneakers", audience: "broad" });
    expect(parseCampaignName("TikTok · Gym Flex · broad").channelName).toBe("TikTok");
    expect(parseCampaignName("Programmatic · Office Loafer · broad").product).toBe("Office Loafer");
  });
  it("shows TikTok, never Tiktok", () => {
    expect(channelDisplay("tiktok")).toBe("TikTok");
    expect(channelDisplay(null)).toBe("—");
  });
  it("kinds and actions", () => {
    expect(kindDisplay("cpc_spike")).toBe("CPC spike");
    expect(kindDisplay("something_new")).toBe("Something new");
    expect(actionTypeDisplay("inventory_protect")).toBe("Protect stock");
  });
  it("strips the kind from an anomaly label", () => {
    expect(anomalyEntity("Creative fatigue · Meta · Summer Sneakers · broad")).toBe("Meta · Summer Sneakers · broad");
    expect(anomalyEntity("CPC spike · Google")).toBe("Google");
  });
  it("maps factor names to colour tokens", () => {
    expect(factorColor("Traffic (sessions)")).toBe("var(--factor-traffic)");
    expect(factorColor("Unknown")).toBe("var(--fog)");
  });
});
