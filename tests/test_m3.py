"""M3 tests: detectors, persistence, brain alerts, brain-event dedupe, evaluation and seed robustness.

Each fixture generates M1 data and runs M2 inside a pytest temp folder; config.RAW_DIR / DB_PATH /
STATE_PATH are monkeypatched (every module reads them from `config` at call time), so the real data/
folder and state.json are never touched.
"""
import json
import time

import numpy as np
import pandas as pd
import pytest

from backend.core import config
from backend.core.db import load_state, read_brain_events, read_table, save_state
from backend.detection import detectors as d
from backend.detection import store
from backend.detection import validate as v
from backend.detection.evaluate import evaluate, expected_pairs, load_ground_truth
from backend.detection.runner import run_detection
from backend.generator import generate as gen
from backend.ingest.pipeline import run_pipeline

AS_OF = "2026-10-06T23:00:00"


def _setup(root, mp, seed=None):
    mp.setattr(config, "DATA_DIR", root)
    mp.setattr(config, "RAW_DIR", root / "raw")
    mp.setattr(config, "DB_PATH", root / "engine.db")
    mp.setattr(config, "STATE_PATH", root / "state.json")
    if seed is not None:
        mp.setattr(config, "SEED", seed)
        mp.setattr(gen, "SEED", seed)  # generate.py imported the name at module level
    gen.main(quiet=True)
    run_pipeline(as_of=AS_OF, verbose=False, emit_brain_events=False)


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    with pytest.MonkeyPatch.context() as mp:
        _setup(tmp_path_factory.mktemp("m3"), mp)
        yield


@pytest.fixture(scope="module")
def alerts(env):
    return d.detect_all()


@pytest.fixture
def fresh_state(env, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "STATE_PATH", tmp_path / "state.json")
    return tmp_path / "state.json"


def pair(alerts, kind, entity):
    return next((a for a in alerts if a.kind == kind and a.entity_id == entity), None)


PLANTED = [("creative_fatigue", "CMP-01"), ("stockout_risk", "SKU-B"), ("cpc_spike", "google"),
           ("attribution_inflation", "meta"), ("attribution_inflation", "google"),
           ("conversion_drop", "SKU-D"), ("positive_spike", "CMP-10")]


# ---------------------------------------------------------------- detection quality
def test_detects_all_planted_scenarios(alerts):
    for kind, entity in PLANTED:
        assert pair(alerts, kind, entity) is not None, (kind, entity)
    assert [p for ps in expected_pairs(load_ground_truth()).values() for p in ps].__len__() == 7


def test_false_alarm_control(alerts):
    q = evaluate(alerts, AS_OF)
    assert q["false_alarms"] == []  # every extra alert is a classified knock-on
    assert q["recall"] == 1.0 and q["expected"] == 7 and q["found"] == 7 and q["missed"] == []
    assert q["precision"] == 1.0


def test_knock_ons_are_classified(alerts):
    q = evaluate(alerts, AS_OF)
    knock = {k["entity_id"]: k for k in q["knock_on"]}
    assert set(knock) == {"CMP-02", "SKU-J"}
    assert knock["CMP-02"]["reason"] == "knock-on of S3" and knock["CMP-02"]["scenario"] == "S3"
    assert knock["SKU-J"]["reason"] == "viral cold traffic converts worse" and knock["SKU-J"]["scenario"] == "S7"


def test_knock_on_related_links(alerts):
    assert pair(alerts, "metric_shift", "CMP-02").detail["related"] == ["cpc_spike:google"]
    assert pair(alerts, "conversion_drop", "SKU-J").detail["related"] == ["positive_spike:CMP-10"]
    linked = {(a.kind, a.entity_id) for a in alerts if a.detail["related"]}
    assert linked == {("metric_shift", "CMP-02"), ("conversion_drop", "SKU-J")}
    # SKU-D's drop is a price effect, not a knock-on of anything
    assert pair(alerts, "conversion_drop", "SKU-D").detail["related"] == []
    # every related key points at an alert that exists
    keys = {store.anomaly_key(a) for a in alerts}
    assert all(r in keys for a in alerts for r in a.detail["related"])


def test_cmp06_not_flagged_by_significance_gate(env, alerts):
    """CMP-06's profit really halves, but it is too noisy to pass the significance gate (two-gate rule)."""
    assert pair(alerts, "metric_shift", "CMP-06") is None and pair(alerts, "positive_spike", "CMP-06") is None
    fact = read_table("fact_daily")
    recent, base = d._windows(fact, config.RECENT_DAYS, config.BASELINE_DAYS)
    r, b = recent[recent["campaign_id"] == "CMP-06"], base[base["campaign_id"] == "CMP-06"]
    z = d.robust_z(r["profit"], b["profit"])
    change = (r["profit"].mean() - b["profit"].mean()) / abs(b["profit"].mean())
    assert abs(change) >= config.MIN_PCT_CHANGE  # practically large ...
    assert abs(z) < config.Z_THRESHOLD  # ... but not significant
    assert z == pytest.approx(-1.08, abs=0.05)


def test_gain_severity_uses_absolute_impact(env, alerts):
    from backend.core import metrics as m
    assert d._sev(13_686, "positive_spike") == "medium"
    assert d._sev(30_000, "positive_spike") == "high"
    assert d._sev(5_000, "positive_spike") == "low"
    assert d._sev(-13_686, "metric_shift") == "medium"  # loss rule unchanged
    assert m.severity_from_impact(13_686) == "low"  # the M0 helper is untouched
    assert pair(alerts, "positive_spike", "CMP-10").severity == "medium"


def test_stockout_z_is_unclipped(env, alerts):
    """SKU-B's z prints as -2.50; recompute it from the table to prove it is real (-2.498), not clipped/defaulted."""
    sku = read_table("sku_daily")
    recent, base = d._windows(sku, config.RECENT_DAYS, config.BASELINE_DAYS)
    r = recent[recent["sku_id"] == "SKU-B"]["days_cover"].to_numpy()
    b = base[base["sku_id"] == "SKU-B"]["days_cover"].to_numpy()
    median = np.median(b)
    mad = np.median(np.abs(b - median)) * config.MAD_SCALE
    expected = (r.mean() - median) / mad * np.sqrt(len(r)) / 2
    assert d.robust_z(r, b) == pytest.approx(expected)
    assert -2.5 < expected < -2.49  # -2.4984...: rounds to -2.50 for display, not clipped at it
    a = pair(alerts, "stockout_risk", "SKU-B")
    assert a.z == round(expected, 2) == -2.5


def test_sorted_by_impact(alerts):
    impacts = [abs(a.profit_impact) for a in alerts]
    assert impacts == sorted(impacts, reverse=True)


def test_fatigue_dedupes_profit_check(alerts):
    assert pair(alerts, "creative_fatigue", "CMP-01") is not None
    assert pair(alerts, "metric_shift", "CMP-01") is None
    assert pair(alerts, "positive_spike", "CMP-01") is None


def test_positive_spike_is_gain_with_new_creative(alerts):
    a = pair(alerts, "positive_spike", "CMP-10")
    assert a.detail["direction"] == "gain" and a.profit_impact > 0 and a.detail["new_creative"] is True
    assert "CR-10b" in a.detail["creative_ids_recent"]
    assert all(x.detail["direction"] == "loss" for x in alerts if x is not a)


def test_conversion_drop_uses_welch_and_links_price_event(alerts):
    a = pair(alerts, "conversion_drop", "SKU-D")
    assert a.detail["test"] == "welch_t" and a.z < -config.Z_THRESHOLD
    assert a.detail["event_id"] == "EV-2"
    assert a.detail["price_change"] == pytest.approx(2299 / 1999 - 1, abs=1e-3)
    assert a.profit_impact < 0


def test_stockout_and_attribution_overrides(alerts):
    assert pair(alerts, "stockout_risk", "SKU-B").severity == "high"
    for ch in ("meta", "google"):
        a = pair(alerts, "attribution_inflation", ch)
        assert a.severity == "medium" and a.profit_impact == 0.0 and a.z == 0.0
        assert "server-side" in a.detail["recommended_fix"]


def test_display_names_everywhere(env, alerts):
    run_detection(as_of=AS_OF, emit_brain_events=False, verbose=False)
    labels = [a.label for a in alerts] + list(read_table("brain_alerts")["message"])
    assert not any("Tiktok" in t for t in labels)
    assert pair(alerts, "positive_spike", "CMP-10").label == "Positive spike · TikTok · Gym Flex · broad"
    assert pair(alerts, "cpc_spike", "google").label == "CPC spike · Google"
    assert pair(alerts, "attribution_inflation", "meta").label == "Attribution inflation · Meta"
    v.check_display_names({"alerts": [a.__dict__ for a in alerts],
                           "tables": {"brain_alerts": read_table("brain_alerts")}})


def test_precision_check(env):
    ctx = v.build_context()
    assert v.check_precision(ctx)[0] and v.check_display_names(ctx)[0]


def test_brain_alert_message_names_the_cause(env, alerts):
    ba = store.build_brain_alerts(alerts).set_index(["target_type", "target_id"])
    assert ba.loc[("neuron", "CMP-02")]["message"].endswith("— caused by CPC spike · Google")
    assert ba.loc[("neuron", "SKU-J")]["message"].endswith("— caused by Positive spike · TikTok · Gym Flex · broad")
    assert "caused by" not in ba.loc[("neuron", "CMP-01")]["message"]
    assert "caused by" not in ba.loc[("cluster", "google")]["message"]


def test_every_alert_has_direction_and_window(alerts):
    for a in alerts:
        assert a.detail["direction"] in ("loss", "gain")
        assert set(a.detail["window"]) == {"recent_start", "recent_end", "baseline_start", "baseline_end"}


# ---------------------------------------------------------------- statistics
def test_ratio_is_sum_over_sum(env, alerts):
    fact = read_table("fact_daily")
    dates = sorted(fact["date"].unique())
    w = fact[(fact["campaign_id"] == "CMP-01") & fact["date"].isin(dates[-config.RECENT_DAYS:])]
    expected = w["clicks"].sum() / w["impressions"].sum()
    a = pair(alerts, "creative_fatigue", "CMP-01")
    assert a.recent == pytest.approx(expected, abs=1e-4)
    assert a.recent != pytest.approx(w["ctr"].mean(), abs=1e-6)  # not a mean of daily ratios


def test_robust_z_ignores_single_outlier():
    rng = np.random.default_rng(0)
    base = rng.normal(100, 5, 21)
    recent = rng.normal(115, 5, 7)
    spiked = base.copy()
    spiked[3] = 10_000  # one absurd day in the baseline
    clean_z, spiked_z = d.robust_z(recent, base), d.robust_z(recent, spiked)
    assert abs(clean_z - spiked_z) / abs(clean_z) < 0.25
    # a plain std-based z would collapse; the MAD-based one keeps the signal
    plain = (recent.mean() - spiked.mean()) / spiked.std() * np.sqrt(7) / 2
    assert abs(spiked_z) > 5 * abs(plain)


def test_mad_zero_guard():
    z = d.robust_z([10, 10, 12], [10.0] * 21)
    assert np.isfinite(z) and z > 0
    assert np.isfinite(d.robust_z([0, 0], [0.0] * 21))
    assert d.robust_z([], [1.0, 2.0]) == 0.0


def test_windows_anchor_on_last_data_date(env):
    fact = read_table("fact_daily")
    recent, base = d._windows(fact, config.RECENT_DAYS, config.BASELINE_DAYS)
    assert recent["date"].max() == fact["date"].max()
    assert recent["date"].nunique() == config.RECENT_DAYS and base["date"].nunique() == config.BASELINE_DAYS
    assert base["date"].max() < recent["date"].min()


def test_deterministic(env):
    def sig():
        return [(a.id, a.kind, a.entity_id, a.baseline, a.recent, a.change_pct, a.z, a.profit_impact,
                 json.dumps(a.detail, sort_keys=True)) for a in d.detect_all()]
    assert sig() == sig()


def test_runs_under_one_second(env):
    t0 = time.perf_counter()
    d.detect_all()
    assert time.perf_counter() - t0 < 1.0


# ---------------------------------------------------------------- persistence and brain targets
def test_brain_alert_targets(env, alerts):
    ba = store.build_brain_alerts(alerts).set_index(["target_type", "target_id"])
    assert ("cluster", "google") in ba.index
    assert ("source", "meta_ads") in ba.index and ("source", "google_ads") in ba.index
    assert ("neuron", "meta") not in ba.index and not any(t == "neuron" and i in ("meta", "google") for t, i in ba.index)
    for cid in ("CMP-03", "CMP-04", "CMP-05"):
        row = ba.loc[("neuron", cid)]
        assert bool(row["stock_locked"]) and row["top_kind"] == "stockout_risk" and row["top_severity"] == "high"
    assert not bool(ba.loc[("neuron", "SKU-B")]["stock_locked"])
    # attribution data issues never mark individual neurons
    attr_ids = {a.id for a in alerts if a.kind == "attribution_inflation"}
    for (ttype, _), row in ba.iterrows():
        if ttype == "neuron":
            assert not attr_ids & set(json.loads(row["anomaly_ids"]))


def test_brain_alert_merge_rules(env, alerts):
    ba = store.build_brain_alerts(alerts).set_index(["target_type", "target_id"])
    sku_b = ba.loc[("neuron", "SKU-B")]
    assert sku_b["profit_impact"] == pytest.approx(pair(alerts, "stockout_risk", "SKU-B").profit_impact)
    locked = ba.loc[("neuron", "CMP-03")]
    assert locked["profit_impact"] == 0.0  # the lock carries no ₹ impact (never triple-counted)
    stockout_id = pair(alerts, "stockout_risk", "SKU-B").id
    assert stockout_id in json.loads(locked["anomaly_ids"])


def test_unknown_brain_target_raises(env, alerts):
    manifest = store.load_manifest()
    bad = pair(alerts, "creative_fatigue", "CMP-01")
    bad = type(bad)(**{**bad.__dict__, "entity_id": "CMP-99"})
    with pytest.raises(ValueError, match="CMP-99"):
        store.build_brain_alerts([bad], manifest)


def test_tables_written(env):
    run_detection(as_of=AS_OF, emit_brain_events=False, verbose=False)
    t = read_table("anomalies")
    assert len(t) == 9 and set(t["direction"]) == {"loss", "gain"}
    assert t["key"].str.contains(":").all() and json.loads(t["detail_json"].iloc[0])["window"]
    assert len(read_table("brain_alerts")) >= 10


# ---------------------------------------------------------------- brain events
def test_no_events_and_no_state_when_disabled(fresh_state):
    res = run_detection(as_of=AS_OF, emit_brain_events=False, verbose=False)
    assert res["events_logged"] == 0 and read_brain_events() == [] and not fresh_state.exists()


def test_brain_events_dedupe(fresh_state, alerts):
    n = len(alerts)
    first = run_detection(as_of=AS_OF, verbose=False)
    assert first["events_logged"] == n
    events = read_brain_events(limit=500)
    assert all(e["type"] == "anomaly" and e["region"] == "diagnose" and e["path"] == ["ingest", "diagnose"] for e in events)
    assert [e["ref_id"] for e in events] == [a["id"] for a in first["anomalies"]]  # ranked order
    assert run_detection(as_of=AS_OF, verbose=False)["events_logged"] == 0

    # worsen one: pretend the last run saw "stockout_risk:SKU-B" at low severity → exactly one new pulse
    state = load_state()
    state["active_anomalies"]["cpc_spike:google"]["severity"] = "low"
    save_state(state)
    third = run_detection(as_of=AS_OF, verbose=False)
    assert third["events_logged"] == 1 and "CPC spike" in third["event_messages"][0]

    # impact growth beyond 25% re-pulses too
    state = load_state()
    state["active_anomalies"]["creative_fatigue:CMP-01"]["profit_impact"] /= 2
    save_state(state)
    assert run_detection(as_of=AS_OF, verbose=False)["events_logged"] == 1


def test_event_message_and_payload(fresh_state):
    run_detection(as_of=AS_OF, verbose=False)
    ev = next(e for e in read_brain_events(limit=500) if e["payload"]["key"] == "creative_fatigue:CMP-01")
    assert ev["message"].startswith("Creative fatigue · Meta · Summer Sneakers · broad — CTR −")
    assert ev["entity_id"] == "CMP-01" and ev["severity"] == "low" and ev["payload"]["related"] == []
    knock = next(e for e in read_brain_events(limit=500) if e["payload"]["key"] == "conversion_drop:SKU-J")
    assert knock["payload"]["related"] == ["positive_spike:CMP-10"]
    cmp02 = next(e for e in read_brain_events(limit=500) if e["payload"]["key"] == "metric_shift:CMP-02")
    assert cmp02["payload"]["related"] == ["cpc_spike:google"]
    sb = next(e for e in read_brain_events(limit=500) if e["payload"]["key"] == "stockout_risk:SKU-B")
    assert {"SKU-B", "CMP-03", "CMP-04", "CMP-05"} <= set(sb["payload"]["targets"])


def test_resolved_keys_removed(fresh_state, monkeypatch):
    run_detection(as_of=AS_OF, verbose=False)
    assert "cpc_spike:google" in load_state()["active_anomalies"]
    real = d.detect_all
    monkeypatch.setattr("backend.detection.runner.detect_all",
                        lambda: [a for a in real() if a.kind != "cpc_spike"])
    res = run_detection(as_of=AS_OF, verbose=False)
    assert res["resolved"] == ["cpc_spike:google"]
    state = load_state()
    assert "cpc_spike:google" not in state["active_anomalies"] and res["events_logged"] == 0
    assert state["detection_quality"]["found"] == 6  # S3 now missed


def test_first_seen_kept_and_quality_saved(fresh_state):
    run_detection(as_of="2026-10-06T10:00:00", verbose=False)
    run_detection(as_of="2026-10-06T11:00:00", verbose=False)
    state = load_state()
    a = state["active_anomalies"]["creative_fatigue:CMP-01"]
    assert a["first_seen"] == "2026-10-06T10:00:00" and a["last_seen"] == "2026-10-06T11:00:00"
    assert state["detection_quality"]["found"] == 7 and state["detection_quality"]["expected"] == 7


# ---------------------------------------------------------------- validation script
def test_validation_script_passes(env):
    results = v.run_checks(v.build_context())
    failed = [(n, detail) for n, ok, detail in results if not ok]
    assert not failed, failed


# ---------------------------------------------------------------- robustness
@pytest.mark.parametrize("seed", [7, 123])
def test_robustness_other_seeds(tmp_path, monkeypatch, seed):
    _setup(tmp_path, monkeypatch, seed=seed)
    found = d.detect_all()
    missing = [p for p in PLANTED if pair(found, *p) is None]
    assert not missing, f"seed {seed} missed {missing}; alerts: {[(a.kind, a.entity_id) for a in found]}"
