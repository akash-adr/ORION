"""M7 tests: seeded history, calibration, simulated outcomes, synapse memory, the M6 hooks and brain events.

M1 → M6 run inside a pytest temp folder; config.RAW_DIR / DB_PATH / STATE_PATH are monkeypatched, a fixed clock is
injected, and every test works on its own throwaway state.json.
"""
import hashlib
import re
from datetime import datetime

import numpy as np
import pytest

from backend.core import config
from backend.core.db import default_state, load_state, read_brain_events, save_state
from backend.decisions import engine as e
from backend.decisions import hooks
from backend.detection.runner import run_detection
from backend.generator import generate as gen
from backend.ingest.pipeline import run_pipeline
from backend.learning import loop
from backend.learning import runner as lrunner
from backend.learning import validate as v
from backend.optimizer.curves import fit_curves

AS_OF = "2026-10-06T23:00:00"
NOW = datetime(2026, 10, 7, 12, 0, 0)


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    root = tmp_path_factory.mktemp("m7")
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
    monkeypatch.setattr(config, "STATE_PATH", tmp_path / "state.json")
    e.set_clock(lambda: NOW)
    yield tmp_path / "state.json"
    e.set_clock(None)
    fit_curves(refresh=True)


def pending(out, action_type, contains=None):
    return next(d for d in out["pending"] if d["action"]["type"] == action_type and (contains is None or contains in d["title"]))


def outcome(decision_id):
    return next((o for o in load_state()["outcomes"] if o["decision_id"] == decision_id), None)


def _ok(result):
    ok, detail = result
    assert ok, detail


def fake_outcome(actual, predicted=1000.0, keys=("CMP-07->SKU-C",), **kw):
    return {"decision_id": "X", "title": "x", "date": "2026-10-01", "predicted": predicted, "actual": actual,
            "error_pct": (actual - predicted) / abs(predicted), "simulated": True, "seeded": False, "measurable": True,
            "synapses": list(keys), "synapse_deltas": {}, **kw}


# ---------------------------------------------------------------- one test per validation check
def test_v01_seed_history(env):
    _ok(v.check_seed_history())


def test_v02_mape_trend(env):
    _ok(v.check_mape_trend())


def test_v03_calibration(env):
    _ok(v.check_calibration())


def test_v04_hook_records_outcome(env):
    _ok(v.check_hook_records_outcome())


def test_v05_determinism(env):
    _ok(v.check_determinism())


def test_v06_synapses(env):
    _ok(v.check_synapses())


def test_v07_rollback(env):
    _ok(v.check_rollback())


def test_v08_data_fix_not_measured(env):
    _ok(v.check_data_fix_not_measured())


def test_v09_m6_uses_calibration(env):
    _ok(v.check_m6_uses_calibration())


def test_v10_report_shape(env):
    _ok(v.check_report_shape())


def test_v11_brain_events(env):
    _ok(v.check_brain_events())


def test_v12_reset(env):
    _ok(v.check_reset())


# ---------------------------------------------------------------- helpers and rules
def test_rng_is_deterministic_per_key():
    a, b = loop._rng("REC-567405").normal(size=5), loop._rng("REC-567405").normal(size=5)
    assert list(a) == list(b) and list(loop._rng("REC-other").normal(size=5)) != list(a)
    assert loop._rng("k").random() == np.random.default_rng(int(hashlib.md5(b"k").hexdigest()[:16], 16)).random()


def test_seeded_history_shape(env):
    s = default_state()
    assert loop.seed_history(s) == config.SEED_HISTORY_N
    o = s["outcomes"]
    assert [x["decision_id"] for x in o] == [f"HIST-{i:02d}" for i in range(1, 13)]
    dates = [x["date"] for x in o]
    assert dates == sorted(dates) and dates[0] == "2026-08-07" and dates[-1] == "2026-10-01"  # 60 → 5 days before END_DATE
    assert all(x["simulated"] and x["seeded"] and x["measurable"] and config.SEED_PRED_MIN <= x["predicted"] <= config.SEED_PRED_MAX for x in o)
    assert all(1 <= len(x["campaigns"]) <= 2 and x["synapses"] and x["synapse_deltas"] for x in o)
    assert all(abs(x["error_pct"] - (x["actual"] - x["predicted"]) / x["predicted"]) < 1e-3 for x in o)
    s2 = default_state()
    loop.seed_history(s2)
    assert s2["outcomes"] == o  # reproducible
    assert s["synapse_strength"] and all(config.SYNAPSE_MIN <= v_ <= config.SYNAPSE_MAX for v_ in s["synapse_strength"].values())


def test_rolling_mape_window(env):
    s = default_state()
    loop.seed_history(s)
    curve = loop.rolling_mape(s["outcomes"])
    errs = [abs(o["error_pct"]) for o in s["outcomes"]]
    assert len(curve) == 12 and curve[0]["rolling_mape"] == pytest.approx(errs[0], abs=1e-3)  # a partial window at the start
    assert curve[5]["rolling_mape"] == pytest.approx(np.mean(errs[2:6]), abs=1e-3)  # then a window of 4
    assert curve[-1]["rolling_mape"] < 0.10 < curve[3]["rolling_mape"]  # the engine visibly learned


def test_calibration_is_clipped_so_one_wild_outcome_cannot_swing_m6():
    s = {"outcomes": [fake_outcome(actual=10.0) for _ in range(8)]}  # actual is 1% of predicted, eight times
    assert loop.calibration(s)["factor"] == config.CALIBRATION_MIN
    s = {"outcomes": [fake_outcome(actual=50000.0) for _ in range(8)]}
    assert loop.calibration(s)["factor"] == config.CALIBRATION_MAX
    s = {"outcomes": [fake_outcome(actual=1000.0)] * 7 + [fake_outcome(actual=-90000.0)]}  # one catastrophic loss
    cal = loop.calibration(s)
    assert config.CALIBRATION_MIN <= cal["factor"] <= config.CALIBRATION_MAX and cal["win_rate"] == 7 / 8
    assert cal["mape"] > 10  # the error itself is not clipped: it is reported honestly
    assert loop.calibration({"outcomes": []}) == {"factor": 1.0, "mape": None, "win_rate": None, "n": 0}


def test_calibration_uses_only_the_last_window_of_measurable_outcomes():
    old = [fake_outcome(actual=2000.0) for _ in range(5)]  # ratio 2.0: would clip to 1.2 if it counted
    recent = [fake_outcome(actual=1000.0) for _ in range(config.CALIBRATION_WINDOW)]
    unmeasured = {**fake_outcome(actual=0.0), "measurable": False, "error_pct": None}
    cal = loop.calibration({"outcomes": old + recent + [unmeasured]})
    assert cal["factor"] == 1.0 and cal["mape"] == 0.0 and cal["n"] == config.CALIBRATION_WINDOW


def test_zero_predicted_guard_and_negative_prediction(env):
    s = default_state()
    d = {"id": "REC-zero01", "title": "fix", "executed_at": "2026-10-07T12:00:00", "expected_profit_delta": 0.4,
         "action": {"type": "data_fix", "changes": [], "settings": {"channel": "meta"}}}
    o = loop.measure_outcome(d, s)
    assert o["measurable"] is False and o["actual"] == 0.0 and o["error_pct"] is None and "not measured in ₹" in o["note"]
    assert o["synapses"] == [] and o["simulated"] is True
    neg = loop.measure_outcome({**d, "id": "REC-neg001", "expected_profit_delta": -5000.0, "action": {"type": "budget_cut", "changes": []}}, s)
    assert neg["measurable"] and neg["actual"] < 0 and neg["error_pct"] == pytest.approx((neg["actual"] + 5000) / 5000, abs=1e-3)


def test_measure_outcome_is_simulated_and_reproducible(env):
    s = default_state()
    d = {"id": "REC-567405", "title": "Protect stock", "executed_at": "2026-10-07T12:00:00", "expected_profit_delta": 53565.63,
         "action": {"type": "inventory_protect", "changes": [{"campaign_id": "CMP-03"}, {"campaign_id": "CMP-04"}]}}
    a, b = loop.measure_outcome(d, s), loop.measure_outcome(d, s)
    assert a == b and a["simulated"] is True and a["seeded"] is False and a["date"] == "2026-10-07"
    assert a["synapses"] == ["CMP-03->SKU-B", "CMP-04->SKU-B"] and a["campaigns"] == ["CMP-03", "CMP-04"]
    z = loop._rng("REC-567405").normal(config.OUTCOME_BIAS_MEAN, config.OUTCOME_NOISE_SD)
    assert a["actual"] == pytest.approx(53565.63 * (1 + z), abs=0.01)


# ---------------------------------------------------------------- synapse learning
def test_synapse_rules_and_exact_reversal(env):
    s = default_state()
    good = fake_outcome(actual=1100.0)  # +10%: good
    loop._apply_synapses(s, good)
    assert s["synapse_strength"]["CMP-07->SKU-C"] == pytest.approx(1.0 + config.SYNAPSE_GAIN) and good["synapse_deltas"] == {"CMP-07->SKU-C": config.SYNAPSE_GAIN}
    loss = fake_outcome(actual=-200.0)
    loop._apply_synapses(s, loss)
    assert s["synapse_strength"]["CMP-07->SKU-C"] == pytest.approx(1.25 - config.SYNAPSE_DECAY)
    meh = fake_outcome(actual=1600.0)  # +60%: profitable but a poor forecast
    loop._apply_synapses(s, meh)
    assert meh["synapse_deltas"]["CMP-07->SKU-C"] == pytest.approx(config.SYNAPSE_GAIN / 2)


def test_synapse_clipping_records_the_applied_delta(env):
    s = default_state()
    s["synapse_strength"]["CMP-07->SKU-C"] = 2.95
    top = fake_outcome(actual=1000.0)
    loop._apply_synapses(s, top)
    assert s["synapse_strength"]["CMP-07->SKU-C"] == config.SYNAPSE_MAX and top["synapse_deltas"]["CMP-07->SKU-C"] == pytest.approx(0.05)
    s["synapse_strength"]["CMP-04->SKU-B"] = 0.55
    low = fake_outcome(actual=-5.0, keys=("CMP-04->SKU-B",))
    loop._apply_synapses(s, low)
    assert s["synapse_strength"]["CMP-04->SKU-B"] == config.SYNAPSE_MIN and low["synapse_deltas"]["CMP-04->SKU-B"] == pytest.approx(-0.05)


def test_removal_reverses_clipped_deltas_exactly(state):
    s = loop.load_state()
    s["synapse_strength"]["CMP-03->SKU-B"] = 2.95
    save_state(s)
    out = e.refresh_decisions(emit_brain_events=False)
    d = pending(out, "inventory_protect")
    e.approve(d["id"], emit_brain_events=False)
    o = outcome(d["id"])
    assert o["synapse_deltas"]["CMP-03->SKU-B"] <= 0.05 + 1e-9  # clipped at the ceiling
    e.rollback(d["id"], emit_brain_events=False)
    assert load_state()["synapse_strength"]["CMP-03->SKU-B"] == pytest.approx(2.95, abs=1e-9)


def test_launch_test_outcome_uses_the_tst_synapse(state):
    out = e.refresh_decisions(emit_brain_events=False)
    d = pending(out, "launch_test")
    assert e.approve(d["id"], emit_brain_events=False)["ok"]
    o = outcome(d["id"])
    test_id = load_state()["launched_tests"][0]["test_campaign_id"]
    assert test_id.startswith("TST-") and o["campaigns"] == [test_id] and o["synapses"] == [f"{test_id}->SKU-C"]
    assert f"{test_id}->SKU-C" in load_state()["synapse_strength"]


def test_executing_a_budget_decision_touches_its_edges(state):
    out = e.refresh_decisions(emit_brain_events=False)
    d = pending(out, "price_review")  # CMP-08 and CMP-09 → SKU-D
    before = dict(loop.load_state().get("synapse_strength", {}))
    e.approve(d["id"], emit_brain_events=False)
    after = load_state()["synapse_strength"]
    o = outcome(d["id"])
    assert set(o["synapses"]) == {"CMP-08->SKU-D", "CMP-09->SKU-D"} and all(k in after for k in o["synapses"])
    assert all(after[k] != before.get(k, config.SYNAPSE_BASE) for k in o["synapses"])


# ---------------------------------------------------------------- hooks and events
def test_hook_exception_does_not_break_m6_execute(state, monkeypatch):
    out = e.refresh_decisions(emit_brain_events=False)
    d = pending(out, "inventory_protect")
    monkeypatch.setattr(loop, "record_outcomes", lambda emit_brain_events=True: (_ for _ in ()).throw(RuntimeError("M7 exploded")))
    res = e.approve(d["id"], emit_brain_events=False)
    assert res["ok"] and load_state()["budget_overrides"]  # the budget change is applied and saved regardless
    monkeypatch.setattr(loop, "remove_outcome", lambda decision_id: (_ for _ in ()).throw(RuntimeError("boom")))
    assert e.rollback(d["id"], emit_brain_events=False)["ok"]


def test_seeded_outcomes_never_emit_events(state):
    new = loop.record_outcomes(emit_brain_events=True)
    st = load_state()
    assert new == [] and sum(o["seeded"] for o in st["outcomes"]) == config.SEED_HISTORY_N
    assert [x for x in read_brain_events(limit=500) if x["type"] == "outcome"] == []
    loop.learning_report()
    loop.record_outcomes()
    assert read_brain_events(limit=500) == []


def test_emit_false_logs_nothing_even_through_the_hook(state):
    out = e.refresh_decisions(emit_brain_events=False)
    e.approve(pending(out, "inventory_protect")["id"], emit_brain_events=False)
    assert read_brain_events(limit=500) == [] and len(load_state()["outcomes"]) == config.SEED_HISTORY_N + 1


def test_outcome_event_message_and_payload(state):
    out = e.refresh_decisions(emit_brain_events=False)
    e.approve(pending(out, "inventory_protect")["id"])
    ev = [x for x in read_brain_events(limit=500) if x["type"] == "outcome"]
    assert len(ev) == 1
    ev = ev[0]
    assert re.fullmatch(r"Protect stock · cut ads on Running Pro by 60%: predicted ₹53\.\dk/day → actual ₹\d+\.\dk/day \([+-]\d+%\) · simulated", ev["message"])
    assert ev["region"] == "learn" and ev["path"] == ["learn"] and ev["entity_id"] == "CMP-03" and ev["ref_id"] == "REC-567405"
    assert ev["severity"] == "low"  # a good outcome
    p = ev["payload"]
    assert p["simulated"] is True and p["measurable"] is True and set(p["calibration"]) == {"factor", "mape", "win_rate", "n"}
    assert [s["key"] for s in p["synapses"]] == ["CMP-03->SKU-B", "CMP-04->SKU-B", "CMP-05->SKU-B"]
    assert all(s["delta"] == config.SYNAPSE_GAIN and s["strength"] > 1.0 for s in p["synapses"])


def test_data_fix_event_is_not_measured_in_rupees(state):
    out = e.refresh_decisions(emit_brain_events=False)
    e.approve(pending(out, "data_fix", "Google")["id"])
    ev = [x for x in read_brain_events(limit=500) if x["type"] == "outcome"][-1]
    assert ev["message"] == "Optimise Google on store-verified conversions: applied — data-quality action, not measured in ₹"
    assert ev["payload"]["measurable"] is False and ev["payload"]["error_pct"] is None and ev["payload"]["synapses"] == []
    assert ev["entity_id"] == "google_ads"  # no campaigns: falls back to the decision's first target


def test_bad_outcome_is_a_medium_event(state, monkeypatch):
    out = e.refresh_decisions(emit_brain_events=False)
    d = pending(out, "creative_refresh")
    monkeypatch.setattr(loop, "OUTCOME_BIAS_MEAN", -0.9)  # simulate a forecast that was far too optimistic
    e.approve(d["id"])
    ev = [x for x in read_brain_events(limit=500) if x["type"] == "outcome"][-1]
    assert ev["severity"] == "medium" and ev["payload"]["error_pct"] < -config.SYNAPSE_GOOD_ERROR


def test_record_outcomes_is_idempotent_and_ignores_unexecuted(state):
    out = e.refresh_decisions(emit_brain_events=False)
    assert loop.record_outcomes() == []  # nothing executed yet
    e.approve(pending(out, "inventory_protect")["id"], emit_brain_events=False)
    assert loop.record_outcomes(emit_brain_events=False) == []  # the hook already recorded it
    assert len([o for o in load_state()["outcomes"] if not o["seeded"]]) == 1
    e.reject(pending(out, "creative_refresh")["id"], emit_brain_events=False)
    assert loop.record_outcomes(emit_brain_events=False) == [] and loop.remove_outcome("REC-unknown") is None


# ---------------------------------------------------------------- report and CLI
def test_learning_report_contents(state):
    out = e.refresh_decisions(emit_brain_events=False)
    e.approve(pending(out, "inventory_protect")["id"], emit_brain_events=False)
    r = loop.learning_report()
    assert r["outcomes"][0]["decision_id"] == "REC-567405" and r["outcomes"][-1]["decision_id"] == "HIST-01"
    assert r["kpis"]["measured_count"] == 13 and r["kpis"]["forecast_error"] == r["calibration"]["mape"]
    assert r["kpis"]["total_measured_profit"] == pytest.approx(sum(o["actual"] for o in r["outcomes"]), abs=0.01)
    assert r["cumulative_profit"][-1]["cumulative"] == pytest.approx(r["kpis"]["total_measured_profit"], abs=0.01)
    assert "simulated" in r["simulated_note"] and "holdout" in r["simulated_note"]
    assert all(o["simulated"] for o in r["outcomes"])  # demo outcomes are ALWAYS labelled simulated


def test_runner_cli_prints_the_story(state, capsys):
    lrunner.main(["--no-brain-events"])
    out = capsys.readouterr().out
    assert "KPIs" in out and "ACCURACY CURVE" in out and "27.6% → 5.9%" in out and "STRONGEST SYNAPSES" in out
    assert "M7 OK · 12 outcomes · MAPE 8% · calibration 1.01 · win-rate 100% · simulated" in out
    assert read_brain_events(limit=500) == []
