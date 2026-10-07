"""M3 anomaly & signal detection: the Neural Brain's "Diagnose" lobe.

Run from the project root:  python -m backend.detection.detectors

Method choice: this is deliberately STATISTICAL anomaly detection, not a trained ML model. There are
no labelled anomalies and only 90 days per entity, and every alert must explain what moved and by
how much. Methods: robust z-score (median + MAD), Welch's t-test (scipy) and threshold rules, behind
two gates: a change must be statistically significant AND practically large.

Seven detectors, each returning M0 `Anomaly` objects (good OR bad, with ₹/day impact, negative = loss):
  creative_fatigue · metric_shift / positive_spike   (per campaign)
  cpc_spike                                           (per channel)
  stockout_risk · conversion_drop                     (per SKU)
  attribution_inflation                               (per channel, from reconciliation)

Rules: reads only SQLite tables (never raw CSVs); every threshold comes from backend.core.config;
window ratios are Σnumerator ÷ Σdenominator; windows end on the LAST date in the data, never today.
"""
from __future__ import annotations

import math
import time
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

from backend.core import metrics as m
from backend.core.config import (
    BASELINE_DAYS, CHANNELS, CPC_SPIKE_MIN, FATIGUE_CTR_DOWN, FATIGUE_FREQ_UP, MAD_SCALE, MIN_PCT_CHANGE,
    PROFIT_BASE_FLOOR, RECENT_DAYS, RECON_GAP_THRESHOLD, SKU_BASELINE_DAYS, SKU_RECENT_DAYS,
    STOCK_COVER_RISK_DAYS, Z_THRESHOLD,
)
from backend.core.db import read_table
from backend.core.schema import Anomaly

KIND_DISPLAY = {
    "creative_fatigue": "Creative fatigue",
    "metric_shift": "Profit drop",
    "positive_spike": "Positive spike",
    "cpc_spike": "CPC spike",
    "stockout_risk": "Stockout risk",
    "conversion_drop": "Conversion drop",
    "attribution_inflation": "Attribution inflation",
}
SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2}
RECOMMENDED_FIX = "server-side conversion tracking (CAPI / enhanced conversions)"
MIN_DAILY_FLOOR = 1e-9  # keeps a perfectly flat baseline from dividing by zero in robust_z


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _windows(df: pd.DataFrame, recent_days: int, base_days: int, date_col: str = "date") -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split df into (recent, baseline) by calendar date.

    recent = the last `recent_days` dates in the data; baseline = the `base_days` dates immediately
    before it. Anchored on the last date present in df, never the wall clock.
    """
    dates = sorted(df[date_col].unique())
    recent_dates = dates[-recent_days:]
    base_dates = dates[-(recent_days + base_days):-recent_days]
    return df[df[date_col].isin(recent_dates)], df[df[date_col].isin(base_dates)]


def _daily(df: pd.DataFrame, by: str, cols: list[str]) -> pd.DataFrame:
    """Daily sums of `cols` per entity (`by`) per date."""
    return df.groupby([by, "date"], as_index=False)[cols].sum()


def _ratio(num: pd.Series, den: pd.Series, count_den: bool = False) -> float | None:
    """Σnum ÷ Σden. With count_den the denominator is guarded by max(Σden, 1); otherwise M0 safe_div."""
    n, d = float(num.sum()), float(den.sum())
    return n / max(d, 1.0) if count_den else m.safe_div(n, d)


def robust_z(recent_values, baseline_values) -> float:
    """Robust z-score of the recent mean against the baseline distribution.

    median = median(baseline); MAD = median(|baseline − median|) × MAD_SCALE;
    if MAD == 0: MAD = max(|median| × 0.01, 1e-9);
    z = (mean(recent) − median) / MAD × sqrt(n_recent) / 2.
    """
    recent = np.asarray(recent_values, dtype=float)
    base = np.asarray(baseline_values, dtype=float)
    recent, base = recent[~np.isnan(recent)], base[~np.isnan(base)]
    if len(recent) == 0 or len(base) == 0:
        return 0.0
    median = float(np.median(base))
    mad = float(np.median(np.abs(base - median))) * MAD_SCALE
    if mad == 0:
        mad = max(abs(median) * 0.01, MIN_DAILY_FLOOR)
    return float((recent.mean() - median) / mad * math.sqrt(len(recent)) / 2)


def _sev(profit_impact: float, kind: str) -> str:
    """Severity from ₹/day impact (M0 severity_from_impact); stockout is always high, attribution medium."""
    if kind == "stockout_risk":
        return "high"
    if kind == "attribution_inflation":
        return "medium"
    return m.severity_from_impact(profit_impact)


def _label(kind: str, name: str) -> str:
    """Alert title, e.g. "Creative fatigue · Meta · Summer Sneakers · broad"."""
    return f"{KIND_DISPLAY[kind]} · {name}"


def _mean(series: pd.Series) -> float:
    return float(series.mean()) if len(series) else 0.0


def _change(recent: float | None, base: float | None) -> float:
    """M0 change_pct, with None (zero baseline) reported as 0.0 change."""
    v = m.change_pct(recent, base)
    return 0.0 if v is None else float(v)


def _window_dict(recent: pd.DataFrame, base: pd.DataFrame) -> dict:
    """The recent/baseline date span stored on every alert's detail."""
    def span(df, which):
        return (df["date"].min() if which == "start" else df["date"].max()) if len(df) else None
    return {"recent_start": span(recent, "start"), "recent_end": span(recent, "end"),
            "baseline_start": span(base, "start"), "baseline_end": span(base, "end")}


def _clean(value: Any, digits: int = 4) -> Any:
    """Make a value JSON-safe and sensibly rounded (numpy → Python, floats to `digits`, NaN → None)."""
    if isinstance(value, dict):
        return {k: _clean(v, digits) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v, digits) for v in value]
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float):
        return round(value, digits) if math.isfinite(value) else None
    return value


def _make(kind: str, entity_type: str, entity_id: str, name: str, metric: str, baseline: float, recent: float,
          change: float, z: float, impact: float, direction: str, window: dict, detail: dict,
          value_digits: int = 2) -> Anomaly:
    """Build an Anomaly with rounding and the mandatory detail keys (id is assigned in detect_all)."""
    detail = {**detail, "direction": direction, "window": window}
    return Anomaly(
        id="", kind=kind, entity_type=entity_type, entity_id=entity_id, label=_label(kind, name), metric=metric,
        baseline=round(float(baseline), value_digits), recent=round(float(recent), value_digits),
        change_pct=round(float(change), 4), z=round(float(z), 2), profit_impact=round(float(impact), 2),
        severity=_sev(impact, kind), detail=_clean(detail),
    )


# ---------------------------------------------------------------------------
# 3.1 Campaign loop
# ---------------------------------------------------------------------------
def detect_campaigns(fact: pd.DataFrame, dim_campaign: pd.DataFrame, dim_creative: pd.DataFrame) -> list[Anomaly]:
    """creative_fatigue first; if it does not fire, check metric_shift / positive_spike. Campaign ID order."""
    recent_all, base_all = _windows(fact, RECENT_DAYS, BASELINE_DAYS)
    window = _window_dict(recent_all, base_all)
    names = dim_campaign.set_index("campaign_id")["campaign_name"]
    out: list[Anomaly] = []
    for cid in sorted(dim_campaign["campaign_id"]):
        rec, base = recent_all[recent_all["campaign_id"] == cid], base_all[base_all["campaign_id"] == cid]
        if rec.empty or base.empty:
            continue
        name = names[cid]
        profit_delta = _mean(rec["profit"]) - _mean(base["profit"])

        # a) creative fatigue: frequency up AND CTR down
        freq_change = _change(_mean(rec["frequency"]), _mean(base["frequency"]))
        ctr_recent, ctr_base = _ratio(rec["clicks"], rec["impressions"]), _ratio(base["clicks"], base["impressions"])
        ctr_change = _change(ctr_recent, ctr_base)
        if freq_change > FATIGUE_FREQ_UP and ctr_change < -FATIGUE_CTR_DOWN:
            out.append(_make(
                "creative_fatigue", "campaign", cid, name, "ctr", ctr_base or 0.0, ctr_recent or 0.0, ctr_change,
                robust_z(rec["ctr"], base["ctr"]), profit_delta, "loss", window,
                {"frequency_baseline": _mean(base["frequency"]), "frequency_recent": _mean(rec["frequency"]),
                 "freq_change": freq_change, "creative_id": rec.sort_values("date")["creative_id"].iloc[-1]},
                value_digits=4))
            continue  # no duplicate alert for the same campaign

        # b) profit shift (bad) / positive spike (good)
        z = robust_z(rec["profit"], base["profit"])
        base_profit = _mean(base["profit"])
        denom = max(abs(base_profit), PROFIT_BASE_FLOOR * _mean(base["spend"]))
        change = m.safe_div(profit_delta, denom) or 0.0
        if abs(z) < Z_THRESHOLD or abs(change) < MIN_PCT_CHANGE:
            continue
        kind = "positive_spike" if profit_delta > 0 else "metric_shift"
        cpc_change = _change(_ratio(rec["spend"], rec["clicks"]), _ratio(base["spend"], base["clicks"]))
        cvr_change = _change(_ratio(rec["orders"], rec["clicks"]), _ratio(base["orders"], base["clicks"]))
        launched = dim_creative[(dim_creative["campaign_id"] == cid)
                                & dim_creative["launch_date"].between(window["recent_start"], window["recent_end"])]
        out.append(_make(
            kind, "campaign", cid, name, "profit", base_profit, _mean(rec["profit"]), change, z, profit_delta,
            "gain" if kind == "positive_spike" else "loss", window,
            {"ctr_change": ctr_change, "cpc_change": cpc_change, "cvr_change": cvr_change,
             "new_creative": bool(len(launched)), "creative_ids_recent": sorted(set(rec["creative_id"]))}))
    return out


# ---------------------------------------------------------------------------
# 3.2 Channel loop
# ---------------------------------------------------------------------------
def detect_channels(fact: pd.DataFrame) -> list[Anomaly]:
    """cpc_spike per channel (CHANNELS order): CPC up more than CPC_SPIKE_MIN AND robust z above Z_THRESHOLD."""
    recent_all, base_all = _windows(fact, RECENT_DAYS, BASELINE_DAYS)
    window = _window_dict(recent_all, base_all)
    cols = ["spend", "clicks", "impressions", "profit"]
    out: list[Anomaly] = []
    for ch in CHANNELS:
        rec, base = recent_all[recent_all["channel"] == ch], base_all[base_all["channel"] == ch]
        if rec.empty or base.empty:
            continue
        rec_d, base_d = _daily(rec, "channel", cols), _daily(base, "channel", cols)
        cpc_recent, cpc_base = _ratio(rec["spend"], rec["clicks"]), _ratio(base["spend"], base["clicks"])
        cpc_change = _change(cpc_recent, cpc_base)
        z = robust_z(rec_d["spend"] / rec_d["clicks"].replace(0, np.nan), base_d["spend"] / base_d["clicks"].replace(0, np.nan))
        if not (cpc_change > CPC_SPIKE_MIN and z > Z_THRESHOLD):
            continue
        impact = _mean(rec_d["profit"]) - _mean(base_d["profit"])
        out.append(_make(
            "cpc_spike", "channel", ch, ch.title(), "cpc", cpc_base or 0.0, cpc_recent or 0.0, cpc_change, z, impact,
            "loss", window,
            {"cpm_change": _change(_ratio(rec["spend"], rec["impressions"]) , _ratio(base["spend"], base["impressions"])),
             "ctr_change": _change(_ratio(rec["clicks"], rec["impressions"]), _ratio(base["clicks"], base["impressions"])),
             "campaigns": sorted(set(fact.loc[fact["channel"] == ch, "campaign_id"]))}))
    return out


# ---------------------------------------------------------------------------
# 3.3 SKU loop
# ---------------------------------------------------------------------------
def detect_skus(fact: pd.DataFrame, sku_daily: pd.DataFrame, dim_sku: pd.DataFrame, events: pd.DataFrame) -> list[Anomaly]:
    """Per SKU (ID order): stockout_risk, then conversion_drop."""
    names = dim_sku.set_index("sku_id")["name"]
    last = sku_daily["date"].max()
    rec7, base21 = _windows(sku_daily, RECENT_DAYS, BASELINE_DAYS)
    win_stock = _window_dict(rec7, base21)
    rec14, base28 = _windows(sku_daily, SKU_RECENT_DAYS, SKU_BASELINE_DAYS)
    win_cvr = _window_dict(rec14, base28)
    fact7 = _windows(fact, RECENT_DAYS, 0)[0]
    out: list[Anomaly] = []
    for sku in sorted(dim_sku["sku_id"]):
        name = names[sku]

        # a) stockout risk: low cover while we are still spending on the SKU
        latest = sku_daily[(sku_daily["sku_id"] == sku) & (sku_daily["date"] == last)]
        r7, b21 = rec7[rec7["sku_id"] == sku], base21[base21["sku_id"] == sku]
        if len(latest) and len(r7):
            row = latest.iloc[0]
            camp7 = fact7[fact7["sku_id"] == sku]
            ad_spend_7d = float(camp7["spend"].sum()) / RECENT_DAYS
            if row["days_cover"] < STOCK_COVER_RISK_DAYS and ad_spend_7d > 0:
                baseline_cover = _mean(b21["days_cover"])
                margin_at_risk = -_mean(r7["units"] * (r7["unit_price"] - r7["cogs"]))
                out.append(_make(
                    "stockout_risk", "sku", sku, name, "days_cover", baseline_cover, float(row["days_cover"]),
                    _change(float(row["days_cover"]), baseline_cover), robust_z(r7["days_cover"], b21["days_cover"]),
                    margin_at_risk, "loss", win_stock,
                    {"days_cover": float(row["days_cover"]), "spend_per_day": ad_spend_7d,
                     "on_hand": int(row["on_hand"]), "inbound": int(row["inbound"]),
                     "campaigns": sorted(set(camp7["campaign_id"]))}))

        # b) conversion drop: site CVR down, significant by Welch's t-test
        rec, base = rec14[rec14["sku_id"] == sku], base28[base28["sku_id"] == sku]
        if rec.empty or base.empty:
            continue
        cvr_recent, cvr_base = _ratio(rec["purchases"], rec["sessions"], True), _ratio(base["purchases"], base["sessions"], True)
        cvr_change = _change(cvr_recent, cvr_base)
        daily_recent = rec["purchases"] / rec["sessions"].clip(lower=1)
        daily_base = base["purchases"] / base["sessions"].clip(lower=1)
        t = float(stats.ttest_ind(daily_recent, daily_base, equal_var=False).statistic)
        if not (cvr_change < -MIN_PCT_CHANGE and t < -Z_THRESHOLD):
            continue
        base_sorted, rec_sorted = base.sort_values("date"), rec.sort_values("date")
        price_start, price_end = float(base_sorted["unit_price"].iloc[-1]), float(rec_sorted["unit_price"].iloc[-1])
        unit_margin = price_end - float(rec_sorted["cogs"].iloc[-1])
        lost = (cvr_base - cvr_recent) * _mean(rec["sessions"]) * unit_margin
        ev = events[(events["entity"] == sku) & events["date"].between(win_cvr["recent_start"], win_cvr["recent_end"])]
        out.append(_make(
            "conversion_drop", "sku", sku, name, "site_cvr", cvr_base, cvr_recent, cvr_change, t, -lost, "loss", win_cvr,
            {"atc_rate_change": _change(_ratio(rec["add_to_cart"], rec["sessions"], True),
                                        _ratio(base["add_to_cart"], base["sessions"], True)),
             "price_start": price_start, "price_end": price_end, "price_change": _change(price_end, price_start),
             "event_id": ev["event_id"].iloc[0] if len(ev) else None, "test": "welch_t"}, value_digits=4))
    return out


# ---------------------------------------------------------------------------
# 3.4 Reconciliation loop
# ---------------------------------------------------------------------------
def detect_attribution(reconciliation: pd.DataFrame, fact: pd.DataFrame) -> list[Anomaly]:
    """attribution_inflation per channel (CHANNELS order): platform over-reports by more than RECON_GAP_THRESHOLD."""
    window = {"recent_start": fact["date"].min(), "recent_end": fact["date"].max(),
              "baseline_start": None, "baseline_end": None}  # a full-period data issue, not a window shift
    by = reconciliation.set_index("channel")
    out: list[Anomaly] = []
    for ch in CHANNELS:
        if ch not in by.index:
            continue
        r = by.loc[ch]
        if not r["inflation_pct"] > RECON_GAP_THRESHOLD:
            continue
        out.append(_make(
            "attribution_inflation", "channel", ch, ch.title(), "platform_vs_store", float(r["store_orders"]),
            float(r["platform_conversions"]), float(r["inflation_pct"]), 0.0, 0.0, "loss", window,
            {"roas_platform": float(r["roas_platform"]), "roas_true": float(r["roas_true"]),
             "trust_score": float(r["trust_score"]), "inflation_pct": float(r["inflation_pct"]),
             "recommended_fix": RECOMMENDED_FIX}))
    return out


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------
def detect_all() -> list[Anomaly]:
    """Run every detector, assign IDs AN-001… in detection order, then rank by |₹ impact| (high severity first on ties)."""
    fact = read_table("fact_daily")
    sku_daily = read_table("sku_daily")
    found = (
        detect_campaigns(fact, read_table("dim_campaign"), read_table("dim_creative"))
        + detect_channels(fact)
        + detect_skus(fact, sku_daily, read_table("dim_sku"), read_table("events"))
        + detect_attribution(read_table("reconciliation"), fact)
    )
    for i, a in enumerate(found, start=1):
        a.id = f"AN-{i:03d}"
    return sorted(found, key=lambda a: (-abs(a.profit_impact), SEVERITY_RANK[a.severity], a.id))


def _statistic(a: Anomaly) -> str:
    if a.kind == "conversion_drop":
        return f"t={a.z:.2f}"
    if a.kind == "attribution_inflation":
        return "—"
    return f"z={a.z:.2f}"


def main() -> None:
    start = time.perf_counter()
    alerts = detect_all()
    elapsed = time.perf_counter() - start
    print(f"{'ID':<7}{'kind':<23}{'entity':<10}{'change':>9}{'stat':>10}{'₹/day':>11}  {'severity':<9}direction")
    for a in alerts:
        print(f"{a.id:<7}{a.kind:<23}{a.entity_id:<10}{a.change_pct:>+9.1%}{_statistic(a):>10}"
              f"{m.format_inr(a.profit_impact):>11}  {a.severity:<9}{a.detail['direction']}")
    counts = {s: sum(a.severity == s for a in alerts) for s in ("high", "medium", "low")}
    print(f"M3 OK · {len(alerts)} anomalies · {counts['high']} high · {counts['medium']} medium · "
          f"{counts['low']} low · {elapsed:.1f}s")


if __name__ == "__main__":
    main()
