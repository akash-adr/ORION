# Autonomous D2C Advertising Decision Engine (DataQuest 3.0)

The project is built around a **Neural Brain**: a live 3D visual where campaigns and SKUs are neurons and every engine event (ingest, anomaly, diagnosis, recommendation, approval, outcome) fires a pulse through brain regions.

---

## 1. What M0 is

M0 (Shared Contract) is the single source of truth for names, units, formulas, thresholds, data shapes, storage and API contracts. It lives in `backend/core/` and every other module (M1–M10) imports from it instead of re-defining anything: thresholds come from `config.py`, formulas from `metrics.py`, data shapes from `schema.py`, and storage plus the brain event log from `db.py`. M0 contains no data generation, detection logic, server or UI.

> **Pitch line:** "We designed a strict data contract first, so every metric — POAS, true ROAS, days of cover — means exactly the same thing in every part of the system. That's why our numbers always add up."

```
backend/core/
├── config.py      # every setting, threshold, vocabulary, ID format, brain mapping
├── schema.py      # dataclasses passed between modules + to_dict + make_brain_event
├── metrics.py     # one definition of every formula
├── db.py          # SQLite helpers, table contract, state.json, brain event log
└── smoke_test.py  # python -m backend.core.smoke_test
```

## 2. How to run

All commands run from the project root and always use `python -m ...` (never run files directly).

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m backend.core.smoke_test      # prints "M0 OK ..."
python -m pytest -q                    # M0 contract tests
rm -f data/state.json                  # reset the demo (or: python -c "from backend.core.db import reset_state; reset_state()")
```

The existing FastAPI scaffold in `backend/app/` keeps its own venv and tests (`cd backend && ./.venv/bin/pytest`).

## 3. Metric formulas (`backend/core/metrics.py`)

All functions accept floats **or** pandas Series. Division by zero → `None` (float) / `NaN` (Series), never `inf`.

| Function | Formula | Unit |
|---|---|---|
| `safe_div(a, b)` | a / b, b = 0 → None/NaN | ratio |
| `ctr(clicks, impressions)` | clicks / impressions | fraction |
| `cpm(spend, impressions)` | spend / impressions × 1000 | ₹ per 1,000 impressions |
| `cpc(spend, clicks)` | spend / clicks | ₹ per click |
| `cvr(orders, clicks)` | **store** orders / clicks | fraction |
| `true_revenue(orders, price)` | orders × price | ₹ (per day if daily inputs) |
| `gross_margin(orders, price, cogs)` | orders × (price − cogs) | ₹ |
| `contribution_profit(gross_margin, spend)` | gross_margin − spend | ₹ |
| `roas_platform(platform_revenue, spend)` | platform_revenue / spend | ₹ per ₹ (inflated) |
| `roas_true(store_revenue, spend)` | store_revenue / spend | ₹ per ₹ |
| `poas(gross_margin, spend)` | gross_margin / spend | ₹ margin per ₹ spend |
| `inflation_pct(platform_conversions, store_orders)` | platform_conversions / store_orders − 1 | fraction |
| `trust_score(inflation)` | clip(1 − 2 × max(inflation, 0), 0, 1) | score 0–1 |
| `days_cover(on_hand, units_7d_avg)` | on_hand / units_7d_avg | days |
| `site_cvr(purchases, sessions)` | purchases / sessions | fraction |
| `change_pct(recent, baseline)` | recent / baseline − 1 | fraction |
| `neuron_health(poas)` | ≥ 1.2 good · ≥ 0.8 weak · else losing · None → weak | label |
| `severity_from_impact(profit_impact)` | loss > 25k high · > 8k medium · else low; gains → low | label |
| `neuron_size(spend, min_spend, max_spend)` | linear 0.6 → 2.0 (min = max → 1.3) | relative size |
| `format_inr(value)` | ₹1.20Cr · ₹1.23L · ₹12.3k · ₹850 · -₹12.3k · None → — | display string |

## 4. Thresholds and guardrails (`backend/core/config.py`)

| Constant | Value | Reasoning |
|---|---|---|
| `RECENT_DAYS` | 7 | One full weekly cycle, removes day-of-week noise |
| `BASELINE_DAYS` | 21 | Three weeks of "normal" before the recent window: stable but still current |
| `Z_THRESHOLD` | 2.5 | ~1% false-positive rate per metric under normality; keeps the alert list short |
| `MIN_PCT_CHANGE` | 0.15 | Ignores statistically significant but commercially tiny moves |
| `STOCK_COVER_RISK_DAYS` | 7 | Typical D2C replenishment lead time; below this, ad spend accelerates a stockout |
| `SEVERITY_HIGH_IMPACT` | 25000 ₹/day | Loss large enough to need same-day action |
| `SEVERITY_MEDIUM_IMPACT` | 8000 ₹/day | Loss worth a look this week |
| `RISK_HIGH_SHIFT` | 0.40 | Moving > 40% of a budget breaks platform learning phases |
| `RISK_HIGH_IMPACT` | 40000 ₹/day | Bets this large always get a human |
| `CONFIDENCE_MIN` / `CONFIDENCE_MAX` | 0.45 / 0.95 | Never present a coin flip as advice; never claim certainty |
| `AUTO_APPLY_MAX_SHIFT` | 0.10 | Autonomous mode only makes small, reversible moves alone |
| `DAILY_CHANGE_CAP` | 0.50 | No campaign budget changes by more than 50% in a day |
| `POAS_FLOOR` | 0.0 | Never scale a campaign that loses margin |
| `STOCK_SPEND_CAP_MULT` | 0.4 | Low-stock SKUs' campaigns are capped at 40% of current spend; increases blocked |
| `NEURON_POAS_GOOD` / `NEURON_POAS_WEAK` | 1.2 / 0.8 | ≥ 1.2 covers overheads comfortably; < 0.8 is clearly losing |
| `BRAIN_MAX_NEURONS` | 40 | Keeps the 3D brain readable and fast |
| `BRAIN_EVENT_HISTORY_LIMIT` | 500 | Bounds state.json size |

## 5. Unit rules

- **Percentages are fractions**: 0.15 means 15%. Never store 15.
- **Money is float ₹ per day** unless the name says otherwise (`spend_7d`, `profit_7d`, `total_effect` are totals over their window).
- **Signs**: profit impact and deltas are signed; negative = loss.
- **Revenue** means store (true) revenue. Platform-reported revenue is always named `platform_revenue`.
- **Dates** `YYYY-MM-DD`; **timestamps** `YYYY-MM-DDTHH:MM:SS`.
- **UI formatting** happens only at the edge via `format_inr`; never store formatted strings.
- JSON never contains NaN/Infinity: `to_dict` turns them into `null`.

## 6. ID formats

| Object | Pattern | Example |
|---|---|---|
| campaign | `^CMP-\d{2}$` | CMP-01 |
| sku | `^SKU-[A-J]$` | SKU-A |
| creative | `^CR-\d{2}[a-z]$` | CR-01a |
| event | `^EV-\d+$` | EV-2 |
| anomaly | `^AN-\d{3}$` | AN-005 |
| recommendation | `^REC-[0-9a-f]{6}$` | REC-567405 (md5 of title) |
| brain_event | `^BE-\d{5}$` | BE-00001 (assigned by `db.log_brain_event`) |

## 7. Data shapes (`backend/core/schema.py`)

Field names and order are the contract. Fields with defaults come last.

**Anomaly** (M3 → M4, M6, M8, M10)

| Field | Type | Notes |
|---|---|---|
| id | str | AN-001 |
| kind | str | ANOMALY_KINDS |
| entity_type | str | campaign / sku / channel |
| entity_id | str | |
| label | str | |
| metric | str | |
| baseline | float | |
| recent | float | |
| change_pct | float | fraction |
| z | float | |
| profit_impact | float | ₹/day, negative = loss |
| severity | str | low / medium / high |
| detail | dict | default {} |

**Factor**: name: str · impact: float (₹/day) · pct: float (fraction)

**RootCause** (M4 → M6, M8, M10): anomaly_id: str · entity_id: str · total_change: float · factors: list[Factor] = [] · funnel: list[dict] = [] · narrative: str = "" · method `check_sum(tol=1.0)` → bool (factor impacts sum to total_change)

**CausalResult** (M4b → M6, M10): event_id: str · description: str · effect_per_day: float · total_effect: float · ci_low: float · ci_high: float · series: list[dict] = [] (each `{date, actual, counterfactual}`)

**Recommendation** (M6 → M7, M8, M9, M10)

| Field | Type | Notes |
|---|---|---|
| id | str | `Recommendation.make_recommendation_id(title)` |
| title | str | |
| issue | str | |
| cause | str | |
| action | dict | `{"type": ACTION_TYPES, "changes": [{campaign_id, name, channel, from_budget, to_budget}]}` or settings / launch / creative_refresh dicts |
| expected_profit_delta | float | ₹/day |
| confidence | float | 0.45–0.95 |
| risk | str | low / medium / high |
| requires_approval | bool | |
| blocked | bool | guardrail blocked |
| priority | float | |
| evidence | list[str] | default [] |
| anomaly_id | str \| None | default None |
| status | str | default "pending"; DECISION_STATUSES |

**Opportunity** (M5b → M6, M10): sku_id · channel · audience · predicted_conv_per_1k · predicted_poas · unit_margin · stock_days · score · test_budget

**NeuronNode** (M9 → M10)

| Field | Type | Notes |
|---|---|---|
| entity_id | str | CMP-01 / SKU-A |
| entity_type | str | campaign / sku |
| label | str | |
| cluster | str | channel for campaigns, "catalog" for SKUs |
| channel | str \| None | |
| sku_id | str \| None | |
| spend_7d | float | ₹ total |
| poas_7d | float \| None | |
| profit_7d | float | ₹ total |
| change_pct | float \| None | fraction |
| health | str | `metrics.neuron_health(poas_7d)` |
| size | float | `metrics.neuron_size(spend_7d, ...)` |
| is_alerting | bool | default False; open anomaly references this entity |
| anomaly_id | str \| None | default None |

**BrainEvent** (every module → state.json → M9 → M10): id: str · ts: str · type: str · region: str · path: list[str] · entity_id: str \| None · ref_id: str \| None · severity: str · message: str · payload: dict = {}. Build with `make_brain_event(type, entity_id=None, ref_id=None, severity="low", message="", payload=None, event_id=None, ts=None)`, which fills region, path and ts and raises `ValueError` for unknown types.

**BrainState** (M9 → M10): mode: str · active_region: str \| None · last_event_id: str \| None · counts: dict = {} (e.g. `{"anomalies": 3, "pending_decisions": 2, "outcomes": 5}`)

**`to_dict(obj)`** converts any of the above (nested) into JSON-safe Python: NaN/±inf → null, numpy → Python, timestamps → ISO strings, DataFrame → records, Series → list.

## 8. Storage contract (`backend/core/db.py`)

SQLite at `data/engine.db`: `connect`, `write_table(df, name)` (replace), `read_table(name)` (clear error if missing), `query(sql, params)`, `table_exists`, `list_tables`, `drop_table`, `validate_table(df, name)`.

| Table | Grain | Required columns |
|---|---|---|
| fact_daily | campaign × day | date, channel, campaign_id, sku_id, audience, creative_id, spend, impressions, clicks, frequency, platform_conversions, platform_revenue, orders, price, cogs, revenue, gross_margin, profit, ctr, cpc, cpm, cvr, roas_platform, roas_true, poas, campaign_name, format |
| sku_daily | product × day | date, sku_id, orders_paid, orders_organic, unit_price, units, revenue, on_hand, inbound, sessions, pdp_views, add_to_cart, checkout, purchases, name, cogs, margin_pct, units_7d, days_cover |
| reconciliation | channel | channel, platform_conversions, store_orders, platform_revenue, true_revenue, spend, inflation_pct, roas_platform, roas_true, trust_score, last_synced |
| feature_store | campaign | campaign_id, channel, sku_id, audience, spend_7d, spend_28d, poas_7d, poas_28d, ctr_7d, cvr_7d, cpm_7d, freq_7d, profit_7d |
| dim_sku | sku | sku_id, name, category, price, cogs, rating, organic_per_day, margin_pct |
| dim_campaign | campaign | campaign_id, channel, sku_id, audience, daily_budget, sat_mult, format, campaign_name |
| dim_creative | creative | creative_id, campaign_id, format, hook, ugc, launch_date |
| events | event | event_id, date, type, entity, description |

**Raw files** (M1 → `data/raw/`): ad_performance.csv, store_orders_by_utm.csv, orders.csv, inventory.csv, pricing.csv, ga_events.csv, sku_master.csv, campaigns.csv, creatives.csv, events.csv, ground_truth.json

**state.json** (`data/state.json`), via `load_state()` (missing/corrupt → defaults; old files gain new keys), `save_state(state)` (atomic temp file + `os.replace`), `reset_state()`:

```json
{
  "decisions": [],
  "audit": [],
  "outcomes": [],
  "budget_overrides": {},
  "autonomy": "supervised",
  "objective": "max_profit",
  "calibration": {"factor": 1.0, "mape": null, "win_rate": null, "n": 0},
  "brain_events": [],
  "brain_event_seq": 0
}
```

**Brain event log**: `log_brain_event(event)` assigns `BE-00001`, `BE-00002`, … and keeps the newest 500; `read_brain_events(since_id=None, limit=100)` returns events after `since_id`, oldest first; `clear_brain_events()` empties the log and resets the sequence.

## 9. API contract (built by M9)

All numbers are plain floats; NaN/Infinity become `null`; CORS open for the demo.

| Method & path | Response |
|---|---|
| `GET /health` | `{ok: true}` |
| `GET /kpis?period=7` | `{spend, revenue, profit, poas, roas_true, roas_platform: {value, change}, stock_at_risk: {value, skus[]}, as_of, last_synced, data_trust}` |
| `GET /trend?days=45` | `[{date, spend, revenue, platform_revenue, profit, poas}]` |
| `GET /channels`, `GET /campaigns` | per-channel / per-campaign summaries |
| `GET /anomalies` | `[Anomaly]` |
| `GET /anomalies/{id}/diagnosis` | `{anomaly, root_cause, evidence: {daily[], causal?}}` |
| `GET /causal/{event_id}` | `CausalResult` |
| `GET /reconciliation` | `[reconciliation rows]` |
| `GET /recommendations?objective=` | `{objective, summary, recommendations: [Recommendation]}` |
| `POST /decisions/{id}/approve \| reject \| rollback` | `{ok, api_calls? \| reason?}` |
| `GET /audit` | `[audit entries, newest first]` |
| `POST /optimize {objective, total_budget?}` | `{objective, plan: {campaign_id: spend}, summary, campaigns[]}` |
| `POST /simulate {plan}`, `POST /simulate/channels {multipliers}` | `{summary: {current, simulated, profit_delta}, campaigns[]}` |
| `GET /curves` | `[{campaign_id, name, current_spend, marginal_poas, points[]}]` |
| `GET /opportunities` | `{model_r2_holdout, opportunities: [Opportunity]}` |
| `GET /learning` | `{outcomes[], accuracy_curve[], calibration: {factor, mape, win_rate, n}}` |
| `GET \| POST /settings {autonomy?, objective?}` | `{autonomy, objective, autonomy_modes, objectives}` |
| `POST /refresh` | `{ok, auto_applied[], outcomes_measured}` |
| `POST /ask {question}` | `{answer, engine}` |
| `GET /brain/nodes` | `{as_of, nodes: [NeuronNode]}` (max `BRAIN_MAX_NEURONS`, sorted by spend_7d desc) |
| `GET /brain/events?since=BE-00012&limit=100` | `{events: [BrainEvent], last_id}` |
| `GET /brain/state` | `BrainState` (mode = `EVENT_MODE` of the most recent event within the last 10 s, else "idle") |
| `POST /brain/replay` | `{ok, events_queued}` (re-emits the demo scenario for "Replay last 7 days") |

## 10. Neural Brain contract

**Regions**: `ingest`, `diagnose`, `decide`, `learn` · **Modes**: `idle`, `ingesting`, `anomaly`, `deciding`, `learning`

| Event type | Region (`EVENT_REGION`) | Pulse path (`PULSE_PATHS`) | UI mode (`EVENT_MODE`) | Emitted by |
|---|---|---|---|---|
| ingest | ingest | ingest | ingesting | M2, after loading data |
| anomaly | diagnose | ingest → diagnose | anomaly | M3, once per anomaly |
| diagnosis | diagnose | diagnose | anomaly | M4, once per root cause |
| recommendation | decide | diagnose → decide | deciding | M6, once per recommendation |
| approval | decide | decide → learn | deciding | approve endpoint |
| rejection | decide | decide | deciding | reject endpoint |
| rollback | decide | learn → decide | deciding | rollback endpoint |
| auto_apply | decide | decide → learn | deciding | auto-apply (autonomous mode) |
| outcome | learn | learn | learning | outcome measurement |

**Neurons**: campaigns and SKUs, at most 40, clustered by channel (campaigns) or `"catalog"` (SKUs). Health: POAS ≥ 1.2 good, 0.8–1.2 weak, < 0.8 losing, unknown → weak. Size scales linearly with 7-day spend from 0.6 to 2.0. `is_alerting` is true while an open anomaly references the entity.

Emitting a pulse is always:

```python
from backend.core.db import log_brain_event
from backend.core.schema import make_brain_event

log_brain_event(make_brain_event("anomaly", entity_id="CMP-01", ref_id="AN-001", severity="high",
                                 message="Creative fatigue · Meta · Summer Sneakers · broad"))
```

## 11. Contract change rules

1. Add, never rename or delete.
2. Announce before editing `config.py` or `schema.py`; one person edits at a time.
3. New fields get defaults so old code keeps working.
4. Run the full test suite after any M0 change.
5. Document threshold changes here with the reason.
6. Units never change.

### Contract changes log

| Date | Change | Why |
|---|---|---|
| 2026-10-07 | Appended `"brain_manifest.json"` to `db.RAW_FILES` (additive, nothing renamed or reordered) | The Neural Brain needs the static structure (sources, neurons, synapses, scenario timeline) written by M1 |
| 2026-10-07 | Appended `RECON_GAP_THRESHOLD = 0.10`, `REFRESH_MINUTES = 5`, `FRESHNESS_WARN_MINUTES = 15` to `config.py` | M2 flags reconciliation gaps (S5); the demo loop and stale-data badge need shared intervals |
| 2026-10-07 | Added `neuron_metrics`, `source_status`, `data_quality` to `db.TABLE_COLUMNS` | The Neural Brain needs live per-neuron numbers and per-stream status; data-quality results must be stored and shown |
| 2026-10-07 | Appended `FATIGUE_FREQ_UP`, `FATIGUE_CTR_DOWN`, `CPC_SPIKE_MIN`, `SKU_RECENT_DAYS`, `SKU_BASELINE_DAYS`, `PROFIT_BASE_FLOOR`, `MAD_SCALE` to `config.py` | M3 detectors need shared, documented thresholds (fatigue, CPC spike, 14/28-day site-conversion windows, robust-z scaling) so no module hard-codes them |
| 2026-10-07 | Added `anomalies`, `brain_alerts` to `db.TABLE_COLUMNS`; added `active_anomalies`, `detection_quality` to `default_state()` (old state files gain them via `load_state`) | M3 persists detection results, maps them onto brain targets (neuron / cluster / source), emits Diagnose pulses only for new or worsening anomalies, and stores the ground-truth evaluation for the "7/7 detected" badge |

## 12. Assumptions

_(Team: add assumptions here as they are made.)_

- **M1 calibration (2026-10-07): `CVR_SCALE = 0.9`.** At 1.0 blended POAS was 1.02 (above the 0.88–0.98 band). Set to 0.9 and re-checked: blended POAS 0.91, every channel's true ROAS within ±20% of target, and the profitable list unchanged (CMP-03, 04, 05, 06, 07, 13, 14), so no further 0.02 steps were needed. Other knobs unchanged: `CH_CVR` meta 1.00, google 1.15, amazon 1.30, tiktok 0.80, programmatic 0.70; `ELASTICITY = -2.5`. Achieved economics are in the Module 1 section below.
- **M2 validation, CMP-02 band:** the M2 spec asked for CMP-02 full-period true ROAS 1.85–1.95, which assumed `CVR_SCALE = 1.0`. After recalibrating to 0.9 it is 1.66, so `backend/ingest/validate.py` uses M1's ±20% band around 1.9 (1.52–2.28) while still requiring POAS < 1.
- **M2 last-7-day headline numbers** (POAS 0.83, true ROAS 2.05, platform ROAS 2.27) sit below the spec's estimates (≈ 0.93 / 2.3 / 2.55) for the same reason, plus S1 fatigue and the S3 Google CPC spike falling in that window. All are within the validation tolerances.
- **M2 `change_pct` sign:** measured against |previous| (still via M0 `change_pct`), so a deepening loss reads as negative. With a plain recent ÷ previous − 1, CMP-01 (−₹43.0k → −₹45.6k/day, a worse loss) would show as +6%.
- **M1 weekly budget tests** use calendar weeks (Monday–Sunday) for the first 55 days; the last 35 days run at budget so detection baselines are clean.

## 13. Common mistakes

- Percentages as `15` instead of `0.15`.
- Mixing ₹ totals (`spend_7d`) with ₹/day values.
- Using platform revenue as revenue (always use store/true revenue).
- Renaming fields mid-hackathon.
- Running files directly (`python backend/core/smoke_test.py`) instead of `python -m backend.core.smoke_test`.
- Committing `data/engine.db` or `data/state.json`.

---

# Module 1 — Data Generator

> **Pitch line:** "We built a realistic Indian D2C world with eight hidden problems and an answer key — so instead of claiming accuracy, we prove it: the engine finds every one."

`backend/generator/generate.py` builds 90 days (2026-07-09 → 2026-10-06) of fully linked data for a fictional Indian footwear brand: 10 SKUs, 16 campaigns, 5 channels. One seeded random generator, fixed iteration order, byte-identical on every run (~0.5 s). It writes only to `data/raw/`; never to `engine.db`, `state.json` or the brain event log.

## How to run

```bash
python -m backend.generator.generate    # writes 12 files into data/raw/
python -m backend.generator.validate    # 15-point PASS/FAIL table, exit 1 on any failure
python -m pytest -q                     # M0 + M1 tests (M1 generates into a temp folder)
```

## The business world

**Products**

| SKU | Name | Category | Price ₹ | COGS ₹ | Margin | Rating | Organic/day | Role |
|---|---|---|---|---|---|---|---|---|
| SKU-A | Summer Sneakers | lifestyle | 2,499 | 2,050 | 0.18 | 4.0 | 12 | low margin, heavily advertised → fatigue |
| SKU-B | Running Pro | running | 3,999 | 2,360 | 0.41 | 4.6 | 18 | best seller → stockout risk |
| SKU-C | Trail Max | running | 4,499 | 2,250 | 0.50 | 4.5 | 6 | high margin, under-funded |
| SKU-D | Casual X | lifestyle | 1,999 | 1,200 | 0.40 | 4.2 | 14 | price hike → conversion drop |
| SKU-E | Kids Glow | kids | 1,499 | 750 | 0.50 | 4.4 | 8 | overstocked |
| SKU-F | Office Loafer | formal | 2,999 | 1,800 | 0.40 | 4.1 | 7 | programmatic loss-maker |
| SKU-G | Slide Comfort | casual | 899 | 450 | 0.50 | 4.0 | 20 | cheap, weak on TikTok |
| SKU-H | Hiking Boot | outdoor | 5,499 | 3,300 | 0.40 | 4.3 | 4 | premium, Amazon |
| SKU-I | Sock Pack | accessories | 499 | 200 | 0.60 | 4.2 | 25 | low-price add-on |
| SKU-J | Gym Flex | training | 2,799 | 1,500 | 0.46 | 4.4 | 9 | viral TikTok creative |

**Channels**

| Channel | CPM ₹ | Base CTR | CVR mult | Platform over-reporting |
|---|---|---|---|---|
| meta | 220 | 0.012 | 1.00 | 1.22 |
| google | 600 | 0.035 | 1.15 | 1.15 |
| amazon | 450 | 0.020 | 1.30 | 1.00 |
| tiktok | 150 | 0.010 | 0.80 | 1.00 |
| programmatic | 110 | 0.004 | 0.70 | 1.00 |

Audience base CVR: broad 0.010 · lookalike 0.014 · interest 0.012 · retargeting 0.028. Price elasticity −2.5.

**Campaigns**

| ID | Channel | SKU | Audience | Budget ₹/day | Sat mult | Format | Full-period POAS |
|---|---|---|---|---|---|---|---|
| CMP-01 | meta | SKU-A | broad | 50,000 | 0.6 | static | 0.15 |
| CMP-02 | google | SKU-A | interest | 25,000 | 1.0 | search_text | 0.30 |
| CMP-03 | meta | SKU-B | lookalike | 40,000 | 1.2 | video | 1.45 |
| CMP-04 | google | SKU-B | interest | 30,000 | 1.2 | search_text | 1.43 |
| CMP-05 | amazon | SKU-B | retargeting | 20,000 | 1.0 | sponsored | 2.62 |
| CMP-06 | google | SKU-C | interest | 8,000 | 4.0 | search_text | 2.69 |
| CMP-07 | meta | SKU-C | lookalike | 6,000 | 4.0 | video | 2.56 |
| CMP-08 | meta | SKU-D | broad | 25,000 | 1.0 | carousel | 0.37 |
| CMP-09 | amazon | SKU-D | interest | 15,000 | 1.0 | sponsored | 0.52 |
| CMP-10 | tiktok | SKU-J | broad | 15,000 | 1.5 | video | 0.90 |
| CMP-11 | tiktok | SKU-G | interest | 10,000 | 1.0 | video | 0.25 |
| CMP-12 | programmatic | SKU-F | broad | 18,000 | 0.8 | display | 0.23 |
| CMP-13 | amazon | SKU-H | interest | 15,000 | 1.0 | sponsored | 1.41 |
| CMP-14 | meta | SKU-E | retargeting | 8,000 | 1.5 | carousel | 1.25 |
| CMP-15 | google | SKU-I | interest | 6,000 | 1.0 | search_text | 0.21 |
| CMP-16 | programmatic | SKU-A | retargeting | 10,000 | 1.0 | display | 0.27 |

## The 8 planted scenarios

T = 90 (day index t = 0..89). Answer key: `data/raw/ground_truth.json`.

| # | Scenario | Exact injection | Must be found by |
|---|---|---|---|
| S1 | Creative fatigue, CMP-01 | t ≥ T−14: k ramps 0→1; frequency = 1.8 + 2.4·k; CTR × (1 − 0.5·k) | M3 |
| S2 | Stockout risk, SKU-B | days of cover 40 until t = 60, then falls linearly to 5; no inbound after t = 60 | M3 (guardrail in M5/M6) |
| S3 | Google CPC spike | t ≥ T−7: CPM × 1.6 on CMP-02, 04, 06, 15 (EV-3) | M3 |
| S4 | Under-funded winner | CMP-06 and CMP-07 saturation = 4 × budget (all days) | M5 |
| S5 | Double counting | platform conversions × 1.22 (Meta), × 1.15 (Google), all days | M2 reconciliation |
| S6 | Price hike, SKU-D | price 1,999 → 2,299 for t ≥ T−14 (EV-2); elasticity −2.5 lowers paid and organic CVR | M3 + M4b |
| S7 | Viral creative, CMP-10 | t ≥ T−7: CTR × 2.2, creative CR-10a → CR-10b UGC (EV-4) | M3 |
| S8 | Untested opportunity | most SKU × channel × audience combinations never funded | M5b |

## How each scenario appears in the Neural Brain

| # | Start | Brain event | Kind / action | Region | Direction | Entities |
|---|---|---|---|---|---|---|
| S1 | 2026-09-23 | anomaly | creative_fatigue | diagnose | loss | CMP-01, SKU-A |
| S2 | 2026-09-07 | anomaly | stockout_risk | diagnose | loss | SKU-B, CMP-03, CMP-04, CMP-05 |
| S3 | 2026-09-30 | anomaly | cpc_spike | diagnose | loss | CMP-02, CMP-04, CMP-06, CMP-15 |
| S4 | 2026-07-09 | recommendation | scale_up | decide | gain | CMP-06, CMP-07, SKU-C |
| S5 | 2026-07-09 | anomaly | attribution_inflation | ingest | loss | all Meta + Google campaigns |
| S6 | 2026-09-23 | anomaly | conversion_drop | diagnose | loss | SKU-D, CMP-08, CMP-09 |
| S7 | 2026-09-30 | anomaly | positive_spike | diagnose | gain | CMP-10, SKU-J |
| S8 | 2026-07-09 | recommendation | launch_test | decide | gain | (none: unfunded combos) |

Replay order (by start date, ties by scenario number): **S4, S5, S8, S2, S1, S6, S3, S7**.

## Brain manifest (`data/raw/brain_manifest.json`)

Static structure only; live numbers (spend, POAS, health, size) come from M9's `/brain/nodes`. Deterministic, dated from `END_DATE`, every enum validated against M0.

| Key | Contents |
|---|---|
| `version`, `seed`, `date_range` | 1, 42, `{start, end, n_days}` |
| `sources` | 9 data-stream nodes: 5 ad platforms (feed `ad_performance.csv`) + store, inventory, ga4, pricing |
| `clusters` | meta, google, amazon, tiktok, programmatic, catalog |
| `neurons` | 26: 16 campaigns (meta 5, google 4, amazon 3, tiktok 2, programmatic 2) + 10 SKUs (catalog), static attributes only |
| `synapses` | 72: 16 ad source → campaign `feeds`, 16 campaign → SKU `promotes`, 40 store/inventory/ga4/pricing → SKU `feeds` |
| `stimuli` | EV-1 sale (gain, all SKUs), EV-2 price raise (loss), EV-3 competitor (loss), EV-4 UGC launch (gain) |
| `scenario_timeline` | S1–S8 as expected brain pulses (table above), with detector module and headline |
| `replay_order` | scenario ids for `/brain/replay` |
| `hero_story` | the 5-step, 30-second demo path (S1 → S1 → S4 → S2 → S4) |

## Achieved economics (calibration)

Knobs: `CVR_SCALE = 0.9` (lowered from 1.0 to bring blended POAS into 0.88–0.98), `CH_CVR` unchanged.

| Metric | Target | Achieved |
|---|---|---|
| Average daily spend | ≈ ₹3.0L | ₹2.93L |
| True ROAS Amazon / Google / Meta / TikTok / Programmatic | 4.5 / 3.1 / 2.1 / 1.5 / 1.0 | 3.89 / 2.77 / 1.97 / 1.37 / 0.90 |
| Platform ROAS Meta / Google | 2.6 / 3.5 | 2.40 / 3.18 |
| Attribution inflation Meta / Google | +22% / +15% | +22.0% / +14.8% |
| Blended POAS | 0.93 (accept 0.88–0.98) | 0.91 |
| Profitable campaigns (POAS > 1) | CMP-03, 04, 05, 06, 07, 13, 14 | exact match |
| CMP-02 ("ROAS lies") | ROAS ≈ 1.9, POAS < 1 | ROAS 1.66, POAS 0.30 |

---

# Module 2 — Ingestion & Reconciliation

> **Pitch line:** "Every ad platform claims the same sale. We reconcile against store orders — Meta over-reports by 22%, Google by 15% — so every decision is made on the truth, not on what platforms say."

M2 is the Neural Brain's **Ingest lobe**. It pulls every source through one connector interface into `data/engine.db`, reconciles platform claims against store orders, computes every metric later modules use, and pulses the brain. Every later module reads **only** these tables, never raw files.

## How to run

```bash
python -m backend.ingest.pipeline                     # build all tables + log 10 ingest brain events
python -m backend.ingest.pipeline --no-brain-events   # same, without touching state.json
python -m backend.ingest.pipeline --as-of 2026-10-06T23:00:00
python -m backend.ingest.validate                     # 16-point PASS/FAIL table (no brain events on the real state)
python -m pytest -q                                   # M0 + M1 + M2 tests (temp folders only)
```

## Architecture

```
 Meta · Google · Amazon · TikTok · Programmatic   Shopify orders + UTM   GA4   ERP inventory   Pricing
          │ AD_CONNECTORS (5)                           │ STORE, UTM        │ GA4   │ ERP         │ PRICING
          └──────────────────────────────┬──────────────┴────────────────────┴───────┴─────────────┘
                                         ▼
                         1. normalise   (ISO dates IST, ₹ floats, int counts, trimmed strings)
                         2. quality 1–4 (completeness · duplicates · negatives · unmapped campaigns)
                                         ▼
                         3. join        ads ⟕ UTM orders ⟕ daily price ⟕ COGS ⟕ campaign  (LEFT joins)
                         4. derive      revenue · gross margin · profit · CTR · CPC · CPM · CVR · ROAS · POAS
                         5. reconcile   platform conversions vs store orders → inflation · trust (per channel)
                         6. SKU/funnel  orders ⟕ inventory ⟕ GA4 → units_7d · days_cover
                         7. vectors     feature_store (7d / 28d per campaign)
                         8. brain       neuron_metrics (26) · source_status (9)
                         9. quality 5–9 (gap · freshness · orders consistency · ±inf · manifest alignment)
                                         ▼
                 validate_table → write_table (replace)  →  11 tables in data/engine.db
                                         ▼
                 10 "ingest" brain events → state.json  (9 data streams + 1 settle pulse)
```

## Connectors (`backend/ingest/connectors.py`)

All connectors share `fetch() -> DataFrame` (normalised), so replacing a CSV with the real API changes nothing downstream.

| Connector | File today | Real API it stands in for | Brain source |
|---|---|---|---|
| meta_ads | ad_performance.csv (meta rows) | Meta Marketing API (Insights) | meta_ads |
| google_ads | ad_performance.csv (google rows) | Google Ads API (GAQL; cost_micros ÷ 1,000,000) | google_ads |
| amazon_ads | ad_performance.csv (amazon rows) | Amazon Ads API (Sponsored Products reports) | amazon_ads |
| tiktok_ads | ad_performance.csv (tiktok rows) | TikTok Marketing API | tiktok_ads |
| programmatic_ads | ad_performance.csv (programmatic rows) | DSP reporting API (e.g. DV360) | programmatic |
| shopify_orders | orders.csv | Shopify Admin API (Orders) | store |
| shopify_utm | store_orders_by_utm.csv | Shopify Admin API (Orders + UTM params) | store |
| erp_inventory | inventory.csv | ERP / Shopify Inventory API | inventory |
| ga4 | ga_events.csv | GA4 Data API | ga4 |
| pricing | pricing.csv | Store catalogue + competitor price feed | pricing |
| sku_master, campaigns, creatives, events | *.csv | Catalogue / ad-account metadata | — |

## Output tables (11)

| Table | Rows | Columns |
|---|---|---|
| fact_daily | 1,440 (campaign × day) | date, channel, campaign_id, sku_id, audience, creative_id, spend, impressions, clicks, frequency, platform_conversions, platform_revenue, orders, price, cogs, revenue, gross_margin, profit, ctr, cpc, cpm, cvr, roas_platform, roas_true, poas, campaign_name, format |
| sku_daily | 900 (SKU × day) | date, sku_id, orders_paid, orders_organic, unit_price, units, revenue, on_hand, inbound, sessions, pdp_views, add_to_cart, checkout, purchases, name, cogs, margin_pct, units_7d, days_cover |
| reconciliation | 5 (channel) | channel, platform_conversions, store_orders, platform_revenue, true_revenue, spend, inflation_pct, roas_platform, roas_true, trust_score, last_synced |
| feature_store | 16 (campaign) | campaign_id, channel, sku_id, audience, spend_7d, spend_28d, poas_7d, poas_28d, ctr_7d, cvr_7d, cpm_7d, freq_7d, profit_7d |
| dim_sku | 10 | sku_id, name, category, price, cogs, rating, organic_per_day, margin_pct |
| dim_campaign | 16 | campaign_id, channel, sku_id, audience, daily_budget, sat_mult, format, campaign_name |
| dim_creative | 17 | creative_id, campaign_id, format, hook, ugc, launch_date |
| events | 4 | event_id, date, type, entity, description |
| neuron_metrics | 26 (brain neuron) | entity_id, entity_type, label, cluster, channel, sku_id, spend_7d, spend_prev_7d, poas_7d, profit_7d, change_pct, roas_platform_7d, roas_true_7d, trust_score, days_cover, health, size |
| source_status | 9 (data stream) | source_id, label, kind, connector, file, rows, min_date, max_date, last_synced, status, trust_score, inflation_pct, detail |
| data_quality | 9 (check) | check, status, affected_rows, detail, action |

Rules: period ratios are Σnumerator ÷ Σdenominator (never averages of daily ratios); division by zero → NaN, never inf; revenue is always store revenue; windows end on the last data date (2026-10-06), never the wall clock. `spend_7d` / `profit_7d` are **average daily** ₹.

## Reconciliation results (full 90 days)

| Channel | Inflation | Platform ROAS | True ROAS | Trust |
|---|---|---|---|---|
| meta | +22.0% | 2.40 | 1.97 | 0.56 |
| google | +14.8% | 3.18 | 2.77 | 0.70 |
| amazon | 0.0% | 3.89 | 3.89 | 1.00 |
| tiktok | 0.0% | 1.37 | 1.37 | 1.00 |
| programmatic | 0.0% | 0.90 | 0.90 | 1.00 |

Spend-weighted **data trust 74%**. Last 7 days: blended POAS 0.83 · true ROAS 2.05 vs platform ROAS 2.27. SKU-B: 5.0 days of cover on the last day.

## Data quality checks (`backend/ingest/quality.py`)

| # | Check | Rule | If it fails | Current |
|---|---|---|---|---|
| 1 | completeness | every campaign has a row every day (16 × 90) | insert 0-spend rows · warn · "filled with 0 spend; lowers trust" | pass |
| 2 | duplicates | unique (date, campaign_id) and (date, sku_id) | keep the last row · warn | pass |
| 3 | negatives | spend, impressions, clicks, orders, units, on_hand, inbound ≥ 0 | drop + log · warn | pass |
| 4 | unmapped_campaigns | every campaign's sku_id exists in dim_sku | exclude from SKU metrics · warn | pass |
| 5 | reconciliation_gap | \|inflation_pct\| ≤ `RECON_GAP_THRESHOLD` (0.10) | warn · M3 raises attribution_inflation; M6 recommends server-side tracking | **warn (Meta +22%, Google +15%, planted S5, correct)** |
| 6 | freshness | max data date = manifest `date_range.end` | warn | pass |
| 7 | orders_consistency | Σ fact orders per SKU-day = sku_daily.orders_paid | fail | pass |
| 8 | infinite_values | no ±inf in any table | fail | pass |
| 9 | manifest_alignment | every manifest neuron/source has a row | fail | pass |

Checks 1–4 clean inputs before `fact_daily` is built; 5–9 audit outputs. A source with a non-passing input check is marked `warn` in `source_status`.

## Neural Brain integration (`backend/ingest/brain.py`)

**`neuron_metrics`** (26 rows, manifest order) gives every neuron its live state. Windows are the last 7 days vs the 7 before.

| Field | Meaning | UI use |
|---|---|---|
| health | `neuron_health(poas_7d)`; neurons with no ad spend: good if days_cover ≥ 7 else weak | **colour** (good / weak / losing) |
| size | `neuron_size(spend_7d, min, max)` across all 26 | **size** |
| trust_score | channel trust (campaigns) / spend-weighted trust (SKUs) | **ring** |
| roas_platform_7d, roas_true_7d, poas_7d | what the platform says vs the truth vs profit | **hover card** ("ROAS lies") |
| days_cover | SKU cover on the last date | **stock bar** |
| change_pct | (profit_7d − prev) ÷ \|prev\|, so a deeper loss is negative | trend arrow |

SKU neurons combine paid metrics from their campaigns with organic sales: `profit_7d = (Σ store revenue − Σ units × cogs − Σ ad spend) ÷ 7`. Current split: good 10 · weak 3 · losing 13.

**`source_status`** (9 rows) powers the 9 data streams flowing into the Ingest lobe: rows, date span, `status` (`warn` when an ad platform's \|inflation\| > 10%, rows = 0, or an input check failed), trust and a one-line `detail` ("Reports 22% more conversions than the store").

**Brain events**: each `run_pipeline(emit_brain_events=True)` logs **10 `ingest` events** in manifest order: 9 per-source pulses (`severity` medium for warn sources) plus 1 settle pulse ("Ingestion complete · data trust 74%"). The Meta and Google `medium` pulses are the visual S5 (double counting) in the Ingest lobe; M3 later raises the formal `attribution_inflation` anomaly in Diagnose. Tests and `validate` use `emit_brain_events=False` or a temporary state file.

## Continuous ingestion

- `POST /refresh` (M9) re-runs M2 → M3 → M6 → M7; every M2 run rewrites tables with `if_exists="replace"`, so refreshes are idempotent (verified by validate check 10).
- `REFRESH_MINUTES = 5` drives the demo loop; `last_synced` older than `FRESHNESS_WARN_MINUTES = 15` shows a stale badge.
- Scaling path: SQLite → DuckDB → Postgres/BigQuery by changing only M0 `db.py` (`connect`, `write_table`, `read_table`, `query`); connectors swap CSVs for APIs behind the same `fetch()`.

---

# Module 3 — Anomaly & Signal Detection

> **Pitch line:** "Instead of a brand manager staring at dashboards, the engine scans every campaign, channel and product every cycle, and found all seven planted problems — including a positive spike to scale — ranked by rupees."

M3 is the Neural Brain's **Diagnose lobe**. It watches every campaign, channel and SKU and raises a ranked alert (the M0 `Anomaly` shape) whenever efficiency, cost, conversion, stock or data quality shifts significantly, good **or** bad, with its ₹/day impact.

```bash
python -m backend.detection.detectors                    # detect, persist, pulse the brain, print the alerts
python -m backend.detection.detectors --no-brain-events  # same, without touching state.json
python -m backend.detection.validate                     # 15-point PASS/FAIL table (never touches the real state.json)
python -m pytest -q                                      # M0–M3 tests (temp folders only)
```

## Why statistical detection, not ML

We have **no labelled anomalies** and only **90 days per entity**, and every alert must say *what moved and by how much*. A trained model would be starved of data and could not explain itself. So M3 uses robust statistics and threshold rules behind two gates, and we can **prove** it works: it finds 7 of 7 planted problems (and still does on other random seeds). An Isolation Forest is a planned optional second-opinion layer for patterns the rules do not name; it would add a flag, never replace the explanation.

## Method: recent vs baseline, two gates

```
 ◄────────── baseline: 21 days ──────────►◄─ recent: 7 days ─►
 ├──────────────────────────────────────────┼────────────────┤► last date in the data
 campaigns / channels / stock:  BASELINE_DAYS = 21  vs  RECENT_DAYS = 7

 ◄───────────── baseline: 28 days ─────────────►◄──── recent: 14 days ────►
 ├────────────────────────────────────────────────┼─────────────────────────┤► last date
 SKU site conversion:           SKU_BASELINE_DAYS = 28 vs SKU_RECENT_DAYS = 14
```

Windows end on the **last date in the data**, never today. Window ratios are Σnumerator ÷ Σdenominator (Σclicks ÷ Σimpressions), never the mean of daily ratios.

**Two gates**: an alert fires only if the change is **statistically significant** (|z| ≥ `Z_THRESHOLD` 2.5, or a Welch t-test for conversion) **and practically large** (≥ `MIN_PCT_CHANGE` 15%, or the detector's own size threshold). Significance alone flags noise on tiny campaigns; size alone flags random wiggles.

- **Robust z-score** = `(mean(recent) − median(baseline)) ÷ MAD × √n_recent ÷ 2`, with `MAD = median(|baseline − median|) × 1.4826`. Median and MAD are not dragged around by one freak day, so a promotion-day spike in the baseline does not hide a real problem (tested). If MAD = 0 it falls back to 1% of the median.
- **Welch's t-test** (scipy) for site conversion: purchases ÷ sessions per day is noisy and the two windows have different variances and sizes, so the unequal-variance test is the honest choice.

## The 7 detectors

| Kind | Level | Triggers when | ₹/day impact | Planted |
|---|---|---|---|---|
| creative_fatigue | campaign | frequency up > 30% **and** CTR down > 20% | Δ mean daily profit | S1 · CMP-01 |
| metric_shift / positive_spike | campaign | \|z\| ≥ 2.5 **and** \|Δprofit ÷ max(\|baseline profit\|, 10% of baseline spend)\| ≥ 15%; falling = shift, rising = spike | Δ mean daily profit | S7 · CMP-10 (spike); S3 knock-on |
| cpc_spike | channel | CPC up > 25% **and** z > 2.5 | Δ channel daily profit | S3 · Google |
| stockout_risk | SKU | days of cover < 7 **and** ad spend > 0 | −(daily gross margin at risk) | S2 · SKU-B |
| conversion_drop | SKU | site CVR down > 15% **and** Welch t < −2.5 (14 vs 28 days) | −(lost CVR × sessions × unit margin) | S6 · SKU-D |
| attribution_inflation | channel | platform conversions > store orders by > 10% | 0 (a data issue) | S5 · Meta, Google |

If creative fatigue fires for a campaign, the profit check is skipped for it (no duplicate alert).

**Severity** = M0 `severity_from_impact` (loss > ₹25k/day high, > ₹8k medium, else low; gains are always low), except `stockout_risk` is always **high** and `attribution_inflation` always **medium**. **Ranking**: by |₹ impact| descending, ties by severity then id. IDs `AN-001…` follow detection order; the stable identity across runs is the key `kind:entity_id`.

## Output of this run

```
ID     kind                   entity       change      stat      ₹/day  severity direction
AN-005 stockout_risk          SKU-B        -80.4%   z=-2.50    -₹1.56L  high     loss
AN-004 cpc_spike              google       +56.1%   z=28.25    -₹25.7k  high     loss
AN-003 positive_spike         CMP-10      +631.0%    z=5.64     ₹13.7k  low      gain
AN-006 conversion_drop        SKU-D        -18.5%   t=-3.79     -₹6.7k  low      loss
AN-007 conversion_drop        SKU-J        -17.2%   t=-2.62     -₹6.4k  low      loss
AN-002 metric_shift           CMP-02       -17.9%   z=-2.65     -₹3.1k  low      loss
AN-001 creative_fatigue       CMP-01       -36.0%   z=-6.93     -₹2.8k  low      loss
AN-008 attribution_inflation  meta         +22.1%         —         ₹0  medium   loss
AN-009 attribution_inflation  google       +14.8%         —         ₹0  medium   loss
```

**Evaluation against the answer key**: 7/7 planted pairs found (recall 1.00), precision 0.89, one knock-on (`metric_shift` CMP-02, the profit hit from the Google CPC spike), and **one unplanted alert** (`conversion_drop` SKU-J: the viral TikTok creative brings cold traffic that converts worse, so site CVR falls 17% as sessions rise 57%; it is real, just not planted). The check allows up to 2 unexplained extras.

## Edge cases

| Case | How it is handled |
|---|---|
| Sale days / seasonality in the baseline | Median + MAD ignore a few extreme days; a 3-day sale does not inflate the baseline |
| An event (e.g. the SKU-D price change) inside the baseline | Conversion uses a 14-day recent window vs the 28 days before it, so the change sits in the recent window, not the baseline; the matching event id is attached to the alert |
| Near-zero baseline profit | % change uses `max(\|baseline profit\|, 10% of baseline spend)`, so a campaign near break-even does not report absurd percentages |
| Duplicate alerts for one problem | Fatigue suppresses the profit check on the same campaign; one key per `kind:entity` |
| Zero clicks or sessions | Ratios use `safe_div` / `max(den, 1)`: never inf, never a crash |
| New creatives | `new_creative` and `creative_ids_recent` are attached to profit alerts so a spike is explained (CMP-10 → CR-10b) |
| Over-sensitivity | Two gates + a robust statistic; small noisy campaigns (CMP-06, CMP-07) are *not* flagged even when their profit halves, because the change is not statistically significant |
| Different data (seeds 7 and 123) | Regenerated and re-run in tests: all 7 pairs still found |

## Neural Brain integration

**`brain_alerts`** maps anomalies onto the brain, validated against `brain_manifest.json`:

| Anomaly | Brain target |
|---|---|
| campaign anomaly | `neuron` = the campaign |
| SKU anomaly | `neuron` = the SKU |
| `stockout_risk` | the SKU neuron **plus** every promoting campaign neuron with `stock_locked = true` (lock icon: budget increases blocked); the lock carries no ₹ impact, so it is never triple-counted |
| `cpc_spike` | `cluster` = the channel (the whole Google cluster glows) |
| `attribution_inflation` | `source` = `meta_ads` / `google_ads`; never individual neurons (it is a data issue, already shown by trust rings) |

Targets hit by several anomalies merge: `anomaly_ids` list, top = largest |₹ impact| (a stock lock wins), highest severity, summed own impact.

**Diagnose pulses**: one `anomaly` brain event (region `diagnose`, path `ingest → diagnose`) per alert, but **only when the key is new, the severity got worse, or |₹ impact| grew by more than 25%** since last seen. A first run on fresh state logs one per alert; an immediate re-run logs none. Keys that stop firing are dropped from `active_anomalies` and listed as `resolved` (no event for resolved in this module). `emit_brain_events=False` logs nothing and leaves state untouched.

**`detection_quality`** (in `state.json`) stores the answer-key evaluation and powers the "7/7 detected" badge.

---

## Appendix: project scaffold (from setup)

- **Frontend:** Next.js (App Router), TypeScript, Tailwind CSS, shadcn/ui, framer-motion, @react-three/fiber (3D particle brain in `frontend/components/brain/`), recharts, @tanstack/react-query.
- **Backend scaffold:** `backend/app/` (FastAPI `GET /health`, routers for ingest/diagnose/decide/learn) with its own venv in `backend/.venv`.
- **Run everything:** `npm run dev` from the root (frontend on :3000, backend on :8000, Swagger at http://localhost:8000/docs).
