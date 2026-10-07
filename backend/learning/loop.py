"""M7 closed-loop learning: the Neural Brain's "Learn" lobe.

The loop:  predict (M6 expected ₹/day) → execute (M6) → measure what happened → compare → calibrate → predict better.

HOW OUTCOMES ARE MEASURED
  Production: wait MEASURE_WINDOW_DAYS (7) after execution, then actual = profit after − profit before for the affected
  campaigns, compared with a HOLDOUT of similar unchanged campaigns or an M4b synthetic control (so seasonality and
  platform-wide shocks cancel out), using STORE orders (M2 truth), never platform-reported numbers.
  This demo: outcomes are SIMULATED from the prediction with a fixed seed, and every outcome is labelled
  `simulated: True`. That is the honest way to show the loop working before a week of real data exists; the numbers
  prove the mechanism, not the forecast quality of a real campaign.

WHAT LEARNING CHANGES
  * `state["calibration"]` {factor, mape, win_rate, n} from the last CALIBRATION_WINDOW measurable outcomes: M6
    multiplies every expected ₹ by `factor` and scales confidence by (1 − CONF_MAPE_WEIGHT × mape), so a historically
    optimistic engine promises less and asks for human approval more often.
  * Synapse strengths (campaign → SKU edges): good outcomes strengthen them, losses weaken them: the brain's memory.

Reproducible: each decision's randomness comes from a numpy RNG seeded by md5(decision_id).
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

from backend.core import config
from backend.core import metrics as m
from backend.core.config import (
    CALIBRATION_MAX, CALIBRATION_MIN, CALIBRATION_WINDOW, END_DATE, OUTCOME_BIAS_MEAN, OUTCOME_NOISE_SD,
    ROLLING_WINDOW, SEED_BIAS0, SEED_BIAS_DECAY, SEED_ERR_DECAY, SEED_ERR_SD0, SEED_HISTORY_N, SEED_PRED_MAX,
    SEED_PRED_MIN, SYNAPSE_BASE, SYNAPSE_DECAY, SYNAPSE_GAIN, SYNAPSE_GOOD_ERROR, SYNAPSE_MAX, SYNAPSE_MIN,
)
from backend.core.db import load_state, log_brain_event, save_state
from backend.core.schema import make_brain_event

SEED_DAYS_SPAN = 60  # seeded history is spread over the 60 days before END_DATE
SEED_LAST_OFFSET = 5  # ... the newest one lands this many days before END_DATE
SIMULATED_NOTE = ("Outcomes in this demo are simulated with a fixed seed; production measures against a holdout "
                  "or synthetic control after 7 days.")
DATA_QUALITY_NOTE = "data-quality action, not measured in ₹"

# Fixed, realistic past actions: (title, action_type, campaigns). Index i is the i-th oldest seeded outcome.
HISTORY = [
    ("Trim programmatic loss-makers", "budget_cut", ["CMP-12", "CMP-16"]),
    ("Scale Amazon Hiking Boot", "scale_up", ["CMP-13"]),
    ("Refresh TikTok creative", "creative_refresh", ["CMP-11"]),
    ("Rebalance Google bids", "bid_cap", ["CMP-02", "CMP-15"]),
    ("Cut Meta broad prospecting", "budget_cut", ["CMP-01"]),
    ("Scale Trail Max on Meta", "scale_up", ["CMP-07"]),
    ("Trim Casual X ads", "budget_cut", ["CMP-08", "CMP-09"]),
    ("Refresh Meta carousel creative", "creative_refresh", ["CMP-14"]),
    ("Scale Gym Flex on TikTok", "scale_up", ["CMP-10"]),
    ("Rebalance Google Running Pro", "bid_cap", ["CMP-04"]),
    ("Trim Slide Comfort on TikTok", "budget_cut", ["CMP-11"]),
    ("Scale Trail Max on Google", "scale_up", ["CMP-06"]),
]
assert len(HISTORY) >= SEED_HISTORY_N, "HISTORY needs at least SEED_HISTORY_N entries"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _rng(key: str) -> np.random.Generator:
    """Reproducible RNG: seeded by md5(key), so the same decision always produces the same simulated actual."""
    return np.random.default_rng(int(hashlib.md5(key.encode()).hexdigest()[:16], 16))


def _promotes() -> dict[str, str]:
    """campaign → SKU from the brain manifest's "promotes" synapses."""
    manifest = json.loads((Path(config.RAW_DIR) / "brain_manifest.json").read_text(encoding="utf-8"))
    return {e["source"]: e["target"] for e in manifest["synapses"] if e["kind"] == "promotes"}


def _campaign_edges(campaigns: list[str]) -> list[str]:
    edges = _promotes()
    return [f"{c}->{edges[c]}" for c in campaigns if c in edges]


def _edges_for(decision: dict, state: dict | None = None) -> list[str]:
    """Synapse keys ("CMP-07->SKU-C") a decision touches.

    Budget actions: the campaign→SKU `promotes` edge of every campaign in action.changes. Launch tests:
    f"{test_campaign_id}->{sku_id}" from state["launched_tests"]. Data fixes: none.
    """
    state = state if state is not None else load_state()
    action = decision["action"]
    if "launch" in action:
        return [f"{t['test_campaign_id']}->{t['sku_id']}" for t in state.get("launched_tests", []) if t["rec_id"] == decision["id"]]
    return _campaign_edges([c["campaign_id"] for c in action.get("changes", [])])


def _campaigns_for(decision: dict, state: dict) -> list[str]:
    if "launch" in decision["action"]:
        return [t["test_campaign_id"] for t in state.get("launched_tests", []) if t["rec_id"] == decision["id"]]
    return [c["campaign_id"] for c in decision["action"].get("changes", [])]


def _error(actual: float, predicted: float) -> float:
    return (actual - predicted) / abs(predicted)


def is_good(o: dict) -> bool:
    """A "good" outcome: measured, profitable and within SYNAPSE_GOOD_ERROR of the prediction."""
    return bool(o["measurable"] and o["actual"] > 0 and abs(o["error_pct"]) <= SYNAPSE_GOOD_ERROR)


# ---------------------------------------------------------------------------
# Synapse learning
# ---------------------------------------------------------------------------
def _apply_synapses(state: dict, outcome: dict) -> None:
    """Strengthen or weaken the outcome's synapses and record the APPLIED (post-clipping) delta so removal reverses exactly.

    good (actual > 0 and |error| ≤ 25%) → +SYNAPSE_GAIN · loss (actual ≤ 0) → −SYNAPSE_DECAY · otherwise → +SYNAPSE_GAIN / 2.
    Strength = clip(current (default SYNAPSE_BASE) + delta, SYNAPSE_MIN, SYNAPSE_MAX).
    """
    if is_good(outcome):
        delta = SYNAPSE_GAIN
    elif outcome["measurable"] and outcome["actual"] <= 0:
        delta = -SYNAPSE_DECAY
    else:
        delta = SYNAPSE_GAIN / 2
    strengths, applied = state.setdefault("synapse_strength", {}), {}
    for key in outcome["synapses"]:
        cur = strengths.get(key, SYNAPSE_BASE)
        new = round(float(np.clip(cur + delta, SYNAPSE_MIN, SYNAPSE_MAX)), 6)
        applied[key] = round(new - cur, 6)
        strengths[key] = new
    outcome["synapse_deltas"] = applied


# ---------------------------------------------------------------------------
# Calibration
# ---------------------------------------------------------------------------
def calibration(state: dict) -> dict:
    """{factor, mape, win_rate, n} from the last CALIBRATION_WINDOW MEASURABLE outcomes (seeded history included).

    mape = mean |error_pct|; factor = clip(mean(actual ÷ predicted), CALIBRATION_MIN, CALIBRATION_MAX), so one wild
    outcome can never swing M6 outside [0.6, 1.2]; win_rate = share with actual > 0. Empty → factor 1.0, others None.
    """
    rows = [o for o in state.get("outcomes", []) if o["measurable"]][-CALIBRATION_WINDOW:]
    if not rows:
        return {"factor": 1.0, "mape": None, "win_rate": None, "n": 0}
    ratios = [o["actual"] / o["predicted"] for o in rows]
    return {"factor": round(float(np.clip(np.mean(ratios), CALIBRATION_MIN, CALIBRATION_MAX)), 4),
            "mape": round(float(np.mean([abs(o["error_pct"]) for o in rows])), 4),
            "win_rate": round(float(np.mean([o["actual"] > 0 for o in rows])), 4), "n": len(rows)}


# ---------------------------------------------------------------------------
# Seeded history
# ---------------------------------------------------------------------------
def seed_history(state: dict) -> int:
    """Give the brain a past: add SEED_HISTORY_N seeded, simulated outcomes if none exist. Returns how many were added.

    Dates are spread evenly over the 60 days before END_DATE (oldest first). For outcome i:
      prediction ~ U(SEED_PRED_MIN, SEED_PRED_MAX);  error SD = SEED_ERR_SD0 × SEED_ERR_DECAY^i;
      optimism bias = SEED_BIAS0 × SEED_BIAS_DECAY^i;  actual = prediction × (1 + N(bias, SD)).
    Both the spread and the bias shrink with i, so the rolling forecast error falls over the history: the engine
    visibly learned. Synapses are updated too, so the brain starts with memory. The history is the past: it emits no
    brain events.
    """
    if any(o.get("seeded") for o in state.get("outcomes", [])):
        return 0
    rng = _rng("seed_history")
    end = datetime.strptime(END_DATE, "%Y-%m-%d")
    offsets = np.rint(np.linspace(SEED_DAYS_SPAN, SEED_LAST_OFFSET, SEED_HISTORY_N)).astype(int)
    seeded = []
    for i in range(SEED_HISTORY_N):
        predicted = float(rng.uniform(SEED_PRED_MIN, SEED_PRED_MAX))
        sd, bias = SEED_ERR_SD0 * SEED_ERR_DECAY ** i, SEED_BIAS0 * SEED_BIAS_DECAY ** i
        actual = predicted * (1 + float(rng.normal(bias, sd)))
        title, action_type, campaigns = HISTORY[i]
        date = (end - timedelta(days=int(offsets[i]))).strftime("%Y-%m-%d")
        o = {"decision_id": f"HIST-{i + 1:02d}", "title": title, "date": date, "predicted": round(predicted, 2),
             "actual": round(actual, 2), "error_pct": round(_error(actual, predicted), 4), "simulated": True,
             "seeded": True, "action_type": action_type, "campaigns": list(campaigns),
             "synapses": _campaign_edges(campaigns), "synapse_deltas": {}, "measurable": True,
             "note": "historical outcome (seeded)", "measured_at": f"{date}T09:00:00"}
        seeded.append(o)
    state["outcomes"] = seeded + [o for o in state.get("outcomes", []) if not o.get("seeded")]
    for o in seeded:
        _apply_synapses(state, o)
    return len(seeded)


def _ensure_seeded(state: dict) -> bool:
    """Seed the history on first use (so deleting state.json resets cleanly) and refresh the calibration."""
    added = seed_history(state)
    if added:
        state["calibration"] = calibration(state)
    return bool(added)


# ---------------------------------------------------------------------------
# Measuring outcomes
# ---------------------------------------------------------------------------
def measure_outcome(decision: dict, state: dict | None = None) -> dict:
    """The outcome record for one executed decision.

    DEMO (simulated, always labelled): actual = predicted × (1 + N(OUTCOME_BIAS_MEAN, OUTCOME_NOISE_SD)) with an RNG
    seeded by md5(decision_id), so the same decision always yields the same actual.

    PRODUCTION: wait MEASURE_WINDOW_DAYS after execution, then actual = profit after − profit before for the affected
    campaigns, minus the same change on a HOLDOUT of similar unchanged campaigns (or an M4b synthetic control), using
    store orders (M2 truth) and never platform-reported numbers.

    A decision with |predicted| < ₹1 (a data fix) is not measurable in ₹: it is recorded but kept out of MAPE and
    calibration.
    """
    state = state if state is not None else load_state()
    predicted = float(decision["expected_profit_delta"])
    base = {"decision_id": decision["id"], "title": decision["title"], "date": (decision.get("executed_at") or "")[:10],
            "predicted": round(predicted, 2), "simulated": True, "seeded": False, "action_type": decision["action"]["type"],
            "campaigns": _campaigns_for(decision, state), "synapses": _edges_for(decision, state), "synapse_deltas": {},
            "measured_at": decision.get("executed_at")}
    if abs(predicted) < 1:
        return {**base, "actual": 0.0, "error_pct": None, "measurable": False, "note": DATA_QUALITY_NOTE}
    actual = predicted * (1 + float(_rng(decision["id"]).normal(OUTCOME_BIAS_MEAN, OUTCOME_NOISE_SD)))
    return {**base, "actual": round(actual, 2), "error_pct": round(_error(actual, predicted), 4), "measurable": True,
            "note": "simulated outcome (fixed seed)"}


def _outcome_message(o: dict) -> str:
    if not o["measurable"]:
        return f"{o['title']}: applied — {DATA_QUALITY_NOTE}"
    return (f"{o['title']}: predicted {m.format_inr(o['predicted'])}/day → actual {m.format_inr(o['actual'])}/day "
            f"({o['error_pct']:+.0%}) · simulated")


def record_outcomes(emit_brain_events: bool = True) -> list[dict]:
    """Measure every EXECUTED decision that has no outcome yet, learn from it and (optionally) pulse the Learn lobe.

    Appends the outcomes, updates synapse strengths, recomputes state["calibration"], saves, then emits one "outcome"
    event per new outcome (seeded history emits none). Returns the new outcomes.
    """
    state = load_state()
    _ensure_seeded(state)
    have = {o["decision_id"] for o in state["outcomes"]}
    new = []
    for d in state["decisions"]:
        if d["status"] == "executed" and d["id"] not in have:
            o = measure_outcome(d, state)
            state["outcomes"].append(o)
            _apply_synapses(state, o)
            new.append(o)
    state["calibration"] = calibration(state)
    save_state(state)
    if emit_brain_events:
        decisions = {d["id"]: d for d in state["decisions"]}
        for o in new:
            d = decisions[o["decision_id"]]
            entity = (o["campaigns"] or [(d["action"].get("targets") or [{"id": None}])[0]["id"]])[0]
            strengths = state["synapse_strength"]
            log_brain_event(make_brain_event(
                "outcome", entity_id=entity, ref_id=o["decision_id"],
                severity="low" if (is_good(o) or not o["measurable"]) else "medium", message=_outcome_message(o),
                payload={"decision_id": o["decision_id"], "predicted": o["predicted"], "actual": o["actual"],
                         "error_pct": o["error_pct"], "simulated": True, "measurable": o["measurable"],
                         "synapses": [{"key": k, "strength": strengths[k], "delta": o["synapse_deltas"].get(k, 0.0)}
                                      for k in o["synapses"]],
                         "calibration": state["calibration"]}))
    return new


def remove_outcome(decision_id: str) -> dict | None:
    """Undo a decision's outcome (used on rollback): reverse its synapse deltas EXACTLY and recompute the calibration."""
    state = load_state()
    o = next((x for x in state["outcomes"] if x["decision_id"] == decision_id and not x.get("seeded")), None)
    if o is None:
        return None
    for key, delta in o["synapse_deltas"].items():
        state["synapse_strength"][key] = round(state["synapse_strength"][key] - delta, 6)
    state["outcomes"] = [x for x in state["outcomes"] if x is not o]
    state["calibration"] = calibration(state)
    save_state(state)
    return o


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
def rolling_mape(outcomes: list[dict], window: int = ROLLING_WINDOW) -> list[dict]:
    """Rolling MAPE over measurable outcomes, oldest → newest: one point per outcome (a partial window at the start)."""
    rows = [o for o in outcomes if o["measurable"]]
    return [{"index": i + 1, "date": o["date"], "decision_id": o["decision_id"],
             "rolling_mape": round(float(np.mean([abs(x["error_pct"]) for x in rows[max(0, i - window + 1): i + 1]])), 4)}
            for i, o in enumerate(rows)]


def learning_report() -> dict:
    """Everything the Learning page needs: outcomes (newest first), accuracy curve, cumulative profit, calibration,
    synapse strengths and KPIs. Seeds the history on first use."""
    state = load_state()
    if _ensure_seeded(state):
        save_state(state)
    outcomes = state["outcomes"]
    measurable = [o for o in outcomes if o["measurable"]]
    cumulative, total = [], 0.0
    for o in outcomes:
        total += o["actual"]
        cumulative.append({"date": o["date"], "cumulative": round(total, 2)})
    cal = state["calibration"]
    return {
        "outcomes": list(reversed(outcomes)), "accuracy_curve": rolling_mape(outcomes), "cumulative_profit": cumulative,
        "calibration": cal, "synapse_strength": dict(state["synapse_strength"]),
        "kpis": {"forecast_error": cal["mape"], "calibration_factor": cal["factor"], "win_rate": cal["win_rate"],
                 "measured_count": len(measurable), "total_measured_profit": round(sum(o["actual"] for o in measurable), 2)},
        "simulated_note": SIMULATED_NOTE,
    }
