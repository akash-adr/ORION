"""M2 ingestion & reconciliation pipeline: the Neural Brain's "Ingest" lobe.

Run from the project root:  python -m backend.ingest.pipeline

Pulls every source through the connector layer, builds one trusted SQLite database and
reconciles what ad platforms claim against what the store actually sold. Every later module
reads ONLY these tables (never raw files).

Rules: period ratios are Σnumerator ÷ Σdenominator; division by zero → NaN; revenue is store
revenue; windows are anchored on the last date in the data, never the wall clock.
"""
from __future__ import annotations

import argparse
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from backend.core import metrics as m
from backend.core.config import CHANNELS, RECENT_DAYS
from backend.core.db import TABLE_COLUMNS, validate_table, write_table
from backend.ingest import brain
from backend.ingest import connectors as c
from backend.ingest import quality as q

LONG_WINDOW_DAYS = 28  # "28d" feature window
TABLES = ("fact_daily", "sku_daily", "reconciliation", "feature_store", "dim_sku", "dim_campaign",
          "dim_creative", "events")  # the 8 core tables
BRAIN_TABLES = ("neuron_metrics", "source_status", "data_quality")  # added with the brain integration


# ---------------------------------------------------------------------------
# Step 1: fetch + normalise
# ---------------------------------------------------------------------------
def fetch_all() -> dict[str, pd.DataFrame]:
    """Fetch every connector (each applies normalisation). Keys are connector source names."""
    frames = {conn.source: conn.fetch() for conn in c.AD_CONNECTORS}
    for conn in (c.STORE, c.UTM, c.ERP, c.PRICING, c.GA4, c.DIM_SKU, c.DIM_CAMPAIGN, c.DIM_CREATIVE, c.EVENTS):
        frames[conn.source] = conn.fetch()
    return frames


# ---------------------------------------------------------------------------
# Step 2–3: fact_daily
# ---------------------------------------------------------------------------
def concat_ads(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """All 5 ad connectors stacked into one frame."""
    return pd.concat([frames[conn.source] for conn in c.AD_CONNECTORS], ignore_index=True)


def build_fact_daily(frames: dict[str, pd.DataFrame], ads: pd.DataFrame | None = None) -> pd.DataFrame:
    """Campaign × day fact table with true store orders, daily price and every derived metric.

    `ads` is the cleaned ad frame from the quality checks; defaults to the raw concatenation.
    """
    ads = concat_ads(frames) if ads is None else ads
    utm = frames["shopify_utm"][["date", "campaign_id", "orders"]]
    # LEFT join: an inner join would drop zero-order days and bias CVR upward.
    f = ads.merge(utm, on=["date", "campaign_id"], how="left")
    f["orders"] = f["orders"].fillna(0).astype("int64")
    # Daily price, so SKU-D's price change is visible.
    f = f.merge(frames["pricing"][["date", "sku_id", "price"]], on=["date", "sku_id"], how="left")
    f = f.merge(frames["sku_master"][["sku_id", "cogs"]], on="sku_id", how="left")
    f = f.merge(frames["campaigns"][["campaign_id", "campaign_name", "format"]], on="campaign_id", how="left")

    f["revenue"] = m.true_revenue(f["orders"], f["price"])
    f["gross_margin"] = m.gross_margin(f["orders"], f["price"], f["cogs"])
    f["profit"] = m.contribution_profit(f["gross_margin"], f["spend"])
    f["ctr"] = m.ctr(f["clicks"], f["impressions"])
    f["cpc"] = m.cpc(f["spend"], f["clicks"])
    f["cpm"] = m.cpm(f["spend"], f["impressions"])
    f["cvr"] = m.cvr(f["orders"], f["clicks"])
    f["roas_platform"] = m.roas_platform(f["platform_revenue"], f["spend"])
    f["roas_true"] = m.roas_true(f["revenue"], f["spend"])
    f["poas"] = m.poas(f["gross_margin"], f["spend"])
    f = f.sort_values(["date", "campaign_id"], kind="stable").reset_index(drop=True)
    return f[TABLE_COLUMNS["fact_daily"]]


# ---------------------------------------------------------------------------
# Step 4: reconciliation
# ---------------------------------------------------------------------------
def build_reconciliation(fact: pd.DataFrame, as_of: str) -> pd.DataFrame:
    """One row per channel (CHANNELS order): platform claims vs store truth over the full period."""
    g = fact.groupby("channel")[["platform_conversions", "orders", "platform_revenue", "revenue", "spend"]].sum()
    g = g.reindex(list(CHANNELS)).fillna(0.0)
    r = pd.DataFrame({
        "channel": list(CHANNELS),
        "platform_conversions": g["platform_conversions"].to_numpy(),
        "store_orders": g["orders"].astype("int64").to_numpy(),
        "platform_revenue": g["platform_revenue"].to_numpy(),
        "true_revenue": g["revenue"].to_numpy(),
        "spend": g["spend"].to_numpy(),
    })
    r["inflation_pct"] = m.inflation_pct(r["platform_conversions"], r["store_orders"])
    r["roas_platform"] = m.roas_platform(r["platform_revenue"], r["spend"])
    r["roas_true"] = m.roas_true(r["true_revenue"], r["spend"])
    r["trust_score"] = m.trust_score(r["inflation_pct"])
    r["last_synced"] = as_of
    return r[TABLE_COLUMNS["reconciliation"]]


# ---------------------------------------------------------------------------
# Step 5: sku_daily
# ---------------------------------------------------------------------------
def build_sku_daily(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """SKU × day: store orders + ERP inventory + GA4 funnel + catalogue, with units_7d and days_cover."""
    s = frames["shopify_orders"]
    s = s.merge(frames["erp_inventory"][["date", "sku_id", "on_hand", "inbound"]], on=["date", "sku_id"], how="left")
    s = s.merge(frames["ga4"][["date", "sku_id", "sessions", "pdp_views", "add_to_cart", "checkout", "purchases"]],
                on=["date", "sku_id"], how="left")
    s = s.merge(frames["sku_master"][["sku_id", "name", "cogs", "margin_pct"]], on="sku_id", how="left")
    s = s.sort_values(["sku_id", "date"], kind="stable").reset_index(drop=True)
    s["units_7d"] = s.groupby("sku_id")["units"].transform(lambda u: u.rolling(7, min_periods=1).mean())
    s["days_cover"] = m.days_cover(s["on_hand"], s["units_7d"])
    s = s.sort_values(["date", "sku_id"], kind="stable").reset_index(drop=True)
    return s[TABLE_COLUMNS["sku_daily"]]


# ---------------------------------------------------------------------------
# Step 6: feature store
# ---------------------------------------------------------------------------
def window_dates(fact: pd.DataFrame, days: int) -> list[str]:
    """The last `days` calendar dates ending on the last date in the data."""
    last = pd.Timestamp(fact["date"].max())
    return [d.strftime("%Y-%m-%d") for d in pd.date_range(end=last, periods=days)]


def build_feature_store(fact: pd.DataFrame, campaigns: pd.DataFrame) -> pd.DataFrame:
    """One unified-schema vector per campaign over the last RECENT_DAYS and LONG_WINDOW_DAYS days."""
    d7, d28 = window_dates(fact, RECENT_DAYS), window_dates(fact, LONG_WINDOW_DAYS)
    sums = ["spend", "gross_margin", "clicks", "impressions", "orders", "profit"]
    w7 = fact[fact["date"].isin(d7)].groupby("campaign_id")[sums].sum()
    w28 = fact[fact["date"].isin(d28)].groupby("campaign_id")[["spend", "gross_margin"]].sum()
    freq = fact[fact["date"].isin(d7)].groupby("campaign_id")["frequency"].mean()

    fs = campaigns[["campaign_id", "channel", "sku_id", "audience"]].sort_values("campaign_id").reset_index(drop=True)
    w7, w28, freq = (x.reindex(fs["campaign_id"]).reset_index(drop=True) for x in (w7, w28, freq))
    fs["spend_7d"] = w7["spend"] / len(d7)  # average daily spend
    fs["spend_28d"] = w28["spend"] / len(d28)
    fs["poas_7d"] = m.poas(w7["gross_margin"], w7["spend"])
    fs["poas_28d"] = m.poas(w28["gross_margin"], w28["spend"])
    fs["ctr_7d"] = m.ctr(w7["clicks"], w7["impressions"])
    fs["cvr_7d"] = m.cvr(w7["orders"], w7["clicks"])
    fs["cpm_7d"] = m.cpm(w7["spend"], w7["impressions"])
    fs["freq_7d"] = freq
    fs["profit_7d"] = w7["profit"] / len(d7)  # average daily contribution profit
    return fs[TABLE_COLUMNS["feature_store"]]


# ---------------------------------------------------------------------------
# Step 7: dimensions and events
# ---------------------------------------------------------------------------
def build_dims(frames: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Dimension tables and the events log, copied with the exact M0 columns."""
    return {
        "dim_sku": frames["sku_master"][TABLE_COLUMNS["dim_sku"]],
        "dim_campaign": frames["campaigns"][TABLE_COLUMNS["dim_campaign"]],
        "dim_creative": frames["creatives"][TABLE_COLUMNS["dim_creative"]],
        "events": frames["events"][TABLE_COLUMNS["events"]],
    }


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
def summarise(tables: dict[str, pd.DataFrame], frames: dict[str, pd.DataFrame], as_of: str, duration_ms: float) -> dict:
    """Run summary: row counts, reconciliation, spend-weighted data trust and last-7-day headline ratios."""
    fact, rec = tables["fact_daily"], tables["reconciliation"]
    w7 = fact[fact["date"].isin(window_dates(fact, RECENT_DAYS))]
    spend7 = w7["spend"].sum()
    data_trust = m.safe_div((rec["spend"] * rec["trust_score"]).sum(), rec["spend"].sum())
    return {
        "as_of": as_of,
        "rows": {name: int(len(df)) for name, df in tables.items()},
        "connector_rows": {name: int(len(df)) for name, df in frames.items()},
        "reconciliation": rec.to_dict(orient="records"),
        "data_trust": data_trust,
        "blended_poas_7d": m.poas(w7["gross_margin"].sum(), spend7),
        "roas_true_7d": m.roas_true(w7["revenue"].sum(), spend7),
        "roas_platform_7d": m.roas_platform(w7["platform_revenue"].sum(), spend7),
        "duration_ms": duration_ms,
    }


def now_ist() -> str:
    """Current IST time as "YYYY-MM-DDTHH:MM:SS" (only used to stamp last_synced)."""
    return datetime.now(ZoneInfo(c.TIMEZONE)).strftime("%Y-%m-%dT%H:%M:%S")


def run_pipeline(as_of: str | None = None, verbose: bool = True, emit_brain_events: bool = True) -> dict:
    """Run the full M2 pipeline and return a summary.

    1. fetch + normalise every source        4. reconcile, SKU/funnel, feature vectors, dims
    2. quality checks 1–4 clean the inputs   5. neuron_metrics + source_status for the Neural Brain
    3. build fact_daily                      6. quality checks 5–9, validate + write all 11 tables
    7. (emit_brain_events) log 10 "ingest" brain events: 9 data streams + 1 settle pulse
    Re-runs replace every table (idempotent).
    """
    start = time.perf_counter()
    as_of = as_of or now_ist()
    frames = fetch_all()
    manifest = brain.load_manifest()

    # Checks 1–4: clean inputs before building facts.
    ads, q_complete = q.check_completeness(concat_ads(frames), frames["campaigns"])
    clean, ads, q_dupes = q.check_duplicates(frames, ads)
    clean, ads, q_neg = q.check_negatives(clean, ads)
    unmapped, q_unmapped = q.check_unmapped_campaigns(clean["campaigns"], clean["sku_master"])

    fact = build_fact_daily(clean, ads)
    tables = {
        "fact_daily": fact,
        "sku_daily": build_sku_daily(clean),
        "reconciliation": build_reconciliation(fact, as_of),
        "feature_store": build_feature_store(fact, clean["campaigns"]),
        **build_dims(clean),
    }
    assert tuple(tables) == TABLES

    # Checks 5–7, then brain tables, then checks 8–9.
    quality_rows = [
        q_complete, q_dupes, q_neg, q_unmapped,
        q.check_reconciliation_gap(tables["reconciliation"]),
        q.check_freshness(fact, manifest["date_range"]["end"]),
        q.check_orders_consistency(fact, tables["sku_daily"], unmapped),
    ]
    tables["neuron_metrics"] = brain.build_neuron_metrics(fact, tables["sku_daily"], tables["reconciliation"],
                                                          manifest, unmapped)
    tables["source_status"] = brain.build_source_status(frames, tables["reconciliation"], quality_rows, manifest, as_of)
    quality_rows.append(q.check_infinite_values(tables))
    quality_rows.append(q.check_manifest_alignment(manifest, tables["neuron_metrics"], tables["source_status"]))
    tables["data_quality"] = q.public(quality_rows)

    for name, df in tables.items():
        validate_table(df, name)
        write_table(df[TABLE_COLUMNS[name]], name)  # if_exists="replace": re-runs are idempotent
    duration_ms = (time.perf_counter() - start) * 1000

    summary = summarise(tables, frames, as_of, duration_ms)
    summary["neurons"] = tables["neuron_metrics"]["health"].value_counts().reindex(["good", "weak", "losing"],
                                                                                 fill_value=0).to_dict()
    summary["sources"] = dict(zip(tables["source_status"]["source_id"], tables["source_status"]["status"]))
    summary["quality"] = tables["data_quality"]["status"].value_counts().reindex(["pass", "warn", "fail"],
                                                                               fill_value=0).to_dict()
    events = []
    if emit_brain_events:
        events = brain.emit_ingest_events(tables["source_status"], summary["data_trust"], summary["rows"], duration_ms)
    summary["brain_events_logged"] = len(events)
    summary["brain_event_ids"] = [e.id for e in events]
    if verbose:
        print_summary(summary)
    return summary


def print_summary(s: dict) -> None:
    rows = s["rows"]
    print(f"M2 OK · {len(rows)} tables · fact_daily {rows['fact_daily']:,} · sku_daily {rows['sku_daily']:,} · "
          f"data trust {s['data_trust']:.0%} · {s['duration_ms'] / 1000:.1f}s")
    print()
    print(f"{'channel':<14}{'inflation':>10}{'platform ROAS':>15}{'true ROAS':>11}{'trust':>8}")
    for r in s["reconciliation"]:
        print(f"{r['channel']:<14}{r['inflation_pct']:>+10.1%}{r['roas_platform']:>15.2f}{r['roas_true']:>11.2f}"
              f"{r['trust_score']:>8.2f}")
    print()
    print(f"Last {RECENT_DAYS} days: blended POAS {s['blended_poas_7d']:.2f} · "
          f"true ROAS {s['roas_true_7d']:.2f} vs platform ROAS {s['roas_platform_7d']:.2f}")
    print()
    n, qc = s.get("neurons", {}), s.get("quality", {})
    print(f"Brain: neurons good {n.get('good', 0)} · weak {n.get('weak', 0)} · losing {n.get('losing', 0)} | "
          f"quality pass {qc.get('pass', 0)} · warn {qc.get('warn', 0)} · fail {qc.get('fail', 0)} | "
          f"brain events logged {s.get('brain_events_logged', 0)}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="M2 ingestion & reconciliation pipeline")
    parser.add_argument("--no-brain-events", action="store_true", help="do not log ingest brain events")
    parser.add_argument("--as-of", help='fixed run timestamp "YYYY-MM-DDTHH:MM:SS" (default: now, IST)')
    args = parser.parse_args(argv)
    run_pipeline(as_of=args.as_of, emit_brain_events=not args.no_brain_events)


if __name__ == "__main__":
    main()
