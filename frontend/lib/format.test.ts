import { describe, expect, it } from "vitest";
import { dateShort, inr, inrDay, num, pct, ratio, timeShort, tone } from "./format";

describe("inr (matches backend format_inr)", () => {
  it.each([
    [123456, "₹1.23L"],
    [12000000, "₹1.20Cr"],
    [12300, "₹12.3k"],
    [-12300, "-₹12.3k"],
    [850, "₹850"],
    [0, "₹0"],
    [999.4, "₹999"],
    [100000, "₹1.00L"],
    [1000, "₹1.0k"],
    [-156000, "-₹1.56L"],
  ])("%s → %s", (v, out) => expect(inr(v)).toBe(out));
  it("null and NaN are an em dash", () => {
    expect(inr(null)).toBe("—");
    expect(inr(undefined)).toBe("—");
    expect(inr(NaN)).toBe("—");
    expect(inr(Infinity)).toBe("—");
  });
  it("inrDay appends /day", () => {
    expect(inrDay(12300)).toBe("₹12.3k/day");
    expect(inrDay(null)).toBe("—");
  });
});

describe("pct", () => {
  it("uses a true minus sign", () => {
    expect(pct(-0.254)).toBe("−25%");
    expect(pct(-0.05, 1, true)).toBe("−5.0%");
  });
  it("signs gains only when asked", () => {
    expect(pct(0.254)).toBe("25%");
    expect(pct(0.05, 0, true)).toBe("+5%");
  });
  it("does not sign a rounded zero", () => {
    expect(pct(-0.001)).toBe("0%");
    expect(pct(0.001, 0, true)).toBe("0%");
    expect(pct(null)).toBe("—");
  });
});

describe("num, ratio, tone, dates", () => {
  it("num", () => {
    expect(num(1234.5, 1)).toBe("1,234.5");
    expect(num(-3)).toBe("−3");
    expect(num(null)).toBe("—");
  });
  it("ratio", () => expect(ratio(2.0496)).toBe("2.05×"));
  it("tone", () => {
    expect(tone(5)).toBe("gain");
    expect(tone(-5)).toBe("loss");
    expect(tone(0)).toBe("muted");
    expect(tone(null)).toBe("muted");
    expect(tone(5, true)).toBe("loss");
  });
  it("dates", () => {
    expect(dateShort("2026-10-06")).toBe("6 Oct");
    expect(dateShort("2026-10-06", true)).toBe("6 Oct 2026");
    expect(timeShort("2026-10-07T14:54:39")).toBe("2:54 pm");
    expect(timeShort("2026-10-07T00:05:00")).toBe("12:05 am");
  });
});
