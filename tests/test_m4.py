"""M4 / M4b tests: LMDI waterfall, narratives, drill-downs, synthetic-control causal analysis, persistence and
brain-event dedupe.

M1 data is generated and M2 run inside a pytest temp folder; config.RAW_DIR / DB_PATH / STATE_PATH are
monkeypatched (every module reads them from `config` at call time), so the real data/ is never touched.
"""
import json
import math

import numpy as np
import pandas as pd
import pytest

from backend.core import config
from backend.core.db import load_state, read_brain_events, read_table, save_state
from backend.core.schema import Anomaly, RootCause
from backend.detection.detectors import detect_all
from backend.diagnosis import causal as cz
from backend.diagnosis import decompose as d
from backend.diagnosis import validate as v
from backend.diagnosis.runner import run_diagnosis
from backend.generator import generate as gen
from backend.ingest.pipeline import run_pipeline

AS_OF = "2026-10-06T23:00:00"


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    root = tmp_path_factory.mktemp("m4")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(config, "DATA_DIR", root)
        mp.setattr(config, "RAW_DIR", root / "raw")
        mp.setattr(config, "DB_PATH", root / "engine.db")
        mp.setattr(config, "STATE_PATH", root / "state.json")
        gen.main(quiet=True)
        run_pipeline(as_of=AS_OF, verbose=False, emit_brain_events=False)
        yield


@pytest.fixture(scope="module")
def anomalies(env):
    return detect_all()


@pytest.fixture(scope="module")
def causal(env, anomalies):
    return cz.compute_causal(anomalies)


@pytest.fixture(scope="module")
def roots(env, anomalies, causal):
    return d.diagnose_all(anomalies, causal)


@pytest.fixture
def fresh_state(env, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "STATE_PATH", tmp_path / "state.json")
    return tmp_path / "state.json"


def by(anomalies, roots, kind, entity):
    for a, rc in zip(anomalies, roots):
        if (a.kind, a.entity_id) == (kind, entity):
            return a, rc
    raise AssertionError((kind, entity))


def factor(rc, name):
    return next(f.impact for f in rc.factors if f.name == name)


def campaign_frames(window=("2026-09-09", "2026-09-29")):
    fact = read_table("fact_daily")
    return fact[(fact["campaign_id"] == "CMP-06") & fact["date"].between(*window)].copy()


# ---------------------------------------------------------------- waterfall exactness
def test_waterfall_sums_exactly(anomalies, roots):
    checked = 0
    for a, rc in zip(anomalies, roots):
        if a.kind == "attribution_inflation":
            assert rc.factors == [] and rc.total_change == 0.0
            continue
        assert abs(sum(f.impact for f in rc.factors) - rc.total_change) < 1e-6  # rounded bars sum exactly
        assert rc.check_sum(tol=0.01)
        assert sum(f.pct for f in rc.factors) == pytest.approx(1.0, abs=0.01)
        checked += 1
    assert checked == 7


def test_lmdi_exact_on_synthetic_inputs():
    rng = np.random.default_rng(3)
    for _ in range(25):
        d0 = {k: float(rng.uniform(0.5, 5)) for k in d.CAMPAIGN_DRIVERS}
        d1 = {k: float(rng.uniform(0.5, 5)) for k in d.CAMPAIGN_DRIVERS}
        gm = lambda x: x["spend"] / x["cpm"] * x["ctr"] * x["cvr"] * x["unit_margin"]  # noqa: E731
        c = d._lmdi(gm(d0), gm(d1), d0, d1, d.SIGNS)
        assert sum(c.values()) == pytest.approx(gm(d1) - gm(d0), abs=1e-6)
    assert d._lmdi(40.0, 40.0, d0, d1, d.SIGNS) == {k: 0.0 for k in d.CAMPAIGN_DRIVERS}


def test_lmdi_fallback_when_gm_nonpositive():
    d0 = {k: 1.0 for k in d.CAMPAIGN_DRIVERS}
    d1 = {k: 2.0 for k in d.CAMPAIGN_DRIVERS}
    for gm0, gm1 in [(-50.0, 30.0), (20.0, -10.0), (0.0, 25.0), (-5.0, -9.0)]:
        c = d._lmdi(gm0, gm1, d0, d1, d.SIGNS)
        assert all(v == pytest.approx((gm1 - gm0) / 5) for v in c.values())  # equal split
        assert sum(c.values()) == pytest.approx(gm1 - gm0)


def test_budget_factor_subtracts_extra_spend(env):
    base = campaign_frames()
    recent = base.copy()
    for col in ("spend", "impressions", "clicks", "orders", "gross_margin"):
        recent[col] = recent[col] * 1.2  # pure budget scale-up: every rate unchanged
    factors, total, p0, p1 = d._decompose_campaign_frame(recent, base, 21, 21)
    by_name = {f.name: f.impact for f in factors}
    expected = (p1["gm"] - p0["gm"]) - (p1["spend"] - p0["spend"])
    assert by_name[d.BUDGET] == pytest.approx(expected, abs=0.01)
    assert total == pytest.approx(expected, abs=0.01)
    assert all(abs(v) < 0.011 for n, v in by_name.items() if n != d.BUDGET)


def test_cpm_sign_negative(env):
    base = campaign_frames()
    recent = base.copy()
    for col in ("impressions", "clicks", "orders", "gross_margin"):
        recent[col] = recent[col] / 1.3  # same spend buys fewer impressions: CPM up 30%
    factors, total, p0, p1 = d._decompose_campaign_frame(recent, base, 21, 21)
    assert p1["cpm"] == pytest.approx(p0["cpm"] * 1.3)
    by_name = {f.name: f.impact for f in factors}
    assert by_name[d.AUCTION] < 0 and by_name[d.AUCTION] == pytest.approx(total, abs=0.01)
    assert d.SIGNS["cpm"] == -1.0


# ---------------------------------------------------------------- planted scenarios
def test_top_factors_for_planted_scenarios(anomalies, roots):
    expected = {("cpc_spike", "google"): d.AUCTION, ("creative_fatigue", "CMP-01"): d.CREATIVE,
                ("positive_spike", "CMP-10"): d.CREATIVE, ("metric_shift", "CMP-02"): d.AUCTION}
    for key, name in expected.items():
        _, rc = by(anomalies, roots, *key)
        assert d._top_factor(rc.factors, rc.total_change).name == name, key


def test_conversion_drop_tradeoff_signs(anomalies, roots):
    _, rc = by(anomalies, roots, "conversion_drop", "SKU-D")
    assert factor(rc, d.SITE_CVR) < 0 and factor(rc, d.MARGIN) > 0
    assert [f.name for f in rc.factors] == d.FACTOR_ORDER["sku"]
    assert "traded customers for margin" in rc.narrative and "See causal analysis for proof." in rc.narrative


def test_narrative_direction_consistency(anomalies, roots):
    for a, rc in zip(anomalies, roots):
        if not rc.factors:
            continue
        top = d._top_factor(rc.factors, rc.total_change)
        assert top.impact * rc.total_change > 0  # the named driver never contradicts the total
        assert ("rose by" if rc.total_change > 0 else "fell by") in rc.narrative
        assert top.name in rc.narrative


def test_narrative_offset_sentence(env):
    t = d.Tables()
    a = Anomaly("AN-999", "metric_shift", "campaign", "CMP-01", "Profit drop · test", "profit", 0.0, 0.0, -0.3, -3.0,
                -1000.0, "low", {"direction": "loss", "related": [],
                                "window": {"recent_start": "2026-09-30", "recent_end": "2026-10-06",
                                           "baseline_start": "2026-09-09", "baseline_end": "2026-09-29"}})
    big = [d.Factor(d.BUDGET, 0.0, 0.0), d.Factor(d.AUCTION, -1000.0, 0.7), d.Factor(d.CREATIVE, 0.0, 0.0),
           d.Factor(d.CONVERSION, 300.0, 0.3), d.Factor(d.MARGIN, 0.0, 0.0)]
    text = d._narrative(a, big, -700.0, {}, t, [])
    assert "Partly offset by Conversion rate (₹300/day)." in text
    small = [d.Factor(f.name, 150.0 if f.name == d.CONVERSION else f.impact, f.pct) for f in big]
    assert "Partly offset" not in d._narrative(a, small, -850.0, {}, t, [])  # 15% < 20%


def test_knock_on_narratives_linked(anomalies, roots):
    _, cmp02 = by(anomalies, roots, "metric_shift", "CMP-02")
    assert "Linked to: CPC spike · Google." in cmp02.narrative
    _, skuj = by(anomalies, roots, "conversion_drop", "SKU-J")
    assert "Linked to: Positive spike · TikTok · Gym Flex · broad." in skuj.narrative
    assert "scale carefully" in skuj.narrative
    for a, rc in zip(anomalies, roots):
        if not a.detail["related"]:
            assert "Linked to:" not in rc.narrative


def test_kind_specific_sentences(anomalies, roots):
    assert "Frequency rose from" in by(anomalies, roots, "creative_fatigue", "CMP-01")[1].narrative
    assert "A new creative (CR-10b) launched" in by(anomalies, roots, "positive_spike", "CMP-10")[1].narrative
    cpc = by(anomalies, roots, "cpc_spike", "google")[1].narrative
    assert "more expensive across 4 Google campaigns" in cpc and "Likely cause: Competitor sale" in cpc and "(EV-3)" in cpc
    stock = by(anomalies, roots, "stockout_risk", "SKU-B")[1].narrative
    assert "with no inbound shipment" in stock and "of margin is at risk" in stock
    assert "daily gross margin" in stock  # SKU level wording
    assert "Platform ROAS" in by(anomalies, roots, "attribution_inflation", "meta")[1].narrative


def test_zero_orders_window_no_crash(env):
    base = campaign_frames()
    recent = campaign_frames(("2026-09-30", "2026-10-06"))
    recent["orders"], recent["gross_margin"], recent["profit"] = 0, 0.0, -recent["spend"]
    factors, total, _, p1 = d._decompose_campaign_frame(recent, base, 7, 21)
    assert p1["gm"] == 0.0 and math.isfinite(total)
    assert sum(f.impact for f in factors) == pytest.approx(total, abs=0.01)
    recent["clicks"], recent["impressions"], recent["spend"] = 0, 0, 0.0  # a fully dark window too
    factors, total, _, _ = d._decompose_campaign_frame(recent, base, 7, 21)
    assert math.isfinite(total) and sum(f.impact for f in factors) == pytest.approx(total, abs=0.01)


# ---------------------------------------------------------------- funnel and drill-down
def test_funnel_shapes(anomalies, roots):
    keys = {"stage", "from", "baseline_rate", "recent_rate", "change_pct", "baseline_count_per_day",
            "recent_count_per_day", "is_biggest_drop"}
    for a, rc in zip(anomalies, roots):
        if a.entity_type == "sku":
            assert len(rc.funnel) == 4 and [s["stage"] for s in rc.funnel] == d.FUNNEL_STAGES[1:]
            assert all(set(s) == keys for s in rc.funnel) and sum(s["is_biggest_drop"] for s in rc.funnel) == 1
            drop = next(s for s in rc.funnel if s["is_biggest_drop"])
            assert drop["change_pct"] == min(s["change_pct"] for s in rc.funnel)
        elif a.entity_type == "campaign":
            assert len(rc.funnel) == 4  # the campaign's SKU funnel over the same windows


def test_channel_drilldown_sorted(anomalies, roots):
    _, rc = by(anomalies, roots, "cpc_spike", "google")
    assert len(rc.funnel) == 4 and {r["campaign_id"] for r in rc.funnel} == {"CMP-02", "CMP-04", "CMP-06", "CMP-15"}
    changes = [r["change"] for r in rc.funnel]
    assert changes == sorted(changes) and changes[0] < 0
    assert all(set(r) == {"campaign_id", "campaign_name", "baseline_profit", "recent_profit", "change", "top_factor"}
               for r in rc.funnel)
    assert rc.funnel[0]["campaign_name"] in rc.narrative  # "hardest hit" names the worst campaign


# ---------------------------------------------------------------- M4b causal
def test_causal_controls_exclude_disturbed(env, anomalies, causal):
    c = causal["EV-2"]
    assert set(c["controls"]).isdisjoint({"SKU-D", "SKU-B", "SKU-J"})
    assert c["excluded"] == {"SKU-B": "active stockout_risk",
                             "SKU-J": "campaign CMP-10 has an active positive_spike"}
    # rule-based, not hard-coded: a stockout on another SKU removes that SKU from the controls
    fake = Anomaly("AN-998", "stockout_risk", "sku", "SKU-C", "x", "days_cover", 0, 0, 0, 0, 0, "high",
                   {"direction": "loss", "related": [], "window": {}})
    c2 = cz.event_effect_details("EV-2", anomalies + [fake])
    assert "SKU-C" not in c2["controls"] and "SKU-C" in c2["excluded"]
    assert len(c2["controls"]) == len(c["controls"]) - 1


def test_causal_weights_nonnegative_and_fit_tracks(causal):
    c = causal["EV-2"]
    assert all(w >= 0 for w in c["weights"].values()) and sum(c["weights"].values()) > 0
    assert c["pre_fit_rmse"] / c["mean_cvr_pre"] < 0.15
    pre = [s for s in c["result"].series if not s["is_post"]]
    assert abs(np.mean([s["actual"] for s in pre]) / np.mean([s["counterfactual"] for s in pre]) - 1) < 0.05
    assert len(c["result"].series) == config.CAUSAL_CHART_DAYS and c["n_pre"] >= config.CAUSAL_MIN_PRE_DAYS
    assert sum(1 for s in c["result"].series if s["is_post"]) == c["n_post"] == 14


def test_causal_effect_sign_consistent_with_elasticity(causal):
    c = causal["EV-2"]
    elasticity_units = (2299 / 1999) ** -2.5 - 1  # what the price elasticity alone implies: about −29%
    assert c["units_change_pct"] < 0
    assert abs(c["units_change_pct"] - elasticity_units) < 0.12
    r = c["result"]
    assert r.ci_low < r.total_effect < r.ci_high  # CI brackets the total effect
    assert r.total_effect == pytest.approx(r.effect_per_day * c["n_post"], abs=1.0)
    assert (c["old_price"], c["new_price"]) == (1999.0, 2299.0)
    half = (r.ci_high - r.ci_low) / 2
    assert half > 0 and (r.ci_low + r.ci_high) / 2 == pytest.approx(r.total_effect, abs=0.02)


def test_causal_unknown_event_type_raises(env):
    with pytest.raises(NotImplementedError, match="creative launches"):
        cz.event_effect("EV-4")  # creative_launch
    with pytest.raises(NotImplementedError, match="price_change"):
        cz.event_effect("EV-1")  # sale
    with pytest.raises(KeyError, match="EV-99"):
        cz.event_effect("EV-99")
    assert cz.event_effect("EV-2").event_id == "EV-2"  # the M0 CausalResult shape


def test_causal_linked_into_diagnosis(anomalies, roots, causal, env):
    a, rc = by(anomalies, roots, "conversion_drop", "SKU-D")
    assert "Causal check (synthetic control): units ≈ −22% vs what would have happened anyway" in rc.narrative
    assert "95% CI" in rc.narrative
    from backend.diagnosis.store import diagnoses_frame
    t = diagnoses_frame(anomalies, roots, AS_OF, causal).set_index("anomaly_key")
    assert t.at["conversion_drop:SKU-D", "causal_event_id"] == "EV-2"
    assert t["causal_event_id"].notna().sum() == 1 and pd.isna(t.at["conversion_drop:SKU-J", "causal_event_id"])


# ---------------------------------------------------------------- persistence
def test_tables_written(env):
    run_diagnosis(as_of=AS_OF, emit_brain_events=False, verbose=False)
    t = read_table("diagnoses")
    assert len(t) == 9 and t["anomaly_key"].is_unique
    row = t.set_index("anomaly_key").loc["cpc_spike:google"]
    assert row["top_factor"] == d.AUCTION and 0.5 < row["top_factor_pct"] <= 1
    assert [f["name"] for f in json.loads(row["factors_json"])] == d.FACTOR_ORDER["campaign"]
    attr = t.set_index("anomaly_key").loc["attribution_inflation:meta"]
    assert pd.isna(attr["top_factor"]) and json.loads(attr["factors_json"]) == []  # NULL reads back as NaN
    c = read_table("causal_results")
    assert len(c) == 1 and c.at[0, "method"] == "synthetic_control_nnls" and c.at[0, "treated_sku"] == "SKU-D"
    assert len(json.loads(c.at[0, "series_json"])) == config.CAUSAL_CHART_DAYS
    assert "intercept" in json.loads(c.at[0, "weights_json"])


# ---------------------------------------------------------------- brain events
def test_brain_events_dedupe(fresh_state, anomalies):
    n = len(anomalies)
    first = run_diagnosis(as_of=AS_OF, verbose=False)
    assert first["events_logged"] == n + 1
    events = read_brain_events(limit=500)
    assert all(e["type"] == "diagnosis" and e["region"] == "diagnose" and e["path"] == ["diagnose"] for e in events)
    assert [e["ref_id"] for e in events][:n] == [a.id for a in anomalies] and events[-1]["ref_id"] == "EV-2"
    assert run_diagnosis(as_of=AS_OF, verbose=False)["events_logged"] == 0

    state = load_state()
    state["active_diagnoses"]["cpc_spike:google"] = "Budget change|-100.0"  # its signature "changed"
    save_state(state)
    third = run_diagnosis(as_of=AS_OF, verbose=False)
    assert third["events_logged"] == 1 and third["event_messages"][0].startswith("CPC spike · Google: daily profit fell")

    state = load_state()
    state["active_diagnoses"]["causal:EV-2"] = "0.0|0.0"
    save_state(state)
    fourth = run_diagnosis(as_of=AS_OF, verbose=False)
    assert fourth["events_logged"] == 1 and fourth["event_messages"][0].startswith("Causal proof · Casual X price rise")


def test_event_messages_and_payloads(fresh_state):
    run_diagnosis(as_of=AS_OF, verbose=False)
    evs = {e["payload"].get("anomaly_key") or f"causal:{e['ref_id']}": e for e in read_brain_events(limit=500)}
    cpc = evs["cpc_spike:google"]
    assert cpc["message"].startswith("CPC spike · Google: daily profit fell by ₹25.7k. Largest driver: Auction cost (CPM/CPC) (")
    assert cpc["message"].endswith("/day).") and "Likely cause" not in cpc["message"]
    assert cpc["payload"]["top_factor"] == d.AUCTION and cpc["payload"]["has_waterfall"] is True
    assert [f["name"] for f in cpc["payload"]["factors"]] == d.FACTOR_ORDER["campaign"]
    assert evs["conversion_drop:SKU-J"]["payload"]["related"] == ["positive_spike:CMP-10"]
    assert evs["conversion_drop:SKU-D"]["payload"]["causal_event_id"] == "EV-2"
    meta = evs["attribution_inflation:meta"]
    assert meta["payload"]["has_waterfall"] is False and meta["payload"]["top_factor"] is None
    proof = evs["causal:EV-2"]
    assert proof["entity_id"] == "SKU-D" and proof["severity"] == "medium"
    assert proof["message"].startswith("Causal proof · Casual X price rise: units −22% vs counterfactual, net margin ")
    assert proof["message"].endswith("(95% CI includes zero)")
    assert {"event_id", "effect_per_day", "total_effect", "ci_low", "ci_high", "units_change_pct"} <= set(proof["payload"])


def test_resolved_keys_and_no_state_without_events(fresh_state, monkeypatch):
    res = run_diagnosis(as_of=AS_OF, emit_brain_events=False, verbose=False)
    assert res["events_logged"] == 0 and not fresh_state.exists()
    run_diagnosis(as_of=AS_OF, verbose=False)
    real = detect_all
    monkeypatch.setattr("backend.diagnosis.runner.detect_all", lambda: [a for a in real() if a.kind != "cpc_spike"])
    res = run_diagnosis(as_of=AS_OF, verbose=False)
    assert "cpc_spike:google" in res["resolved"]
    assert "cpc_spike:google" not in load_state()["active_diagnoses"]


# ---------------------------------------------------------------- determinism and the validation script
def test_deterministic(env):
    def sig():
        s = run_diagnosis(as_of=AS_OF, emit_brain_events=False, verbose=False)
        return ([(rc.anomaly_id, rc.total_change, [(f.name, f.impact, f.pct) for f in rc.factors], rc.funnel,
                  rc.narrative) for rc in s["_roots"]], s["causal"])
    assert sig() == sig()


def test_validation_script_passes(env):
    failed = [(n, detail) for n, ok, detail in v.run_checks(v.build_context()) if not ok]
    assert not failed, failed
