"""Module 9: every public service function runs on a temporary pipeline and returns JSON-serialisable output,
then approve → learning → rollback works end to end. No HTTP involved."""
import json
import tempfile
from pathlib import Path

import pytest

from backend.api import service
from backend.core import config
from backend.core.db import reset_state
from backend.generator import generate as gen


@pytest.fixture(scope="module")
def pipe():
    root = Path(tempfile.mkdtemp(prefix="dq_pipe_"))
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(config, "DATA_DIR", root)
        mp.setattr(config, "RAW_DIR", root / "raw")
        mp.setattr(config, "DB_PATH", root / "engine.db")
        mp.setattr(config, "STATE_PATH", root / "state.json")
        gen.main(quiet=True)
        reset_state()
        service.invalidate()
        assert service.refresh()["ok"]
        yield root


def _dumps(obj):
    return json.dumps(obj, allow_nan=False)  # raises on NaN / Infinity


def test_every_read_function_is_json_safe(pipe):
    aid = service.anomalies()[0]["id"]
    calls = [service.kpis(), service.kpis(30), service.trend(), service.trend(14), service.channels(), service.campaigns(), service.sources(),
             service.data_quality(), service.anomalies(), service.diagnosis(aid), service.causal(), service.reconciliation(), service.audit(),
             service.learning(), service.pending_recommendations(), service.recommendations(), service.recommendations("clear_inventory"),
             service.optimize_plan(), service.optimize_plan("revenue_target"), service.simulate({"CMP-01": 30000}),
             service.channel_simulate({"google": 1.2}), service.curves(), service.opportunities(), service.get_settings(),
             service.brain_manifest(), service.brain_nodes(), service.brain_snapshot(), service.brain_events(), service.brain_events(limit=3),
             service.brain_state(), service.ask("Give me today's brief"), service.brain_targets_for(["CMP-01", "meta"])]
    for c in calls:
        assert json.loads(_dumps(c)) is not None
    assert isinstance(service.json_safe({"x": float("nan")}), str)


def test_write_functions_are_json_safe(pipe):
    assert _dumps(service.update_settings(autonomy="supervised", objective="max_profit"))
    assert service.brain_replay()["ok"] and _dumps(service.brain_replay())
    assert _dumps(service.refresh())
    assert _dumps(service.demo_reset())


def test_approve_learning_rollback(pipe):
    service.demo_reset()
    d = next(x for x in service.recommendations()["pending"] if x["action"]["changes"] and not x["blocked"])
    cid = d["action"]["changes"][0]["campaign_id"]
    spend = lambda: next(n for n in service.brain_nodes()["nodes"] if n["entity_id"] == cid)["current_spend"]  # noqa: E731
    before, outcomes = spend(), len(service.learning()["outcomes"])
    res = service.approve(d["id"])
    assert _dumps(res) and res["ok"]
    assert spend() != before
    assert len(service.learning()["outcomes"]) == outcomes + 1
    assert service.audit()
    assert service.approve(d["id"])["ok"] is False
    assert service.rollback(d["id"])["ok"] is True
    assert abs(spend() - before) < 0.01


def test_errors_are_typed(pipe):
    with pytest.raises(KeyError, match="Not found"):
        service.diagnosis("NOPE")
    with pytest.raises(KeyError):
        service.approve("REC-nope")
    with pytest.raises(ValueError):
        service.update_settings(autonomy="reckless")


def test_meta_config_and_last_refresh(pipe):
    cfg = service.meta_config()
    assert _dumps(cfg)
    assert cfg["detection"]["Z_THRESHOLD"] == config.Z_THRESHOLD and cfg["guardrails"]["CONFIDENCE_MAX"] == config.CONFIDENCE_MAX
    assert cfg["loop"]["REFRESH_MINUTES"] == config.REFRESH_MINUTES and cfg["currency"] == "INR"
    assert "ANTHROPIC_API_KEY" not in _dumps(cfg)
    reset_state()
    service.invalidate()
    assert service.last_refresh() is None
    res = service.refresh()
    last = service.last_refresh()
    assert last["ok"] is True and last["at"] and last["duration_ms"] == res["duration_ms"]
    assert set(last["steps"]) == {"ingest", "detect", "diagnose", "optimize", "decide", "learn"}
    assert all({"ok", "duration_ms", "events"} <= set(s) for s in last["steps"].values())
    assert sum(s["events"] for s in last["steps"].values()) == last["events_logged"]
