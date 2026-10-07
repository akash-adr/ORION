import { expect, test, type Page } from "@playwright/test";
import { inr, inrDay, num, pct, ratio } from "../lib/format";

const API = process.env.E2E_API ?? "http://localhost:8000";
const SHOTS = "e2e/screenshots/pitch";

test.describe.configure({ mode: "serial" });

test("the pitch page and its guided walkthrough, with no console errors", async ({ page, request }) => {
  test.setTimeout(420_000);
  const errors: string[] = [];
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.addInitScript(() => sessionStorage.setItem("mm-intro-shown", "1"));

  expect((await (await request.post(`${API}/demo/reset`)).json()).ok).toBe(true);
  const get = async <T>(path: string): Promise<T> => (await request.get(`${API}${path}`)).json();

  const caption = page.locator('[data-pitch="caption"]');
  const counter = page.locator('[data-pitch="step-counter"]');
  const body = page.locator('[data-pitch="caption-body"]');
  const headline = page.locator('[data-pitch="caption-headline"]');
  const opacity = (key: string) => page.locator(`[data-pitch="${key}"]`).evaluate((el) => Number(getComputedStyle(el).opacity));
  const shot = (name: string) => page.screenshot({ path: `${SHOTS}/${name}.png` });
  const start = async (p: Page) => {
    await p.getByRole("button", { name: /walkthrough/i }).first().click();
    await p.keyboard.press("p"); // pause the autoplay so the keyboard drives it
    await expect(counter).toHaveText("1 of 9");
  };

  type K = { profit: { value: number }; poas: { value: number }; data_trust: number };
  type Snap = { headline: { planned_profit: number; detection_quality: { found: number; expected: number }; calibration: { factor: number } }; ghosts: { id: string }[] };
  type LearningT = { outcomes: { predicted: number; actual: number | null; measured_at: string }[] };
  const [kpis, snap, sources, recon, anomalies, opps, recs] = await Promise.all([
    get<K>("/kpis"),
    get<Snap>("/brain/snapshot"),
    get<{ source_id: string }[]>("/sources"),
    get<{ channel: string; inflation_pct: number; trust_score: number }[]>("/reconciliation"),
    get<{ id: string; kind: string; profit_impact: number }[]>("/anomalies"),
    get<{ opportunities: { sku_name: string; predicted_poas: number }[]; model_r2_holdout: number }>("/opportunities"),
    get<{ pending: { id: string; title: string; priority: number; expected_profit_delta: number; confidence: number }[] }>("/recommendations"),
  ]);

  await test.step("open /pitch: the headline equals the API", async () => {
    await page.goto("/pitch");
    await expect(page.getByRole("heading", { name: "How Margin Mind thinks", level: 1 })).toBeVisible();
    const head = page.locator("main header");
    for (const want of [inr(kpis.profit.value), inr(snap.headline.planned_profit), pct(kpis.data_trust), `${snap.headline.detection_quality.found} of ${snap.headline.detection_quality.expected}`, `×${snap.headline.calibration.factor.toFixed(2)}`]) {
      await expect(head).toContainText(want);
    }
    await page.waitForTimeout(3000); // let the brain and connector lines settle
    await shot("01-pitch");
  });

  await test.step("hover the Meta source: Perception and its line highlight", async () => {
    await page.locator('[data-pitch="source:meta_ads"]').hover();
    await expect.poll(() => opacity("callout:reasoning")).toBeLessThan(0.7);
    expect(await opacity("callout:perception")).toBe(1);
    await expect(page.locator('path[data-line="src-meta_ads"]')).toHaveAttribute("data-active", "true");
    await expect(page.locator('path[data-line="br-perception"]')).toHaveAttribute("data-active", "true");
    await page.mouse.move(700, 880);
  });

  await test.step("click Reasoning: focus mode and a detail sheet; Esc exits", async () => {
    await page.locator('[data-pitch="callout:reasoning"]').click();
    const sheet = page.getByRole("complementary", { name: "Reasoning details" });
    await expect(sheet).toBeVisible();
    await expect(sheet).toContainText(`${anomalies.length}`);
    await page.keyboard.press("Escape");
    await expect(sheet).toBeHidden();
  });

  await test.step("start the walkthrough and step through all nine with the keyboard", async () => {
    await start(page);
    // 0 overview
    await expect(headline).toHaveText("Margin Mind runs your ad spend like a brain.");
    await expect(body).toContainText(inr(kpis.profit.value));
    await expect(body).toContainText(ratio(kpis.poas.value));
    await shot("step-0");

    // 1 perception
    await page.keyboard.press("ArrowRight");
    await expect(counter).toHaveText("2 of 9");
    await expect(body).toContainText(`${sources.length} sources are live`);
    const meta = recon.find((r) => r.channel === "meta")!;
    await expect(body).toContainText(`${pct(meta.inflation_pct)} more than the store verified`);
    await expect(body).toContainText(`Data trust is ${pct(kpis.data_trust)}`);
    await shot("step-1");

    // 2 reasoning
    await page.keyboard.press("ArrowRight");
    await expect(body).toContainText(`${anomalies.length} signals`);
    const top = [...anomalies].sort((a, b) => Math.abs(b.profit_impact) - Math.abs(a.profit_impact))[0];
    await expect(body).toContainText(inrDay(top.profit_impact));
    await expect(body).toContainText(`${snap.headline.detection_quality.found} of ${snap.headline.detection_quality.expected} planted problems found`);
    await shot("step-2");

    // 3 why: a waterfall, and the largest factor's share
    await page.keyboard.press("ArrowRight");
    await expect(counter).toHaveText("4 of 9");
    await expect(page.locator('[data-pitch="waterfall"] svg')).toBeVisible();
    const cpc = anomalies.find((a) => a.kind === "cpc_spike");
    if (cpc) {
      const dx = await get<{ root_cause: { total_change: number; factors: { name: string; impact: number; pct: number }[] } }>(`/anomalies/${cpc.id}/diagnosis`);
      const f = [...dx.root_cause.factors].sort((a, b) => Math.abs(b.impact) - Math.abs(a.impact))[0];
      await expect(body).toContainText(`${f.name} explains ${pct(f.pct)}`);
      await expect(body).toContainText(inrDay(dx.root_cause.total_change));
    }
    await shot("step-3");

    // 4 prediction
    await page.keyboard.press("ArrowRight");
    const best = opps.opportunities[0];
    await expect(body).toContainText(best.sku_name);
    await expect(body).toContainText(`predicted POAS ${ratio(best.predicted_poas)}`);
    await expect(body).toContainText(`R² is ${opps.model_r2_holdout.toFixed(2)}`);
    await shot("step-4");

    // 5 decision
    await page.keyboard.press("ArrowRight");
    const topRec = [...recs.pending].sort((a, b) => b.priority - a.priority)[0];
    await expect(body).toContainText(inrDay(topRec.expected_profit_delta));
    await expect(body).toContainText(`${pct(topRec.confidence)} confident`);
    await shot("step-5");

    // 6 action: approve (supervised) → a toast about budget changes
    await page.keyboard.press("ArrowRight");
    await expect(counter).toHaveText("7 of 9");
    await expect(page.locator('[data-pitch="approve"]')).toBeVisible();
    await shot("step-6");
    await page.locator('[data-pitch="approve"]').click();
    await expect(page.getByRole("alertdialog", { name: "Confirm approval" })).toContainText("mock ad-platform API calls");
    await page.getByRole("alertdialog").getByRole("button", { name: "Approve", exact: true }).click();
    await expect(page.getByText(/Approved · \d+ budget changes? sent to ad APIs/)).toBeVisible();
    await expect(headline).toContainText(/Approved: \d+ budget changes? sent/);
    await shot("step-6-approved");

    // 7 memory: an outcome came back (simulated)
    await page.keyboard.press("ArrowRight");
    await expect(counter).toHaveText("8 of 9");
    await expect.poll(async () => {
      const l = await get<LearningT>("/learning");
      const latest = [...l.outcomes].filter((o) => o.actual !== null).sort((a, b) => (a.measured_at < b.measured_at ? 1 : -1))[0];
      return (await body.textContent())?.includes(`predicted ${inrDay(latest.predicted)}, measured ${inrDay(latest.actual)}`) ?? false;
    }).toBe(true);
    await expect(body).toContainText("simulated in this demo");
    await shot("step-7");

    // 8 close
    await page.keyboard.press("ArrowRight");
    await expect(counter).toHaveText("9 of 9");
    await expect(page.locator('[data-pitch="ask-chip"]')).toHaveCount(2);
    await expect(caption).toContainText(`${num(sources.length)} sources`);
    await shot("step-8");

    // back, number keys, notes, exit
    await page.keyboard.press("ArrowLeft");
    await expect(counter).toHaveText("8 of 9");
    await page.keyboard.press("3");
    await expect(counter).toHaveText("3 of 9");
    await page.keyboard.press("n");
    await expect(page.locator('[data-pitch="notes"]')).toBeVisible();
    await page.keyboard.press("n");
    await expect(page.locator('[data-pitch="notes"]')).toBeHidden();
    await page.keyboard.press("Escape");
    await expect(caption).toBeHidden();
  });

  await test.step("autoplay runs at least two steps, then pauses on hover", async () => {
    await page.getByRole("button", { name: /walkthrough/i }).first().click(); // autoplay stays on
    await expect(counter).toHaveText("1 of 9");
    await expect(counter).toHaveText("3 of 9", { timeout: 40_000 });
    await caption.hover();
    await page.waitForTimeout(11_000);
    await expect(counter).toHaveText("3 of 9");
    await page.keyboard.press("Escape");
  });

  await test.step("/pitch?step=4 opens the walkthrough there", async () => {
    await page.goto("/pitch?step=4");
    await expect(counter).toHaveText("5 of 9");
    await expect(body).toContainText(opps.opportunities[0].sku_name);
  });

  await test.step("presenter mode hides the rail and the top bar, and restores them", async () => {
    await page.goto("/pitch");
    const rail = page.getByRole("navigation", { name: "Main" });
    const ask = page.getByPlaceholder(/Ask the engine/);
    await expect(rail).toBeVisible();
    await page.getByRole("button", { name: "Presenter mode" }).click();
    await expect(rail).toBeHidden();
    await expect(ask).toBeHidden();
    await expect(page.getByRole("button", { name: "Ask", exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Exit presenter" }).click();
    await expect(rail).toBeVisible();
    await expect(ask).toBeVisible();
  });

  expect((await (await request.post(`${API}/demo/reset`)).json()).ok).toBe(true);
  expect((await get<{ autonomy: string }>("/settings")).autonomy).toBe("supervised");
  expect(errors, errors.join("\n")).toEqual([]);
});
