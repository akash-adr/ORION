import { expect, test } from "@playwright/test";

const ROUTES = ["/command", "/neural", "/diagnosis", "/performance", "/performance?tab=products", "/data", "/simulator", "/opportunities", "/learning"];

test("keyboard: every page is reachable by Tab and every focused element shows a focus indicator", async ({ page }) => {
  await page.addInitScript(() => sessionStorage.setItem("mm-intro-shown", "1"));
  const problems: string[] = [];
  for (const route of ROUTES) {
    await page.goto(route);
    await expect(page.locator("main h1")).toBeVisible();
    await page.waitForTimeout(3000);
    let reachedMain = false;
    for (let i = 0; i < 45; i++) {
      await page.keyboard.press("Tab");
      const r = await page.evaluate(() => {
        const el = document.activeElement as HTMLElement | SVGElement | null;
        if (!el || el === document.body) return null;
        const cs = getComputedStyle(el);
        // a chart <svg> root takes the global outline; items inside the map use their own focus ring
        const inSvg = el instanceof SVGElement && el.tagName.toLowerCase() !== "svg";
        const ring = inSvg ? el.querySelector(".focus-ring") : null;
        const visible = inSvg ? !!ring && getComputedStyle(ring).opacity === "1" : cs.outlineStyle !== "none" && parseFloat(cs.outlineWidth) >= 2;
        const wrapped = !inSvg && el instanceof HTMLInputElement && !!el.closest("form") && getComputedStyle(el.closest("form") as Element).outlineStyle !== "none";
        const name = (el.getAttribute("aria-label") || el.textContent || el.tagName).trim().slice(0, 40);
        return { visible: visible || wrapped, name, tag: el.tagName, inMain: !!el.closest("main") };
      });
      if (!r) continue;
      if (r.inMain) reachedMain = true;
      if (!r.visible) problems.push(`${route}: no visible focus on <${r.tag}> "${r.name}"`);
    }
    const hasInteractive = await page.evaluate(() => !!document.querySelector("main a[href], main button, main input, main select, main [tabindex='0']"));
    if (hasInteractive && !reachedMain) problems.push(`${route}: Tab never reached the page content`);
  }
  expect(problems, problems.join("\n")).toEqual([]);
});

test.describe("reduced motion", () => {
  test.use({ contextOptions: { reducedMotion: "reduce" } });
  test("skips the intro and stops the alert pulses", async ({ page }) => {
    const errors: string[] = [];
    page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
    await page.goto("/");
    await expect(page).toHaveURL(/\/command$/);
    await expect(page.getByRole("status", { name: "Margin Mind is loading" })).toHaveCount(0);
    await page.goto("/neural");
    await page.waitForTimeout(4000);
    const anim = await page.evaluate(() => [...document.querySelectorAll(".neuron-alert")].map((e) => getComputedStyle(e).animationName));
    expect(anim.length).toBeGreaterThan(0);
    expect(anim.every((a) => a === "none")).toBe(true);
    expect(errors).toEqual([]);
  });
});
