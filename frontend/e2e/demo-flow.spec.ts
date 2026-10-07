import { expect, test, type Locator, type Page } from "@playwright/test";
import { inr, inrDay, pct, ratio } from "../lib/format";

const API = process.env.E2E_API ?? "http://localhost:8000";
const SHOTS = "e2e/screenshots";
let n = 0;
const shot = (page: Page, name: string) => page.screenshot({ path: `${SHOTS}/${String(++n).padStart(2, "0")}-${name}.png`, fullPage: false });

test.describe.configure({ mode: "serial" });

test("the whole demo, mouse only, with no console errors", async ({ page, request }) => {
  const errors: string[] = [];
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  page.on("pageerror", (e) => errors.push(String(e)));

  const reset = await request.post(`${API}/demo/reset`);
  expect((await reset.json()).ok).toBe(true);
  const get = async <T>(path: string): Promise<T> => (await request.get(`${API}${path}`)).json();

  const rail = (name: string): Locator => page.getByRole("navigation", { name: "Main" }).getByRole("link", { name, exact: true });
  const row = (text: string): Locator => page.locator("li").filter({ hasText: text }).filter({ has: page.locator('button[aria-controls^="trace-"]') }).first();

  await test.step("a. intro, skip, command", async () => {
    await page.goto("/");
    await expect(page.getByRole("status", { name: "Profit Pilot is loading" })).toBeVisible();
    await shot(page, "intro");
    await page.mouse.click(700, 450); // any click skips
    await expect(page.getByRole("status", { name: "Profit Pilot is loading" })).toBeHidden({ timeout: 15_000 });
    await expect(page).toHaveURL(/\/command$/);
    await expect(page.getByRole("heading", { name: "Command", level: 1 })).toBeVisible();
  });

  await test.step("b. the P&L strip equals /kpis", async () => {
    const k = await get<{ profit: { value: number }; poas: { value: number }; spend: { value: number }; revenue: { value: number }; roas_true: { value: number }; roas_platform: { value: number }; data_trust: number }>("/kpis");
    const strip = page.locator('section[aria-label^="P&L"]');
    await expect(strip).toBeVisible();
    for (const want of [inr(k.profit.value), ratio(k.poas.value), inr(k.spend.value), inr(k.revenue.value), pct(k.data_trust)]) await expect(strip).toContainText(want);
    await shot(page, "command-strip");
  });

  await test.step("c. the ad spend cell shows verified against claimed ROAS", async () => {
    const k = await get<{ roas_true: { value: number }; roas_platform: { value: number } }>("/kpis");
    const strip = page.locator('section[aria-label^="P&L"]');
    await expect(strip).toContainText(`Store-verified ROAS ${ratio(k.roas_true.value)}`);
    await expect(strip).toContainText(`platforms claim ${ratio(k.roas_platform.value)}`);
  });

  await test.step("d. Protect stock: trace, diagnosis, stock chart with the guard line", async () => {
    const r = row("Protect stock");
    await r.locator('button[aria-controls^="trace-"]').click();
    await expect(r.locator('ol[aria-label^="Decision trace"] > li')).toHaveCount(7);
    await r.locator('ol[aria-label^="Decision trace"]').scrollIntoViewIfNeeded();
    await shot(page, "decision-trace");
    await r.getByRole("link", { name: "Open diagnosis" }).click();
    await expect(page).toHaveURL(/\/diagnosis\?anomaly=AN-/);
    await expect(page.getByRole("heading", { name: "Days of stock left" })).toBeVisible();
    await expect(page.locator("svg text", { hasText: /^Guard: \d+ days$/ })).toBeVisible();
    await page.getByRole("heading", { name: "Days of stock left" }).scrollIntoViewIfNeeded();
    await shot(page, "diagnosis-stockout-guard");
  });

  await test.step("e. back, approve, handled row with an outcome", async () => {
    await page.goBack();
    await expect(page).toHaveURL(/\/command$/);
    const r = row("Protect stock");
    await r.getByRole("button", { name: "Approve" }).click();
    await expect(page.getByRole("region", { name: "Notifications" }).getByText(/Approved/)).toBeVisible();
    await shot(page, "approved-toast");
    await page.getByRole("button", { name: /^Handled/ }).click();
    const handled = page.locator("li").filter({ hasText: "Protect stock" }).filter({ hasText: "Approved and sent" }).first();
    await expect(handled).toBeVisible();
    // going back restores the page as it was, so the row may already be open: open it only if it is not
    const header = handled.locator('button[aria-controls^="trace-"]');
    if ((await header.getAttribute("aria-expanded")) !== "true") await header.click();
    await expect(handled.locator('ol[aria-label^="Decision trace"] > li').nth(6)).toContainText(/Predicted .* actual/);
    await handled.scrollIntoViewIfNeeded();
    await shot(page, "handled-with-outcome");
  });

  await test.step("f. diagnosis: CPC spike's biggest bar is auction cost; Casual X has a causal chart", async () => {
    await rail("Diagnosis").click();
    await page.locator('nav[aria-label="Anomalies"] button', { hasText: "CPC spike" }).click();
    const d = await get<{ root_cause: { factors: { name: string; impact: number }[] } }>("/anomalies/AN-004/diagnosis");
    const biggest = [...d.root_cause.factors].sort((a, b) => Math.abs(b.impact) - Math.abs(a.impact))[0];
    expect(biggest.name).toBe("Auction cost (CPM/CPC)");
    await expect(page.locator(`svg[role="img"][aria-label*="${biggest.name} ${inrDay(biggest.impact)}"]`)).toBeVisible();
    await shot(page, "diagnosis-cpc-spike");
    await page.locator('nav[aria-label="Anomalies"] button', { hasText: "Casual X" }).click();
    await expect(page.getByRole("heading", { name: "Did the change cause it?" })).toBeVisible();
    await page.getByRole("heading", { name: "Did the change cause it?" }).scrollIntoViewIfNeeded();
    await shot(page, "diagnosis-casual-x-causal");
  });

  await test.step("g. performance: Running Pro is at risk", async () => {
    await rail("Performance").click();
    await page.getByRole("tab", { name: "Products" }).click();
    const r = page.locator("tbody tr").filter({ hasText: "Running Pro" }).first();
    await expect(r).toContainText("At risk");
    await expect(r).toContainText("5.0 days");
    await shot(page, "performance-products");
  });

  await test.step("h. data truth: Meta and Google over-report", async () => {
    await rail("Data truth").click();
    const meta = page.locator("tbody tr").filter({ hasText: "Meta Ads" }).first();
    const google = page.locator("tbody tr").filter({ hasText: "Google Ads" }).first();
    await expect(meta).toContainText("Needs attention");
    await expect(meta).toContainText(/22%/);
    await expect(google).toContainText("Needs attention");
    await expect(google).toContainText(/15%/);
    await expect(page.locator("tbody tr").filter({ hasText: "Reconciliation gap" })).toContainText("Warning");
    await shot(page, "data-truth");
  });

  await test.step("i. simulator: max profit is positive; Google at 120% is negative", async () => {
    await rail("Simulator").click();
    const optimizer = page.locator("section").filter({ has: page.getByRole("heading", { name: "Optimizer", exact: true }) });
    await expect(optimizer.locator(".t-hero")).toContainText(/^↑/);
    const slider = page.locator("#sl-google");
    const box = (await slider.boundingBox())!;
    await page.mouse.click(box.x + box.width * 0.6, box.y + box.height / 2); // 60% of 0–200 is 120%
    await expect(slider).toHaveAttribute("aria-valuetext", /^1[12]\d%/);
    const whatIf = page.locator("section").filter({ has: page.getByRole("heading", { name: "What if", exact: true }) });
    await expect(whatIf.locator(".t-hero")).toContainText(/^↓/);
    await shot(page, "simulator");
  });

  await test.step("j. opportunities: Trail Max on Google is first", async () => {
    await rail("Opportunities").click();
    const first = page.locator("tbody tr").first();
    await expect(first).toContainText("Trail Max");
    await expect(first).toContainText("Google");
    await shot(page, "opportunities");
  });

  await test.step("k. learning: the outcome and the audit API calls", async () => {
    await rail("Learning & audit").click();
    const outcomes = page.locator("section").filter({ has: page.getByRole("heading", { name: "Predicted against actual" }) });
    await expect(outcomes).toContainText("Protect stock");
    const audit = page.locator("section").filter({ has: page.getByRole("heading", { name: "Audit log" }) });
    await expect(audit.locator("tbody tr").first()).toContainText("Executed");
    await audit.getByRole("button", { name: "Show API calls" }).first().click();
    await expect(audit.locator("ul.font-mono").first()).toContainText("POST");
    await audit.scrollIntoViewIfNeeded();
    await shot(page, "learning-audit");
  });

  await test.step("l. ask: creative fatigue, with the CMP-01 chip", async () => {
    await page.getByRole("textbox", { name: "Ask the engine" }).click();
    await page.getByRole("button", { name: "Why did Summer Sneakers drop?" }).click();
    await expect(page.getByText(/Creative fatigue/).first()).toBeVisible();
    await expect(page.locator('[data-highlight="CMP-01"]')).toBeVisible();
    await shot(page, "ask-answer");
  });

  await test.step("m. neural view: replay fills the feed; CMP-01 opens a drawer with a waterfall", async () => {
    await rail("Neural view").click();
    await expect(page.getByRole("heading", { name: "Neural view", level: 1 })).toBeVisible();
    await page.locator("main").getByRole("button", { name: /Replay the last 7 days/ }).click();
    const feed = page.locator('ol[aria-label="Recent engine events"] > li');
    await expect.poll(() => feed.count(), { timeout: 90_000 }).toBeGreaterThanOrEqual(5);
    await shot(page, "neural-replay");
    await page.locator('g[role="button"][aria-label^="Meta · Summer Sneakers · broad"]').click({ force: true });
    const drawer = page.getByRole("complementary", { name: "Campaign details" });
    await expect(drawer).toBeVisible();
    await expect(drawer.locator('svg[role="img"]').first()).toBeVisible();
    await expect(drawer).toContainText("What moved profit");
    await shot(page, "neural-drawer");
  });

  expect(errors, `console errors:\n${errors.join("\n")}`).toEqual([]);
});

test.afterAll(async ({ request }) => {
  await request.post(`${API}/demo/reset`);
});
