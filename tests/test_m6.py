"""M6 tests: recommendation builder, guardrails, executor, rollback, autopilot, audit and brain events.

M1 data is generated and M2 / M3 run inside a pytest temp folder; config.RAW_DIR / DB_PATH / STATE_PATH are
monkeypatched, a fixed clock is injected, and every test works on its own throwaway state.json.
"""
import hashlib
import re
from datetime import datetime

import pandas as pd
import pytest

from backend.core import config
from backend.core.db import load_state, read_brain_events, save_state
from backend.core.schema import Recommendation
from backend.decisions import engine as e
from backend.decisions import hooks
from backend.decisions import validate as v
from backend.decisions.ads_api import MockAdsAPI
from backend.detection.runner import run_detection
from backend.generator import generate as gen
from backend.ingest.pipeline import run_pipeline
from backend.optimizer.curves import fit_curves

AS_OF = "2026-10-06T23:00:00"
NOW = datetime(2026, 10, 7, 12, 0, 0)


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    root = tmp_path_factory.mktemp("m6")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(config, "DATA_DIR", root)
        mp.setattr(config, "RAW_DIR", root / "raw")
        mp.setattr(config, "DB_PATH", root / "engine.db")
        mp.setattr(config, "STATE_PATH", root / "state.json")
        gen.main(quiet=True)
        run_pipeline(as_of=AS_OF, verbose=False, emit_brain_events=False)
        run_detection(as_of=AS_OF, emit_brain_events=False, verbose=False)
        yield


@pytest.fixture
def state(env, monkeypatch, tmp_path):
    """A fresh state file and a fixed clock for one test."""
    monkeypatch.setattr(config, "STATE_PATH", tmp_path / "state.json")
    e.set_clock(lambda: NOW)
    yield tmp_path / "state.json"
    e.set_clock(None)
    fit_curves(refresh=True)


@pytest.fixture(scope="module")
def built(env):
    e.set_clock(lambda: NOW)
    out = e.build_recommendations()
    e.set_clock(None)
    return out


def rec(built, action_type, contains=None):
    return next(r for r in built["recommendations"] if r.action["type"] == action_type and (contains is None or contains in r.title))


def pending(out, action_type, contains=None):
    return next(d for d in out["pending"] if d["action"]["type"] == action_type and (contains is None or contains in d["title"]))


def _ok(result):
    ok, detail = result
    assert ok, detail


# ---------------------------------------------------------------- one test per validation check
def test_v01_inbox_shape(env):
    _ok(v.check_inbox_shape())


def test_v02_no_campaign_in_two_recommendations(env):
    _ok(v.check_no_double_cover())


def test_v03_no_low_stock_raise(env):
    _ok(v.check_no_low_stock_raise())


def test_v04_scoring_formulas(env):
    _ok(v.check_scoring_formulas())


def test_v05_stable_ids_and_titles(env):
    _ok(v.check_stable_ids())


def test_v06_supervised_execute(env):
    _ok(v.check_supervised_execute())


def test_v07_closed_loop(env):
    _ok(v.check_closed_loop())


def test_v08_refresh_keeps_executed(env):
    _ok(v.check_refresh_keeps_executed())


def test_v09_rollback(env):
    _ok(v.check_rollback())


def test_v10_hard_block(env):
    _ok(v.check_hard_block())


def test_v11_advisory(env):
    _ok(v.check_advisory())


def test_v12_autopilot_scope(env):
    _ok(v.check_autopilot())


def test_v13_reject(env):
    _ok(v.check_reject())


def test_v14_launch_test(env):
    _ok(v.check_launch_test())


def test_v15_data_fix(env):
    _ok(v.check_data_fix())


def test_v16_brain_events(env):
    _ok(v.check_brain_events())


def test_v17_speed(env):
    _ok(v.check_speed())


# ---------------------------------------------------------------- scoring unit tests
def test_confidence_formula():
    base = config.CONF_BASE
    assert e._confidence(2.5, 0.5, None) == pytest.approx(base + 0.08 * 2.5 - 0.15 * 0.5)  # 0.675
    assert e._confidence(10.0, 0.0, None) == pytest.approx(base + config.CONF_Z_WEIGHT * config.CONF_Z_CAP)  # |z| is capped
    assert e._confidence(-2.5, 0.5, None) == e._confidence(2.5, 0.5, None)  # sign does not matter
    assert e._confidence(0.0, 2.0, None) == config.CONFIDENCE_MIN  # floored
    assert e._confidence(4.0, 0.0, 0.0) <= config.CONFIDENCE_MAX
    assert e._confidence(2.5, 0.5, 0.4) == pytest.approx(0.675 * (1 - config.CONF_MAPE_WEIGHT * 0.4))  # M7's MAPE scales it down
    assert e._confidence(2.5, 0.5, None) == e._confidence(2.5, 0.5, 0.0)  # MAPE None counts as 0


def test_risk_tiers():
    assert e._risk(0.41, 0) == "high" and e._risk(0.0, config.RISK_HIGH_IMPACT + 1) == "high"
    assert e._risk(0.0, -(config.RISK_HIGH_IMPACT + 1)) == "high"  # |impact|
    assert e._risk(config.RISK_HIGH_SHIFT, 0) == "medium"  # the boundary itself is not "above"
    assert e._risk(0.11, 0) == "medium" and e._risk(config.RISK_MEDIUM_SHIFT, 0) == "low" and e._risk(0.05, 100) == "low"


def test_shift_cases():
    chg = lambda f, t: {"campaign_id": "X", "from_budget": f, "to_budget": t}  # noqa: E731
    assert e._shift([chg(10000, 6000), chg(30000, 18000)], 300000) == pytest.approx(0.4)  # |Σnew − Σcur| ÷ Σcur
    assert e._shift([chg(10000, 15000)], 300000) == pytest.approx(0.5)
    assert e._shift([chg(0, 5000)], 250000) == pytest.approx(0.02)  # a launch test: Σ new ÷ brand total
    assert e._shift([], 250000) == 0.0  # a data fix changes no budget
    assert e._shift([chg(0, 5000)], 0) == 0.0  # no division by zero


def test_requires_approval_rule():
    assert e._requires_approval("low", 0.02) is False
    assert e._requires_approval("low", config.AUTO_APPLY_MAX_SHIFT) is True  # must be strictly below
    assert e._requires_approval("medium", 0.05) is True and e._requires_approval("high", 0.0) is True


def test_blocked_rule(env):
    curves = fit_curves().set_index("campaign_id")
    raise03 = {"campaign_id": "CMP-03", "from_budget": 40000.0, "to_budget": 41000.0}
    cut03 = {"campaign_id": "CMP-03", "from_budget": 40000.0, "to_budget": 16000.0}
    raise06 = {"campaign_id": "CMP-06", "from_budget": 8000.0, "to_budget": 9000.0}
    assert e._blocked([raise03], curves) is True  # raising spend on a 5-day-cover SKU
    assert e._blocked([cut03], curves) is False and e._blocked([raise06], curves) is False and e._blocked([], curves) is False
    assert e._blocked([cut03, raise03], curves) is True


def test_priority_formula():
    assert e._priority(10000, 0.5, "low") == 5000
    assert e._priority(10000, 0.5, "high") == 5000 + config.URGENCY_BONUS
    assert e._priority(-4000, 0.9, "low") == 0.0 and e._priority(-4000, 0.9, "high") == config.URGENCY_BONUS


def test_stockout_value_cutting_ads_is_profitable_when_cover_is_short():
    gm0, s0, gm1, s1 = 126000.0, 89000.0, 70000.0, 35700.0
    short = e._stockout_value(gm0, s0, gm1, s1, cover=5.0)
    assert short > 40000  # worth ~₹50k/day: stops paying for clicks that land on an empty page
    # with plenty of cover there is no wasted post-stockout spend, so the cut no longer pays for itself
    assert e._stockout_value(gm0, s0, gm1, s1, cover=60.0) < short
    assert e._stockout_value(gm0, s0, gm1, s1, cover=60.0) == pytest.approx((gm1 - s1) - (gm0 - s0))  # cover capped at the horizon
    assert e._stockout_value(gm0, s0, 0.0, 0.0, cover=5.0) > 0  # gm1 ≤ 0 → treated as lasting the whole horizon


def test_stable_id_generation(built):
    stock = rec(built, "inventory_protect")
    assert stock.id == Recommendation.make_recommendation_id(stock.title) == "REC-" + hashlib.md5(stock.title.encode()).hexdigest()[:6]
    assert re.match(config.ID_PATTERNS["recommendation"], stock.id)
    assert all(r.id == Recommendation.make_recommendation_id(r.title) for r in built["recommendations"])
    assert not any(re.search(r"₹|\d{3,}", r.title) for r in built["recommendations"])  # no amounts or counts


# ---------------------------------------------------------------- builder behaviour
def test_covered_set_conflict_resolution(built):
    stock = rec(built, "inventory_protect")
    assert {c["campaign_id"] for c in stock.action["changes"]} == {"CMP-03", "CMP-04", "CMP-05"}
    google = rec(built, "bid_cap")
    assert "CMP-04" not in {c["campaign_id"] for c in google.action["changes"]}  # Google, but already claimed by rule 1
    owners = {}
    for r in built["recommendations"]:
        for c in r.action["changes"]:
            assert c["campaign_id"] not in owners
            owners[c["campaign_id"]] = r.id
    assert owners == built["covered"] and len(owners) == 16


def test_scale_under_funded_is_cmp07_only(built):
    scale = next(r for r in built["recommendations"] if r.title == "Scale under-funded high-margin campaigns")
    assert [c["campaign_id"] for c in scale.action["changes"]] == ["CMP-07"]
    assert rec(built, "launch_test").title == "Launch test · Trail Max on Google (retargeting)"
    assert "CMP-06" in {c["campaign_id"] for c in rec(built, "bid_cap").action["changes"]}  # CMP-06 holds inside the Google rebalance


def test_knock_on_note_attached_to_gym_flex_scale_up(built):
    winner = next(r for r in built["recommendations"] if r.title.startswith("Scale winner"))
    assert winner.action["notes"] == ["Scale carefully: viral traffic converts 17% worse (site CVR)"]
    assert winner.action["related"] == ["conversion_drop:SKU-J"]
    change = winner.action["changes"][0]
    assert change["to_budget"] == pytest.approx(change["from_budget"] * (1 + config.POSITIVE_SCALE_UP / 2), abs=10)  # halved
    assert not any("SKU-J" in str(r.action["targets"]) or r.anomaly_id == "AN-007" for r in built["recommendations"])  # no rec of its own
    google = rec(built, "bid_cap")
    assert google.action["related"] == ["metric_shift:CMP-02"] and "AN-002" in google.action["notes"][1]


def test_action_payloads(built):
    pr = rec(built, "price_review").action["price_review"]
    assert (pr["sku_id"], pr["price_from"], pr["price_to"], pr["event_id"]) == ("SKU-D", 1999.0, 2299.0, "EV-2")
    assert set(pr["causal"]) == {"effect_per_day", "ci_low", "ci_high", "units_change_pct"}
    assert rec(built, "creative_refresh").action["creative_refresh"]["suggested"] == "UGC testimonial variant"
    launch = rec(built, "launch_test")
    assert launch.action["launch"]["daily_budget"] == config.OPP_TEST_BUDGET and launch.action["changes"] == []
    assert launch.action["targets"][-1] == {"type": "ghost", "id": "Trail Max · Google · retargeting"}
    fix = rec(built, "data_fix", "Google")
    assert fix.action["settings"]["conversion_source"] == "server_side" and fix.action["targets"] == [{"type": "source", "id": "google_ads"}]
    assert fix.expected_profit_delta == 0.0 and fix.requires_approval is False
    assert {"type": "cluster", "id": "google"} in rec(built, "bid_cap").action["targets"]


# ---------------------------------------------------------------- MockAdsAPI
def test_mock_api_call_shapes():
    api = MockAdsAPI(clock=lambda: NOW)
    b = api.update_budget("CMP-03", "meta", 16010.456)
    assert b == {"platform": "meta", "endpoint": "/meta/campaigns/CMP-03/budget", "method": "POST", "daily_budget": 16010.46,
                 "status": "OK", "ts": "2026-10-07T12:00:00"}
    t = api.create_test_campaign("SKU-C", "google", "retargeting", 5000)
    assert t["endpoint"] == "/google/campaigns" and t["method"] == "POST" and t["daily_budget"] == 5000
    assert t["campaign_id"] == "TST-" + hashlib.md5(b"SKU-C|google|retargeting").hexdigest()[:6]
    assert api.create_test_campaign("SKU-C", "google", "retargeting", 5000)["campaign_id"] == t["campaign_id"]  # deterministic
    assert api.create_test_campaign("SKU-C", "google", "broad", 5000)["campaign_id"] != t["campaign_id"]
    s = api.set_conversion_source("meta", "server_side")
    assert (s["endpoint"], s["conversion_source"], s["status"]) == ("/meta/conversions/settings", "server_side", "OK")
    p = api.pause_test_campaign(t["campaign_id"], "google")
    assert p["endpoint"] == f"/google/campaigns/{t['campaign_id']}/pause" and p["status"] == "PAUSED"
    r = api.rotate_creative("CMP-01", "meta", "UGC testimonial variant")
    assert r["endpoint"] == "/meta/campaigns/CMP-01/creatives" and r["status"] == "QUEUED"
    assert MockAdsAPI().update_budget("CMP-01", "meta", 1.0)["ts"][:2] == "20"  # the real clock works too


# ---------------------------------------------------------------- executor behaviour
def test_hook_exception_does_not_break_execute(state, monkeypatch):
    d = pending(e.refresh_decisions(emit_brain_events=False), "inventory_protect")
    monkeypatch.setattr(hooks, "on_executed", lambda *a: (_ for _ in ()).throw(RuntimeError("M7 exploded")))
    monkeypatch.setattr(hooks, "on_rolled_back", lambda *a: (_ for _ in ()).throw(RuntimeError("M7 exploded")))
    res = e.approve(d["id"], emit_brain_events=False)
    assert res["ok"] and load_state()["budget_overrides"]
    assert e.rollback(d["id"], emit_brain_events=False)["ok"]  # the rollback hook failing is harmless too


def test_hooks_are_wired_to_the_learning_loop(monkeypatch):
    """M7 implements the hooks: executing records outcomes, rolling back removes one, and the emit flag travels along."""
    from backend.learning import loop
    seen = []
    monkeypatch.setattr(loop, "record_outcomes", lambda emit_brain_events=True: seen.append(("record", emit_brain_events)))
    monkeypatch.setattr(loop, "remove_outcome", lambda decision_id: seen.append(("remove", decision_id)))
    hooks.on_executed({}, {})
    with hooks.emitting(False):
        hooks.on_executed({}, {})
    hooks.on_rolled_back({"id": "REC-1"}, {})
    assert seen == [("record", True), ("record", False), ("remove", "REC-1")]


def test_refusals(state):
    out = e.refresh_decisions(emit_brain_events=False)
    stock = pending(out, "inventory_protect")
    assert e.approve("REC-nope00") == {"ok": False, "reason": "Unknown decision REC-nope00"}
    assert e.rollback(stock["id"])["reason"].startswith("Only executed decisions")  # nothing to roll back yet
    assert e.approve(stock["id"], emit_brain_events=False)["ok"]
    assert e.approve(stock["id"], emit_brain_events=False)["reason"] == "Already executed"
    cr = pending(out, "creative_refresh")
    assert e.reject(cr["id"], emit_brain_events=False)["ok"]
    assert e.approve(cr["id"])["reason"] == "Decision was rejected"
    assert e.reject(cr["id"])["reason"].startswith("Only pending decisions")
    assert e.rollback(stock["id"], emit_brain_events=False)["ok"]
    assert e.rollback(stock["id"])["reason"].startswith("Only executed decisions")
    assert e.approve(stock["id"])["reason"] == "Decision was rolled back"


def test_multi_action_execute_api_calls(state):
    out = e.refresh_decisions(emit_brain_events=False)
    cr = pending(out, "creative_refresh")
    res = e.approve(cr["id"], emit_brain_events=False)
    assert [c["status"] for c in res["api_calls"]] == ["OK", "QUEUED"]  # budget change + creative rotation
    assert res["api_calls"][1]["endpoint"] == "/meta/campaigns/CMP-01/creatives"
    audit = load_state()["audit"][-1]
    assert audit["rollback"] == [{"type": "budget", "campaign_id": "CMP-01", "channel": "meta", "budget": audit["rollback"][0]["budget"]}]
    price = pending(out, "price_review")
    assert len(e.approve(price["id"], emit_brain_events=False)["api_calls"]) == len(price["action"]["changes"])


def test_pending_rebuilt_and_dropped_on_refresh(state, monkeypatch):
    out = e.refresh_decisions(emit_brain_events=False)
    n = len(out["pending"])
    real = e.build_recommendations

    def without_trim(objective=None):
        r = real(objective)
        r["recommendations"] = [x for x in r["recommendations"] if x.title != "Trim loss-making campaigns"]
        return r
    monkeypatch.setattr(e, "build_recommendations", without_trim)
    again = e.refresh_decisions(emit_brain_events=False)
    assert len(again["pending"]) == n - 1 and "Trim loss-making campaigns" not in [d["title"] for d in again["pending"]]
    assert load_state()["last_build_at"] == "2026-10-07T12:00:00"


def test_history_is_newest_first_and_audit_too(state):
    out = e.refresh_decisions(emit_brain_events=False)
    stock, cr = pending(out, "inventory_protect"), pending(out, "creative_refresh")
    e.approve(stock["id"], emit_brain_events=False)
    e.reject(cr["id"], emit_brain_events=False)
    e.rollback(stock["id"], emit_brain_events=False)
    audit = e.get_audit()
    assert [a["action"] for a in audit] == ["rollback", "reject", "execute"]  # newest first
    inbox = e.refresh_decisions(emit_brain_events=False)
    assert [d["status"] for d in inbox["history"]] == ["rolled_back", "rejected"] or {d["status"] for d in inbox["history"]} == {"rolled_back", "rejected"}
    assert inbox["summary"]["rolled_back"] == 1 and inbox["summary"]["rejected"] == 1 and inbox["summary"]["executed"] == 0
    assert all(d["status"] == "pending" for d in inbox["pending"]) and inbox["decisions"][: len(inbox["pending"])] == inbox["pending"]


def test_autopilot_only_in_autonomous_mode(state):
    e.refresh_decisions(emit_brain_events=False)
    assert e.auto_apply(emit_brain_events=False) == []  # supervised: autopilot does nothing
    assert not any(d["status"] == "executed" for d in load_state()["decisions"])
    e.set_autonomy("autonomous")
    done = e.auto_apply(emit_brain_events=False)
    st = load_state()
    ran = [d for d in st["decisions"] if d["id"] in done]
    assert len(done) == 4 and all(d["approver"] == "autopilot" for d in ran)
    assert all(not d["requires_approval"] and not d["blocked"] for d in ran)
    assert e.auto_apply(emit_brain_events=False) == []  # nothing left that is eligible


def test_autonomous_refresh_applies_automatically(state):
    e.set_autonomy("autonomous")
    out = e.refresh_decisions(emit_brain_events=False)
    assert len(out["auto_applied"]) == 4 and out["summary"]["executed"] == 4 and out["summary"]["auto_eligible"] == 0


def test_settings_validation(state):
    assert e.set_autonomy("advisory")["autonomy"] == "advisory" and e.set_objective("clear_inventory")["objective"] == "clear_inventory"
    with pytest.raises(ValueError, match="autonomy"):
        e.set_autonomy("reckless")
    with pytest.raises(ValueError, match="objective"):
        e.set_objective("make_money")
    s = e.get_settings()
    assert s["autonomy_modes"] == list(config.AUTONOMY_MODES) and s["objectives"] == list(config.OBJECTIVES)


def test_objective_changes_the_plan(state):
    e.set_objective("clear_inventory")
    out = e.refresh_decisions(emit_brain_events=False)
    assert out["objective"] == "clear_inventory"
    kids = next(c for d in out["pending"] for c in d["action"]["changes"] if c["campaign_id"] == "CMP-14")
    assert kids["to_budget"] > kids["from_budget"]  # Kids Glow is pushed instead of trimmed


def test_executing_changes_the_next_build(state):
    d = pending(e.refresh_decisions(emit_brain_events=False), "creative_refresh")
    target = d["action"]["changes"][0]["to_budget"]
    e.approve(d["id"], emit_brain_events=False)
    assert fit_curves().set_index("campaign_id").at["CMP-01", "current_spend"] == target
    after = e.refresh_decisions(emit_brain_events=False)
    assert not any(x["id"] == d["id"] for x in after["pending"])  # not proposed again


# ---------------------------------------------------------------- brain events
def test_no_events_when_disabled(state):
    out = e.refresh_decisions(emit_brain_events=False)
    d = pending(out, "inventory_protect")
    e.approve(d["id"], emit_brain_events=False)
    e.rollback(d["id"], emit_brain_events=False)
    e.reject(pending(out, "creative_refresh")["id"], emit_brain_events=False)
    assert read_brain_events() == [] and load_state()["rec_signatures"] == {}


def test_recommendation_events_dedupe_by_signature(state):
    out = e.refresh_decisions()
    n = len(out["pending"])
    events = read_brain_events(limit=500)
    assert out["events_logged"] == n == len(events)
    assert [x["ref_id"] for x in events] == [d["id"] for d in out["pending"]]  # ranked order
    assert all(x["type"] == "recommendation" and x["path"] == ["diagnose", "decide"] for x in events)
    assert e.refresh_decisions()["events_logged"] == 0
    st = load_state()
    victim = next(iter(st["rec_signatures"]))
    st["rec_signatures"][victim] = "changed"  # its signature moved → exactly one new pulse
    save_state(st)
    assert e.refresh_decisions()["events_logged"] == 1


def test_recommendation_event_message_and_payload(state):
    e.refresh_decisions()
    ev = {x["ref_id"]: x for x in read_brain_events(limit=500)}
    stock_id = Recommendation.make_recommendation_id("Protect stock · cut ads on Running Pro by 60%")
    s = ev[stock_id]
    assert re.fullmatch(r"Protect stock · cut ads on Running Pro by 60% — ₹53\.\dk/day · \d+% confidence", s["message"])
    assert s["entity_id"] == "SKU-B" and s["severity"] == "high"
    assert s["payload"]["action_type"] == "inventory_protect" and len(s["payload"]["campaigns"]) == 3
    assert {"rec_id", "targets", "anomaly_id", "related", "expected_profit_delta", "confidence", "risk",
            "requires_approval", "blocked"} <= set(s["payload"])
    launch = ev[Recommendation.make_recommendation_id("Launch test · Trail Max on Google (retargeting)")]
    assert launch["severity"] == "low" and launch["entity_id"] == "SKU-C"


def _last(event_type):
    return [x for x in read_brain_events(limit=500) if x["type"] == event_type][-1]


def test_approval_event_payload_and_launch_data_fix(state):
    out = e.refresh_decisions()
    e.approve(pending(out, "inventory_protect")["id"])
    ap = _last("approval")
    assert ap["type"] == "approval" and ap["path"] == ["decide", "learn"] and ap["payload"]["approver"] == "user"
    assert ap["payload"]["api_calls_count"] == 3 and len(ap["payload"]["changes"]) == 3
    assert {(s["source"], s["target"]) for s in ap["payload"]["synapses"]} == {("CMP-03", "SKU-B"), ("CMP-04", "SKU-B"), ("CMP-05", "SKU-B")}
    e.approve(pending(out, "launch_test")["id"])
    ln = _last("approval")
    assert ln["payload"]["launched_test"]["test_campaign_id"].startswith("TST-") and ln["payload"]["synapses"] == []
    e.approve(pending(out, "data_fix", "Meta")["id"])
    fx = _last("approval")
    assert fx["payload"]["data_fix"]["channel"] == "meta" and fx["payload"]["data_fix"]["conversion_source"] == "server_side"


def test_autopilot_reject_rollback_events(state):
    e.set_autonomy("autonomous")
    e.refresh_decisions()
    auto = [x for x in read_brain_events(limit=500) if x["type"] == "auto_apply"]
    assert len(auto) == 4 and all(x["payload"]["approver"] == "autopilot" and x["path"] == ["decide", "learn"] for x in auto)
    e.set_autonomy("supervised")
    st = load_state()
    cr = next(d for d in st["decisions"] if d["action"]["type"] == "creative_refresh")
    e.reject(cr["id"], reason="later")
    rej = _last("rejection")
    assert rej["type"] == "rejection" and rej["path"] == ["decide"] and rej["payload"]["reason"] == "later"
    fix = next(d for d in st["decisions"] if d["action"]["type"] == "data_fix")
    e.rollback(fix["id"])
    rb = _last("rollback")
    assert rb["type"] == "rollback" and rb["path"] == ["learn", "decide"] and rb["payload"]["api_calls_count"] == 1


# ---------------------------------------------------------------- CLI
def test_cli_prints_inbox_and_acts(state, capsys):
    e.main(["--no-brain-events"])
    out = capsys.readouterr().out
    assert "Protect stock · cut ads on Running Pro by 60%" in out and "M6 OK · 11 pending" in out and "BLOCKED" not in out
    e.main(["--no-brain-events", "--approve", "REC-567405"])
    out = capsys.readouterr().out
    assert "approve REC-567405: OK" in out and "/meta/campaigns/CMP-03/budget" in out and "executed" in out
    e.main(["--no-brain-events", "--rollback", "REC-567405", "--autonomy", "advisory"])
    out = capsys.readouterr().out
    assert "rollback REC-567405: OK" in out and "'autonomy': 'advisory'" in out
    e.main(["--no-brain-events", "--approve", "REC-567405"])
    assert "REFUSED — Decision was rolled back" in capsys.readouterr().out
