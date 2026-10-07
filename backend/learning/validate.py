"""M7 validation. Run from the project root:  python -m backend.learning.validate

Every check runs on a TEMPORARY state file (the real state.json is never touched) with a fixed clock; prints
PASS / FAIL and the demo numbers; exit 1 on any failure. Each check is `check_*() -> (ok, detail)`.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable

import numpy as np

from backend.core import config
from backend.core.config import (
    CALIBRATION_MAX, CALIBRATION_MIN, CALIBRATION_WINDOW, CONF_MAPE_WEIGHT, CONFIDENCE_MIN, ROLLING_WINDOW,
    SEED_HISTORY_N, SYNAPSE_BASE, SYNAPSE_DECAY, SYNAPSE_GAIN, SYNAPSE_MAX, SYNAPSE_MIN,
)
from backend.core.db import default_state, load_state, read_brain_events
from backend.decisions import engine as e
from backend.decisions.validate import by_type, temp_state
from backend.learning import loop
from backend.learning.runner import first_last_rolling

DEMO: dict = {}  # demo numbers collected while the checks run


def _seeded_state() -> dict:
    state = default_state()
    loop.seed_history(state)
    state["calibration"] = loop.calibration(state)
    return state


def _approve_top() -> tuple[dict, dict]:
    """In the current temp state: refresh, approve the top-ranked decision (supervised) and return (decision, result)."""
    top = e.refresh_decisions(emit_brain_events=False)["pending"][0]
    return top, e.approve(top["id"], emit_brain_events=False)


def _outcome(decision_id: str) -> dict | None:
    return next((o for o in load_state()["outcomes"] if o["decision_id"] == decision_id), None)


# ---------------------------------------------------------------------------
def check_seed_history():
    state = default_state()
    n1 = loop.seed_history(state)
    seeded = [o for o in state["outcomes"] if o["seeded"]]
    n2 = loop.seed_history(state)
    ok = n1 == SEED_HISTORY_N == len(seeded) and all(o["simulated"] for o in seeded) and n2 == 0 and len(state["outcomes"]) == SEED_HISTORY_N
    return ok, f"{n1} seeded, simulated outcomes; a second call added {n2}"


def check_mape_trend():
    state = _seeded_state()
    curve = loop.rolling_mape(state["outcomes"])
    full = [p["rolling_mape"] for p in curve[ROLLING_WINDOW - 1:]]
    slope = float(np.polyfit(np.arange(len(full)), full, 1)[0])
    first, last = first_last_rolling(curve)
    DEMO["first_rolling_mape"], DEMO["last_rolling_mape"] = first, last
    return first > last and slope < 0, f"rolling MAPE {first:.1%} → {last:.1%} (slope {slope:+.4f} per step)"


def check_calibration():
    state = _seeded_state()
    cal = state["calibration"]
    rows = [o for o in state["outcomes"] if o["measurable"]][-CALIBRATION_WINDOW:]
    factor = float(np.clip(np.mean([o["actual"] / o["predicted"] for o in rows]), CALIBRATION_MIN, CALIBRATION_MAX))
    mape = float(np.mean([abs(o["error_pct"]) for o in rows]))
    win = float(np.mean([o["actual"] > 0 for o in rows]))
    DEMO.update(mape=cal["mape"], factor=cal["factor"], win_rate=cal["win_rate"])
    ok = (CALIBRATION_MIN <= cal["factor"] <= CALIBRATION_MAX and abs(cal["factor"] - factor) < 1e-3
          and abs(cal["mape"] - mape) < 1e-3 and abs(cal["win_rate"] - win) < 1e-3 and cal["n"] == len(rows) == CALIBRATION_WINDOW)
    return ok, f"MAPE {cal['mape']:.1%} · factor {cal['factor']:.3f} · win-rate {cal['win_rate']:.0%} (last {cal['n']} outcomes)"


def check_hook_records_outcome():
    with temp_state():
        top, res = _approve_top()
        o = _outcome(top["id"])
        DEMO["approved"] = (top["title"], o["predicted"], o["actual"], o["error_pct"]) if o else None
        ok = (res["ok"] and o is not None and o["predicted"] == round(top["expected_profit_delta"], 2) and o["simulated"] is True
              and o["seeded"] is False and o["measurable"] and o["actual"] != o["predicted"])
        return ok, (f"{top['title']}: predicted {o['predicted']:,.0f} → actual {o['actual']:,.0f} ({o['error_pct']:+.1%}), simulated"
                    if o else "no outcome recorded")


def check_determinism():
    actuals = []
    for _ in range(2):  # two separate runs, each from a fresh state
        with temp_state():
            top, _ = _approve_top()
            actuals.append(_outcome(top["id"])["actual"])
    again = loop.measure_outcome({**top, "executed_at": "2026-10-07T12:00:00"}, default_state())["actual"]
    return actuals[0] == actuals[1] == again, f"same decision id → identical actual ({actuals[0]:,.2f}) across runs"


def check_synapses():
    with temp_state():
        before = _seeded_state()["synapse_strength"]  # the seeded history is deterministic: this is the pre-approval memory
        top, _ = _approve_top()
        o = _outcome(top["id"])
        after = load_state()["synapse_strength"]
        good = o["actual"] > 0 and abs(o["error_pct"]) <= config.SYNAPSE_GOOD_ERROR
        expect = SYNAPSE_GAIN if good else (-SYNAPSE_DECAY if o["actual"] <= 0 else SYNAPSE_GAIN / 2)
        bad = []
        for key in o["synapses"]:
            want = float(np.clip(before.get(key, SYNAPSE_BASE) + expect, SYNAPSE_MIN, SYNAPSE_MAX))
            if abs(after[key] - want) > 1e-5 or not SYNAPSE_MIN <= after[key] <= SYNAPSE_MAX:
                bad.append(key)
        ok = bool(o["synapses"]) and not bad and set(o["synapse_deltas"]) == set(o["synapses"])
        return ok, f"{', '.join(f'{k} {before.get(k, SYNAPSE_BASE):.2f}→{after[k]:.2f}' for k in o['synapses'])} (delta {expect:+.3f})"


def check_rollback():
    with temp_state():
        top, _ = _approve_top()
        after_exec = load_state()
        e.rollback(top["id"], emit_brain_events=False)
        st = load_state()
        base = _seeded_state()
        same = all(abs(st["synapse_strength"].get(k, SYNAPSE_BASE) - base["synapse_strength"].get(k, SYNAPSE_BASE)) < 1e-9
                   for k in set(st["synapse_strength"]) | set(base["synapse_strength"]))
        ok = _outcome(top["id"]) is None and same and st["calibration"] == loop.calibration(st) == base["calibration"]
        moved = after_exec["calibration"] != base["calibration"]  # informative: executing really changed the calibration
        return ok, ("outcome removed, synapse deltas reversed exactly, calibration recomputed back to the seeded one"
                    + (" (it had moved after execution)" if moved else ""))


def check_data_fix_not_measured():
    with temp_state():
        out = e.refresh_decisions(emit_brain_events=False)
        loop.record_outcomes(emit_brain_events=False)
        before = load_state()["calibration"]
        fix = by_type(out["pending"], "data_fix", "Google")
        e.approve(fix["id"], emit_brain_events=False)
        o = _outcome(fix["id"])
        after = load_state()["calibration"]
        ok = o is not None and o["measurable"] is False and o["error_pct"] is None and o["actual"] == 0.0 and before == after
        return ok, f"data fix recorded as measurable=False; calibration unchanged ({after['n']} measurable outcomes)"


def check_m6_uses_calibration():
    with temp_state():
        base = {r.id: r for r in e.build_recommendations()["recommendations"]}  # no history yet: factor 1.0, MAPE None
        loop.learning_report()  # seeds the history and the calibration
        cal = load_state()["calibration"]
        new = {r.id: r for r in e.build_recommendations()["recommendations"]}
        bad, checked_conf = [], 0
        for rid, old in base.items():
            n = new[rid]
            if abs(n.expected_profit_delta - round(old.expected_profit_delta * cal["factor"], 2)) > 0.02:
                bad.append((rid, "expected"))
            if old.confidence > CONFIDENCE_MIN + 1e-6 and n.confidence > CONFIDENCE_MIN + 1e-6:
                checked_conf += 1
                if abs(n.confidence - old.confidence * (1 - CONF_MAPE_WEIGHT * cal["mape"])) > 1e-3:
                    bad.append((rid, "confidence"))
        ok = not bad and checked_conf > 0 and cal["factor"] != 1.0
        return ok, f"expected ₹ × {cal['factor']:.3f}; confidence × (1 − {CONF_MAPE_WEIGHT} × {cal['mape']:.3f}) on {checked_conf} unclipped items"


def check_report_shape():
    with temp_state():
        top, _ = _approve_top()
        r = loop.learning_report()
        keys = {"outcomes", "accuracy_curve", "cumulative_profit", "calibration", "synapse_strength", "kpis", "simulated_note"}
        asc = list(reversed(r["outcomes"]))
        running = np.cumsum([o["actual"] for o in asc])
        ok = (keys <= set(r) and "simulated" in r["simulated_note"] and {"forecast_error", "calibration_factor", "win_rate",
              "measured_count", "total_measured_profit"} <= set(r["kpis"]) and len(r["accuracy_curve"]) == r["kpis"]["measured_count"]
              and all(abs(c["cumulative"] - float(v)) < 0.01 for c, v in zip(r["cumulative_profit"], running))
              and r["outcomes"][0]["decision_id"] == top["id"])
        return ok, f"{len(r['outcomes'])} outcomes (newest first), {len(r['accuracy_curve'])} curve points, cumulative = running Σ actual"


def check_brain_events():
    with temp_state():
        out = e.refresh_decisions(emit_brain_events=False)
        loop.record_outcomes()  # seeds the history; nothing is executed yet
        seeded_events = [x for x in read_brain_events(limit=500) if x["type"] == "outcome"]
        e.approve(by_type(out["pending"], "inventory_protect")["id"], emit_brain_events=True)
        outcomes = [x for x in read_brain_events(limit=500) if x["type"] == "outcome"]
        again = loop.record_outcomes()
        outcomes2 = [x for x in read_brain_events(limit=500) if x["type"] == "outcome"]
        ev = outcomes[0] if outcomes else {}
        ok = (not seeded_events and len(outcomes) == 1 and len(outcomes2) == 1 and again == []
              and ev["region"] == "learn" and ev["path"] == ["learn"] and ev["payload"]["simulated"] is True
              and ev["entity_id"] == "CMP-03" and len(ev["payload"]["synapses"]) == 3 and "predicted" in ev["message"])
        return bool(ok), f"seeded history logged 0, approval logged {len(outcomes)} outcome event, re-run logged {len(outcomes2) - len(outcomes)}: {ev.get('message', '')[:90]}"


def check_reset():
    with temp_state():
        first = loop.learning_report()
        Path(config.STATE_PATH).unlink()
        second = loop.learning_report()
        same = first["outcomes"] == second["outcomes"] and first["synapse_strength"] == second["synapse_strength"]
        return same and len(second["outcomes"]) == SEED_HISTORY_N, "deleting state.json regenerates the identical seeded history"


CHECKS: list[tuple[str, Callable[[], tuple[bool, str]]]] = [
    ("1  seed history, once", check_seed_history),
    ("2  rolling MAPE falls", check_mape_trend),
    ("3  calibration", check_calibration),
    ("4  hook records the outcome", check_hook_records_outcome),
    ("5  deterministic actuals", check_determinism),
    ("6  synapse learning", check_synapses),
    ("7  rollback reverses", check_rollback),
    ("8  data fix not measured", check_data_fix_not_measured),
    ("9  M6 uses calibration", check_m6_uses_calibration),
    ("10 learning_report shape", check_report_shape),
    ("11 brain events", check_brain_events),
    ("12 clean reset", check_reset),
]


def run_checks() -> list[tuple[str, bool, str]]:
    results = []
    for name, fn in CHECKS:
        try:
            ok, detail = fn()
        except Exception as exc:  # a crashing check is a failing check
            ok, detail = False, f"error: {exc!r}"
        results.append((name, bool(ok), detail))
    return results


def main() -> int:
    real = Path(config.STATE_PATH).read_bytes() if Path(config.STATE_PATH).exists() else None
    results = run_checks()
    width = max(len(n) for n, _, _ in results)
    print(f"{'check'.ljust(width)}  result  detail")
    print("-" * (width + 90))
    for name, ok, detail in results:
        print(f"{name.ljust(width)}  {'PASS' if ok else 'FAIL'}    {detail}")
    failed = sum(not ok for _, ok, _ in results)
    after = Path(config.STATE_PATH).read_bytes() if Path(config.STATE_PATH).exists() else None
    print("-" * (width + 90))
    print(f"M7 validation: {len(results) - failed}/{len(results)} PASS" + (f", {failed} FAIL" if failed else "")
          + ("  (real state.json untouched)" if real == after else "  (WARNING: real state.json changed!)"))
    if all(k in DEMO for k in ("mape", "first_rolling_mape")):
        a = DEMO.get("approved")
        print(f"\nDEMO NUMBERS: MAPE (last {CALIBRATION_WINDOW}) {DEMO['mape']:.1%} · calibration factor {DEMO['factor']:.3f} · "
              f"win-rate {DEMO['win_rate']:.0%} · rolling MAPE {DEMO['first_rolling_mape']:.1%} → {DEMO['last_rolling_mape']:.1%}")
        if a:
            print(f"APPROVED DECISION: {a[0]} · predicted ₹{a[1]:,.0f}/day → actual ₹{a[2]:,.0f}/day ({a[3]:+.1%}) · simulated")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
