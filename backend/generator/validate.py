"""M1 validation: checks every generated file in data/raw/ against the spec.

Run from the project root:  python -m backend.generator.validate
Prints a PASS/FAIL table and exits 1 if anything fails. Every check is a function
`check_*(raw_dir) -> (ok, detail)` so tests/test_m1.py can call them individually.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import tempfile
from pathlib import Path
from typing import Callable

import pandas as pd

from backend.core import config, metrics
from backend.core.config import (
    ACTION_TYPES, ANOMALY_KINDS, BRAIN_EVENT_TYPES, BRAIN_REGIONS, CHANNELS, END_DATE, ID_PATTERNS, N_DAYS,
)
from backend.generator import generate as gen

T = N_DAYS
CSV_COLUMNS: dict[str, list[str]] = {  # exact names and order, spec section 8
    "ad_performance.csv": ["date", "channel", "campaign_id", "sku_id", "audience", "creative_id", "spend",
                           "impressions", "clicks", "frequency", "platform_conversions", "platform_revenue"],
    "store_orders_by_utm.csv": ["date", "campaign_id", "orders"],
    "orders.csv": ["date", "sku_id", "orders_paid", "orders_organic", "unit_price", "units", "revenue"],
    "inventory.csv": ["date", "sku_id", "on_hand", "inbound"],
    "pricing.csv": ["date", "sku_id", "price", "list_price", "competitor_price"],
    "ga_events.csv": ["date", "sku_id", "sessions", "pdp_views", "add_to_cart", "checkout", "purchases"],
    "sku_master.csv": ["sku_id", "name", "category", "price", "cogs", "rating", "organic_per_day", "margin_pct"],
    "campaigns.csv": ["campaign_id", "channel", "sku_id", "audience", "daily_budget", "sat_mult", "format",
                      "campaign_name"],
    "creatives.csv": ["creative_id", "campaign_id", "format", "hook", "ugc", "launch_date"],
    "events.csv": ["event_id", "date", "type", "entity", "description"],
}
ROW_COUNTS = {"ad_performance.csv": 1440, "store_orders_by_utm.csv": 1440, "orders.csv": 900, "inventory.csv": 900,
              "pricing.csv": 900, "ga_events.csv": 900, "sku_master.csv": 10, "campaigns.csv": 16,
              "creatives.csv": 17, "events.csv": 4}
NON_NEGATIVE = {"ad_performance.csv": ["spend", "impressions", "clicks"], "store_orders_by_utm.csv": ["orders"],
                "orders.csv": ["orders_paid", "orders_organic", "units"], "inventory.csv": ["on_hand", "inbound"]}

# Economics targets (Part 1). Ratios must be within ±ECON_TOL of target.
ECON_TOL = 0.20
TARGET_SPEND_PER_DAY = 300000
TARGET_TRUE_ROAS = {"amazon": 4.5, "google": 3.1, "meta": 2.1, "tiktok": 1.5, "programmatic": 1.0}
TARGET_PLATFORM_ROAS = {"meta": 2.6, "google": 3.5}
TARGET_BLENDED_POAS = 0.93
BLENDED_POAS_RANGE = (0.88, 0.98)  # tighter band than ±20%, set during calibration
TARGET_CMP02_ROAS = 1.9
PROFITABLE = ["CMP-03", "CMP-04", "CMP-05", "CMP-06", "CMP-07", "CMP-13", "CMP-14"]
EXPECTED_INFLATION = {"meta": 0.22, "google": 0.15, "amazon": 0.0, "tiktok": 0.0, "programmatic": 0.0}
INFLATION_TOL = 0.03


def load(raw_dir: Path, name: str) -> pd.DataFrame:
    return pd.read_csv(Path(raw_dir) / name)


def load_json(raw_dir: Path, name: str) -> dict:
    return json.loads((Path(raw_dir) / name).read_text(encoding="utf-8"))


def _dates() -> list[str]:
    return [d.strftime("%Y-%m-%d") for d in gen.build_dates()]


def _within(value: float, target: float, tol: float = ECON_TOL) -> bool:
    return value is not None and abs(value - target) <= abs(target) * tol


def campaign_frame(raw_dir: Path) -> pd.DataFrame:
    """ad_performance joined with true store orders, price and cogs, with M0 revenue/margin metrics."""
    ad = load(raw_dir, "ad_performance.csv")
    df = (ad.merge(load(raw_dir, "store_orders_by_utm.csv"), on=["date", "campaign_id"])
            .merge(load(raw_dir, "pricing.csv")[["date", "sku_id", "price"]], on=["date", "sku_id"])
            .merge(load(raw_dir, "sku_master.csv")[["sku_id", "cogs"]], on="sku_id"))
    df["store_revenue"] = metrics.true_revenue(df["orders"], df["price"])
    df["gross_margin"] = metrics.gross_margin(df["orders"], df["price"], df["cogs"])
    return df


def economics(raw_dir: Path) -> dict:
    """Headline economics computed with M0 metric functions."""
    df = campaign_frame(raw_dir)
    ch = df.groupby("channel")[["spend", "store_revenue", "platform_revenue", "gross_margin"]].sum()
    cp = df.groupby("campaign_id")[["spend", "store_revenue", "gross_margin"]].sum()
    return {
        "spend_per_day": df["spend"].sum() / N_DAYS,
        "true_roas": {c: metrics.roas_true(ch.at[c, "store_revenue"], ch.at[c, "spend"]) for c in ch.index},
        "platform_roas": {c: metrics.roas_platform(ch.at[c, "platform_revenue"], ch.at[c, "spend"]) for c in ch.index},
        "blended_poas": metrics.poas(df["gross_margin"].sum(), df["spend"].sum()),
        "campaign_poas": {c: metrics.poas(cp.at[c, "gross_margin"], cp.at[c, "spend"]) for c in cp.index},
        "campaign_roas": {c: metrics.roas_true(cp.at[c, "store_revenue"], cp.at[c, "spend"]) for c in cp.index},
    }


def _window(df: pd.DataFrame, start: int, end: int) -> pd.DataFrame:
    """Rows whose date falls in day indices [start, end)."""
    dates = _dates()
    return df[df["date"].isin(dates[start:end])]


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------
def _hash_dir(folder: Path) -> dict[str, str]:
    return {p.name: hashlib.md5(p.read_bytes()).hexdigest() for p in sorted(Path(folder).iterdir()) if p.is_file()}


def check_determinism(raw_dir: Path):
    """Re-run the generator into a temp folder; every file hash must match raw_dir."""
    with tempfile.TemporaryDirectory() as tmp:
        gen.main(raw_dir=Path(tmp), quiet=True)
        fresh = _hash_dir(Path(tmp))
    current = {k: v for k, v in _hash_dir(raw_dir).items() if k in fresh}
    diff = sorted(k for k in fresh if current.get(k) != fresh[k])
    return not diff, f"{len(fresh)} files identical" if not diff else f"differs: {diff}"


def check_row_counts(raw_dir: Path):
    """Row counts match spec section 8, ground truth has 8 keys."""
    bad = {f: len(load(raw_dir, f)) for f, n in ROW_COUNTS.items() if len(load(raw_dir, f)) != n}
    gt = load_json(raw_dir, "ground_truth.json")
    if len(gt) != 8:
        bad["ground_truth.json"] = len(gt)
    return not bad, "all match" if not bad else f"mismatch: {bad}"


def check_columns(raw_dir: Path):
    """Exact column names and order for every CSV."""
    bad = {f: list(load(raw_dir, f).columns) for f, cols in CSV_COLUMNS.items() if list(load(raw_dir, f).columns) != cols}
    return not bad, f"{len(CSV_COLUMNS)} CSVs exact" if not bad else f"wrong: {list(bad)}"


def check_non_negative(raw_dir: Path):
    """No negative spend, impressions, clicks, orders, units, on_hand, inbound."""
    bad = [f"{f}:{c}" for f, cols in NON_NEGATIVE.items() for c in cols if (load(raw_dir, f)[c] < 0).any()]
    return not bad, "none negative" if not bad else f"negative: {bad}"


def check_no_true_orders_in_ads(raw_dir: Path):
    """ad_performance.csv must not expose true store orders."""
    cols = set(load(raw_dir, "ad_performance.csv").columns)
    leaked = cols & {"orders", "store_orders", "true_orders"}
    return not leaked, "no orders column" if not leaked else f"leaked: {sorted(leaked)}"


def inflation_by_channel(raw_dir: Path) -> dict[str, float]:
    df = load(raw_dir, "ad_performance.csv").merge(load(raw_dir, "store_orders_by_utm.csv"), on=["date", "campaign_id"])
    g = df.groupby("channel")[["platform_conversions", "orders"]].sum()
    return {c: metrics.inflation_pct(g.at[c, "platform_conversions"], g.at[c, "orders"]) for c in g.index}


def check_inflation(raw_dir: Path):
    """Platform conversions vs store orders: Meta ≈ +22%, Google ≈ +15% (±3 pts), others ≈ 0%."""
    infl = inflation_by_channel(raw_dir)
    bad = {c: round(v, 3) for c, v in infl.items() if abs(v - EXPECTED_INFLATION[c]) > INFLATION_TOL}
    shown = ", ".join(f"{c} {v:+.1%}" for c, v in infl.items())
    return not bad, shown


def sku_days_cover(raw_dir: Path, sku_id: str) -> pd.Series:
    o = load(raw_dir, "orders.csv")
    inv = load(raw_dir, "inventory.csv")
    units = o[o["sku_id"] == sku_id].sort_values("date")["units"].reset_index(drop=True)
    on_hand = inv[inv["sku_id"] == sku_id].sort_values("date")["on_hand"].reset_index(drop=True)
    return metrics.days_cover(on_hand, units.rolling(7, min_periods=1).mean())


def check_stockout(raw_dir: Path):
    """SKU-B days of cover on the last day between 4 and 7 (≈ 5)."""
    last = float(sku_days_cover(raw_dir, "SKU-B").iloc[-1])
    return 4 <= last <= 7, f"SKU-B last-day cover {last:.1f} days"


def check_creative_fatigue(raw_dir: Path):
    """CMP-01: frequency rises toward 4.2 over the last 14 days; last-7-day CTR ≥ 30% below the prior 21 days."""
    ad = load(raw_dir, "ad_performance.csv")
    c = ad[ad["campaign_id"] == "CMP-01"].sort_values("date")
    win = _window(c, T - 14, T)
    freq_rising = win["frequency"].tail(3).mean() > win["frequency"].head(3).mean() and win["frequency"].iloc[-1] >= 3.8
    base, recent = _window(c, T - 35, T - 14), _window(c, T - 7, T)
    drop = metrics.change_pct(metrics.ctr(recent["clicks"].sum(), recent["impressions"].sum()),
                              metrics.ctr(base["clicks"].sum(), base["impressions"].sum()))
    ok = freq_rising and drop <= -0.30
    return ok, f"freq {win['frequency'].iloc[0]:.2f}→{win['frequency'].iloc[-1]:.2f}, CTR {drop:+.0%}"


def check_cpc_spike(raw_dir: Path):
    """Google CPC (spend ÷ clicks) last 7 days is +45%..+75% vs the prior 21 days."""
    ad = load(raw_dir, "ad_performance.csv")
    g = ad[ad["channel"] == "google"]
    base, recent = _window(g, T - 28, T - 7), _window(g, T - 7, T)
    change = metrics.change_pct(metrics.cpc(recent["spend"].sum(), recent["clicks"].sum()),
                                metrics.cpc(base["spend"].sum(), base["clicks"].sum()))
    return 0.45 <= change <= 0.75, f"Google CPC {change:+.0%}"


def check_price_hike(raw_dir: Path):
    """SKU-D site CVR (purchases ÷ sessions) after EV-2 drops 15–35% vs the 14 days before."""
    ga = load(raw_dir, "ga_events.csv")
    d = ga[ga["sku_id"] == "SKU-D"]
    before, after = _window(d, T - 28, T - 14), _window(d, T - 14, T)
    change = metrics.change_pct(metrics.site_cvr(after["purchases"].sum(), after["sessions"].sum()),
                                metrics.site_cvr(before["purchases"].sum(), before["sessions"].sum()))
    return -0.35 <= change <= -0.15, f"SKU-D site CVR {change:+.0%}"


def check_viral_creative(raw_dir: Path):
    """CMP-10 last-7-day CTR ≥ 1.8× the prior 21 days; CR-10b appears only in that window."""
    ad = load(raw_dir, "ad_performance.csv")
    c = ad[ad["campaign_id"] == "CMP-10"]
    base, recent = _window(c, T - 28, T - 7), _window(c, T - 7, T)
    ratio = metrics.safe_div(metrics.ctr(recent["clicks"].sum(), recent["impressions"].sum()),
                             metrics.ctr(base["clicks"].sum(), base["impressions"].sum()))
    window_dates = set(_dates()[T - 7:])
    b_dates = set(ad.loc[ad["creative_id"] == "CR-10b", "date"])
    only_window = b_dates == window_dates and set(c.loc[c["creative_id"] == "CR-10b", "date"]) == window_dates
    return ratio >= 1.8 and only_window, f"CTR ×{ratio:.2f}, CR-10b on {len(b_dates)} days"


def check_economics(raw_dir: Path):
    """Spend, true/platform ROAS within ±20%; blended POAS in 0.88–0.98; profitable set exact; CMP-02 ROAS ≈ 1.9 with POAS < 1."""
    e = economics(raw_dir)
    fails = []
    if not _within(e["spend_per_day"], TARGET_SPEND_PER_DAY):
        fails.append("spend")
    fails += [f"true_roas:{c}" for c, t in TARGET_TRUE_ROAS.items() if not _within(e["true_roas"][c], t)]
    fails += [f"platform_roas:{c}" for c, t in TARGET_PLATFORM_ROAS.items() if not _within(e["platform_roas"][c], t)]
    if not (BLENDED_POAS_RANGE[0] <= e["blended_poas"] <= BLENDED_POAS_RANGE[1]):
        fails.append("blended_poas")
    profitable = sorted(c for c, p in e["campaign_poas"].items() if p > 1)
    if profitable != PROFITABLE:
        fails.append(f"profitable={profitable}")
    if not (_within(e["campaign_roas"]["CMP-02"], TARGET_CMP02_ROAS) and e["campaign_poas"]["CMP-02"] < 1):
        fails.append("CMP-02")
    detail = (f"₹{e['spend_per_day']:,.0f}/day, POAS {e['blended_poas']:.2f}, "
              f"CMP-02 ROAS {e['campaign_roas']['CMP-02']:.2f}/POAS {e['campaign_poas']['CMP-02']:.2f}")
    return not fails, detail if not fails else f"{detail} · off: {fails}"


def check_manifest(raw_dir: Path):
    """Brain manifest: 26 neurons, synapse counts, endpoints exist, M0 enums valid, 8 scenarios, dates in range."""
    m = load_json(raw_dir, "brain_manifest.json")
    dates = _dates()
    errors = []
    neurons, synapses = m["neurons"], m["synapses"]
    if len(neurons) != 26 or sum(n["entity_type"] == "campaign" for n in neurons) != 16:
        errors.append("neurons")
    counts = {
        "promotes": sum(s["kind"] == "promotes" for s in synapses),
        "feeds_campaign": sum(s["kind"] == "feeds" and s["target"].startswith("CMP-") for s in synapses),
        "feeds_sku": sum(s["kind"] == "feeds" and s["target"].startswith("SKU-") for s in synapses),
    }
    if counts != {"promotes": 16, "feeds_campaign": 16, "feeds_sku": 40}:
        errors.append(f"synapses {counts}")
    ids = {n["entity_id"] for n in neurons} | {s["id"] for s in m["sources"]}
    if any(s["source"] not in ids or s["target"] not in ids for s in synapses):
        errors.append("synapse endpoint")
    cluster_ids = {c["id"] for c in m["clusters"]}
    if any(n["cluster"] not in cluster_ids for n in neurons) or not set(CHANNELS) <= cluster_ids:
        errors.append("clusters")
    if any(s["channel"] is not None and s["channel"] not in CHANNELS for s in m["sources"]):
        errors.append("source channel")
    tl = m["scenario_timeline"]
    if sorted(s["scenario"] for s in tl) != [f"S{i}" for i in range(1, 9)]:
        errors.append("scenarios")
    for s in tl:
        if s["expected_event_type"] not in BRAIN_EVENT_TYPES or s["expected_region"] not in BRAIN_REGIONS:
            errors.append(f"{s['scenario']} enum")
        if "expected_kind" in s and s["expected_kind"] not in ANOMALY_KINDS:
            errors.append(f"{s['scenario']} kind")
        if "expected_action" in s and s["expected_action"] not in ACTION_TYPES:
            errors.append(f"{s['scenario']} action")
        if not (dates[0] <= s["start_date"] <= s["end_date"] <= END_DATE):
            errors.append(f"{s['scenario']} dates")
        if s["scenario"] in ("S1", "S3", "S6", "S7") and s["start_date"] < dates[T - 14]:
            errors.append(f"{s['scenario']} outside last 14 days")
        if any(e not in ids for e in s["entities"]):
            errors.append(f"{s['scenario']} entity")
    if sorted(m["replay_order"]) != sorted(s["scenario"] for s in tl):
        errors.append("replay_order")
    if m["date_range"] != {"start": dates[0], "end": END_DATE, "n_days": N_DAYS}:
        errors.append("date_range")
    detail = f"{len(neurons)} neurons, synapses {counts['feeds_campaign']}+{counts['promotes']}+{counts['feeds_sku']}"
    return not errors, detail if not errors else f"{detail} · {errors}"


def check_id_patterns(raw_dir: Path):
    """Campaign, SKU, creative and event IDs match M0 ID_PATTERNS everywhere they appear."""
    checks = {
        "campaign": list(load(raw_dir, "campaigns.csv")["campaign_id"]) + list(load(raw_dir, "ad_performance.csv")["campaign_id"]),
        "sku": list(load(raw_dir, "sku_master.csv")["sku_id"]) + list(load(raw_dir, "orders.csv")["sku_id"]),
        "creative": list(load(raw_dir, "creatives.csv")["creative_id"]) + list(load(raw_dir, "ad_performance.csv")["creative_id"]),
        "event": list(load(raw_dir, "events.csv")["event_id"]),
    }
    bad = {k: sorted({v for v in vals if not re.match(ID_PATTERNS[k], str(v))}) for k, vals in checks.items()}
    bad = {k: v for k, v in bad.items() if v}
    return not bad, "all IDs valid" if not bad else f"invalid: {bad}"


def check_dates(raw_dir: Path):
    """Every date column lies within [start, END_DATE]."""
    dates = _dates()
    lo, hi = dates[0], END_DATE
    cols = {f: ["date"] for f in CSV_COLUMNS if "date" in CSV_COLUMNS[f]}
    cols["creatives.csv"] = ["launch_date"]
    bad = [f for f, cs in cols.items() for c in cs
           if not load(raw_dir, f)[c].astype(str).between(lo, hi).all()]
    m = load_json(raw_dir, "brain_manifest.json")
    if any(not (lo <= s["date"] <= hi) for s in m["stimuli"]):
        bad.append("brain_manifest.json:stimuli")
    return not bad, f"{lo} → {hi}" if not bad else f"out of range: {bad}"


CHECKS: list[tuple[str, Callable[[Path], tuple[bool, str]]]] = [
    ("1  determinism", check_determinism),
    ("2  row counts", check_row_counts),
    ("3  columns", check_columns),
    ("4  non-negative", check_non_negative),
    ("5  no true orders in ads", check_no_true_orders_in_ads),
    ("6  attribution inflation", check_inflation),
    ("7  S2 stockout cover", check_stockout),
    ("8  S1 creative fatigue", check_creative_fatigue),
    ("9  S3 Google CPC spike", check_cpc_spike),
    ("10 S6 price hike CVR", check_price_hike),
    ("11 S7 viral creative", check_viral_creative),
    ("12 economics", check_economics),
    ("13 brain manifest", check_manifest),
    ("14 ID patterns", check_id_patterns),
    ("15 date range", check_dates),
]


def run_checks(raw_dir: Path) -> list[tuple[str, bool, str]]:
    results = []
    for name, fn in CHECKS:
        try:
            ok, detail = fn(raw_dir)
        except Exception as exc:  # a crashing check is a failing check
            ok, detail = False, f"error: {exc!r}"
        results.append((name, bool(ok), detail))
    return results


def main(raw_dir: Path | None = None) -> int:
    raw = Path(raw_dir if raw_dir is not None else config.RAW_DIR)
    results = run_checks(raw)
    width = max(len(n) for n, _, _ in results)
    print(f"{'check'.ljust(width)}  result  detail")
    print("-" * (width + 60))
    for name, ok, detail in results:
        print(f"{name.ljust(width)}  {'PASS' if ok else 'FAIL'}    {detail}")
    failed = sum(not ok for _, ok, _ in results)
    print("-" * (width + 60))
    print(f"M1 validation: {len(results) - failed}/{len(results)} PASS" + (f", {failed} FAIL" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
