"""M1 tests: generator output, planted scenarios, economics and the brain manifest.

Data is generated once into a pytest temp folder (config.RAW_DIR monkeypatched),
so the real data/raw/ is never touched.
"""
import json

import pandas as pd
import pytest

from backend.core import config, db
from backend.generator import generate as gen
from backend.generator import validate as v


@pytest.fixture(scope="module")
def raw(tmp_path_factory):
    out = tmp_path_factory.mktemp("raw")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(config, "RAW_DIR", out)
        gen.main(quiet=True)  # default target is config.RAW_DIR, read at call time
        yield out


def _ok(result):
    ok, detail = result
    assert ok, detail


# ---------------------------------------------------------------- validation checks (1–15)
def test_writes_to_monkeypatched_raw_dir(raw):
    assert sorted(p.name for p in raw.iterdir()) == sorted(db.RAW_FILES)


def test_determinism(raw):
    _ok(v.check_determinism(raw))


def test_row_counts(raw):
    _ok(v.check_row_counts(raw))


def test_columns(raw):
    _ok(v.check_columns(raw))


def test_non_negative(raw):
    _ok(v.check_non_negative(raw))


def test_no_true_orders_in_ads(raw):
    _ok(v.check_no_true_orders_in_ads(raw))


def test_attribution_inflation(raw):
    _ok(v.check_inflation(raw))


def test_s2_stockout(raw):
    _ok(v.check_stockout(raw))


def test_s1_creative_fatigue(raw):
    _ok(v.check_creative_fatigue(raw))


def test_s3_cpc_spike(raw):
    _ok(v.check_cpc_spike(raw))


def test_s6_price_hike(raw):
    _ok(v.check_price_hike(raw))


def test_s7_viral_creative(raw):
    _ok(v.check_viral_creative(raw))


def test_economics(raw):
    _ok(v.check_economics(raw))


def test_brain_manifest(raw):
    _ok(v.check_manifest(raw))


def test_id_patterns(raw):
    _ok(v.check_id_patterns(raw))


def test_dates_in_range(raw):
    _ok(v.check_dates(raw))


def test_display_names(raw):
    _ok(v.check_display_names(raw))


def test_channel_display_covers_every_channel_and_names_tiktok():
    assert set(config.CHANNEL_DISPLAY) == set(config.CHANNELS)
    assert config.CHANNEL_DISPLAY["tiktok"] == "TikTok"


def test_campaign_names_use_display_names(raw):
    camps = v.load(raw, "campaigns.csv").set_index("campaign_id")
    assert camps.at["CMP-10", "campaign_name"] == "TikTok · Gym Flex · broad"
    assert camps.at["CMP-01", "campaign_name"] == "Meta · Summer Sneakers · broad"
    m = pd.read_json(raw / "brain_manifest.json", typ="series")
    assert {s["label"] for s in m["sources"]} >= {"TikTok Ads", "Programmatic"}


# ---------------------------------------------------------------- extra integrity tests
def test_ground_truth_exact(raw):
    assert json.loads((raw / "ground_truth.json").read_text()) == {
        "S1": {"type": "creative_fatigue", "campaign": "CMP-01"},
        "S2": {"type": "stockout_risk", "sku": "SKU-B"},
        "S3": {"type": "cpc_spike", "channel": "google"},
        "S4": {"type": "underfunded", "campaigns": ["CMP-06", "CMP-07"]},
        "S5": {"type": "double_counting", "channels": {"meta": 1.22, "google": 1.15}},
        "S6": {"type": "price_change", "sku": "SKU-D", "event": "EV-2", "elasticity": -2.5},
        "S7": {"type": "positive_spike", "campaign": "CMP-10"},
        "S8": {"type": "opportunity", "note": "unfunded combos scored before any spend"},
    }


def test_referential_integrity(raw):
    ad = v.load(raw, "ad_performance.csv")
    assert set(ad["campaign_id"]) <= set(v.load(raw, "campaigns.csv")["campaign_id"])
    skus = set(v.load(raw, "sku_master.csv")["sku_id"])
    assert set(ad["sku_id"]) <= skus
    assert set(v.load(raw, "campaigns.csv")["sku_id"]) <= skus


def test_utm_orders_sum_to_paid_orders(raw):
    so = v.load(raw, "store_orders_by_utm.csv").merge(v.load(raw, "campaigns.csv")[["campaign_id", "sku_id"]],
                                                       on="campaign_id")
    paid = so.groupby(["date", "sku_id"])["orders"].sum()
    o = v.load(raw, "orders.csv").set_index(["date", "sku_id"])["orders_paid"]
    joined = o.to_frame().join(paid.rename("utm")).fillna(0)
    assert (joined["orders_paid"] == joined["utm"]).all()


def test_units_and_revenue(raw):
    o = v.load(raw, "orders.csv")
    assert (o["units"] == o["orders_paid"] + o["orders_organic"]).all()
    assert ((o["revenue"] - o["units"] * o["unit_price"]).abs() <= 1).all()


def test_ga_funnel_monotonic(raw):
    ga = v.load(raw, "ga_events.csv")
    assert (ga["pdp_views"] >= ga["add_to_cart"]).all()
    assert (ga["add_to_cart"] >= ga["checkout"]).all()
    assert (ga["checkout"] >= ga["purchases"]).all()


def test_margin_pct_is_fraction(raw):
    m = v.load(raw, "sku_master.csv")["margin_pct"]
    assert ((m > 0) & (m < 1)).all()


def test_manifest_neuron_clusters(raw):
    m = json.loads((raw / "brain_manifest.json").read_text())
    clusters = {c["id"] for c in m["clusters"]}
    assert all(n["cluster"] in clusters for n in m["neurons"])


def test_replay_order(raw):
    m = json.loads((raw / "brain_manifest.json").read_text())
    order = m["replay_order"]
    assert sorted(order) == [f"S{i}" for i in range(1, 9)] and len(order) == len(set(order))
    start = {s["scenario"]: s["start_date"] for s in m["scenario_timeline"]}
    assert [start[s] for s in order] == sorted(start[s] for s in order)


def test_manifest_has_no_live_metrics(raw):
    m = json.loads((raw / "brain_manifest.json").read_text())
    live = {"spend_7d", "poas_7d", "profit_7d", "health", "size", "is_alerting"}
    assert all(not (live & set(n)) for n in m["neurons"])


def test_raw_files_contract_includes_manifest():
    assert db.RAW_FILES[-1] == "brain_manifest.json" and len(db.RAW_FILES) == 12
