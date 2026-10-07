import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

const ROUTES = ["/pitch", "/command", "/neural", "/diagnosis", "/performance", "/performance?tab=campaigns", "/performance?tab=products", "/data", "/simulator", "/opportunities", "/learning"];

async function settle(page: Page) {
  await page.addInitScript(() => sessionStorage.setItem("mm-intro-shown", "1"));
}

for (const theme of ["dark", "light"] as const) {
  test(`accessibility, ${theme} theme: no WCAG A or AA violations`, async ({ page }) => {
    await settle(page);
    const found: string[] = [];
    for (const route of ROUTES) {
      await page.goto(route);
      await expect(page.locator("main h1")).toBeVisible();
      await page.waitForTimeout(3500); // let the data and charts load
      if (theme === "light") await page.getByRole("button", { name: /Light theme/ }).click();
      await page.waitForTimeout(400);
      const r = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
      for (const v of r.violations) found.push(`${route} [${v.impact}] ${v.id}: ${v.help} (${v.nodes.length} nodes) e.g. ${v.nodes[0]?.target?.join(" ")}`);
    }
    expect(found, found.join("\n")).toEqual([]);
  });
}
