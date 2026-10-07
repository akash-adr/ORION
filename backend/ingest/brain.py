"""M2 ↔ Neural Brain: the Ingest lobe.

- neuron_metrics: live numbers for the 26 manifest neurons (colour = health, size = spend,
  ring = trust, hover = platform vs true ROAS vs POAS, stock bar = days_cover)
- source_status: one row per manifest data stream (the 9 streams flowing into Ingest)
- emit_ingest_events: 9 per-source "ingest" pulses + 1 settle pulse per pipeline run

Windows are anchored on the last date in the data. No anomaly / is_alerting logic here (M3/M9).
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from backend.core import config
from backend.core import metrics as m
from backend.core.config import RECENT_DAYS, RECON_GAP_THRESHOLD, STOCK_COVER_RISK_DAYS
from backend.core.db import TABLE_COLUMNS, log_brain_event
from backend.core.schema import make_brain_event
from backend.ingest.connectors import SOURCE_MAP

MANIFEST_FILE = "brain_manifest.json"
AD_KIND = "ad_platform"


def load_manifest() -> dict:
    """Read data/raw/brain_manifest.json (RAW_DIR resolved at call time)."""
    path = Path(config.RAW_DIR) / MANIFEST_FILE
    if not path.exists():
        raise FileNotFoundError(f"missing {path}. Run `python -m backend.generator.generate` first.")
    return json.loads(path.read_text(encoding="utf-8"))


def period_dates(last_date: str, days: int, offset: int = 0) -> list[str]:
    """`days` dates ending `offset` days before last_date (offset=0 → the last `days` days)."""
    end = pd.Timestamp(last_date) - pd.Timedelta(days=offset)
    return [d.strftime("%Y-%m-%d") for d in pd.date_range(end=end, periods=days)]


def signed_change(recent: pd.Series, previous: pd.Series) -> pd.Series:
    """Change vs the previous period, measured against |previous| so a deeper loss is negative.

    Uses M0 change_pct: change_pct(|prev| + (recent − prev), |prev|) = (recent − prev) ÷ |prev|.
    previous == 0 → NaN.
    """
    base = previous.abs()
    return m.change_pct(base + (recent - previous), base)


# ---------------------------------------------------------------------------
# neuron_metrics
# ---------------------------------------------------------------------------
def build_neuron_metrics(fact: pd.DataFrame, sku_daily: pd.DataFrame, rec: pd.DataFrame, manifest: dict,
                         unmapped: set[str] = frozenset()) -> pd.DataFrame:
    """One row per manifest neuron (same ids, same order) with 7-day live metrics."""
    last = fact["date"].max()
    d7, dprev = period_dates(last, RECENT_DAYS), period_dates(last, RECENT_DAYS, offset=RECENT_DAYS)
    n = float(RECENT_DAYS)
    cols = ["spend", "gross_margin", "profit", "platform_revenue", "revenue"]
    cur = fact[fact["date"].isin(d7)].groupby("campaign_id")[cols].sum()
    prev = fact[fact["date"].isin(dprev)].groupby("campaign_id")[cols].sum()
    trust = rec.set_index("channel")["trust_score"]
    cover = sku_daily[sku_daily["date"] == last].set_index("sku_id")["days_cover"]

    # --- campaigns ---
    camp = pd.DataFrame(index=cur.index.union(prev.index))
    cur, prev = cur.reindex(camp.index).fillna(0.0), prev.reindex(camp.index).fillna(0.0)
    channel_of = fact.drop_duplicates("campaign_id").set_index("campaign_id")["channel"]
    sku_of = fact.drop_duplicates("campaign_id").set_index("campaign_id")["sku_id"]
    camp["spend_7d"] = cur["spend"] / n
    camp["spend_prev_7d"] = prev["spend"] / n
    camp["poas_7d"] = m.poas(cur["gross_margin"], cur["spend"])
    camp["profit_7d"] = cur["profit"] / n
    camp["change_pct"] = signed_change(camp["profit_7d"], prev["profit"] / n)
    camp["roas_platform_7d"] = m.roas_platform(cur["platform_revenue"], cur["spend"])
    camp["roas_true_7d"] = m.roas_true(cur["revenue"], cur["spend"])
    camp["trust_score"] = channel_of.reindex(camp.index).map(trust)
    camp["days_cover"] = sku_of.reindex(camp.index).map(cover)
    camp["no_spend"] = cur["spend"] <= 0

    # --- SKUs: paid metrics from their campaigns, profit from paid + organic ---
    mapped = fact[~fact["campaign_id"].isin(unmapped)].copy()
    mapped["trust_spend"] = mapped["spend"] * mapped["channel"].map(trust)
    sku_cols = cols + ["trust_spend"]
    s_cur = mapped[mapped["date"].isin(d7)].groupby("sku_id")[sku_cols].sum()
    s_prev = mapped[mapped["date"].isin(dprev)].groupby("sku_id")[sku_cols].sum()

    def store_margin(dates: list[str]) -> pd.Series:
        w = sku_daily[sku_daily["date"].isin(dates)]
        return (w["revenue"] - w["units"] * w["cogs"]).groupby(w["sku_id"]).sum()

    skus = pd.DataFrame(index=pd.Index(sorted(sku_daily["sku_id"].unique()), name="sku_id"))
    s_cur, s_prev = s_cur.reindex(skus.index).fillna(0.0), s_prev.reindex(skus.index).fillna(0.0)
    margin_cur = store_margin(d7).reindex(skus.index).fillna(0.0)
    margin_prev = store_margin(dprev).reindex(skus.index).fillna(0.0)
    skus["spend_7d"] = s_cur["spend"] / n
    skus["spend_prev_7d"] = s_prev["spend"] / n
    skus["poas_7d"] = m.poas(s_cur["gross_margin"], s_cur["spend"])
    skus["profit_7d"] = (margin_cur - s_cur["spend"]) / n
    skus["change_pct"] = signed_change(skus["profit_7d"], (margin_prev - s_prev["spend"]) / n)
    skus["roas_platform_7d"] = m.roas_platform(s_cur["platform_revenue"], s_cur["spend"])
    skus["roas_true_7d"] = m.roas_true(s_cur["revenue"], s_cur["spend"])
    skus["trust_score"] = m.safe_div(s_cur["trust_spend"], s_cur["spend"]).fillna(1.0)
    skus["days_cover"] = cover.reindex(skus.index)
    skus["no_spend"] = s_cur["spend"] <= 0

    rows = []
    for neuron in manifest["neurons"]:
        src = camp if neuron["entity_type"] == "campaign" else skus
        r = src.loc[neuron["entity_id"]] if neuron["entity_id"] in src.index else None
        rows.append({
            "entity_id": neuron["entity_id"], "entity_type": neuron["entity_type"], "label": neuron["label"],
            "cluster": neuron["cluster"], "channel": neuron["channel"], "sku_id": neuron["sku_id"],
            **({k: (r[k] if r is not None else float("nan")) for k in
                ("spend_7d", "spend_prev_7d", "poas_7d", "profit_7d", "change_pct", "roas_platform_7d",
                 "roas_true_7d", "trust_score", "days_cover")}),
            "_no_spend": bool(r["no_spend"]) if r is not None else True,
        })
    out = pd.DataFrame(rows)
    out["spend_7d"] = out["spend_7d"].fillna(0.0)
    out["health"] = m.neuron_health(out["poas_7d"])
    # Neurons with no ad spend have no POAS: judge them on stock instead.
    no_spend = out["_no_spend"]
    out.loc[no_spend, "health"] = out.loc[no_spend, "days_cover"].map(
        lambda c: "good" if pd.notna(c) and c >= STOCK_COVER_RISK_DAYS else "weak")
    out["size"] = m.neuron_size(out["spend_7d"], out["spend_7d"].min(), out["spend_7d"].max())
    return out[TABLE_COLUMNS["neuron_metrics"]]


# ---------------------------------------------------------------------------
# source_status
# ---------------------------------------------------------------------------
def connectors_for(source_id: str) -> list[str]:
    """Connector source names feeding a manifest source id (SOURCE_MAP inverted, stable order)."""
    return [k for k, v in SOURCE_MAP.items() if v == source_id]


def build_source_status(frames: dict[str, pd.DataFrame], rec: pd.DataFrame, quality_rows: list[dict],
                        manifest: dict, as_of: str) -> pd.DataFrame:
    """One row per manifest source (manifest order): rows fetched, date span, trust and a status badge."""
    rec_by_channel = rec.set_index("channel")
    flagged = {s for q in quality_rows if q["status"] != "pass" and q["check"] != "reconciliation_gap"
               for s in q.get("sources", [])}
    rows = []
    for src in manifest["sources"]:
        conns = connectors_for(src["id"])
        dfs = [frames[c] for c in conns if c in frames]
        n_rows = int(sum(len(d) for d in dfs))
        dates = pd.concat([d["date"] for d in dfs]) if dfs and n_rows else pd.Series(dtype=str)
        min_d, max_d = (dates.min(), dates.max()) if len(dates) else (None, None)
        n_days = dates.nunique() if len(dates) else 0
        trust = infl = None
        is_ad = src["kind"] == AD_KIND
        if is_ad and src["channel"] in rec_by_channel.index:
            trust = float(rec_by_channel.at[src["channel"], "trust_score"])
            infl = float(rec_by_channel.at[src["channel"], "inflation_pct"])
        gap = is_ad and infl is not None and abs(infl) > RECON_GAP_THRESHOLD
        status = "warn" if (gap or n_rows == 0 or any(c in flagged for c in conns)) else "ok"
        if n_rows == 0:
            detail = "no rows received"
        elif gap:
            word = "more" if infl > 0 else "fewer"
            detail = f"Reports {abs(infl):.0%} {word} conversions than the store"
        elif is_ad:
            detail = f"{n_days} days · {n_rows:,} rows · matches store orders"
        else:
            detail = f"{n_days} days · {n_rows:,} rows"
        if status == "warn" and not gap and n_rows:
            detail += " · data-quality issues"
        rows.append({
            "source_id": src["id"], "label": src["label"], "kind": src["kind"], "connector": "+".join(conns),
            "file": src["file"], "rows": n_rows, "min_date": min_d, "max_date": max_d, "last_synced": as_of,
            "status": status, "trust_score": trust, "inflation_pct": infl, "detail": detail,
        })
    return pd.DataFrame(rows, columns=TABLE_COLUMNS["source_status"])


# ---------------------------------------------------------------------------
# Brain events
# ---------------------------------------------------------------------------
def _none_if_nan(v):
    return None if v is None or (isinstance(v, float) and v != v) else v


def ingest_message(row: dict) -> str:
    msg = f"{row['label']} synced · {row['rows']:,} rows"
    infl = _none_if_nan(row["inflation_pct"])
    if row["kind"] == AD_KIND and infl is not None:
        msg += f" · reports {infl:+.0%} conversions" if abs(infl) > RECON_GAP_THRESHOLD else " · matches store"
    elif row["status"] == "warn":
        msg += " · data-quality issues"
    return msg


def emit_ingest_events(source_status: pd.DataFrame, data_trust: float, table_rows: dict, duration_ms: float) -> list:
    """Log 9 per-source "ingest" pulses (manifest order) + 1 settle pulse. Returns the logged events."""
    events = []
    for row in source_status.to_dict(orient="records"):
        ev = make_brain_event(
            "ingest", entity_id=row["source_id"], ref_id=None,
            severity="medium" if row["status"] == "warn" else "low",
            message=ingest_message(row),
            payload={"source_id": row["source_id"], "rows": row["rows"], "status": row["status"],
                     "trust_score": _none_if_nan(row["trust_score"]), "inflation_pct": _none_if_nan(row["inflation_pct"]),
                     "last_synced": row["last_synced"]},
        )
        events.append(log_brain_event(ev))
    summary = make_brain_event(
        "ingest", entity_id=None, severity="low", message=f"Ingestion complete · data trust {data_trust:.0%}",
        payload={"data_trust": data_trust, "tables": table_rows, "duration_ms": round(duration_ms, 1)},
    )
    events.append(log_brain_event(summary))
    return events
