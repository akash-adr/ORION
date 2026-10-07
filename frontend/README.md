# Margin Mind: the dashboard

The front end of the DataQuest 3.0 decision engine. Decisions first, proof one click away: every number on every screen comes from the engine's API and is labelled with its period (per day, last 7 days).

![Command](e2e/screenshots/review/command-1440-dark.png)

## Run it

You need the backend on port 8000. Either server serves the same routes and the same JSON:

```bash
# from the repository root
.venv/bin/uvicorn backend.api.main:app --port 8000          # FastAPI, docs at /docs
.venv/bin/python -m backend.api.devserver --port 8000       # the zero-dependency fallback
```

Then the dashboard:

```bash
cd frontend
npm install
npm run dev          # http://localhost:3000   (NEXT_PUBLIC_API_URL defaults to http://localhost:8000)
```

If the engine is not reachable the app shows a banner with a Retry button instead of breaking.

| Command | What it does |
|---|---|
| `npm run dev` | development server |
| `npm run build` then `npx next start -p 3100` | production build (used by the end-to-end tests) |
| `npm run lint` | ESLint, including the React 19 rules |
| `npm test` | 41 unit tests (formatting, names, layout, decision logic, thresholds) |
| `npm run e2e` | the mouse-only demo flow in Chrome against the running backend and `:3100` |
| `npx playwright test -c e2e/playwright.config.ts e2e/a11y.spec.ts` | axe accessibility scan, both themes, every page |
| `npx playwright test -c e2e/playwright.config.ts e2e/pitch.spec.ts` | the Pitch page and its walkthrough, including the approve in step 7 (it resets the demo before and after) |
| `node e2e/capture.mjs` | re-captures every page at 1440 and 900 wide in both themes |
| `node e2e/capture-pitch.mjs` | re-captures `/pitch`, each callout in focus mode, and all nine walkthrough steps at 1920 and 1440, both themes |

After CSS edits to `app/globals.css` restart the dev server; in this setup it does not recompile that file on change.

## Routes and what each screen shows

| Route | What it shows |
|---|---|
| `/pitch` | The engine explained on one screen: live brain, five stage callouts, inputs, actions, the loop, and a guided walkthrough with presenter mode (see below) |
| `/command` | The P&L strip (profit, profit on spend, ad spend with store-verified against claimed ROAS, revenue, stock at risk, data trust), the decision ledger with a 7-step trace per decision, the live Engine map, ranked signals, and the loop timeline |
| `/neural` | The whole engine as a live map: campaigns, products, data sources, untested ideas and the memory between them, with a live pulse feed, a legend, and a details drawer |
| `/diagnosis` | Why a signal happened: brief, waterfall of causes, factor table, evidence charts, causal proof, funnel, and the matching decision |
| `/performance` | Channels, campaigns and products as sortable tables, with response curves and stock cover |
| `/data` | Sources, platform claims against the store, data quality checks, and the engine's thresholds in plain words |
| `/simulator` | What-if sliders per channel, the optimizer per objective, and every response curve |
| `/opportunities` | Untested product, channel and audience combinations, ranked, with a launch-test decision each |
| `/learning` | Forecast error, calibration, predicted against actual, what the brain remembers, and the audit log with rollback |

### Where every factor the engine computes is visible

| The engine computes | Where you see it |
|---|---|
| Ingestion, reconciliation, source trust, data quality | `/data` (all four sections); data trust in the Command strip; source nodes on `/neural` |
| Platform against store-verified ROAS, over-reporting | Command strip; `/performance` Channels; `/data` reconciliation; trust rings on `/neural` |
| Anomaly detection (z-score, minimum change, windows, severity) | Signals on `/command`; `/diagnosis` brief and list; alert pulses on `/neural`; thresholds on `/data` |
| Root cause (7-factor waterfall, factor shares) | `/diagnosis` waterfall and factor table; trace step 2; neural drawer |
| Funnel (GA4 stages and step rates) | `/diagnosis`; `/performance` Products |
| Causal proof (synthetic control, interval, controls) | `/diagnosis` for price-change anomalies; decision trace for price reviews |
| Budget optimizer (objectives, bounds, solver) | `/simulator` optimizer; planned change in `/performance` Campaigns and on `/neural` hover cards |
| Response curves (Hill fit, marginal POAS, saturation, headroom) | `/simulator` curves; `/performance` row detail; trace step 3; headroom halos on `/neural` |
| What-if simulation and stock warnings | `/simulator` what-if |
| Opportunity model (ridge, held-out R², stock factor, test budget) | `/opportunities`; ghost nodes on `/neural` |
| Decision engine (priority, risk, approval tier, blocked) | The ledger on `/command`; compact rows in `/diagnosis`, `/opportunities` and the neural drawer |
| Guardrails (daily cap, stock guard, auto-apply limit, hard block) | Trace step 4; `/data` thresholds; limits listed under the optimizer |
| Confidence (signal strength, curve uncertainty, forecast error) | Trace step 5 |
| Calibration (factor, raw against calibrated impact) | Trace step 6; `/learning` strip |
| Execution, API calls, audit, rollback | Toasts; `/learning` audit log with each API call and Roll back |
| Closed-loop learning (outcomes, forecast error, synapse memory) | `/learning`; line thickness on `/neural` |
| The AI agent (Claude or the rules engine, with traceable numbers) | The Ask bar on every page, with highlights on the map |
| The continuous loop (steps, events, next run) | Loop timeline on `/command`; the status orb in the top bar |

## Pitch walkthrough

`/pitch` tells the engine's story in two to three minutes, using only what the API says right now. Nothing on it is typed in: every caption is built from the live queries, so it changes when the data does.

**How to present**

1. Reset the demo first (`Reset demo` in the left rail, or `POST /demo/reset`), so autonomy is Supervised and the numbers are the planted ones.
2. Open `/pitch`. Press **Presenter mode** (full screen, with the sidebar and top bar hidden on this page only; a small **Ask** button stays in the corner).
3. Press **Start walkthrough**. It starts on step 1 and autoplays (9 seconds a step, 11 for the two with a chart or a button). Autoplay holds while the pointer is over the caption or anything on the page, or a detail sheet is open, and carries on when you move away. With reduced motion it starts paused, with instant camera moves and no pulses.
4. Drive it by hand whenever you like:

| Key | Does |
|---|---|
| `→` or `Space` | next step |
| `←` | back |
| `1`–`9` | jump to a step |
| `P` | play or pause autoplay |
| `N` | speaker notes (two sentences from the live data) |
| `Esc` | close a sheet, then leave the walkthrough, then leave presenter mode |

`/pitch?step=4` opens the walkthrough at step 4 (counting from 0, so the Prediction step), paused.

**What each step shows** (the number in brackets is the step in the URL)

| Step | Caption says | Brain |
|---|---|---|
| 1 Overview (0) | profit per day and profit on spend | the whole brain |
| 2 Perception (1) | sources live, how much Meta and Google claim over the store, data trust | Ingest region, the platform sources |
| 3 Reasoning (2) | signals, the biggest one and the biggest riser, planted problems found | alerting neurons ringed one by one |
| 4 Why (3) | the biggest cause as a share of the change, a cost waterfall, and (on wide screens) the price-change causal chart | the anomaly's cluster |
| 5 Prediction (4) | the best untested idea, how many campaigns can grow, the model's held-out R² | the top untested idea |
| 6 Decision (5) | the top decision, its confidence, the stock lock, profit now against planned | Decide region, locked neurons |
| 7 Action (6) | autonomy mode, decisions waiting, decisions automatic, and **Approve top decision** | Decide region |
| 8 Memory (7) | forecast error first against last, calibration, win-rate, the latest outcome (simulated) | Learn region |
| 9 Close (8) | one line per stage, two question chips that go to the Ask bar | the whole brain, the loop strip lit once |

Step 7 only offers **Approve top decision** when autonomy is not Advisory and the top decision is not blocked. It asks for confirmation, runs the normal approve with the mock ad-platform calls, and the caption then says what was sent. Step 8 shows the outcome that came back. **Reset the demo afterwards** so the next run starts from the same state. Starting the walkthrough again forgets the approval, so the captions read the engine's current state.

If a step's own data is missing it shows the nearest fact instead of an error (for example, no causal result: the Why step shows the cost waterfall alone; no cost spike: it explains the biggest loss).

## Design principles

The full contract is [DESIGN.md](DESIGN.md). In short:

- **A neuro-lab for your P&L.** Calm and clinical; neural activity is the one vivid element. Machine numbers are in Manrope, the engine's own reasoning is in Newsreader.
- **Colour means something.** Gain, loss and risk only, always with an icon or a word. The accent colour is for engine activity and primary actions.
- **Structure over cards.** One P&L strip, ledger rows that expand, real tables.
- **Names are structured**, never dotted strings. Money and ratios go through `lib/format.ts`, which matches the backend's formatter.
- **Motion answers actions.** The only choreographed moment is the intro. Brain pulses play real events only.
- **Both themes pass WCAG AA** (checked with axe on every page), keyboard focus is always visible, and every chart has a written summary.

## The demo script

Reset first (`Reset demo` in the left rail, or `POST /demo/reset`). Say what the screen shows; the numbers come from the live UI.

1. **Intro, then Command.** We are losing money on ads (the profit cell is red), and the platforms over-claim ROAS (the ad spend cell shows store-verified against claimed).
2. **Engine map.** The brain already shows Running Pro locked by the stock guard and Summer Sneakers fading.
3. **Top decision.** Expand the trace: signal, cause, plan, guardrails, confidence. Approve. Open the audit to see the API calls and the measured outcome.
4. **Diagnosis.** The Google CPC spike (auction cost is the biggest bar); the Casual X price change and its causal proof.
5. **Neural view.** Replay the last 7 days. Click the Trail Max ghost and launch the test.
6. **Simulator.** Max profit, before and after. Move Google to 120% and watch profit fall.
7. **Data truth.** Store-verified against claimed ROAS; the guardrails panel.
8. **Learning.** Forecast error falling; the audit log with a rollback.
9. **Ask.** "Why did Summer Sneakers drop?" and follow the highlight to the map.

## Screenshots

Captured by `node e2e/capture.mjs` into `e2e/screenshots/review/` (`<page>-<width>-<theme>.png`, widths 1440 and 900), and by the end-to-end test into `e2e/screenshots/` (one per demo step).

| Neural view | Decision trace |
|---|---|
| ![Neural view](e2e/screenshots/review/neural-1440-dark.png) | ![Decision trace](e2e/screenshots/03-decision-trace.png) |
| ![Diagnosis](e2e/screenshots/review/diagnosis-1440-dark.png) | ![Simulator](e2e/screenshots/review/simulator-1440-light.png) |

## Architecture notes

- `lib/api.ts` is the only code that talks to the engine; `lib/queries.ts` wraps it in TanStack Query hooks and `invalidateAfterAction` refreshes every view an action can change.
- `lib/brain/` is the shared brain engine: a deterministic layout, an event store, and a player that polls `/brain/events` every 2 s into a queue and plays one event at a time. The compact Engine map and the full neural view both use it.
- Charts are plain SVG in `components/charts/`. The brain is a WebGL dot cloud with SVG items on top, so hover, focus and click stay crisp and accessible. Without WebGL (or below 768px) the same items draw on a flat map.
- Query results report "pending" until the page has hydrated, so server-rendered skeletons always match the first client render.

## What the API does not expose

Reported while building the screens (the backend was not changed): a reason for a blocked decision; the weights of the synthetic control; per-fold R² of the opportunity model; product price and units per day (only for products with an open diagnosis); paid against organic orders; a daily history per campaign; the confidence level of the causal interval (95% is assumed from the method).
