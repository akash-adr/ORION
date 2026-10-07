"""M5 / M5b tests: response curves, optimizer, simulator, opportunity scorer and persistence.

M1 data is generated and M2 / M3 run inside a pytest temp folder; config.RAW_DIR / DB_PATH / STATE_PATH are
monkeypatched (every module reads them from `config` at call time), so the real data/ is never touched.
"""
import dataclasses
import json
import time

import numpy as np
import pandas as pd
import pytest
from sklearn.linear_model import Ridge
from sklearn.metrics import r2_score
from sklearn.model_selection import GroupKFold, KFold

from backend.core import config
from backend.core.db import load_state, read_brain_events, read_table, save_state
from backend.core.schema import Opportunity
from backend.detection.runner import run_detection
from backend.generator import generate as gen
from backend.ingest.pipeline import run_pipeline
from backend.optimizer import curves as cv
from backend.optimizer import opportunity as opp
from backend.optimizer import optimize as op
from backend.optimizer import validate as v
from backend.optimizer.runner import headroom, run_optimizer

AS_OF = "2026-10-06T23:00:00"
LOW_STOCK = ("CMP-03", "CMP-04", "CMP-05")


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    root = tmp_path_factory.mktemp("m5")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(config, "DATA_DIR", root)
        mp.setattr(config, "RAW_DIR", root / "raw")
        mp.setattr(config, "DB_PATH", root / "engine.db")
        mp.setattr(config, "STATE_PATH", root / "state.json")
        gen.main(quiet=True)
        run_pipeline(as_of=AS_OF, verbose=False, emit_brain_events=False)
        run_detection(as_of=AS_OF, emit_brain_events=False, verbose=False)
        yield


@pytest.fixture(scope="module")
def curves(env):
    return cv.fit_curves(refresh=True)


@pytest.fixture(scope="module")
def results(env, curves):
    return {o: op.optimize(o) for o in config.OBJECTIVES}


@pytest.fixture
def fresh_state(env, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "STATE_PATH", tmp_path / "state.json")
    return tmp_path / "state.json"


def row(cover, current=10000.0):
    return {"current_spend": current, "days_cover": cover}


# ---------------------------------------------------------------- curve math
def test_hill_and_marginal_math():
    a, b = 50000.0, 20000.0
    for s in (0.0, 5000.0, 20000.0, 90000.0):
        h = 1e-3
        numeric = (cv.hill(s + h, a, b) - cv.hill(max(s - h, 0.0), a, b)) / (s + h - max(s - h, 0.0))
        assert cv.marginal_poas(s, a, b) == pytest.approx(numeric, rel=1e-4)
    assert cv.hill(b, a, b) == pytest.approx(a / 2)  # b is the half-saturation spend
    assert cv.hill(np.array([0.0, 1e12]), a, b)[1] == pytest.approx(a, rel=1e-6)  # a is the ceiling


def test_optimal_spend_where_marginal_equals_one():
    for a, b in [(40000.0, 8000.0), (115000.0, 45000.0), (3000.0, 9000.0)]:
        s = cv.optimal_spend(a, b)
        if a > b:
            assert cv.marginal_poas(s, a, b) == pytest.approx(1.0)
            profit = lambda x: cv.hill(x, a, b) - x  # noqa: E731
            assert profit(s) >= profit(s * 0.9) and profit(s) >= profit(s * 1.1)
        else:
            assert s == 0.0  # the very first rupee already loses money


def test_reanchor_passes_through_recent_point(curves):
    for _, r in curves.iterrows():
        assert r["gm_7d"] > 0
        assert cv.hill(r["spend_7d"], r["a"], r["b"]) == pytest.approx(r["gm_7d"], rel=1e-9)
    assert list(curves["campaign_id"]) == sorted(curves["campaign_id"]) and len(curves) == 16
    assert curves["flags"].map(lambda f: "negative_recent_margin" not in f).all()


def test_curve_fields_and_points(curves):
    r = curves.iloc[0]
    assert r["saturation_spend"] == pytest.approx(config.SATURATION_MULT * r["b"])
    pts = cv.curve_points(r)
    assert len(pts) == config.CURVE_POINTS and pts[0]["spend"] == 0.0 and pts[0]["gross_margin"] == 0.0
    assert pts[-1]["spend"] == pytest.approx(max(2.5 * r["current_spend"], 1.2 * r["saturation_spend"]), abs=0.01)
    assert all(p["profit"] == pytest.approx(p["gross_margin"] - p["spend"], abs=0.02) for p in pts)


def test_budget_override_used_as_current_spend(fresh_state):
    base = cv.fit_curves(refresh=True).set_index("campaign_id")
    state = load_state()
    state["budget_overrides"] = {"CMP-06": 12345.0}
    save_state(state)
    over = cv.fit_curves().set_index("campaign_id")  # the state file changed → cache invalidated
    assert over.at["CMP-06", "current_spend"] == 12345.0 and base.at["CMP-06", "current_spend"] != 12345.0
    assert over.at["CMP-06", "marginal_poas"] == pytest.approx(
        cv.marginal_poas(12345.0, over.at["CMP-06", "a"], over.at["CMP-06", "b"]))
    assert over.at["CMP-07", "current_spend"] == base.at["CMP-07", "current_spend"]


# ---------------------------------------------------------------- bounds
def test_bounds_change_cap():
    lo, hi, reasons = op._bounds(row(cover=50), "max_profit")
    assert (lo, hi, reasons) == (5000.0, 15000.0, ["change_cap"])


def test_bounds_stock_guard():
    lo, hi, reasons = op._bounds(row(cover=5), "max_profit")
    assert hi == 10000.0 * config.STOCK_SPEND_CAP_MULT and lo == hi  # increases blocked, forced down to the cap
    assert reasons == ["change_cap", "stock_guard"]
    assert op._bounds(row(cover=config.STOCK_COVER_RISK_DAYS), "max_profit")[2] == ["change_cap"]  # boundary is safe


def test_bounds_overstock_only_for_clear_inventory():
    assert op._bounds(row(cover=77), "clear_inventory") == (5000.0, 20000.0, ["change_cap", "overstock_boost"])
    for obj in ("max_profit", "revenue_target", "launch_sku"):
        assert op._bounds(row(cover=77), obj)[1] == 15000.0
    assert op._bounds(row(cover=config.OVERSTOCK_COVER_DAYS), "clear_inventory")[1] == 15000.0  # must be ABOVE 60


# ---------------------------------------------------------------- optimizer
def test_max_profit_improves_profit(results):
    r = results["max_profit"]
    assert r["solver"]["ok"] and r["summary"]["profit_delta"] > 0
    assert r["summary"]["planned"]["profit"] > r["summary"]["current"]["profit"]
    rows = {c["campaign_id"]: c for c in r["campaigns"]}
    assert rows["CMP-07"]["change_pct"] > 0 and rows["CMP-01"]["change_pct"] < 0  # scale the winner, cut the loser
    assert rows["CMP-01"]["marginal_poas_planned"] >= rows["CMP-01"]["marginal_poas_current"]  # moving toward 1


def test_no_spend_increase_on_low_stock_skus(results):
    for obj, r in results.items():
        rows = {c["campaign_id"]: c for c in r["campaigns"]}
        for k in LOW_STOCK:
            assert rows[k]["planned_spend"] <= rows[k]["current_spend"], (obj, k)
            assert rows[k]["stock_locked"] is True and "stock_guard" in rows[k]["bound_reasons"]
            assert rows[k]["planned_spend"] <= rows[k]["current_spend"] * config.STOCK_SPEND_CAP_MULT + 1e-6


def test_every_campaign_within_cap_except_exceptions(results):
    for obj, r in results.items():
        for c in r["campaigns"]:
            if "stock_guard" in c["bound_reasons"] or "overstock_boost" in c["bound_reasons"]:
                continue
            assert abs(c["change_pct"]) <= config.DAILY_CHANGE_CAP + 0.001, (obj, c["campaign_id"])
    assert any("overstock_boost" in c["bound_reasons"] for c in results["clear_inventory"]["campaigns"])
    assert not any("overstock_boost" in c["bound_reasons"] for c in results["max_profit"]["campaigns"])


def test_budget_constraint_respected(results):
    for obj, r in results.items():
        cap = r["total_budget"] * (1 - (config.LAUNCH_TEST_RESERVE if obj == "launch_sku" else 0))
        assert r["summary"]["planned"]["spend"] <= cap + 1e-6, obj
    tight = op.optimize("max_profit", total_budget=190000)  # a smaller budget binds the constraint
    assert tight["solver"]["ok"] and tight["summary"]["planned"]["spend"] <= 190000 + 1e-6 and tight["total_budget"] == 190000
    assert tight["summary"]["planned"]["spend"] > 0.9 * 190000  # and it actually uses the money where it earns


def test_infeasible_budget_is_reported_not_hidden(env):
    """Below the minimum reachable spend (daily change cap + stock guard) no plan can fit: say so."""
    r = op.optimize("max_profit", total_budget=120000)
    assert r["solver"]["ok"] is False and "infeasible" in r["solver"]["message"]
    assert all(c["planned_spend"] <= c["current_spend"] for c in r["campaigns"])  # at the lower bounds: never an increase


def test_revenue_target_holds_profit(results):
    s = results["revenue_target"]["summary"]
    assert s["planned"]["profit"] >= s["current"]["profit"] - 1.0
    assert results["revenue_target"]["solver"]["ok"]
    # it spends more than max_profit (it chases revenue, not margin) but never gives up the profit it has today
    assert s["planned"]["spend"] > results["max_profit"]["summary"]["planned"]["spend"]
    assert s["planned"]["revenue"] > results["max_profit"]["summary"]["planned"]["revenue"]


def test_clear_inventory_pushes_overstock(results):
    ci = {c["campaign_id"]: c for c in results["clear_inventory"]["campaigns"]}
    mp = {c["campaign_id"]: c for c in results["max_profit"]["campaigns"]}
    assert ci["CMP-14"]["planned_spend"] >= mp["CMP-14"]["planned_spend"]
    assert ci["CMP-14"]["planned_spend"] <= ci["CMP-14"]["current_spend"] * config.OVERSTOCK_UPPER_MULT + 10
    w = op._inventory_weight(np.array([10.0, 30.0, 60.0, 200.0]))
    assert list(w[:2]) == [1.0, 1.0] and w[2] == pytest.approx(2.0) and w[3] == pytest.approx(1 + config.CLEAR_INV_MAX_BONUS)


def test_launch_sku_reserves_budget(results):
    r = results["launch_sku"]
    assert r["reserved_test_budget"] == pytest.approx(config.LAUNCH_TEST_RESERVE * r["total_budget"], abs=0.01)
    assert r["summary"]["planned"]["spend"] <= 0.95 * r["total_budget"] + 1e-6
    assert "reserved_test_budget" not in results["max_profit"]


def test_plan_values_rounded_and_solver_ok(results):
    for r in results.values():
        assert r["solver"]["ok"] and set(r["solver"]) == {"ok", "iterations", "message"}
        assert all(v % 10 == 0 for v in r["plan"].values())
        assert set(r["plan"]) == {c["campaign_id"] for c in r["campaigns"]} and len(r["plan"]) == 16
    with pytest.raises(ValueError, match="unknown objective"):
        op.optimize("make_money")


# ---------------------------------------------------------------- simulator
def test_simulate_speed_and_stock_warning(curves):
    cv.fit_curves()
    cur = curves.set_index("campaign_id")["current_spend"]
    t0 = time.perf_counter()
    s = op.simulate({"CMP-03": cur["CMP-03"] * 1.2, "CMP-06": cur["CMP-06"] * 1.2})
    assert (time.perf_counter() - t0) * 1000 < config.SIMULATE_MAX_MS
    assert s["summary"]["stock_warnings"] == ["CMP-03"]  # CMP-06's SKU has plenty of stock
    assert not op.simulate({"CMP-03": cur["CMP-03"] * 0.8})["summary"]["stock_warnings"]  # a cut is safe
    assert op.simulate({})["summary"]["profit_delta"] == pytest.approx(0.0, abs=1e-6)  # no change, no delta
    with pytest.raises(ValueError, match="CMP-99"):
        op.simulate({"CMP-99": 1000.0})


def test_channel_simulate_google_up_hurts(curves):
    t0 = time.perf_counter()
    up = op.channel_simulate({"google": 1.2})
    assert (time.perf_counter() - t0) * 1000 < config.SIMULATE_MAX_MS
    assert up["summary"]["profit_delta"] < 0 and up["summary"]["spend_delta"] > 0
    moved = {c["campaign_id"] for c in up["campaigns"] if c["new_spend"] != c["current_spend"]}
    assert moved == {"CMP-02", "CMP-04", "CMP-06", "CMP-15"}  # exactly the Google campaigns
    assert op.channel_simulate({"google": 0.8})["summary"]["profit_delta"] > 0  # trimming Google helps
    with pytest.raises(ValueError, match="unknown channels"):
        op.channel_simulate({"myspace": 2.0})


# ---------------------------------------------------------------- M5b
def test_opportunities_exclude_existing_and_low_stock(env):
    rows = opp.scored_rows()
    camps = read_table("dim_campaign")
    existing = set(zip(camps["sku_id"], camps["channel"], camps["audience"]))
    assert rows and len(rows) <= config.OPP_TOP_N
    assert not any((r["sku_id"], r["channel"], r["audience"]) in existing for r in rows)
    assert all(r["stock_days"] >= config.STOCK_COVER_RISK_DAYS for r in rows) and not any(r["sku_id"] == "SKU-B" for r in rows)
    assert [r["score"] for r in rows] == sorted((r["score"] for r in rows), reverse=True)
    assert len({(r["sku_id"], r["channel"]) for r in rows}) == len(rows)  # best audience per SKU × channel
    assert rows[0]["sku_id"] == "SKU-C" and rows[0]["channel"] == "google"
    assert sum(r["is_ghost"] for r in rows) == min(config.OPP_GHOST_N, len(rows))
    assert [r["rank"] for r in rows] == list(range(1, len(rows) + 1))
    assert rows[0]["label"] == "Trail Max · Google · retargeting"


def test_stock_factor_rules():
    assert opp.stock_factor(5) == 0.0 and opp.stock_factor(config.STOCK_COVER_RISK_DAYS - 0.1) == 0.0
    assert opp.stock_factor(config.STOCK_COVER_RISK_DAYS) == config.STOCK_FACTOR_MIN  # 7/30 clipped up to 0.5
    assert opp.stock_factor(30) == 1.0 and opp.stock_factor(500) == config.STOCK_FACTOR_MAX


def test_groupkfold_not_random(env):
    df = opp.training_frame()
    splits = opp.cv_splits(df)
    assert len(splits) == config.CV_FOLDS
    for tr, te in splits:
        assert set(df.iloc[tr]["campaign_id"]).isdisjoint(set(df.iloc[te]["campaign_id"]))  # whole campaigns held out
    covered = np.sort(np.concatenate([te for _, te in splits]))
    assert list(covered) == list(range(len(df)))  # every row is tested exactly once
    assert isinstance(GroupKFold(n_splits=config.CV_FOLDS), GroupKFold)
    # why it matters: a random KFold leaks campaign identity and flatters the score
    x, y = opp._features(df), df["y"].to_numpy(float)
    random_r2 = np.mean([r2_score(y[te], Ridge(alpha=config.RIDGE_ALPHA).fit(x[tr], y[tr]).predict(x[te]))
                         for tr, te in KFold(config.CV_FOLDS, shuffle=True, random_state=0).split(x)])
    grouped_r2 = opp.train()["r2_holdout"]
    assert grouped_r2 < random_r2


def test_train_reports_honest_metrics(env):
    t = opp.train()
    assert len(t["r2_folds"]) == config.CV_FOLDS and np.isfinite(t["r2_holdout"])
    assert t["r2_holdout"] == pytest.approx(np.mean(t["r2_folds"])) and t["r2_holdout"] < 0.5  # a ranking signal only
    assert t["n_rows"] == 1440 and t["n_features"] == len(t["features"]) == len(t["coefficients"])
    assert t["coefficients"]["log_spend"] < 0  # diminishing returns: more spend, fewer orders per ₹
    assert t["coefficients"]["rating"] > 0 and t["coefficients"]["audience=retargeting"] > t["coefficients"]["audience=broad"]


def test_opportunity_fields_match_m0_shape(env):
    objs = opp.score_opportunities()
    assert objs and all(isinstance(o, Opportunity) for o in objs)
    assert [f.name for f in dataclasses.fields(Opportunity)] == [
        "sku_id", "channel", "audience", "predicted_conv_per_1k", "predicted_poas", "unit_margin", "stock_days",
        "score", "test_budget"]
    o = objs[0]
    assert o.test_budget == config.OPP_TEST_BUDGET
    assert o.predicted_poas == pytest.approx(o.predicted_conv_per_1k / 1000 * o.unit_margin)
    assert o.score == pytest.approx(o.predicted_poas * opp.stock_factor(o.stock_days))


# ---------------------------------------------------------------- persistence and brain outputs
def test_headroom_classes():
    assert headroom(1.6, 50) == "scale" and headroom(0.5, 50) == "cut" and headroom(1.0, 50) == "hold"
    assert headroom(config.HEADROOM_SCALE_POAS, 50) == "hold" and headroom(config.HEADROOM_CUT_POAS, 50) == "hold"
    assert headroom(2.0, 5) == "locked" and headroom(0.1, 5) == "locked"  # the stock guard wins over POAS


def test_tables_written_brain_ready(env):
    s = run_optimizer(as_of=AS_OF, verbose=False)
    c = read_table("curves").set_index("campaign_id")
    assert len(c) == 16 and set(c["headroom"]) <= {"scale", "hold", "cut", "locked"}
    assert all(c.loc[k, "headroom"] == "locked" for k in LOW_STOCK)
    assert (c.loc[["CMP-11", "CMP-12", "CMP-15", "CMP-16"], "headroom"] == "cut").all()
    assert c.loc["CMP-07", "headroom"] == "scale" and sum(s["headroom"].values()) == 16
    assert all(len(json.loads(p)) == config.CURVE_POINTS for p in c["points_json"])
    p = read_table("budget_plans")
    assert len(p) == 64 and set(p["objective"]) == set(config.OBJECTIVES) and p.groupby("objective").size().eq(16).all()
    sm = read_table("plan_summaries").set_index("objective")
    assert len(sm) == 4 and sm.at["launch_sku", "reserved_test_budget"] > 0 and sm.at["max_profit", "reserved_test_budget"] == 0
    assert sm.at["max_profit", "profit_delta"] == pytest.approx(s["objectives"]["max_profit"])
    o = read_table("opportunities")
    assert len(o) == s["opportunities"] and o["is_ghost"].sum() == s["ghosts"] == config.OPP_GHOST_N
    mm = read_table("model_metrics").iloc[0]
    assert mm["model"] == "ridge" and "GroupKFold" in mm["cv"] and mm["r2_holdout"] == pytest.approx(s["r2_holdout"])


def test_m5_emits_no_brain_events(fresh_state):
    run_optimizer(as_of=AS_OF, verbose=False)
    assert read_brain_events() == [] and not fresh_state.exists()  # M5 analyses; M6 emits the recommendation pulses
    state = load_state()
    assert state["brain_events"] == [] and state["brain_event_seq"] == 0


# ---------------------------------------------------------------- determinism and the validation script
def test_deterministic(env):
    def sig():
        s = run_optimizer(as_of=AS_OF, verbose=False)
        return (s["_curves"].drop(columns=["flags"]).round(8).to_dict("records"),
                {o: r["plan"] for o, r in s["_results"].items()}, s["_rows"], s["r2_holdout"])
    assert sig() == sig()


def test_validation_script_passes(env):
    results = v.run_checks(v.build_context())
    failed = [(n, d) for n, status, d in results if status == "FAIL"]
    assert not failed, failed
