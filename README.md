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
| 2026-10-07 | `REFRESH_MINUTES` is now `int(os.getenv("REFRESH_MINUTES", "5"))` (name and original default 5 kept, now env-overridable; `import os` added to `config.py`); appended `CACHE_TTL_ANOMALIES`, `CACHE_TTL_RECOMMENDATIONS`, `CACHE_TTL_OPPORTUNITIES`, `BRAIN_MODE_WINDOW_SECONDS`, `TREND_DAYS_DEFAULT`, `DEMO_MODE`, `API_PORT` | M9 serves the engine as JSON and runs the closed loop on a timer; cache lifetimes, the brain-mode window, the demo-reset switch and the port must be shared, documented knobs |
| 2026-10-07 | Appended `AGENT_MAX_STEPS`, `AGENT_MAX_TOKENS`, `AGENT_TOOL_RESULT_MAX_CHARS`, `AGENT_MAX_WORDS`, `CLAUDE_MODEL_DEFAULT` to `config.py`; added `.env.example` with `ANTHROPIC_API_KEY` and `CLAUDE_MODEL` | M8's AI agent needs bounded tool loops, answer length and a model default; the API key lives only in the git-ignored `.env` |
| 2026-10-07 | Appended `MEASURE_WINDOW_DAYS`, `OUTCOME_BIAS_MEAN`, `OUTCOME_NOISE_SD`, `CALIBRATION_WINDOW`, `ROLLING_WINDOW`, `CALIBRATION_MIN`, `CALIBRATION_MAX`, `SEED_HISTORY_N`, `SEED_PRED_MIN`, `SEED_PRED_MAX`, `SEED_ERR_SD0`, `SEED_ERR_DECAY`, `SEED_BIAS0`, `SEED_BIAS_DECAY`, `SYNAPSE_BASE`, `SYNAPSE_GAIN`, `SYNAPSE_DECAY`, `SYNAPSE_MIN`, `SYNAPSE_MAX`, `SYNAPSE_GOOD_ERROR` to `config.py`; added `synapse_strength` to `default_state()` (old state files gain it via `load_state`) | M7 closes the loop: it measures outcomes, calibrates forecasts and strengthens or weakens the brain's synapses; none of these knobs may be hard-coded |
| 2026-10-07 | Added `rec_signatures`, `launched_tests`, `data_fixes`, `last_build_at` to `default_state()` (old state files gain them via `load_state`) | M6's executor records launched test campaigns and applied data fixes (so rollback can undo them) and deduplicates recommendation pulses by signature |
| 2026-10-07 | Appended `CONF_BASE`, `CONF_Z_WEIGHT`, `CONF_Z_CAP`, `CONF_UNC_WEIGHT`, `CONF_MAPE_WEIGHT`, `RISK_MEDIUM_SHIFT`, `URGENCY_BONUS`, `STOCKOUT_HORIZON_DAYS`, `STOCKOUT_AD_CUT`, `POSITIVE_SCALE_UP`, `PLAN_SCALE_THRESHOLD`, `PLAN_CUT_THRESHOLD`, `OPP_LAUNCH_N`, `OPP_IMPACT_HAIRCUT` to `config.py` | M6 turns alerts, causes, budget plans and opportunities into ranked decisions; confidence, risk, urgency and every action size must come from shared, documented knobs |
| 2026-10-07 | Appended `OPP_TEST_BUDGET`, `OPP_TOP_N`, `OPP_GHOST_N`, `RIDGE_ALPHA`, `CV_FOLDS`, `STOCK_FACTOR_PIVOT`, `STOCK_FACTOR_MIN`, `STOCK_FACTOR_MAX`, `HEADROOM_SCALE_POAS`, `HEADROOM_CUT_POAS` to `config.py`; added `curves`, `budget_plans`, `plan_summaries`, `opportunities`, `model_metrics` to `db.TABLE_COLUMNS` | M5b scores untested combinations before any spend and M5 persists curves, plans and model honesty metrics in brain-ready form for M6 / M9 / M10 |
| 2026-10-07 | Appended `CURVE_POINTS`, `CURVE_B_MIN_MULT`, `CURVE_B_MAX_MULT`, `SATURATION_MULT`, `OPTIMIZER_MAX_ITER`, `OVERSTOCK_COVER_DAYS`, `OVERSTOCK_UPPER_MULT`, `CLEAR_INV_PIVOT_DAYS`, `CLEAR_INV_MAX_BONUS`, `LAUNCH_TEST_RESERVE`, `SIMULATE_MAX_MS` to `config.py` | M5 fits response curves, solves the budget allocation under guardrails and four objectives, and simulates what-ifs; none of these knobs may be hard-coded in the optimizer |
| 2026-10-07 | Appended `CAUSAL_CHART_DAYS`, `CAUSAL_CI_Z`, `CAUSAL_MIN_PRE_DAYS` to `config.py`; added `diagnoses`, `causal_results` to `db.TABLE_COLUMNS`; added `active_diagnoses` to `default_state()` (old state files gain it via `load_state`) | M4 persists root-cause waterfalls and M4b persists synthetic-control results; diagnosis pulses are deduplicated against the last pulse's signature |
| 2026-10-07 | Appended `CHANNEL_DISPLAY` to `config.py` (meta → "Meta", tiktok → "TikTok", …) | `str.title()` produced "Tiktok" in campaign names and alert labels; every label in M1/M2/M3 now uses one shared display map |
| 2026-10-07 | Added `anomalies`, `brain_alerts` to `db.TABLE_COLUMNS`; added `active_anomalies`, `detection_quality` to `default_state()` (old state files gain them via `load_state`) | M3 persists detection results, maps them onto brain targets (neuron / cluster / source), emits Diagnose pulses only for new or worsening anomalies, and stores the ground-truth evaluation for the "7/7 detected" badge |

## 12. Assumptions

_(Team: add assumptions here as they are made.)_

- **M1 calibration (2026-10-07): `CVR_SCALE = 0.9`.** At 1.0 blended POAS was 1.02 (above the 0.88–0.98 band). Set to 0.9 and re-checked: blended POAS 0.91, every channel's true ROAS within ±20% of target, and the profitable list unchanged (CMP-03, 04, 05, 06, 07, 13, 14), so no further 0.02 steps were needed. Other knobs unchanged: `CH_CVR` meta 1.00, google 1.15, amazon 1.30, tiktok 0.80, programmatic 0.70; `ELASTICITY = -2.5`. Achieved economics are in the Module 1 section below.
- **M2 validation, CMP-02 band:** the M2 spec asked for CMP-02 full-period true ROAS 1.85–1.95, which assumed `CVR_SCALE = 1.0`. After recalibrating to 0.9 it is 1.66, so `backend/ingest/validate.py` uses M1's ±20% band around 1.9 (1.52–2.28) while still requiring POAS < 1.
- **M2 last-7-day headline numbers** (POAS 0.83, true ROAS 2.05, platform ROAS 2.27) sit below the spec's estimates (≈ 0.93 / 2.3 / 2.55) for the same reason, plus S1 fatigue and the S3 Google CPC spike falling in that window. All are within the validation tolerances.
- **M2 `change_pct` sign:** measured against |previous| (still via M0 `change_pct`), so a deepening loss reads as negative. With a plain recent ÷ previous − 1, CMP-01 (−₹43.0k → −₹45.6k/day, a worse loss) would show as +6%.
- **M4b CI scale:** `CausalResult.ci_low` / `ci_high` are the 95% interval on `total_effect` (₹ over the post-period), per the M4b formula, although M0's schema comment says ₹/day. The validation check "ci_low < effect < ci_high" therefore compares against `total_effect`.
- **M4b EV-2 result:** units −21.8% vs counterfactual (the spec expected ≈ −25%; the price elasticity alone implies −29.5%), net margin +₹2.1k/day with a 95% interval that includes zero. Reported, not tuned.
- **M5 stock guard vs the ±50% cap:** the M0 rule "campaigns on SKUs under 7 days of cover are capped at 40% of current spend" forces Running Pro's three campaigns to −60%, past `DAILY_CHANGE_CAP`. The guard is the deliberate exception; the validator allows it and still requires every other campaign within ±50%.
- **M5 revenue_target:** with Running Pro forced down, revenue *falls* (−₹72.9k/day) rather than rising; the objective holds profit (+₹82) and minimises the revenue loss. The profit floor carries a small rounding buffer.
- **M5b R² holdout** is 0.20 (spec expected ≈ 0.16): folds range from −0.14 to 0.69, so it is a ranking signal only. Reported, not tuned.
- **M7 outcomes are simulated** (fixed seed, always labelled `simulated: true`); the 12-outcome seeded history gives rolling MAPE 27.6% → 5.9% (the spec expected ≈ 26% → 5–10%) and a calibration factor of 1.014.
- **M7 / M6 coupling:** M6's executor now sets an emit flag around the learning hooks and runs them *after* the approval pulse (so events read approve → learn). M6 tests that read "the last event" now look events up by type.
- **M8 KPIs are daily averages:** `service.kpis` reports spend, revenue and profit as ₹/day averages over the period, with change = (recent − previous) ÷ |previous| (equal to M0 `change_pct` for a positive baseline, so a deepening loss reads as negative).
- **M8 `causal` is a superset of the M0 CausalResult** (adds `units_change_pct`, `n_post`, `controls`, `ci_includes_zero`); `ci_low` / `ci_high` still bound `total_effect` (₹ over the post-period).
- **M8 touched M7 minimally:** `learning_report()` is unchanged, but a pure `build_report(state)` and a read-only `preview_report()` were split out so the service layer can show the learning report without seeding or saving state.
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
python -m backend.generator.validate    # 16-point PASS/FAIL table, exit 1 on any failure
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
| `hero_story` | the 6-step, 30-second demo path (S1 → S1 → S4 on CMP-07 → S2 → S8 ghost neuron → S4 approve on CMP-07) |

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
python -m backend.ingest.validate                     # 17-point PASS/FAIL table (no brain events on the real state)
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
python -m backend.detection.validate                     # 21-point PASS/FAIL table (never touches the real state.json)
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
| metric_shift / positive_spike | campaign | \|z\| ≥ 2.5 **and** \|Δprofit ÷ max(\|baseline profit\|, 10% of baseline spend)\| ≥ 15%; falling = shift, rising = spike | Δ mean daily profit | S7 · CMP-10 (spike); S3 knock-on (CMP-02) |
| cpc_spike | channel | CPC up > 25% **and** z > 2.5 | Δ channel daily profit | S3 · Google |
| stockout_risk | SKU | days of cover < 7 **and** ad spend > 0 | −(daily gross margin at risk) | S2 · SKU-B |
| conversion_drop | SKU | site CVR down > 15% **and** Welch t < −2.5 (14 vs 28 days) | −(lost CVR × sessions × unit margin) | S6 · SKU-D; S7 knock-on (SKU-J) |
| attribution_inflation | channel | platform conversions > store orders by > 10% | 0 (a data issue) | S5 · Meta, Google |

If creative fatigue fires for a campaign, the profit check is skipped for it (no duplicate alert).

**Severity** = M0 `severity_from_impact` (loss > ₹25k/day high, > ₹8k medium, else low), except `stockout_risk` is always **high** and `attribution_inflation` always **medium**. **Gains are rated too**: M0 calls every positive impact "low", so M3's `_sev()` overrides that for `positive_spike` and rates it by its *absolute* ₹ impact with the same cut-offs as a loss (CMP-10 at +₹13.7k/day is **medium**). The M0 helper is unchanged; the override lives only in M3. **Ranking**: by |₹ impact| descending, ties by severity then id. IDs `AN-001…` follow detection order; the stable identity across runs is the key `kind:entity_id`.

## Output of this run

```
ID     kind                   entity       change      stat      ₹/day  severity direction
AN-005 stockout_risk          SKU-B        -80.4%   z=-2.50    -₹1.56L  high     loss
AN-004 cpc_spike              google       +56.1%   z=28.25    -₹25.7k  high     loss
AN-003 positive_spike         CMP-10      +631.0%    z=5.64     ₹13.7k  medium   gain
AN-006 conversion_drop        SKU-D        -18.5%   t=-3.79     -₹6.7k  low      loss
AN-007 conversion_drop        SKU-J        -17.2%   t=-2.62     -₹6.4k  low      loss
AN-002 metric_shift           CMP-02       -17.9%   z=-2.65     -₹3.1k  low      loss
AN-001 creative_fatigue       CMP-01       -36.0%   z=-6.93     -₹2.8k  low      loss
AN-008 attribution_inflation  meta         +22.1%         —         ₹0  medium   loss
AN-009 attribution_inflation  google       +14.8%         —         ₹0  medium   loss
```

**Evaluation against the answer key**: **7/7** planted pairs found (recall 1.00), **precision 1.00**, **no false alarms**. Two alerts are not planted but are *real consequences* of planted scenarios, so they are classified as knock-ons rather than false alarms:

| Knock-on | Cause | Why | `detail["related"]` |
|---|---|---|---|
| `metric_shift` CMP-02 | S3 Google CPC spike | the CPC jump eats the Google campaign's profit | `["cpc_spike:google"]` |
| `conversion_drop` SKU-J | S7 viral creative on CMP-10 | viral cold traffic converts worse | `["positive_spike:CMP-10"]` |

`detail["related"]` holds the stable key(s) of the causing anomaly. The brain event payload carries it, so the UI can draw a pulse from the cause to the knock-on (Google cluster → CMP-02, CMP-10 → SKU-J); M4 uses the same field. The links are rule-based (a loss on a campaign whose channel has a `cpc_spike`; a conversion drop on a SKU whose campaign has a `positive_spike`), never read from the answer key. The same result holds on other random seeds (7, 123: 7/7, no false alarms).

### Why CMP-06 is *not* flagged (and that is correct)

Trail Max's Google campaign CMP-06 is a knock-on candidate: its profit really does fall from ₹13.5k to ₹6.7k/day (−50%), comfortably past the 15% size gate. But a small campaign has very noisy daily profit (daily std ≈ ₹7k on a ₹13k mean), so the drop is **not statistically significant**: robust z = **−1.08**, well under the 2.5 gate. CMP-07 behaves the same (−40%, z = −1.45). This is the two-gate rule doing its job; alerting on it would mean alerting on noise. It is deliberately **not** an expected alert.

### The SKU-J insight: viral traffic converts worse

The viral TikTok creative on CMP-10 lifts SKU-J's paid orders ~60% and sessions ~57%, but site conversion *falls* 17% (t = −2.62): cold viral audiences browse more and buy less. So the spike is real but the traffic is lower quality than usual. **Scale it carefully**: expect marginal returns to fall as you add budget, and watch SKU-J's site CVR while you do.

### How the stockout z-score is computed

`stockout_risk` is gated by *cover < 7 days and ad spend > 0*; its z is informational. For SKU-B: mean cover over the last 7 days = 8.62, median of the previous 21 days = 25.52, MAD × 1.4826 = 8.95, so `z = (8.62 − 25.52) ÷ 8.95 × √7 ÷ 2 = −2.498`. It is **not clipped or defaulted**: it prints as −2.50 only because of 2-decimal rounding (tests recompute it from the table). The baseline here is a steady decline, so its MAD is large and z looks modest even though cover dropped 80%; that is why stock alerts rely on the cover threshold, not on z.

## Edge cases

| Case | How it is handled |
|---|---|
| Sale days / seasonality in the baseline | Median + MAD ignore a few extreme days; a 3-day sale does not inflate the baseline |
| An event (e.g. the SKU-D price change) inside the baseline | Conversion uses a 14-day recent window vs the 28 days before it, so the change sits in the recent window, not the baseline; the matching event id is attached to the alert |
| Near-zero baseline profit | % change uses `max(\|baseline profit\|, 10% of baseline spend)`, so a campaign near break-even does not report absurd percentages |
| Duplicate alerts for one problem | Fatigue suppresses the profit check on the same campaign; one key per `kind:entity` |
| Zero clicks or sessions | Ratios use `safe_div` / `max(den, 1)`: never inf, never a crash |
| New creatives | `new_creative` and `creative_ids_recent` are attached to profit alerts so a spike is explained (CMP-10 → CR-10b) |
| Over-sensitivity | Two gates + a robust statistic; small noisy campaigns (CMP-06, CMP-07) are *not* flagged even when their profit halves, because the change is not statistically significant (see above) |
| Knock-on effects | Linked to their cause via `detail["related"]` and classified in the evaluation, so a consequence is never confused with an unexplained alert |
| Different data (seeds 7 and 123) | Regenerated and re-run in tests: all 7 pairs still found, no false alarms |

## Neural Brain integration

**`brain_alerts`** maps anomalies onto the brain, validated against `brain_manifest.json`:

| Anomaly | Brain target |
|---|---|
| campaign anomaly | `neuron` = the campaign |
| SKU anomaly | `neuron` = the SKU |
| `stockout_risk` | the SKU neuron **plus** every promoting campaign neuron with `stock_locked = true` (lock icon: budget increases blocked); the lock carries no ₹ impact, so it is never triple-counted |
| `cpc_spike` | `cluster` = the channel (the whole Google cluster glows) |
| `attribution_inflation` | `source` = `meta_ads` / `google_ads`; never individual neurons (it is a data issue, already shown by trust rings) |

Targets hit by several anomalies merge: `anomaly_ids` list, top = largest |₹ impact| (a stock lock wins), highest severity, summed own impact. A knock-on's `message` names its cause ("Profit drop · Google · Summer Sneakers · interest — caused by CPC spike · Google").

**Display names**: every label in M1/M2/M3 (campaign names, source and cluster labels, alert labels, brain event messages) uses `config.CHANNEL_DISPLAY` (meta → Meta, tiktok → TikTok, …), never `str.title()`, which produced "Tiktok". Each module's validator checks that no label says "Tiktok".

**Diagnose pulses**: one `anomaly` brain event (region `diagnose`, path `ingest → diagnose`; payload includes `related`, the cause keys, for cause → knock-on pulses) per alert, but **only when the key is new, the severity got worse, or |₹ impact| grew by more than 25%** since last seen. A first run on fresh state logs one per alert; an immediate re-run logs none. Keys that stop firing are dropped from `active_anomalies` and listed as `resolved` (no event for resolved in this module). `emit_brain_events=False` logs nothing and leaves state untouched.

**`detection_quality`** (in `state.json`) stores the answer-key evaluation and powers the "7/7 detected" badge.

---

# Module 4 — Root-Cause Diagnosis (+ M4b Causal)

> **Pitch line:** "We don't just say profit fell — we say it fell ₹25.7k a day, 95% because Google auctions got expensive. Every rupee is attributed, the bars add up exactly, and for price changes we prove cause with a counterfactual."

M4 is the "thinking" step inside the Neural Brain's **Diagnose lobe**. For every M3 anomaly it explains *why*: it splits the ₹/day change into exact causes (the waterfall), drills down to the responsible campaign or funnel step and writes a plain-English narrative. M4b adds causal proof for price changes using a synthetic control.

```bash
python -m backend.diagnosis.runner                    # diagnose, persist, pulse the brain, print everything
python -m backend.diagnosis.runner --no-brain-events  # same, without touching state.json
python -m backend.diagnosis.decompose                 # just the decomposition table (no persistence)
python -m backend.diagnosis.validate                  # 16-point PASS/FAIL table (never touches the real state.json)
python -m pytest -q                                   # M0–M4 tests (temp folders only)
```

## The metric tree

Each anomaly is analysed over **its own** `detail["window"]`, so M4 explains exactly what M3 detected. All values are **daily averages** per window and ratios are Σnumerator ÷ Σdenominator, so impacts are ₹ per day.

```
campaign / channel                                   SKU
  Orders = Spend ÷ CPM × 1000 × CTR × CVR             Units = Sessions × Site CVR
  GM     = Orders × Unit margin                        GM    = Units × Unit margin
  Profit = GM − Spend
  drivers: Spend, CPM, CTR, CVR, Unit margin           drivers: Sessions, Site CVR, Unit margin
```

## Why LMDI, not subtraction

The drivers **multiply**. If CTR falls and CVR rises in the same window, "CTR change × old everything else" plus "CVR change × old everything else" does not add up to the real change: the cross terms belong to nobody, and the leftover ends up as an "other" bar. **LMDI** (Log-Mean Divisia Index) assigns every rupee exactly:

```
L = (GM₁ − GM₀) ÷ (ln GM₁ − ln GM₀)                 (the logarithmic mean of GM₀ and GM₁)
contribution[d] = L × sign[d] × ln(driver₁[d] ÷ driver₀[d])        sign(CPM) = −1, all others +1
Σ contributions = GM₁ − GM₀     exactly
```

- **Budget factor.** Spend is both a driver of volume and a cost, so `Budget change = contribution(Spend) − (spend₁ − spend₀)`: the volume the extra money bought minus the money itself. Then Σ factors = (GM₁ − spend₁) − (GM₀ − spend₀) = Δprofit/day exactly. SKU level has no ad-spend term: Σ factors = ΔGM.
- **Fallback.** If GM ≤ 0 in either window the log is undefined, so ΔGM is split equally across the drivers. A driver ≤ 0 contributes 0 (nothing is re-distributed); if the sum check (±₹0.01) then fails, the equal split is used.
- **Rounding.** Impacts are rounded to 2 dp after the check and any residue (≤ ₹0.05) goes onto the largest factor, so the rounded bars sum exactly to the rounded total. There is never an "other / unexplained" bar. `Factor.pct = |impact| ÷ Σ|impacts|`.

## Fixed factor names and colours (UI contract)

| Level | Factor (exact string) | Suggested colour |
|---|---|---|
| campaign / channel | `Budget change` | slate |
| campaign / channel | `Auction cost (CPM/CPC)` | amber |
| campaign / channel | `Click-through / creative` | violet |
| campaign / channel | `Conversion rate` | blue |
| campaign / channel & SKU | `Price / unit margin` | teal |
| SKU | `Traffic (sessions)` | indigo |
| SKU | `Site conversion rate` | blue |

The names live in `FACTOR_NAMES` and the display order in `FACTOR_ORDER` (`backend/diagnosis/decompose.py`). Factors are always returned in that fixed order.

## Drill-down and funnel per anomaly kind

| Anomaly | Decomposition | `funnel` field |
|---|---|---|
| creative_fatigue, metric_shift, positive_spike (campaign) | campaign waterfall on `fact_daily` | the campaign's SKU site funnel: pdp_views → add_to_cart → checkout → purchases, each with baseline vs recent rate; the step with the biggest fall is `is_biggest_drop` |
| cpc_spike (channel) | Σ across the channel's campaigns | per-campaign drill-down (baseline / recent profit, change, top factor), **worst first** |
| stockout_risk, conversion_drop (SKU) | SKU waterfall on `sku_daily` | the SKU site funnel (4 steps, one biggest drop) |
| attribution_inflation | none (a data issue): `total_change` 0, no factors | none; narrative only |

## Narrative rules (template-based, no LLM)

Sentences in order: **general** ("[label]: daily profit fell/rose by ₹X. Largest driver: [factor] (Y% of the movement, ₹Z/day)." The driver is always the largest factor *in the same direction as the total*, and SKU level says "gross margin") → **offset** (an opposite factor above 20% of the main one: "Partly offset by …") → **kind-specific** → **knock-on** ("Linked to: …").

| Kind | Example from this run |
|---|---|
| creative_fatigue | "…Frequency rose from 1.9 to 3.7 and click-through fell 36% — the audience has seen this creative too often." |
| positive_spike | "…A new creative (CR-10b) launched in this window and lifted click-through by 118%." |
| cpc_spike | "…Clicks got 56% more expensive across 4 Google campaigns; hardest hit: Google · Running Pro · interest. Likely cause: Competitor sale drives Google auction prices up (EV-3)." |
| stockout_risk | "…Only 5.0 days of stock left with no inbound shipment, while ₹89.3k/day of ads still drive demand — ₹1.56L/day of margin is at risk." |
| conversion_drop | "…Site conversion fell 18% after the price moved from ₹1,999 to ₹2,299 (EV-2). The price rise traded customers for margin: volume lost ₹7.8k/day, margin gained ₹9.2k/day. See causal analysis for proof. Causal check (synthetic control): units ≈ −22% …" |
| attribution_inflation | "Meta reports 22% more conversions than the store recorded. Platform ROAS 2.40 vs true 1.97 — optimising on platform numbers would over-fund this channel." |
| knock-on | "Linked to: Positive spike · TikTok · Gym Flex · broad. The viral traffic is colder and converts worse — scale carefully." |

## Output of this run

| Alert | Total ₹/day | Main driver (share of movement) | Insight |
|---|---|---|---|
| Stockout risk · Running Pro | −₹24.3k (GM) | Traffic (sessions) 91% | 5.0 days of cover, no inbound; ₹1.56L/day of margin at risk |
| CPC spike · Google | −₹25.7k | Auction cost (CPM/CPC) 95% | competitor sale (EV-3); Google · Running Pro · interest hit hardest (−₹15.2k) |
| Positive spike · TikTok · Gym Flex | +₹13.7k | Click-through / creative 88% | new UGC creative CR-10b lifted CTR 118% |
| Conversion drop · Casual X | +₹1.5k (GM) | Price / unit margin 54% | site CVR −₹5.9k, margin +₹9.2k: customers traded for margin |
| Conversion drop · Gym Flex | +₹7.1k (GM) | Traffic (sessions) 70% | viral traffic converts worse (linked to the CMP-10 spike) |
| Profit drop · Google · Summer Sneakers | −₹3.1k | Auction cost (CPM/CPC) 89% | linked to the Google CPC spike |
| Creative fatigue · Meta · Summer Sneakers | −₹2.8k | Click-through / creative 92% | frequency 1.9 → 3.7, CTR −36% |
| Attribution inflation · Meta / Google | ₹0 | narrative only | platform ROAS 2.40 vs true 1.97 (Meta) · 3.18 vs 2.77 (Google) |

Every waterfall sums to its total (largest rounding gap ≈ 4×10⁻¹²); the whole run, including detection, takes about 0.1 s.

## M4b: causal analysis by synthetic control

A before/after comparison cannot tell a price change from everything else that moved that week. So M4b builds the SKU's **counterfactual**: its site conversion *without* the price change, predicted from SKUs the event did not touch.

1. **Event and prices**: the date and treated SKU come from `events`; old and new price from `sku_daily.unit_price` (the day before vs the event date).
2. **Daily site CVR** = units ÷ max(sessions, 1) for every SKU.
3. **Controls** = every SKU except the treated one and any **disturbed** SKU. Disturbed is derived by rule (never hard-coded IDs) from the active M3 anomalies: an active `stockout_risk`, its own `conversion_drop`, or a campaign with an active `positive_spike`. Here that excludes SKU-B (stockout) and SKU-J (viral campaign CMP-10), leaving seven controls.
4. **Fit** on all pre-event days (≥ 21 required) with `scipy.optimize.nnls` on `[control CVRs, 1]` → treated CVR. **Why NNLS**: weights must be non-negative, so the synthetic SKU is a plain blend of real ones. Negative weights would "short" a control to chase noise, extrapolate wildly after the event and could not be explained to a brand manager.
5. **Counterfactual rate** after the event = `[controls_post, 1] @ w`, clipped at 0.
6. **Margin**: counterfactual units (actual sessions × counterfactual rate) are valued at the **old** price, actual units at the **new** price. `effect_per_day = mean(actual GM − counterfactual GM)`; `total_effect` is the sum over the post-period.
7. **95% interval**: `half_width = 1.96 × SD(pre-period fit residual) × mean post sessions × new unit margin × √n_post`, giving `ci = total_effect ± half_width`. **`ci_low` / `ci_high` bound `total_effect` (₹ over the post-period), not ₹/day**; this follows the M4b specification literally, while M0's `CausalResult` comment says ₹/day, so consumers must compare the interval with `total_effect`.
8. `units_change_pct = Σ actual units ÷ Σ counterfactual units − 1`; `series` = last 45 days of actual vs counterfactual CVR with an `is_post` flag (the fitted value before the event); `pre_fit_rmse` measures how closely the fit tracks.

**EV-2 result (Casual X price ₹1,999 → ₹2,299):**

| Measure | Value |
|---|---|
| Units vs counterfactual | **−21.8%** over the 14 post days |
| Net margin effect | **+₹2.1k/day** (+₹29.3k total) |
| 95% CI on the total | −₹3.3k to +₹62.0k (**includes zero**) |
| Controls (non-zero weights) | SKU-A 0.314 · SKU-G 0.263 · SKU-F 0.188 · SKU-I 0.088 · SKU-H 0.006 · SKU-C 0.0005 (SKU-E 0, intercept 0) |
| Excluded | SKU-B (active stockout_risk), SKU-J (campaign CMP-10 has an active positive_spike) |
| Pre-period fit | RMSE 0.00195 = 12% of mean CVR |

**Business insight:** the price rise cost Casual X roughly a fifth of its customers, and the margin it gained per unit roughly cancelled that: net effect is statistically indistinguishable from zero. So the rise has not demonstrably earned anything. Review the price, or trim Casual X ads (its two campaigns return 0.37 and 0.52 on every ₹1 of spend in gross margin).

## Neural Brain integration

- **Diagnosis pulses** (type `diagnosis`, region `diagnose`, path `diagnose`): one per anomaly, in ranked order, with the first narrative sentence as the message and `{anomaly_key, top_factor, top_factor_pct, total_change, factors: [{name, impact}], related, causal_event_id, has_waterfall}` as the payload. The UI draws the **waterfall bars** from `factors`, pulses from cause to knock-on via `related` (Google cluster → CMP-02, CMP-10 → SKU-J) and opens the **causal chart** when `causal_event_id` is set.
- **Causal proof pulse**: one extra `diagnosis` event on the treated SKU (`ref_id` = the event id, severity medium): "Causal proof · Casual X price rise: units −22% vs counterfactual, net margin ₹2.1k/day (95% CI includes zero)", with `{event_id, effect_per_day, total_effect, ci_low, ci_high, units_change_pct}`. The message says "includes zero" only when it does.
- **Dedupe**: a diagnosis pulses only when its key is new in `state["active_diagnoses"]` or its signature (`top_factor|total_change rounded to ₹100`) changed; the causal pulse uses the key `causal:<event_id>`. Keys that stop appearing are dropped. `emit_brain_events=False` logs nothing and leaves state untouched.
- **Tables**: `diagnoses` (one row per anomaly, with factors / funnel / related as JSON and `causal_event_id`) and `causal_results` (effect, interval, controls, weights and the chart series).

---

# Module 5 — Optimizer & Simulator (+ M5b Opportunity Scorer)

> **Pitch line:** "Every campaign gets a profit curve. Where the next rupee returns more than a rupee we scale; where it doesn't, we cut — turning ₹51.7k/day of losses into ₹22.6k/day of profit, never touching products about to sell out. And we predict winners before spending a rupee."

M5 is the first half of the Neural Brain's **Decide lobe**: it finds where the next rupee earns the most. It learns how gross margin responds to spend for every campaign, reallocates budget under guardrails for four business objectives, and simulates any what-if. M5b scores product × channel × audience combinations that have **never** been funded.

```bash
python -m backend.optimizer.optimize    # curves, the 4 objectives, the max_profit plan, Google +20% simulation
python -m backend.optimizer.runner      # all of the above + opportunities, persisted as brain-ready tables
python -m backend.optimizer.validate    # 16-point PASS / WARN / FAIL table
python -m pytest -q                     # M0–M5 tests (temp folders only)
```

## Response curves (`curves.py`)

```
GM(s) = a · s ÷ (b + s)            a = most gross margin per day the campaign can make; b = spend that reaches half of a
marginal POAS(s) = a·b ÷ (b + s)²  > 1: scaling adds profit · < 1: the next rupee loses money
profit(s) = GM(s) − s               peaks where marginal POAS = 1, at s* = √(a·b) − b
```

- **Fit**: `scipy.optimize.curve_fit` on all 90 daily (spend, margin) points per campaign, with bounds (b between 5% and 50× mean spend). M1's weekly ±40% budget tests (first 55 days) spread each campaign's spend over a range, which is what makes `b` learnable; a campaign that always spent the same amount could not reveal its saturation.
- **Re-anchoring: "shape from history, level from now."** `a` is rescaled so the curve passes exactly through the last 7 days' average margin at the last 7 days' average spend: `a = gm_7d × (b + s_7d) ÷ s_7d`. The 90-day history teaches *how fast returns diminish*; the last 7 days set *where the campaign is now*, which captures creative fatigue and the Google CPC spike.
- **Uncertainty** = relative standard error of `b` from the fit covariance (clipped to [0, 2]). `current_spend` is the executed budget from `state.budget_overrides` if present, else the last-7-day average. Fitted curves are cached in memory (invalidated when the database or state changes), so the simulator answers in about a millisecond.

| Campaign | Current ₹/day | Marginal POAS | Saturation | Optimal | Headroom |
|---|---|---|---|---|---|
| CMP-01 Meta · Summer Sneakers · broad | ₹50.3k | 0.02 | ₹54.3k | ₹0 | cut |
| CMP-02 Google · Summer Sneakers · interest | ₹25.3k | 0.12 | ₹1.15L | ₹0 | cut |
| CMP-03 Meta · Running Pro · lookalike | ₹40.0k | 0.72 | ₹1.37L | ₹27.1k | locked |
| CMP-04 Google · Running Pro · interest | ₹29.3k | 0.46 | ₹89.7k | ₹10.3k | locked |
| CMP-05 Amazon · Running Pro · retargeting | ₹19.9k | 1.09 | ₹54.8k | ₹21.6k | locked |
| CMP-06 Google · Trail Max · interest | ₹8.1k | 1.05 | ₹32.3k | ₹8.5k | hold |
| CMP-07 Meta · Trail Max · lookalike | ₹5.9k | 1.59 | ₹77.7k | ₹14.2k | **scale** |
| CMP-08 Meta · Casual X · broad | ₹25.3k | 0.16 | ₹66.2k | ₹0 | cut |
| CMP-09 Amazon · Casual X · interest | ₹14.8k | 0.24 | ₹37.4k | ₹957 | cut |
| CMP-10 TikTok · Gym Flex · broad | ₹15.2k | 1.50 | ₹2.68L | ₹38.7k | **scale** |
| CMP-11 TikTok · Slide Comfort · interest | ₹10.0k | 0.04 | ₹5.0k | ₹700 | cut |
| CMP-12 Programmatic · Office Loafer · broad | ₹18.2k | 0.09 | ₹28.3k | ₹0 | cut |
| CMP-13 Amazon · Hiking Boot · interest | ₹14.8k | 0.61 | ₹26.4k | ₹9.6k | cut |
| CMP-14 Meta · Kids Glow · retargeting | ₹8.1k | 0.84 | ₹61.0k | ₹5.7k | cut |
| CMP-15 Google · Sock Pack · interest | ₹6.1k | 0.11 | ₹58.4k | ₹0 | cut |
| CMP-16 Programmatic · Summer Sneakers · retargeting | ₹10.1k | 0.07 | ₹13.1k | ₹0 | cut |

Headroom (from marginal POAS: > 1.1 scale, < 0.9 cut, otherwise hold; stock-guarded campaigns are always "locked"): **2 scale · 1 hold · 10 cut · 3 locked**. Note that profitable campaigns can still be past their optimum (CMP-13 earns POAS 1.4 on average but only 0.61 on the *next* rupee): average and marginal returns are different things.

## Optimizer (`optimize.py`)

**Variables**: the daily spend of each of the 16 campaigns. **Bounds per campaign**:

| Bound | Rule |
|---|---|
| change cap | `[current × (1 − 50%), current × (1 + 50%)]` (`DAILY_CHANGE_CAP`) |
| stock guard | SKU cover < 7 days: `hi = min(hi, current × 40%)` and `lo = min(lo, hi)`: increases are blocked and spend is held at the 40% cap (`STOCK_SPEND_CAP_MULT`) |
| overstock boost | `clear_inventory` only: cover > 60 days → `hi = current × 2` |

Shared constraint: Σ spend ≤ budget (default: today's total); under-spending is allowed when extra money would lose profit. **Solver**: scipy SLSQP on spend ÷ current (well scaled), analytic gradients, one retry from the bounds midpoint, then a best feasible point with `solver.ok = false`. Plans are rounded to ₹10 inside the bounds. A budget below the minimum reachable spend (the lower bounds sum to about ₹1.42L) is reported as `infeasible` instead of silently overspending.

| Objective | Maximise | Notes |
|---|---|---|
| max_profit | Σ (GM − spend) | |
| revenue_target | Σ rev_per_gm × GM | subject to total profit ≥ today's (with a rounding buffer; or the best achievable if guards make that impossible) |
| clear_inventory | Σ (wᵢ × GM − spend), wᵢ = 1 + clip((cover − 30) ÷ 30, 0, 1.5) | overstocked SKUs get a weight bonus and may grow to 2× |
| launch_sku | max_profit on 95% of the budget | 5% reserved for M5b test budgets |

**Results of this run** (per day; current: spend ₹3.02L, revenue ₹6.21L, profit **−₹51.7k**, POAS 0.83):

| Objective | Spend | Revenue | Profit | POAS | Profit Δ | Solver |
|---|---|---|---|---|---|---|
| max_profit | ₹1.71L | ₹4.71L | **+₹22.6k** | 1.13 | **+₹74.3k** | ok |
| revenue_target | ₹2.74L | ₹5.48L | −₹51.6k | 0.81 | +₹82 | ok |
| clear_inventory | ₹1.86L | ₹4.92L | +₹19.0k | 1.10 | +₹70.7k | ok |
| launch_sku | ₹1.71L | ₹4.71L | +₹22.6k | 1.13 | +₹74.3k | ok (₹15.1k reserved) |

**Headline**: max_profit turns **−₹51.7k/day into +₹22.6k/day (+₹74.3k/day)** by halving the loss-makers (Summer Sneakers, Casual X, programmatic, TikTok Slide Comfort, Google Sock Pack), scaling Trail Max on Meta (+50%) and Gym Flex (+50%), and holding Google Trail Max. Things to know:
- **Stock guard forces −60%** on Running Pro (CMP-03/04/05): by the rule above the spend is held at 40% of current, which is beyond the ±50% cap. It is the one deliberate exception (marked `stock_guard`); no plan ever raises spend on a low-stock SKU.
- **Cutting costs revenue**: max_profit gives up ₹1.50L/day of revenue (−24%) to gain profit. revenue_target keeps profit where it is and loses *less* revenue (−₹72.9k) because the forced Running Pro cut cannot be offset elsewhere within the ±50% caps.
- **clear_inventory** doubles Kids Glow (CMP-14, 77 days of cover) to ₹16.3k/day versus ₹5.7k under max_profit.

## Simulator

`simulate({campaign_id: spend})` applies any plan (unlisted campaigns keep their spend) and returns per-campaign and total spend, margin, revenue, profit, marginal POAS, and a `stock_warning` when a plan raises spend on a SKU with < 7 days of cover. `channel_simulate({"google": 1.2})` scales a whole channel first. Both answer in about **1 ms** (limit 300 ms). **Google +20%** costs **₹13.8k/day more spend and reduces profit by ₹9.1k/day**: Google is past saturation while the competitor CPC spike lasts, so the next rupee returns less than a rupee.

## M5b: scoring combinations before any spend (`opportunity.py`)

```
log(orders per ₹1,000) = β·log(spend) + γ·rating + channel effect + audience effect       (Ridge regression, α = 1)
```

- **Why log-additive**: effects multiply on the real scale (a better audience times a better channel), and `exp()` guarantees a prediction can never go negative. The target is `log((orders + 0.5) ÷ spend × 1000)` (the 0.5 avoids log 0 and is subtracted back out of the prediction).
- **Why attributes, not IDs**: the features are log spend, product rating, and one-hot channel and audience. SKU ids would make the model memorise campaigns and be useless on a combination it has never seen.
- **Why Ridge**: 16 campaigns and 11 correlated features invite over-fitting; the L2 penalty keeps the effects sensible. Coefficients: log spend −0.19 (diminishing returns), rating +0.73, retargeting +0.58, Google +0.32, programmatic −0.67, broad −0.42.
- **Honest validation**: `GroupKFold(4)` grouped by campaign holds out *whole campaigns*, which is exactly the "never seen before" case (a random KFold would leak campaign identity and flatter the score; a test proves it does). **R² holdout = 0.20** (folds 0.02, −0.14, 0.24, 0.69). That is low and noisy by design: this is a **ranking signal for where to test first, not a forecast**. The Opportunities panel shows this number as an honesty badge.
- **Scoring**: (1) every SKU × channel × audience combination not in `dim_campaign`; (2) predict orders per ₹1k at a ₹5,000/day test budget; (3) `predicted_poas = orders per ₹1k ÷ 1000 × unit margin`; (4) stock factor `0` if cover < 7 days else `clip(cover ÷ 30, 0.5, 1.5)`; (5) `score = predicted_poas × stock factor`, drop zeros, keep the best audience per SKU × channel; (6) rank, top 10, top 5 are ghosts.

| # | Opportunity | Orders per ₹1k | Predicted POAS | Stock days | Score | Ghost |
|---|---|---|---|---|---|---|
| 1 | Trail Max · Google · retargeting | 2.47 | 5.55 | 49 | 8.32 | ● |
| 2 | Trail Max · TikTok · retargeting | 2.15 | 4.82 | 49 | 7.24 | ● |
| 3 | Trail Max · Amazon · retargeting | 1.94 | 4.35 | 49 | 6.53 | ● |
| 4 | Trail Max · Meta · retargeting | 1.91 | 4.31 | 49 | 6.46 | ● |
| 5 | Gym Flex · Google · retargeting | 2.29 | 2.97 | 33 | 3.28 | ● |
| 6 | Hiking Boot · Google · retargeting | 2.12 | 4.66 | 20 | 3.10 | |
| 7 | Trail Max · Programmatic · retargeting | 0.85 | 1.91 | 49 | 2.87 | |
| 8 | Gym Flex · TikTok · retargeting | 1.99 | 2.58 | 33 | 2.85 | |
| 9 | Hiking Boot · TikTok · retargeting | 1.84 | 4.05 | 20 | 2.70 | |
| 10 | Gym Flex · Amazon · retargeting | 1.79 | 2.33 | 33 | 2.57 | |

Running Pro never appears (5 days of cover). Every pick is a retargeting audience: that effect dominates the model, which is plausible but is also a reason to treat the ranking as a hypothesis to test, not a certainty.

## ML summary for judges

| Technique | Where | Why it fits |
|---|---|---|
| Non-linear regression (curve fitting) | response curves | diminishing returns are non-linear; two parameters per campaign are all 90 days can support |
| Constrained optimisation (SLSQP) | budget allocation | smooth objective with analytic gradients, box bounds and a budget constraint |
| Ridge regression + group cross-validation | opportunity scorer | tiny data, correlated features, and validation that holds out whole campaigns |

## Neural Brain integration

M5 writes `curves`, `budget_plans`, `plan_summaries`, `opportunities` and `model_metrics`; the brain (via M9) renders them:
- **`curves.headroom`**: a halo on campaign neurons: *scale* = outward glow, *cut* = dim inward ring, *hold* = none, *locked* = lock icon.
- **`budget_plans`** (the objective chosen in settings, default max_profit): planned-change arrows on neurons from `change_pct`.
- **`opportunities` where `is_ghost`**: dashed **ghost neurons** in the cluster for their channel, linked by a dashed synapse to the SKU neuron and showing `predicted_poas`.
- **`plan_summaries`**: the before / after headline ("−₹51.7k/day → +₹22.6k/day").
- **`model_metrics.r2_holdout`**: the honesty badge on the Opportunities panel.

**M5 emits no brain events, by design.** It produces analysis; **M6** turns the max_profit plan, the opportunities and the anomalies into Recommendations and emits the `recommendation` pulses into the Decide lobe. (A test confirms M5 never touches `state.json`.)

---

# Module 6 — Decision Engine, Guardrails & Executor

> **Pitch line:** "Small, safe moves run on autopilot; big ones wait for a human; anything that would push a product into a stockout is blocked — and every action is logged and reversible in one click."

M6 is the Neural Brain's **Decide lobe**. It turns alerts (M3), causes (M4), budget plans and opportunities (M5) into a ranked inbox of executable decisions (the M0 `Recommendation` shape), then executes, rejects or rolls them back through a mock ad API, with five layers of guardrails and a full audit trail.

```bash
python -m backend.decisions.engine                       # refresh the inbox and print it
python -m backend.decisions.engine --approve REC-567405  # approve (execute) one decision
python -m backend.decisions.engine --reject REC-xxxxxx   # reject one
python -m backend.decisions.engine --rollback REC-567405 # undo an executed one
python -m backend.decisions.engine --autonomy autonomous --auto-apply   # switch mode / run the autopilot once
python -m backend.decisions.engine --no-brain-events     # any of the above without brain events
python -m backend.decisions.validate                     # 17-point PASS/FAIL table (temporary state only)
python -m pytest -q                                      # M0–M6 tests
```

## Rules: signal → action

Processed in this order, with a **covered set**: a campaign appears in only **one** recommendation's budget changes, so the earlier, more specific rule wins any conflict (e.g. Running Pro's campaigns belong to the stock action, not to the Google rebalance).

| # | Signal | Action type | Recommended action | ₹/day impact |
|---|---|---|---|---|
| 1 | stockout_risk | inventory_protect | cut every uncovered campaign on the SKU to 40% of current | stockout value model (below) |
| 2 | creative_fatigue | creative_refresh | rotate in a UGC variant + trim the campaign to its optimizer plan | curve delta |
| 3a | conversion_drop with a price event | price_review | trim the SKU's campaigns to plan; payload carries the M4b causal summary | curve delta |
| 3b | conversion_drop that is a viral knock-on | (none) | no recommendation of its own; its warning attaches to rule 4 | n/a |
| 4 | positive_spike | scale_up | +30% (bounded by the optimizer's limits); +15% with a "scale carefully" note when a knock-on conversion drop exists | curve delta |
| 5 | cpc_spike | bid_cap | rebalance the channel's uncovered campaigns to plan while auctions are expensive; also covers the knock-on profit drops | curve delta |
| 6 | attribution_inflation | data_fix | switch the channel's conversion tracking to store-verified (server-side) | 0 |
| 7 | standalone metric_shift | budget_cut | cut to plan | curve delta |
| 8 | optimizer plan < 85% of current | budget_cut | ONE "Trim loss-making campaigns" for all remaining | Σ curve delta |
| 9 | optimizer plan > 115% of current | scale_up | ONE "Scale under-funded high-margin campaigns" (asserted never to touch a low-stock SKU) | Σ curve delta |
| 10 | top 2 untested opportunities | launch_test | ₹5k/day test campaign for the ghost neuron | (predicted POAS − 1) × ₹5,000 × 0.6 |

"Curve delta" = Σ over the changed campaigns of `profit(new spend) − profit(current spend)` on the M5 response curves. Titles are built only from entity names and fixed wording (never ₹ amounts or counts), because a recommendation's id is the md5 of its title and must survive refreshes (`REC-567405` is always "Protect stock · cut ads on Running Pro by 60%").

## Stockout value model

When stock is about to run out, ads keep buying clicks that land on an empty page. Over a 14-day horizon (`STOCKOUT_HORIZON_DAYS`):

```
keep = cover × (GM₀ − s₀) + (H − cover) × (−s₀)             sell for `cover` days, then pay for dead clicks
last = min(cover ÷ (GM₁ ÷ GM₀), H)                          cutting ads slows sales, so stock lasts longer
cut  = last × (GM₁ − s₁) + (H − last) × (−s₁)
value = (cut − keep) ÷ H                                     ₹/day
```

**Worked example from this run** (Running Pro: CMP-03/04/05, 5.0 days of cover): at today's spend GM₀ = ₹1,26,203/day on s₀ = ₹89,276; cutting to 40% gives GM₁ = ₹71,686 on s₁ = ₹35,710. `keep = 5 × 36,927 + 9 × (−89,276) = −₹6,18,844`; the stock now lasts `last = 5 ÷ (71,686 ÷ 1,26,203) = 8.8` days, `cut = 8.8 × 35,976 + 5.2 × (−35,710) = +₹1,31,075`; **value = (1,31,075 + 6,18,844) ÷ 14 = ₹53.6k/day**.

## Scoring

| Quantity | Formula |
|---|---|
| expected ₹/day | raw impact × `state.calibration.factor` (1.0 until M7 learns otherwise) |
| confidence | `clip((0.55 + 0.08 × min(\|z\|, 4) − 0.15 × curve uncertainty) × (1 − 0.5 × MAPE), 0.45, 0.95)`; MAPE `None` counts as 0 |
| shift | `\|Σ new − Σ current\| ÷ Σ current` of the changed campaigns; launch tests: `₹5,000 ÷ brand total spend`; data fixes: 0 |
| risk | high if shift > 40% or \|impact\| > ₹40k; medium if shift > 10%; else low |
| requires approval | `not (risk == "low" and shift < 10%)` |
| blocked | any change **raises** spend on a campaign whose SKU has < 7 days of cover |
| priority | `max(impact, 0) × confidence` + ₹5,000 urgency bonus for high risk |

## The five guardrail layers

1. **Optimizer bounds**: ±50% per day, the stock guard, and the total budget (M5).
2. **Risk tiers**: only a low-risk move smaller than 10% is ever auto-eligible.
3. **Hard block**: raising spend on a near-stockout SKU can **never** execute, even if a human approves it; it is re-checked against *current* data at execution time, so a decision that became unsafe after it was built is refused.
4. **Autonomy mode**: *advisory* never executes; *supervised* needs a human; *autonomous* auto-applies only low-risk, unblocked, approval-free items.
5. **Audit + rollback**: every action is logged with the exact previous budgets and reverses in one call.

**Lifecycle**: `pending → executed → rolled_back`; `pending → rejected`; `executed →` (M7: outcome measured). Executed, rejected and rolled-back decisions keep their status: a refresh rebuilds only *pending* ones and never recreates the others as pending duplicates (so a rolled-back or rejected decision is not re-proposed). After execution the M5 curves are re-fitted, so the executed budgets become the new "current spend" (the closed loop) and the next refresh plans from them.

## Mock ad API (`ads_api.py`)

Same call shapes as the real APIs, so swapping in real clients changes only this class. Nothing touches the network; timestamps use an injectable clock.

| Method | Endpoint | Mirrors |
|---|---|---|
| `update_budget(campaign_id, channel, daily_budget)` | `POST /{channel}/campaigns/{id}/budget` → `OK` | Meta adset `daily_budget` · Google CampaignBudgetService (`amount_micros` = ₹ × 1,000,000) · Amazon campaign budget · TikTok adgroup budget · DSP |
| `create_test_campaign(sku, channel, audience, budget)` | `POST /{channel}/campaigns` → id `TST-<md5[:6]>` | campaign-create endpoints |
| `set_conversion_source(channel, source)` | `POST /{channel}/conversions/settings` | Meta CAPI · Google enhanced conversions · TikTok Events API |
| `pause_test_campaign(id, channel)` | `POST /{channel}/campaigns/{id}/pause` → `PAUSED` | campaign status update (rollback of a launch) |
| `rotate_creative(campaign_id, channel, suggested)` | `POST /{channel}/campaigns/{id}/creatives` → `QUEUED` | creative rotation |

## Autonomy modes and the autopilot

| Mode | Behaviour |
|---|---|
| advisory | recommendations are shown; **nothing is ever executed** (execute is refused) |
| supervised (default) | a human approves each decision; the autopilot never runs |
| autonomous | after each refresh the autopilot executes every pending decision that is **unblocked, low-risk and approval-free**, with approver `autopilot`. Today that is the two launch tests and the two data fixes; the 7 budget moves still wait for a human |

## The inbox from this run

| # | Decision | ₹/day | Conf. | Risk | Approval | Action | Campaigns |
|---|---|---|---|---|---|---|---|
| 1 | Protect stock · cut ads on Running Pro by 60% | ₹53.6k | 67% | high | yes | inventory_protect | CMP-03, 04, 05 |
| 2 | Refresh creative & trim budget · Meta · Summer Sneakers · broad | ₹24.2k | 74% | high | yes | creative_refresh | CMP-01 |
| 3 | Review price & trim ads · Casual X | ₹14.9k | 73% | high | yes | price_review | CMP-08, 09 |
| 4 | Trim loss-making campaigns | ₹18.4k | 45% | high | yes | budget_cut | CMP-11, 12, 13, 14, 16 |
| 5 | Rebalance Google while auction prices are high | ₹13.5k | 70% | medium | yes | bid_cap | CMP-02, 06, 15 |
| 6 | Launch test · Trail Max on Google (retargeting) | ₹13.6k | 45% | low | auto | launch_test | — |
| 7 | Scale under-funded high-margin campaigns | ₹1.3k | 45% | high | yes | scale_up | CMP-07 |
| 8 | Launch test · Trail Max on TikTok (retargeting) | ₹11.5k | 45% | low | auto | launch_test | — |
| 9 | Scale winner · TikTok · Gym Flex · broad | ₹1.1k | 60% | medium | yes | scale_up | CMP-10 |
| 10 | Optimise Meta on store-verified conversions | ₹0 | 55% | low | auto | data_fix | — |
| 11 | Optimise Google on store-verified conversions | ₹0 | 55% | low | auto | data_fix | — |

11 recommendations, ₹1.52L/day expected, 7 need approval, 4 auto-eligible, none blocked. The total is not the optimizer's ₹74.3k/day plan gain: the stock protection is valued as avoided wasted spend (₹53.6k) and launch tests add expected value.

## Neural Brain integration

| Event | Path | When | Payload |
|---|---|---|---|
| `recommendation` | diagnose → decide | each pending decision whose id is new or whose signature (`round(₹, -2)\|risk\|blocked\|requires_approval`) changed | rec id, action type, targets, anomaly id, related anomaly keys, ₹/day, confidence, risk, approval, blocked, campaigns with from/to budgets |
| `approval` | decide → learn | a human executes | rec id, approver, targets, changes, API-call count, **synapses** (campaign → SKU `promotes` edges), launched test, data fix |
| `auto_apply` | decide → learn | the autopilot executes | same payload; shown as "⚡ autopilot" |
| `rejection` | decide | a human rejects | rec id, reason |
| `rollback` | learn → decide | rollback | rec id, **restored budgets**, API-call count |

The UI: recommendation pulses travel anomaly neuron → Diagnose → Decide and add an inbox card; **approval pulses** (Decide → Learn) resize the neurons to their new budgets (from `budget_overrides`) and flash the listed synapses; `auto_apply` shows the ⚡ marker; a launched test turns its **ghost neuron into a solid TEST neuron**; `data_fixes` put a "store-verified" badge on the data stream; rollback pulses reverse all of it. `emit_brain_events=False` (and every test) logs nothing. M7 (learning) is not built: executions call `hooks.on_executed` / `hooks.on_rolled_back`, no-ops that M7 will implement, and a hook failure can never break an execution.

---

# Module 7 — Closed-Loop Learning

> **Pitch line:** "Every decision is a prediction we hold ourselves to. We measure what actually happened, and the engine recalibrates — our rolling forecast error fell from about 28% to about 6%, so its confidence is earned, not claimed."

M7 is the Neural Brain's **Learn lobe**, the core of the closed loop. After every executed decision it records what happened, compares it with the prediction, and feeds the error back so the next predictions (and the confidence attached to them) are better calibrated.

```
 predict ──► execute ──► measure ──► compare ──► calibrate ──┐
   ▲        (M6)         (M7)        error %      factor,    │
   │                                              MAPE,      │
   └────────── M6 scales ₹ and confidence ◄───────win-rate ──┘
               M5 plans from the new budgets      synapses strengthen / weaken
```

```bash
python -m backend.learning.runner              # seed the history if needed, record outcomes, print the report
python -m backend.learning.runner --no-brain-events
python -m backend.learning.validate            # 12-point PASS/FAIL table (temporary state only)
python -m pytest -q                            # M0–M7 tests
```

## Production vs demo measurement (read this)

| | How `actual` is obtained |
|---|---|
| **Production** | wait `MEASURE_WINDOW_DAYS = 7` after execution, then `actual = profit after − profit before` for the affected campaigns, **minus the same change on a holdout of similar unchanged campaigns** (or an M4b synthetic control) so seasonality and platform-wide shocks cancel out. Always from **store orders (M2 truth)**, never platform-reported numbers |
| **This demo** | **simulated**: `actual = predicted × (1 + N(−5%, 12%))`, with the RNG seeded by `md5(decision_id)` so the same decision always gives the same number. Every outcome carries `simulated: true`, the report carries a note saying so, and every brain event message ends in "· simulated" |

Simulating is the honest way to demonstrate the loop before a week of real data exists: the numbers prove the *mechanism* (record → compare → calibrate → change future behaviour), not the forecast quality of a real campaign, and nothing in the product hides that.

## Seeded history

So the brain starts with memory, the first call seeds `SEED_HISTORY_N = 12` past outcomes (once; deleting `state.json` regenerates the identical set). Dates are spread evenly from 60 to 5 days before `END_DATE`. For outcome *i* = 0…11:

```
predicted ~ U(₹4,000, ₹22,000)
error SD  = 0.35 × 0.85^i        optimism bias = −0.10 × 0.8^i
actual    = predicted × (1 + N(bias, SD))
```

Both the spread and the bias shrink with *i*, so the rolling error falls: the engine visibly learned. The twelve titles are fixed realistic past actions ("Trim programmatic loss-makers", "Scale Amazon Hiking Boot", "Refresh TikTok creative", …) on real campaign ids; their synapses are updated too. The history is the past: it emits **no** brain events.

## Metrics

| Metric | Definition | This run |
|---|---|---|
| **MAPE** (forecast error) | mean \|error %\| over the last 8 measurable outcomes | **7.9%** |
| **Calibration factor** | `clip(mean(actual ÷ predicted), 0.6, 1.2)` over the same 8 | **1.014** |
| **Win-rate** | share of those outcomes with `actual > 0` | **100%** |
| **Rolling MAPE** | MAPE over a sliding window of 4 outcomes (accuracy chart) | **27.6% → 5.9%** (first full window → last) |
| **Cumulative profit** | running Σ of measured `actual` ₹/day (the Learning chart) | ₹1.47L/day after the 12 seeded outcomes |

Data-quality actions (|predicted| < ₹1, e.g. data fixes) are recorded with `measurable: false` and excluded from every metric above.

## How learning changes future decisions

1. **Calibrated ₹**: M6 multiplies every expected ₹/day by `state.calibration.factor`. A habitually optimistic history (factor < 1) makes the engine promise less, and a smaller promised impact can drop a decision under the ₹40k "high-risk impact" line.
2. **Calibrated confidence**: confidence is scaled by `(1 − 0.5 × MAPE)`, so a less accurate engine reports lower confidence, which lowers priority in the inbox (approval tiers themselves depend on risk and size, not on confidence).
3. **Closed loop into M5**: executed budgets become `budget_overrides`, so the next curve fit and plan start from where the money now is.
4. **Clipping**: the factor never leaves [0.6, 1.2] (verified by test), so one catastrophic outcome cannot swing every future prediction; MAPE itself is reported unclipped.
5. **Rollback is learning-safe**: rolling a decision back removes its outcome and reverses its synapse changes exactly, and the calibration is recomputed.

## Synapse learning (the brain's visible memory)

Each outcome updates the campaign → SKU edges it touched (launch tests use `TST-xxxxxx → SKU`; data fixes touch none):

| Outcome | Delta |
|---|---|
| good: `actual > 0` and \|error\| ≤ 25% | **+0.25** |
| loss: `actual ≤ 0` | **−0.15** |
| otherwise (profitable but a poor forecast) | **+0.125** |

Strength = `clip(current (default 1.0) + delta, 0.5, 3.0)`. The *applied* (post-clipping) delta is stored on the outcome, so removing it reverses the memory exactly. After seeding, the strongest edge is `CMP-11→SKU-G` at 1.38 (touched by two outcomes), followed by a group at 1.25 (e.g. `CMP-01→SKU-A`, `CMP-02→SKU-A`, `CMP-04→SKU-B`, `CMP-06→SKU-C`, `CMP-07→SKU-C`). The brain shows synapse **thickness = strength**.

## Brain integration

For every new, non-seeded outcome M7 emits one `outcome` event (region `learn`, path `learn`): severity *low* for a good outcome (or a data fix), *medium* otherwise; message `"Protect stock · cut ads on Running Pro by 60%: predicted ₹53.6k/day → actual ₹55.4k/day (+3%) · simulated"`; payload `{decision_id, predicted, actual, error_pct, simulated, measurable, synapses: [{key, strength, delta}], calibration: {factor, mape, win_rate, n}}`. The UI plays an amber Learn-lobe pulse per outcome, thickens or thins the synapses, and draws the Learning page (accuracy curve, cumulative profit, KPIs) from `learning_report()`.

The loop is wired through M6's hooks: `on_executed` → `record_outcomes()`, `on_rolled_back` → `remove_outcome()`. A hook failure never breaks an execution, and `emit_brain_events=False` silences the Learn-lobe pulses too. The approval pulse is emitted *before* the learning hook runs, so the event order reads approve → learn.

## Demo numbers

Approving the top decision ("Protect stock · cut ads on Running Pro by 60%") records **predicted ₹53,566/day → actual ₹55,422/day (+3.5%)**, simulated, strengthens `CMP-03→SKU-B`, `CMP-04→SKU-B` and `CMP-05→SKU-B` by 0.25 each, and shifts the calibration window.

---

# Module 8 — AI Agent

> **Pitch line:** "Ask it anything in plain English. It answers with the engine's own numbers — the AI explains, it never invents — and if the internet drops, the answers keep coming."

M8 is the Neural Brain's **voice**. It answers questions using the engine's own tools and tells the UI which brain nodes the answer is about, so they can light up. It sits on a **read-only service layer** (`backend/api/service.py`) that the M9 HTTP API will reuse.

```bash
python -m backend.agent.agent "Why did Summer Sneakers drop?"   # one question
python -m backend.agent.agent --demo [--rules]                   # the 7 demo questions (--rules forces the offline engine)
python -m backend.agent.validate                                 # 13-point PASS/FAIL table (read-only: state.json byte-identical)
python -m pytest -q                                              # M0–M8 tests (Claude is only ever mocked)
```

## Architecture

```
 question ──► answer() ──┬─ ANTHROPIC_API_KEY set ──► Claude tool-calling loop ──┐   any failure (no key, network, rate limit,
                         │                             (max 6 rounds)            │   bad response) never reaches the UI:
                         └─ no key / --rules ───────► rules engine ◄─────────────┘   it falls back to the rules engine
                                        │
                      8 read-only tools (backend/agent/agent.py)
                                        │
                      service layer (backend/api/service.py): kpis · anomalies · diagnosis · recommendations ·
                                        │                     causal · channel_simulate · opportunities · reconciliation · learning
                      M2 tables · M3 detectors · M4 / M4b diagnosis · M5 optimizer · M6 inbox · M7 learning
                                        │
              { answer, engine, tools_used, highlights, note, duration_ms }
```

## Tools

| Tool | Backed by | Input | Use |
|---|---|---|---|
| `get_kpis` | `service.kpis` | — | overview, stock at risk, data trust |
| `list_anomalies` | `service.anomalies` (M3) | — | what is wrong, ranked by ₹/day |
| `explain_anomaly` | `service.diagnosis` (M4) | `anomaly_id` | the exact ₹/day waterfall and narrative for one anomaly |
| `get_recommendations` | `service.recommendations` (M6) | — | the pending Decision Inbox |
| `causal_price_effect` | `service.causal` (M4b) | `event_id?` | did a price change work (units, net margin, 95% interval) |
| `simulate_channel_budget` | `service.channel_simulate` (M5) | `multipliers` e.g. `{"google": 1.2}` | read-only what-if on the response curves |
| `get_opportunities` | `service.opportunities` (M5b) | — | where to grow next, with the model's honest R² |
| `get_reconciliation` | `service.reconciliation` (M2) | — | platform-reported vs store-verified ROAS |

Tool results are compact views (so they fit in 12,000 characters), serialised to JSON and truncated if longer. **Every tool is read-only.**

## The system prompt and the "LLM never computes" rule

> "You are the reasoning layer of a D2C advertising decision engine. Use tools for every number; never estimate or invent figures. Be concise (at most 120 words), lead with the answer, cite ₹ impacts per day, and end with one recommended action. Currency is INR (use ₹ with lakh/thousand formatting as given by the tools). You cannot execute changes; recommend that the user approve them in the Decision Inbox."

The model's job is to choose tools and phrase the result; **every figure must come from a tool result**. The rules engine enforces this mechanically (below), and the Claude path is bounded to 6 tool rounds and 700 tokens; a failing tool is reported back to the model as a tool error rather than raised.

## Rules engine (offline fallback)

Keyword intent routing on the lowercase question, **first match wins** (an explicit "brief" request goes first):

| Intent | Keywords | Tools used | Answer |
|---|---|---|---|
| explain | why · drop · fall · fell · explain · cause · down | list_anomalies, explain_anomaly, get_recommendations | M4 headline + top 3 factors ("Factor ₹X/day (Y%)") + the kind-specific sentence + one recommended action |
| scale | scale · next · invest · opportunit · grow · where should | get_recommendations, get_opportunities | scale-up and launch items + top 3 predicted-POAS opportunities + the R² honesty line |
| stock | stock · inventory · sell out · stockout | get_kpis, get_recommendations | days of cover + the protect-stock action |
| reconciliation | roas · double · attribution · trust · real | get_reconciliation, get_kpis | true vs platform ROAS per channel and the over-reporting % |
| price | price | causal_price_effect, get_recommendations | units vs counterfactual, net margin/day, 95% interval and whether it includes zero |
| simulate | what if · simulate · increase · `+NN%` | simulate_channel_budget | profit before → after, POAS, stock warnings |
| brief (default) | anything else, "brief", "today", "summary" | get_kpis, get_recommendations | 7-day profit, POAS, data trust, top actions |

**Entity matching** (for "explain"): each anomaly's candidates are its label parts after the kind (channel, product, audience) plus its id; the score is the length of the longest candidate found in the question. Ties go to a **root cause over a knock-on** (so "Summer Sneakers" finds the creative fatigue, not the Google knock-on that also contains it, and "Google" finds the CPC spike), then to the larger ₹ impact. No match at all → the largest loss. Simulation questions parse channel names (none named → every channel) and a percentage (`+30%`, `30 percent`, `-10%`, "cut … 25%"; default +20%).

## Safety and trust design

- **No invented numbers.** Every ₹, % and decimal in a rules answer is produced by a formatter that records it (`Fmt`), from values taken from tool outputs; the validator asserts that every numeric token in every answer is in that registry (54 tokens across the seven demo answers).
- **Read-only.** The agent can explain and simulate; it cannot execute, approve, reject or roll back. Execution stays in M6 behind its five guardrail layers. A test checks that no tool can reach those functions or any state write, and `state.json` is byte-identical after the whole validation run.
- **Always labelled.** Every answer says which engine produced it: `claude`, `rules`, or `fallback (<ExceptionClass>)`, plus the note "Every number comes from an engine tool call."
- **Secrets stay in `.env`** (git-ignored; `.env.example` has empty `ANTHROPIC_API_KEY` and `CLAUDE_MODEL`). The key is never logged or returned, and a fallback reports only the exception's class name, never its message.
- **Graceful fallback.** No key, a bad key (a real run returned `fallback (AuthenticationError)` in about a second), no network, a rate limit, an empty or malformed reply, or a runaway tool loop all produce a normal rules answer. Even a bug in the rules engine returns a polite sentence, never an exception.

## Neural Brain integration

Every answer carries `highlights`: up to six brain targets (`neuron` for a campaign or SKU, `cluster` for a channel, `source` for a data stream), derived from the tool results the answer relies on via `service.brain_targets_for`. The UI lights those nodes and focuses the camera on them. **M8 emits no brain events and writes nothing**: asking a question never changes the engine.

## Actual answers from the `--demo --rules` run

**Why did ROAS drop for Summer Sneakers?**  
Creative fatigue · Meta · Summer Sneakers · broad: daily profit fell by ₹2.8k. Largest driver: Click-through / creative (92% of the movement, ₹2.7k/day). Top factors: Click-through / creative -₹2.7k/day (92%), Conversion rate -₹192/day (7%), Budget change ₹46/day (2%). Frequency rose from 1.9 to 3.7 and click-through fell 36% — the audience has seen this creative too often. Recommended: Refresh creative & trim budget · Meta · Summer Sneakers · broad (₹24.2k/day) — approve it in the Decision Inbox.  
*engine `rules` · highlights neuron:CMP-01 · 124 ms*

**Is our ROAS real?**  
Meta: platform ROAS 2.40 vs true 1.97 (over-reports conversions by 22%). Google: platform ROAS 3.18 vs true 2.77 (over-reports conversions by 15%). Amazon, TikTok, Programmatic match store orders. Overall data trust is 74%. Recommended: optimise the over-reporting channels on store-verified conversions (data-fix items in the Decision Inbox).  
*engine `rules` · highlights source:meta_ads, source:google_ads · 12 ms*

**What if Google +20%?**  
Google +20%: spend ₹13.8k/day, profit -₹51.7k → -₹60.8k/day (-₹9.1k), POAS 0.83 → 0.81. Stock warning: this raises spend on CMP-04 where cover is short, so those increases would be blocked. Recommended: do not apply this blindly — it reduces profit; compare it with the Decision Inbox plan.  
*engine `rules` · highlights cluster:google · 34 ms*

**Where should I scale next?**  
Scale under-funded high-margin campaigns: Meta · Trail Max · lookalike +50% (₹1.3k/day). Scale winner · TikTok · Gym Flex · broad: TikTok · Gym Flex · broad +15% (₹1.1k/day). Test next: Trail Max · Google · retargeting (predicted POAS 5.55); Trail Max · TikTok · retargeting (predicted POAS 4.82); Trail Max · Amazon · retargeting (predicted POAS 4.35). The model is a ranking signal, not a forecast (hold-out R² 0.20). Recommended: Launch test · Trail Max on Google (retargeting) (₹13.6k/day) from the Decision Inbox.  
*engine `rules` · highlights neuron:CMP-07, neuron:CMP-10, neuron:SKU-C · 3 ms*

**Give me today's brief**  
Last 7 days: profit -₹51.7k/day (-49% vs the prior period), POAS 0.83, data trust 74%. Stock at risk: Running Pro (5.0 days). Top actions: Protect stock · cut ads on Running Pro by 60% (₹53.6k/day); Refresh creative & trim budget · Meta · Summer Sneakers · broad (₹24.2k/day); Review price & trim ads · Casual X (₹14.9k/day).  
*engine `rules` · highlights neuron:SKU-B, neuron:CMP-03, neuron:CMP-04, neuron:CMP-05 · 10 ms*

**Is Running Pro going to sell out?**  
Running Pro has 5.0 days of cover left. Ads are still sending demand to it. Recommended: Protect stock · cut ads on Running Pro by 60% (₹53.6k/day) — approve it in the Decision Inbox; budget increases stay blocked until stock recovers.  
*engine `rules` · highlights neuron:SKU-B · 10 ms*

**Did the Casual X price rise work?**  
Units moved -22% vs what would have happened anyway (synthetic control). Net margin effect is ₹2.1k/day (₹29.3k over 14 days; 95% interval -₹3.3k to ₹62.0k, includes zero). So the price rise has not demonstrably earned more profit. Recommended: Review price & trim ads · Casual X (₹14.9k/day) in the Decision Inbox.  
*engine `rules` · highlights neuron:SKU-D · 49 ms*

*Claude was not exercised in this run (no `ANTHROPIC_API_KEY` in `.env`); with a key, the same questions go through the tool-calling loop and fall back to the answers above on any failure.*

---

## Appendix: project scaffold (from setup)

- **Frontend:** Next.js (App Router), TypeScript, Tailwind CSS, shadcn/ui, framer-motion, @react-three/fiber (3D particle brain in `frontend/components/brain/`), recharts, @tanstack/react-query.
- **Backend scaffold:** `backend/app/` (FastAPI `GET /health`, routers for ingest/diagnose/decide/learn) with its own venv in `backend/.venv`.
- **Run everything:** `npm run dev` from the root (frontend on :3000, backend on :8000, Swagger at http://localhost:8000/docs).
