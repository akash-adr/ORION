import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

const ROUTES = ["/pitch", "/command", "/neural", "/diagnosis", "/performance", "/performance?tab=campaigns", "/performance?tab=products", "/data", "/simulator", "/opportunities", "/learning"];
// the walkthrough dims the parts a step is not about on purpose (inactive, de-emphasised); those are excluded from the contrast scan
const WALK = ["/pitch?step=0", "/pitch?step=1", "/pitch?step=3", "/pitch?step=6", "/pitch?step=7", "/pitch?step=8"];

async function settle(page: Page) {
  await page.addInitScript(() => sessionStorage.setItem("mm-intro-shown", "1"));
}

for (const theme of ["dark", "light"] as const) {
  test(`accessibility, ${theme} theme: no WCAG A or AA violations`, async ({ page }) => {
    await settle(page);
    const found: string[] = [];
    for (const route of [...ROUTES, ...WALK]) {
      await page.goto(route);
      await expect(page.locator("main h1")).toBeVisible();
      await page.waitForTimeout(route.includes("step=") ? 5000 : 3500); // let the data and charts load
      if (theme === "light") await page.getByRole("button", { name: /Light theme/ }).click();
      await page.waitForTimeout(400);
      const axe = new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]);
      const r = await (route.includes("step=") ? axe.exclude("[data-dim]") : axe).analyze();
      for (const v of r.violations) found.push(`${route} [${v.impact}] ${v.id}: ${v.help} (${v.nodes.length} nodes) e.g. ${v.nodes[0]?.target?.join(" ")}`);
    }
    expect(found, found.join("\n")).toEqual([]);
  });
}
