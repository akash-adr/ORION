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

## 12. Assumptions

_(Team: add assumptions here as they are made.)_

-

## 13. Common mistakes

- Percentages as `15` instead of `0.15`.
- Mixing ₹ totals (`spend_7d`) with ₹/day values.
- Using platform revenue as revenue (always use store/true revenue).
- Renaming fields mid-hackathon.
- Running files directly (`python backend/core/smoke_test.py`) instead of `python -m backend.core.smoke_test`.
- Committing `data/engine.db` or `data/state.json`.

---

## Appendix: project scaffold (from setup)

- **Frontend:** Next.js (App Router), TypeScript, Tailwind CSS, shadcn/ui, framer-motion, @react-three/fiber (3D particle brain in `frontend/components/brain/`), recharts, @tanstack/react-query.
- **Backend scaffold:** `backend/app/` (FastAPI `GET /health`, routers for ingest/diagnose/decide/learn) with its own venv in `backend/.venv`.
- **Run everything:** `npm run dev` from the root (frontend on :3000, backend on :8000, Swagger at http://localhost:8000/docs).
