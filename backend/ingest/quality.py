"""M2 data-quality checks.

Every check returns a row for the `data_quality` table:
    {check, status: pass | warn | fail, affected_rows, detail, action}
plus an internal "sources" list (connector sources affected), which pipeline.py strips before
writing and brain.py uses to mark data streams as "warn".

Checks 1–4 clean the inputs BEFORE fact_daily is built; 5–9 audit the outputs afterwards.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from backend.core.config import RECON_GAP_THRESHOLD

AD_COLUMNS = ["date", "channel", "campaign_id", "sku_id", "audience", "creative_id", "spend", "impressions",
              "clicks", "frequency", "platform_conversions", "platform_revenue"]
SKU_SOURCES = {"shopify_orders": "orders", "erp_inventory": "inventory", "ga4": "ga4", "pricing": "pricing"}
NEGATIVE_RULES = {  # connector source → columns that must be ≥ 0
    "ads": ["spend", "impressions", "clicks"],
    "shopify_utm": ["orders"],
    "shopify_orders": ["orders_paid", "orders_organic", "units"],
    "erp_inventory": ["on_hand", "inbound"],
}


def _row(check: str, status: str, affected: int, detail: str, action: str, sources=()) -> dict:
    return {"check": check, "status": status, "affected_rows": int(affected), "detail": detail, "action": action,
            "sources": list(sources)}


def public(rows: list[dict]) -> pd.DataFrame:
    """Rows as the data_quality table (internal keys removed)."""
    return pd.DataFrame([{k: v for k, v in r.items() if k != "sources"} for r in rows],
                        columns=["check", "status", "affected_rows", "detail", "action"])


# ---------------------------------------------------------------------------
# 1–4: input cleaning (run before fact_daily)
# ---------------------------------------------------------------------------
def check_completeness(ads: pd.DataFrame, campaigns: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Every campaign has a row every day. Gaps are filled with 0-spend rows (status warn)."""
    dates = [d.strftime("%Y-%m-%d") for d in pd.date_range(ads["date"].min(), ads["date"].max())]
    have = set(zip(ads["date"], ads["campaign_id"]))
    missing = [(d, cid) for cid in sorted(campaigns["campaign_id"]) for d in dates if (d, cid) not in have]
    expected = len(dates) * len(campaigns)
    if not missing:
        return ads, _row("completeness", "pass", 0, f"{len(campaigns)} campaigns × {len(dates)} days = {expected} rows",
                         "none")
    camp = campaigns.set_index("campaign_id")
    last_creative = ads.sort_values("date").groupby("campaign_id")["creative_id"].last()
    fill = pd.DataFrame([{
        "date": d, "channel": camp.at[cid, "channel"], "campaign_id": cid, "sku_id": camp.at[cid, "sku_id"],
        "audience": camp.at[cid, "audience"],
        "creative_id": last_creative.get(cid, f"CR-{cid.split('-')[1]}a"),
        "spend": 0.0, "impressions": 0, "clicks": 0, "frequency": 0.0,
        "platform_conversions": 0.0, "platform_revenue": 0.0,
    } for d, cid in missing])
    out = pd.concat([ads, fill], ignore_index=True).sort_values(["date", "campaign_id"], kind="stable")
    channels = sorted(set(fill["channel"]))
    return out.reset_index(drop=True), _row(
        "completeness", "warn", len(missing), f"{len(missing)} of {expected} campaign-days missing ({', '.join(channels)})",
        "filled with 0 spend; lowers trust", [f"{ch}_ads" for ch in channels])


def check_duplicates(frames: dict[str, pd.DataFrame], ads: pd.DataFrame) -> tuple[dict, pd.DataFrame, dict]:
    """Unique (date, campaign_id) in ads and (date, sku_id) in SKU tables. Duplicates keep the last row (warn)."""
    affected, sources, frames = 0, [], dict(frames)
    dup = ads.duplicated(["date", "campaign_id"], keep="last")
    if dup.any():
        affected += int(dup.sum())
        sources += sorted({f"{ch}_ads" for ch in ads.loc[dup, "channel"]})
        ads = ads[~dup].reset_index(drop=True)
    for src in SKU_SOURCES:
        df = frames[src]
        d = df.duplicated(["date", "sku_id"], keep="last")
        if d.any():
            affected += int(d.sum())
            sources.append(src)
            frames[src] = df[~d].reset_index(drop=True)
    if not affected:
        return frames, ads, _row("duplicates", "pass", 0, "no duplicate keys", "none")
    return frames, ads, _row("duplicates", "warn", affected, f"{affected} duplicate rows in {', '.join(sources)}",
                             "kept the last row per key", sources)


def check_negatives(frames: dict[str, pd.DataFrame], ads: pd.DataFrame) -> tuple[dict, pd.DataFrame, dict]:
    """spend, impressions, clicks, orders, units, on_hand, inbound must be ≥ 0. Negative rows are dropped (warn)."""
    affected, sources, frames = 0, [], dict(frames)
    for src, cols in NEGATIVE_RULES.items():
        df = ads if src == "ads" else frames[src]
        bad = (df[cols] < 0).any(axis=1)
        if bad.any():
            affected += int(bad.sum())
            if src == "ads":
                sources += sorted({f"{ch}_ads" for ch in df.loc[bad, "channel"]})
                ads = df[~bad].reset_index(drop=True)
            else:
                sources.append(src)
                frames[src] = df[~bad].reset_index(drop=True)
    if not affected:
        return frames, ads, _row("negatives", "pass", 0, "no negative counts or money", "none")
    return frames, ads, _row("negatives", "warn", affected, f"{affected} rows with negative values in {', '.join(sources)}",
                             "dropped and logged", sources)


def check_unmapped_campaigns(campaigns: pd.DataFrame, dim_sku: pd.DataFrame) -> tuple[set[str], dict]:
    """Every campaign's sku_id exists in dim_sku. Unmapped campaigns are excluded from SKU metrics (warn)."""
    unmapped = set(campaigns.loc[~campaigns["sku_id"].isin(dim_sku["sku_id"]), "campaign_id"])
    if not unmapped:
        return unmapped, _row("unmapped_campaigns", "pass", 0, f"all {len(campaigns)} campaigns map to a SKU", "none")
    return unmapped, _row("unmapped_campaigns", "warn", len(unmapped), f"no SKU for {', '.join(sorted(unmapped))}",
                          "excluded from SKU metrics", ["campaigns"])


# ---------------------------------------------------------------------------
# 5–9: output audits (run after the tables are built)
# ---------------------------------------------------------------------------
def check_reconciliation_gap(rec: pd.DataFrame) -> dict:
    """Any channel with |inflation_pct| > RECON_GAP_THRESHOLD is a reconciliation gap (warn)."""
    gap = rec[rec["inflation_pct"].abs() > RECON_GAP_THRESHOLD]
    if gap.empty:
        return _row("reconciliation_gap", "pass", 0, f"all channels within ±{RECON_GAP_THRESHOLD:.0%}", "none")
    detail = ", ".join(f"{r.channel} {r.inflation_pct:+.0%}" for r in gap.itertuples())
    return _row("reconciliation_gap", "warn", len(gap), f"platforms over-report: {detail}",
                "M3 raises attribution_inflation; M6 recommends server-side conversion tracking",
                [f"{ch}_ads" for ch in gap["channel"]])


def check_freshness(fact: pd.DataFrame, expected_last: str) -> dict:
    """Latest data date equals the manifest's date_range.end."""
    last = fact["date"].max()
    if last == expected_last:
        return _row("freshness", "pass", 0, f"data through {last}", "none")
    return _row("freshness", "warn", 0, f"data through {last}, expected {expected_last}",
                "re-run python -m backend.generator.generate / check connector sync")


def check_orders_consistency(fact: pd.DataFrame, sku_daily: pd.DataFrame, unmapped: set[str] = frozenset()) -> dict:
    """Σ fact_daily.orders per SKU-day equals sku_daily.orders_paid."""
    paid = fact[~fact["campaign_id"].isin(unmapped)].groupby(["date", "sku_id"])["orders"].sum()
    s = sku_daily.set_index(["date", "sku_id"])["orders_paid"]
    joined = s.to_frame().join(paid.rename("utm")).fillna(0)
    bad = int((joined["orders_paid"] != joined["utm"]).sum())
    if not bad:
        return _row("orders_consistency", "pass", 0, f"{len(joined)} SKU-days match UTM orders", "none")
    return _row("orders_consistency", "fail", bad, f"{bad} SKU-days where paid orders ≠ Σ UTM orders",
                "investigate UTM mapping before trusting SKU metrics", ["shopify_orders", "shopify_utm"])


def check_infinite_values(tables: dict[str, pd.DataFrame]) -> dict:
    """No ±inf in any written table."""
    found = {name: int(np.isinf(df.select_dtypes("number").to_numpy(dtype=float)).sum()) for name, df in tables.items()}
    found = {k: v for k, v in found.items() if v}
    if not found:
        return _row("infinite_values", "pass", 0, f"{len(tables)} tables free of ±inf", "none")
    return _row("infinite_values", "fail", sum(found.values()), f"±inf in {found}", "fix the formula to use M0 safe_div")


def check_manifest_alignment(manifest: dict, neuron_metrics: pd.DataFrame, source_status: pd.DataFrame) -> dict:
    """Every manifest neuron has a neuron_metrics row and every manifest source a source_status row."""
    missing_n = [n["entity_id"] for n in manifest["neurons"] if n["entity_id"] not in set(neuron_metrics["entity_id"])]
    missing_s = [s["id"] for s in manifest["sources"] if s["id"] not in set(source_status["source_id"])]
    if not missing_n and not missing_s:
        return _row("manifest_alignment", "pass", 0,
                    f"{len(manifest['neurons'])} neurons and {len(manifest['sources'])} sources aligned", "none")
    return _row("manifest_alignment", "fail", len(missing_n) + len(missing_s),
                f"missing neurons {missing_n}, sources {missing_s}", "regenerate brain_manifest.json and re-run M2")
