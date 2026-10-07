"""M0 contract tests. Run from the project root: python -m pytest -q"""
import dataclasses
import datetime as dt
import json
import math
import re

import numpy as np
import pandas as pd
import pytest

from backend.core import config, db, metrics, schema
from backend.core.schema import (
    Anomaly, BrainEvent, BrainState, CausalResult, Factor, NeuronNode, Opportunity,
    Recommendation, RootCause, make_brain_event, to_dict,
)


@pytest.fixture(autouse=True)
def tmp_data(tmp_path, monkeypatch):
    """Point every path at a temp dir so tests never touch real data."""
    data = tmp_path / "data"
    monkeypatch.setattr(config, "DATA_DIR", data)
    monkeypatch.setattr(config, "RAW_DIR", data / "raw")
    monkeypatch.setattr(config, "DB_PATH", data / "engine.db")
    monkeypatch.setattr(config, "STATE_PATH", data / "state.json")
    # db.py reads config.* at call time; guard against any module-level copies too
    for name in ("DB_PATH", "STATE_PATH", "DATA_DIR"):
        if hasattr(db, name):
            monkeypatch.setattr(db, name, getattr(config, name))
    return data


# ---------------------------------------------------------------- config
def test_validate_config():
    config.validate_config()


def test_id_patterns():
    valid = {"campaign": "CMP-01", "sku": "SKU-A", "creative": "CR-01a", "event": "EV-2",
             "anomaly": "AN-005", "recommendation": "REC-567405", "brain_event": "BE-00001"}
    for kind, example in valid.items():
        assert re.match(config.ID_PATTERNS[kind], example), (kind, example)
    assert not re.match(config.ID_PATTERNS["campaign"], "CMP-1")
    assert not re.match(config.ID_PATTERNS["sku"], "SKU-K")
    assert not re.match(config.ID_PATTERNS["recommendation"], "rec-567405")


# ---------------------------------------------------------------- schema
EXPECTED_FIELDS = {
    Anomaly: ["id", "kind", "entity_type", "entity_id", "label", "metric", "baseline", "recent",
              "change_pct", "z", "profit_impact", "severity", "detail"],
    Factor: ["name", "impact", "pct"],
    RootCause: ["anomaly_id", "entity_id", "total_change", "factors", "funnel", "narrative"],
    CausalResult: ["event_id", "description", "effect_per_day", "total_effect", "ci_low", "ci_high", "series"],
    Recommendation: ["id", "title", "issue", "cause", "action", "expected_profit_delta", "confidence", "risk",
                     "requires_approval", "blocked", "priority", "evidence", "anomaly_id", "status"],
    Opportunity: ["sku_id", "channel", "audience", "predicted_conv_per_1k", "predicted_poas", "unit_margin",
                  "stock_days", "score", "test_budget"],
    NeuronNode: ["entity_id", "entity_type", "label", "cluster", "channel", "sku_id", "spend_7d", "poas_7d",
                 "profit_7d", "change_pct", "health", "size", "is_alerting", "anomaly_id"],
    BrainEvent: ["id", "ts", "type", "region", "path", "entity_id", "ref_id", "severity", "message", "payload"],
    BrainState: ["mode", "active_region", "last_event_id", "counts"],
}


@pytest.mark.parametrize("cls", list(EXPECTED_FIELDS))
def test_dataclass_fields(cls):
    assert [f.name for f in dataclasses.fields(cls)] == EXPECTED_FIELDS[cls]


def test_to_dict_handles_everything():
    rc = RootCause("AN-001", "CMP-01", -100.0, [Factor("cpc", np.float64(-60.0), 0.6), Factor("cvr", -40.0, 0.4)])
    obj = {
        "nan": float("nan"), "inf": float("inf"), "ninf": -np.inf,
        "np_int": np.int64(3), "np_float": np.float32(1.5), "np_bool": np.bool_(True), "np_nan": np.float64("nan"),
        "ts": pd.Timestamp("2026-10-06 12:30:00"), "date": dt.date(2026, 10, 6), "nat": pd.NaT,
        "nested": rc, "tuple": (1, np.int8(2)), "arr": np.array([1.0, np.nan]),
        "df": pd.DataFrame({"a": [1, 2], "b": [np.nan, 3.0], "d": pd.to_datetime(["2026-10-05", "2026-10-06"])}),
        "series": pd.Series([1.0, np.inf]), 5: "int key",
    }
    out = to_dict(obj)
    text = json.dumps(out, allow_nan=False)
    assert out["nan"] is None and out["inf"] is None and out["ninf"] is None and out["np_nan"] is None
    assert out["np_int"] == 3 and type(out["np_int"]) is int
    assert out["np_bool"] is True
    assert out["ts"] == "2026-10-06T12:30:00"
    assert out["date"] == "2026-10-06"
    assert out["nat"] is None
    assert out["nested"]["factors"][0] == {"name": "cpc", "impact": -60.0, "pct": 0.6}
    assert out["arr"] == [1.0, None]
    assert out["df"][0] == {"a": 1, "b": None, "d": "2026-10-05T00:00:00"}
    assert out["series"] == [1.0, None]
    assert "5" in out
    assert text


def test_root_cause_check_sum():
    ok = RootCause("AN-001", "CMP-01", -100.0, [Factor("a", -60.0, 0.6), Factor("b", -40.5, 0.4)])
    bad = RootCause("AN-001", "CMP-01", -100.0, [Factor("a", -60.0, 0.6), Factor("b", -10.0, 0.1)])
    assert ok.check_sum()
    assert not bad.check_sum()
    assert RootCause("AN-002", "CMP-02", 0.0).check_sum()


def test_make_recommendation_id():
    rid = Recommendation.make_recommendation_id("Refresh creative on CMP-01")
    assert rid == Recommendation.make_recommendation_id("Refresh creative on CMP-01")
    assert re.match(config.ID_PATTERNS["recommendation"], rid)
    assert rid != Recommendation.make_recommendation_id("Something else")


def test_make_brain_event_all_types():
    for t in config.BRAIN_EVENT_TYPES:
        ev = make_brain_event(t)
        assert ev.region == config.EVENT_REGION[t]
        assert ev.path == config.PULSE_PATHS[t]
        assert ev.id == ""
        assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$", ev.ts)
    with pytest.raises(ValueError):
        make_brain_event("explosion")


# ---------------------------------------------------------------- metrics
def test_basic_metrics_scalar_and_series():
    assert metrics.ctr(20, 1000) == pytest.approx(0.02)
    assert metrics.cpm(500, 100000) == pytest.approx(5.0)
    assert metrics.poas(1500, 1000) == pytest.approx(1.5)
    assert metrics.gross_margin(10, 500, 200) == pytest.approx(3000)
    assert metrics.contribution_profit(3000, 1000) == pytest.approx(2000)
    assert metrics.change_pct(120, 100) == pytest.approx(0.2)
    assert metrics.inflation_pct(130, 100) == pytest.approx(0.3)
    s = metrics.ctr(pd.Series([10, 0, 5]), pd.Series([100, 0, 0]))
    assert s.iloc[0] == pytest.approx(0.1) and math.isnan(s.iloc[1]) and math.isnan(s.iloc[2])
    assert metrics.cpm(pd.Series([10.0]), pd.Series([0])).isna().all()
    assert metrics.gross_margin(pd.Series([2, 3]), 100.0, 40.0).tolist() == [120.0, 180.0]


def test_safe_division_never_inf():
    for fn, args in [(metrics.safe_div, (1, 0)), (metrics.ctr, (5, 0)), (metrics.cpm, (5, 0)),
                     (metrics.cpc, (5, 0)), (metrics.change_pct, (5, 0)), (metrics.days_cover, (50, 0)),
                     (metrics.inflation_pct, (5, 0)), (metrics.safe_div, (None, 2))]:
        assert fn(*args) is None
    s = metrics.safe_div(pd.Series([1.0, -1.0, 0.0]), pd.Series([0.0, 0.0, 0.0]))
    assert s.isna().all() and not np.isinf(s).any()


def test_trust_score_clipping():
    assert metrics.trust_score(0.6) == 0.0
    assert metrics.trust_score(-0.1) == 1.0
    assert metrics.trust_score(0.2) == pytest.approx(0.6)
    assert metrics.trust_score(pd.Series([0.6, -0.1])).tolist() == [0.0, 1.0]


def test_format_inr():
    assert metrics.format_inr(123456) == "₹1.23L"
    assert metrics.format_inr(12000000) == "₹1.20Cr"
    assert metrics.format_inr(12300) == "₹12.3k"
    assert metrics.format_inr(-12300) == "-₹12.3k"
    assert metrics.format_inr(850) == "₹850"
    assert metrics.format_inr(None) == "—"


def test_neuron_health_boundaries():
    assert metrics.neuron_health(1.2) == "good"
    assert metrics.neuron_health(1.19) == "weak"
    assert metrics.neuron_health(0.8) == "weak"
    assert metrics.neuron_health(0.79) == "losing"
    assert metrics.neuron_health(None) == "weak"
    assert metrics.neuron_health(float("nan")) == "weak"


def test_severity_from_impact():
    assert metrics.severity_from_impact(-30000) == "high"
    assert metrics.severity_from_impact(-10000) == "medium"
    assert metrics.severity_from_impact(-1000) == "low"
    assert metrics.severity_from_impact(50000) == "low"


def test_neuron_size():
    assert metrics.neuron_size(0, 0, 100) == pytest.approx(config.NEURON_SIZE_MIN)
    assert metrics.neuron_size(100, 0, 100) == pytest.approx(config.NEURON_SIZE_MAX)
    assert metrics.neuron_size(50, 50, 50) == pytest.approx((config.NEURON_SIZE_MIN + config.NEURON_SIZE_MAX) / 2)


# ---------------------------------------------------------------- db / storage
def test_sqlite_round_trip_and_errors():
    db.write_table(pd.DataFrame({"a": [1, 2]}), "t1")
    assert db.table_exists("t1") and "t1" in db.list_tables()
    assert len(db.read_table("t1")) == 2
    assert db.query("SELECT SUM(a) AS s FROM t1 WHERE a > ?", (0,))["s"].iloc[0] == 3
    with pytest.raises(LookupError, match="nope"):
        db.read_table("nope")


def test_validate_table():
    cols = db.TABLE_COLUMNS["events"]
    db.validate_table(pd.DataFrame(columns=cols + ["extra"]), "events")
    with pytest.raises(ValueError, match="description"):
        db.validate_table(pd.DataFrame(columns=cols[:-1]), "events")


def test_load_state_merges_old_file(tmp_data):
    old = {"decisions": [{"id": "REC-abcdef", "status": "executed"}], "autonomy": "advisory",
           "calibration": {"factor": 0.9}}
    tmp_data.mkdir(parents=True, exist_ok=True)
    config.STATE_PATH.write_text(json.dumps(old))
    s = db.load_state()
    assert s["decisions"] == old["decisions"] and s["autonomy"] == "advisory"
    assert s["brain_events"] == [] and s["brain_event_seq"] == 0
    assert s["calibration"] == {"factor": 0.9, "mape": None, "win_rate": None, "n": 0}
    # fresh dict each time
    assert db.default_state() is not db.default_state()
    del old["calibration"]
    config.STATE_PATH.write_text(json.dumps(old))
    assert db.load_state()["calibration"]["factor"] == 1.0


def test_save_state_atomic_and_corrupt_fallback(tmp_data):
    state = db.load_state()
    state["audit"].append({"value": float("nan"), "n": np.int64(4)})
    db.save_state(state)
    assert json.loads(config.STATE_PATH.read_text())["audit"] == [{"value": None, "n": 4}]
    assert [p.name for p in config.STATE_PATH.parent.iterdir()] == ["state.json"]  # no temp files left
    config.STATE_PATH.write_text("{not json")
    assert db.load_state() == db.default_state()
    db.reset_state()
    assert not config.STATE_PATH.exists()


def test_brain_event_log(monkeypatch):
    e1 = db.log_brain_event(make_brain_event("ingest"))
    e2 = db.log_brain_event(make_brain_event("anomaly", ref_id="AN-001"))
    assert (e1.id, e2.id) == ("BE-00001", "BE-00002")
    for t in ["diagnosis", "recommendation", "approval"]:
        db.log_brain_event(make_brain_event(t))
    newer = db.read_brain_events(since_id="BE-00002")
    assert [e["id"] for e in newer] == ["BE-00003", "BE-00004", "BE-00005"]
    assert [e["id"] for e in db.read_brain_events(limit=2)] == ["BE-00004", "BE-00005"]
    assert db.read_brain_events(since_id="BE-00003", limit=1)[0]["id"] == "BE-00004"

    monkeypatch.setattr(config, "BRAIN_EVENT_HISTORY_LIMIT", 3)
    db.log_brain_event(make_brain_event("outcome"))
    ids = [e["id"] for e in db.load_state()["brain_events"]]
    assert ids == ["BE-00004", "BE-00005", "BE-00006"]

    db.clear_brain_events()
    s = db.load_state()
    assert s["brain_events"] == [] and s["brain_event_seq"] == 0
    assert db.log_brain_event(make_brain_event("ingest")).id == "BE-00001"
