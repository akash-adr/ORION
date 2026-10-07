// node e2e/capture-pitch.mjs  → e2e/screenshots/pitch/ (needs backend :8000 and the app on :3100)
// pitch-<w>-<theme>.png, focus-<callout>-…, and step-<0..8>-<w>-<theme>.png
import { chromium } from "playwright-core";
const BASE = process.env.BASE ?? "http://localhost:3100";
const b = await chromium.launch({ channel: "chrome", args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"] });
for (const [w, h] of [[1920, 1080], [1440, 900]]) {
  for (const theme of ["dark", "light"]) {
    const p = await (await b.newContext({ viewport: { width: w, height: h } })).newPage();
    await p.addInitScript(() => sessionStorage.setItem("mm-intro-shown", "1"));
    await p.goto(`${BASE}/pitch`);
    await p.waitForTimeout(7000);
    if (theme === "light") await p.getByRole("button", { name: /Light theme/ }).click();
    await p.waitForTimeout(500);
    await p.screenshot({ path: `e2e/screenshots/pitch/pitch-${w}-${theme}.png` });
    if (w === 1440) {
      for (const id of ["perception", "reasoning", "prediction", "decision", "memory"]) {
        await p.locator(`[data-pitch="callout:${id}"]`).click();
        await p.waitForTimeout(1200);
        await p.screenshot({ path: `e2e/screenshots/pitch/focus-${id}-${w}-${theme}.png` });
        await p.keyboard.press("Escape");
        await p.waitForTimeout(700);
      }
    }
    // every walkthrough step, by deep link
    for (let n = 0; n < 9; n++) {
      await p.goto(`${BASE}/pitch?step=${n}`);
      await p.waitForTimeout(5500);
      if (theme === "light") await p.getByRole("button", { name: /Light theme/ }).click();
      await p.waitForTimeout(400);
      await p.screenshot({ path: `e2e/screenshots/pitch/step-${n}-${w}-${theme}.png` });
    }
    await p.context().close();
  }
}
await b.close();
