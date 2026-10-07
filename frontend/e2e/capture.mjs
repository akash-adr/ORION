// Captures every page at 1440 and 900 wide, in both themes, into e2e/screenshots/review/.
//   node e2e/capture.mjs   (frontend on :3100, backend on :8000)
import { chromium } from "@playwright/test";

const BASE = process.env.E2E_BASE ?? "http://localhost:3100";
const PAGES = [
  ["command", "/command"], ["neural", "/neural"], ["neural-focus", "/neural?focus=CMP-01"], ["diagnosis", "/diagnosis?anomaly=AN-004"], ["diagnosis-causal", "/diagnosis?anomaly=AN-006"],
  ["performance-channels", "/performance?tab=channels"], ["performance-campaigns", "/performance?tab=campaigns"], ["performance-products", "/performance?tab=products"],
  ["data", "/data"], ["simulator", "/simulator"], ["opportunities", "/opportunities"], ["learning", "/learning"],
];
const browser = await chromium.launch({ channel: "chrome", args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"] });
for (const width of [1440, 900]) {
  for (const theme of ["dark", "light"]) {
    const ctx = await browser.newContext({ viewport: { width, height: 900 } });
    const page = await ctx.newPage();
    await page.addInitScript(() => sessionStorage.setItem("mm-intro-shown", "1"));
    for (const [name, path] of PAGES) {
      await page.goto(BASE + path);
      await page.waitForTimeout(name.startsWith("neural") ? 9000 : 3500);
      if (theme === "light") await page.getByRole("button", { name: /Light theme/ }).click();
      await page.waitForTimeout(500);
      await page.screenshot({ path: `e2e/screenshots/review/${name}-${width}-${theme}.png` });
    }
    await ctx.close();
  }
}
await browser.close();
console.log("done");
