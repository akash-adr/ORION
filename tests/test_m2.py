"""M2 tests: pipeline, reconciliation, data quality and Neural Brain integration.

M1 data is generated into a pytest temp folder; RAW_DIR, DB_PATH, STATE_PATH (and DATA_DIR) are
monkeypatched on backend.core.config, which every M0/M2 module reads at call time, so tests never
touch the real data/ folder or state.json.
"""
import pandas as pd
import pytest

from backend.core import config, metrics as m
from backend.core.db import read_brain_events, read_table
from backend.generator import generate as gen
from backend.ingest import connectors as c
from backend.ingest import pipeline, quality as q
from backend.ingest import validate as v


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    root = tmp_path_factory.mktemp("m2")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(config, "DATA_DIR", root)
        mp.setattr(config, "RAW_DIR", root / "raw")
        mp.setattr(config, "DB_PATH", root / "engine.db")
        mp.setattr(config, "STATE_PATH", root / "state.json")
        gen.main(quiet=True)
        yield root


@pytest.fixture(scope="module")
def ctx(env):
    return v.build_context()


def _ok(result):
    ok, detail = result
    assert ok, detail


# ---------------------------------------------------------------- validation checks 1–16
def test_row_counts(ctx):
    _ok(v.check_row_counts(ctx))


def test_table_contracts(ctx):
    _ok(v.check_table_contracts(ctx))


def test_orders_consistency(ctx):
    _ok(v.check_orders_consistency(ctx))


def test_inflation(ctx):
    _ok(v.check_inflation(ctx))


def test_trust(ctx):
    _ok(v.check_trust(ctx))


def test_data_trust(ctx):
    _ok(v.check_data_trust(ctx))


def test_7d_economics(ctx):
    _ok(v.check_7d_economics(ctx))


def test_stockout(ctx):
    _ok(v.check_stockout(ctx))


def test_nan_inf(ctx):
    _ok(v.check_nan_inf(ctx))


def test_idempotent(ctx):
    _ok(v.check_idempotent(ctx))


def test_store_truth(ctx):
    _ok(v.check_store_truth(ctx))


def test_roas_lies(ctx):
    _ok(v.check_roas_lies(ctx))


def test_neuron_metrics(ctx):
    _ok(v.check_neuron_metrics(ctx))


def test_source_status(ctx):
    _ok(v.check_source_status(ctx))


def test_data_quality(ctx):
    _ok(v.check_data_quality(ctx))


def test_brain_events(ctx):
    _ok(v.check_brain_events(ctx))


# ---------------------------------------------------------------- connectors
def test_missing_file_error_names_file(env):
    with pytest.raises(FileNotFoundError, match=r"nope\.csv.*backend\.generator\.generate"):
        c.CsvConnector("x", "nope.csv").fetch()


def test_ad_connectors_return_own_channel(env):
    for conn in c.AD_CONNECTORS:
        df = conn.fetch()
        assert len(df) > 0 and set(df["channel"]) == {conn.channel}


# ---------------------------------------------------------------- joins and ratios
def test_left_join_keeps_zero_order_days(env):
    frames = pipeline.fetch_all()
    utm = frames["shopify_utm"]
    dropped = utm.iloc[0]
    frames["shopify_utm"] = utm.iloc[1:].reset_index(drop=True)
    fact = pipeline.build_fact_daily(frames)
    assert len(fact) == 1440
    row = fact[(fact["date"] == dropped["date"]) & (fact["campaign_id"] == dropped["campaign_id"])]
    assert len(row) == 1 and row["orders"].iloc[0] == 0


def test_feature_store_ratios_are_sum_over_sum(ctx):
    fact, fs = ctx["tables"]["fact_daily"], ctx["tables"]["feature_store"]
    last7 = sorted(fact["date"].unique())[-config.RECENT_DAYS:]
    w = fact[(fact["campaign_id"] == "CMP-01") & fact["date"].isin(last7)]
    expected = w["gross_margin"].sum() / w["spend"].sum()
    got = fs.set_index("campaign_id").at["CMP-01", "poas_7d"]
    assert got == pytest.approx(expected)
    assert got != pytest.approx(w["poas"].mean())  # not an average of daily ratios


def test_sku_d_price_changes_on_ev2(ctx):
    fact, events = ctx["tables"]["fact_daily"], ctx["tables"]["events"]
    ev2 = events.set_index("event_id").at["EV-2", "date"]
    d = fact[fact["sku_id"] == "SKU-D"]
    assert set(d[d["date"] < ev2]["price"]) == {1999.0}
    assert set(d[d["date"] >= ev2]["price"]) == {2299.0}


# ---------------------------------------------------------------- data quality on broken inputs
def test_completeness_fills_missing_row(env):
    frames = pipeline.fetch_all()
    ads = pipeline.concat_ads(frames)
    removed = ads.iloc[10]
    out, row = q.check_completeness(ads.drop(index=10), frames["campaigns"])
    assert row["status"] == "warn" and row["affected_rows"] == 1 and len(out) == len(ads)
    filled = out[(out["date"] == removed["date"]) & (out["campaign_id"] == removed["campaign_id"])]
    assert filled["spend"].iloc[0] == 0.0 and filled["clicks"].iloc[0] == 0


def test_duplicates_keep_last(env):
    frames = pipeline.fetch_all()
    ads = pipeline.concat_ads(frames)
    dup = ads.iloc[[5]].copy()
    dup["spend"] = 12345.0
    _, out, row = q.check_duplicates(frames, pd.concat([ads, dup], ignore_index=True))
    assert row["status"] == "warn" and row["affected_rows"] == 1 and len(out) == len(ads)
    kept = out[(out["date"] == dup["date"].iloc[0]) & (out["campaign_id"] == dup["campaign_id"].iloc[0])]
    assert kept["spend"].iloc[0] == 12345.0


def test_negatives_dropped(env):
    frames = pipeline.fetch_all()
    ads = pipeline.concat_ads(frames)
    ads.loc[3, "spend"] = -5.0
    _, out, row = q.check_negatives(frames, ads)
    assert row["status"] == "warn" and row["affected_rows"] == 1 and len(out) == len(ads) - 1
    assert (out["spend"] >= 0).all()


def test_reconciliation_gap_flags_meta_and_google(ctx):
    dq = ctx["tables"]["data_quality"].set_index("check")
    assert dq.at["reconciliation_gap", "status"] == "warn"
    assert "meta" in dq.at["reconciliation_gap", "detail"] and "google" in dq.at["reconciliation_gap", "detail"]


# ---------------------------------------------------------------- brain events
def test_no_brain_events_when_disabled(env, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "STATE_PATH", tmp_path / "state.json")
    summary = pipeline.run_pipeline(as_of=v.FIXED_AS_OF, verbose=False, emit_brain_events=False)
    assert summary["brain_events_logged"] == 0
    assert read_brain_events() == []
    assert not (tmp_path / "state.json").exists()


def test_neuron_health_matches_m0(ctx):
    nm = ctx["tables"]["neuron_metrics"]
    spent = nm[nm["spend_7d"] > 0]
    assert list(spent["health"]) == list(m.neuron_health(spent["poas_7d"]))


def test_tests_never_touch_real_data(env):
    assert config.DB_PATH.parent == env and read_table("fact_daily").shape[0] == 1440
