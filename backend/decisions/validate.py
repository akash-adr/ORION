"""M6 validation. Run from the project root:  python -m backend.decisions.validate

Every check runs on a TEMPORARY state file (the real state.json is never touched) with a fixed clock, and prints
PASS / FAIL; exit 1 on any failure. Each check is `check_*() -> (ok, detail)` so tests/test_m6.py can reuse them.
"""
from __future__ import annotations

import re
import sys
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Callable

from backend.core import config
from backend.core.config import CONFIDENCE_MAX, CONFIDENCE_MIN, OPP_TEST_BUDGET, STOCK_COVER_RISK_DAYS
from backend.core.db import load_state, read_brain_events, save_state
from backend.decisions import engine as e
from backend.decisions import hooks
from backend.optimizer.curves import fit_curves

FIXED_NOW = datetime(2026, 10, 7, 12, 0, 0)
LOW_STOCK = ("CMP-03", "CMP-04", "CMP-05")
MAX_REFRESH_S = 2.0


@contextmanager
def temp_state(autonomy: str = "supervised"):
    """A throwaway state.json + fixed clock; restores the real path and clock afterwards."""
    original = config.STATE_PATH
    with tempfile.TemporaryDirectory() as tmp:
        config.STATE_PATH = Path(tmp) / "state.json"
        e.set_clock(lambda: FIXED_NOW)
        try:
            if autonomy != "supervised":
                e.set_autonomy(autonomy)
            yield
        finally:
            config.STATE_PATH = original
            e.set_clock(None)
            fit_curves(refresh=True)


def by_type(pending: list[dict], action_type: str, contains: str | None = None) -> dict:
    return next(d for d in pending if d["action"]["type"] == action_type and (contains is None or contains in d["title"]))


def original_spend() -> dict:
    return fit_curves().set_index("campaign_id")["current_spend"].to_dict()


# ---------------------------------------------------------------------------
def check_inbox_shape():
    with temp_state():
        recs = e.build_recommendations()["recommendations"]
    top = recs[0]
    ok = len(recs) >= 6 and top.action["type"] == "inventory_protect" and any(t["id"] == "SKU-B" for t in top.action["targets"])
    return ok, f"{len(recs)} recommendations; top: {top.title} ({top.action['type']})"


def check_no_double_cover():
    with temp_state():
        recs = e.build_recommendations()["recommendations"]
    seen, dupes = {}, []
    for r in recs:
        for c in r.action["changes"]:
            if c["campaign_id"] in seen:
                dupes.append(c["campaign_id"])
            seen[c["campaign_id"]] = r.id
    return not dupes, f"{len(seen)} campaigns, each in exactly one recommendation" if not dupes else f"in two: {dupes}"


def check_no_low_stock_raise():
    with temp_state():
        recs = e.build_recommendations()["recommendations"]
    bad = [(r.title, c["campaign_id"]) for r in recs for c in r.action["changes"]
           if c["campaign_id"] in LOW_STOCK and c["to_budget"] > c["from_budget"] and not r.blocked]
    return not bad, "CMP-03/04/05 are never raised (and a raise would be blocked)" if not bad else f"unblocked raise: {bad}"


def check_scoring_formulas():
    with temp_state():
        out = e.build_recommendations()
        brand = float(fit_curves()["current_spend"].sum())
    bad = []
    for r in out["recommendations"]:
        if not CONFIDENCE_MIN <= r.confidence <= CONFIDENCE_MAX:
            bad.append((r.id, "confidence"))
        shift = OPP_TEST_BUDGET / brand if r.action["type"] == "launch_test" else e._shift(r.action["changes"], brand)
        risk = e._risk(shift, r.expected_profit_delta)
        if r.risk != risk or r.requires_approval != e._requires_approval(risk, shift):
            bad.append((r.id, "risk/approval"))
    return not bad, "confidence in [0.45, 0.95]; risk and approval match the formulas" if not bad else f"mismatch: {bad}"


def check_stable_ids():
    with temp_state():
        a, b = e.build_recommendations()["recommendations"], e.build_recommendations()["recommendations"]
    stable = [r.id for r in a] == [r.id for r in b] and len({r.id for r in a}) == len(a)
    clean = not any("₹" in r.title for r in a)
    return stable and clean, "ids stable across two builds; no ₹ amount in any title" if stable and clean else "unstable ids or ₹ in a title"


def check_supervised_execute():
    calls = []
    original_hook = hooks.on_executed
    hooks.on_executed = lambda d, entry: calls.append(d["id"])
    try:
        with temp_state():
            before = original_spend()
            d = by_type(e.refresh_decisions(emit_brain_events=False)["pending"], "inventory_protect")
            res = e.approve(d["id"], emit_brain_events=False)
            st = load_state()
            entry = st["audit"][-1]
            prev = {r["campaign_id"]: r["budget"] for r in entry["rollback"]}
            exact = all(abs(prev[c["campaign_id"]] - before[c["campaign_id"]]) < 0.01 for c in d["action"]["changes"])
            ok = (res["ok"] and len(res["api_calls"]) == len(d["action"]["changes"]) and exact and entry["action"] == "execute"
                  and all(st["budget_overrides"][c["campaign_id"]] == c["to_budget"] for c in d["action"]["changes"])
                  and next(x for x in st["decisions"] if x["id"] == d["id"])["status"] == "executed" and calls == [d["id"]])
            return ok, f"{len(res.get('api_calls', []))} API calls, previous budgets recorded, overrides set, hook called {len(calls)}×"
    finally:
        hooks.on_executed = original_hook


def check_closed_loop():
    with temp_state():
        d = by_type(e.refresh_decisions(emit_brain_events=False)["pending"], "inventory_protect")
        e.approve(d["id"], emit_brain_events=False)
        now = fit_curves().set_index("campaign_id")["current_spend"]
        target = next(c["to_budget"] for c in d["action"]["changes"] if c["campaign_id"] == "CMP-03")
    return abs(now["CMP-03"] - target) < 0.01, f"CMP-03 current_spend is now {now['CMP-03']:,.0f} (the approved budget)"


def check_refresh_keeps_executed():
    with temp_state():
        d = by_type(e.refresh_decisions(emit_brain_events=False)["pending"], "inventory_protect")
        e.approve(d["id"], emit_brain_events=False)
        after = e.refresh_decisions(emit_brain_events=False)
        statuses = [x["status"] for x in after["decisions"] if x["id"] == d["id"]]
    return statuses == ["executed"], f"after refresh the decision is {statuses}, never a pending duplicate"


def check_rollback():
    with temp_state():
        before = original_spend()
        d = by_type(e.refresh_decisions(emit_brain_events=False)["pending"], "inventory_protect")
        e.approve(d["id"], emit_brain_events=False)
        res = e.rollback(d["id"], emit_brain_events=False)
        st = load_state()
        now = original_spend()
        ok = (res["ok"] and not st["budget_overrides"] and st["audit"][-1]["action"] == "rollback"
              and next(x for x in st["decisions"] if x["id"] == d["id"])["status"] == "rolled_back"
              and all(abs(now[k] - before[k]) < 0.01 for k in before))
    return ok, f"overrides removed, status rolled_back, curves back to the original spend, {len(res.get('api_calls', []))} API calls"


def check_hard_block():
    with temp_state():
        e.refresh_decisions(emit_brain_events=False)
        st = load_state()
        base = float(fit_curves().set_index("campaign_id").at["CMP-03", "current_spend"])
        change = {"campaign_id": "CMP-03", "name": "Meta · Running Pro · lookalike", "channel": "meta",
                  "from_budget": base, "to_budget": round(base * 1.2, 2)}
        fake = {"id": "REC-bad001", "title": "Test: raise Running Pro", "issue": "", "cause": "", "expected_profit_delta": 1.0,
                "confidence": 0.9, "risk": "low", "requires_approval": False, "blocked": False, "priority": 1.0, "evidence": [],
                "anomaly_id": None, "status": "pending", "action": {"type": "scale_up", "changes": [change], "targets": [], "notes": []}}
        st["decisions"].append(fake)
        save_state(st)
        res = e.approve("REC-bad001", emit_brain_events=False)  # stored blocked=False: caught by the execution-time re-check
        st = load_state()
        st["decisions"][-1]["blocked"] = True
        save_state(st)
        res2 = e.approve("REC-bad001", emit_brain_events=False)
        ok = (not res["ok"] and "Blocked by guardrail" in res["reason"] and not res2["ok"] and "Blocked by guardrail" in res2["reason"]
              and "CMP-03" not in load_state()["budget_overrides"])
    return ok, res["reason"]


def check_advisory():
    with temp_state("advisory"):
        d = by_type(e.refresh_decisions(emit_brain_events=False)["pending"], "inventory_protect")
        res = e.approve(d["id"], emit_brain_events=False)
        untouched = not load_state()["budget_overrides"]
    return (not res["ok"]) and "Advisory mode" in res["reason"] and untouched, res.get("reason", "executed!")


def check_autopilot():
    with temp_state("autonomous"):
        out = e.refresh_decisions(emit_brain_events=False)
        st = load_state()
        ran = [x for x in st["decisions"] if x["status"] == "executed"]
        pending = [x for x in st["decisions"] if x["status"] == "pending"]
        approvers = {a["approver"] for a in st["audit"] if a["action"] == "execute"}
        ok = (bool(ran) and all(not x["requires_approval"] and not x["blocked"] and x["risk"] == "low" for x in ran)
              and approvers == {"autopilot"} and all(x["requires_approval"] or x["blocked"] for x in pending)
              and {x["action"]["type"] for x in ran} == {"launch_test", "data_fix"})
    return ok, f"autopilot executed {len(ran)} low-risk items ({sorted({x['action']['type'] for x in ran})}); {len(pending)} still wait for a human"


def check_reject():
    with temp_state():
        d = by_type(e.refresh_decisions(emit_brain_events=False)["pending"], "creative_refresh")
        res = e.reject(d["id"], reason="not now", emit_brain_events=False)
        again = e.refresh_decisions(emit_brain_events=False)
        st = load_state()
        status = [x["status"] for x in again["decisions"] if x["id"] == d["id"]]
        ok = res["ok"] and status == ["rejected"] and st["audit"][-1]["action"] == "reject" and not st["budget_overrides"]
    return ok, f"rejected, audited, and still {status} after a refresh"


def check_launch_test():
    with temp_state():
        d = by_type(e.refresh_decisions(emit_brain_events=False)["pending"], "launch_test")
        res = e.approve(d["id"], emit_brain_events=False)
        t = load_state()["launched_tests"]
        launched = res["ok"] and len(t) == 1 and t[0]["test_campaign_id"].startswith("TST-") and t[0]["status"] == "running"
        rb = e.rollback(d["id"], emit_brain_events=False)
        paused = rb["ok"] and load_state()["launched_tests"][0]["status"] == "paused" and rb["api_calls"][0]["status"] == "PAUSED"
    return launched and paused, f"{t[0]['test_campaign_id']} launched, then paused on rollback"


def check_data_fix():
    with temp_state():
        d = by_type(e.refresh_decisions(emit_brain_events=False)["pending"], "data_fix", "Google")
        res = e.approve(d["id"], emit_brain_events=False)
        fixed = load_state()["data_fixes"].get("google", {}).get("conversion_source") == "server_side"
        rb = e.rollback(d["id"], emit_brain_events=False)
        removed = "google" not in load_state()["data_fixes"] and rb["api_calls"][0]["conversion_source"] == "platform"
    return res["ok"] and fixed and removed, "data_fixes[google] recorded on approval and removed on rollback"


def check_brain_events():
    with temp_state():
        n = len(e.refresh_decisions()["pending"])
        recs = read_brain_events(limit=500)
        ok = len(recs) == n and all(x["type"] == "recommendation" and x["path"] == ["diagnose", "decide"] for x in recs)
        again = e.refresh_decisions()["events_logged"]
        stock = by_type(load_state()["decisions"], "inventory_protect")
        e.approve(stock["id"])
        ap = read_brain_events(limit=500)[-1]
        ok &= ap["type"] == "approval" and ap["path"] == ["decide", "learn"] and len(ap["payload"]["synapses"]) == 3
        e.set_autonomy("autonomous")
        e.auto_apply()
        auto = [x for x in read_brain_events(limit=500) if x["type"] == "auto_apply"]
        ok &= bool(auto) and auto[0]["path"] == ["decide", "learn"] and auto[0]["payload"]["approver"] == "autopilot"
        e.set_autonomy("supervised")
        cr = by_type(load_state()["decisions"], "creative_refresh")
        e.reject(cr["id"])
        rej = read_brain_events(limit=500)[-1]
        ok &= rej["type"] == "rejection" and rej["path"] == ["decide"]
        e.rollback(stock["id"])
        rb = read_brain_events(limit=500)[-1]
        ok &= rb["type"] == "rollback" and rb["path"] == ["learn", "decide"] and len(rb["payload"]["restored"]) == 3
    return bool(ok) and again == 0, f"{n} recommendation pulses (re-refresh: {again}), then approval / auto_apply / rejection / rollback pulses"


def check_speed():
    with temp_state():
        t0 = time.perf_counter()
        e.refresh_decisions(emit_brain_events=False)
        elapsed = time.perf_counter() - t0
    return elapsed < MAX_REFRESH_S, f"refresh_decisions {elapsed * 1000:.0f} ms"


CHECKS: list[tuple[str, Callable[[], tuple[bool, str]]]] = [
    ("1  inbox shape, stockout on top", check_inbox_shape),
    ("2  no campaign in two recs", check_no_double_cover),
    ("3  no low-stock raise", check_no_low_stock_raise),
    ("4  scoring formulas", check_scoring_formulas),
    ("5  stable ids, no ₹ in titles", check_stable_ids),
    ("6  supervised execute + audit", check_supervised_execute),
    ("7  closed loop into M5", check_closed_loop),
    ("8  refresh keeps executed", check_refresh_keeps_executed),
    ("9  rollback restores", check_rollback),
    ("10 hard block", check_hard_block),
    ("11 advisory refuses", check_advisory),
    ("12 autopilot scope", check_autopilot),
    ("13 reject sticks", check_reject),
    ("14 launch test + pause", check_launch_test),
    ("15 data fix + undo", check_data_fix),
    ("16 brain events", check_brain_events),
    ("17 refresh speed", check_speed),
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
    print("-" * (width + 80))
    for name, ok, detail in results:
        print(f"{name.ljust(width)}  {'PASS' if ok else 'FAIL'}    {detail}")
    failed = sum(not ok for _, ok, _ in results)
    after = Path(config.STATE_PATH).read_bytes() if Path(config.STATE_PATH).exists() else None
    print("-" * (width + 80))
    print(f"M6 validation: {len(results) - failed}/{len(results)} PASS" + (f", {failed} FAIL" if failed else "")
          + ("  (real state.json untouched)" if real == after else "  (WARNING: real state.json changed!)"))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
