"""M4b causal analysis: synthetic control for price changes.

A before/after comparison cannot separate a price change from everything else that moved at the same time.
So we build the SKU's COUNTERFACTUAL: what its site conversion would have been without the price change,
predicted from SKUs that were NOT affected, using weights fitted on the pre-event period.

  1. event date and treated SKU come from `events`; old / new price from `sku_daily.unit_price`
  2. daily site CVR = units ÷ max(sessions, 1) for every SKU
  3. controls = every SKU except the treated one and any "disturbed" SKU (derived by rule from the active
     M3 anomalies: stockout_risk, its own conversion_drop, or a campaign with a positive_spike)
  4. pre-period = all days before the event; non-negative weights from scipy nnls on [control CVRs, 1] → treated CVR
  5. post-period: counterfactual rate = [controls_post, 1] @ w (clipped ≥ 0)
  6. counterfactual units = actual sessions × counterfactual rate, valued at the OLD price; actual units at the NEW price
  7. effect_per_day = mean(actual GM − counterfactual GM); total_effect = Σ over the post-period
  8. 95% CI: half_width = z × SD(pre-period fit residual) × mean post sessions × new unit margin × √n_post,
     applied to total_effect, so **ci_low / ci_high bound total_effect (₹ over the post-period)**.
     (M0's schema comment says ₹/day; this module follows the M4b spec formula literally. See the README.)

NNLS is used because weights must be non-negative: a synthetic control is a convex-ish blend of real SKUs, and
negative weights would "short" a control to fit noise, extrapolate wildly in the post-period and be impossible
to explain. Only price_change events are supported; other event types raise NotImplementedError.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.optimize import nnls

from backend.core.config import CAUSAL_CHART_DAYS, CAUSAL_CI_Z, CAUSAL_MIN_PRE_DAYS
from backend.core.db import read_table
from backend.core.schema import Anomaly, CausalResult

METHOD = "synthetic_control_nnls"
SUPPORTED_EVENT_TYPES = ("price_change",)


def disturbed_skus(anomalies: list[Anomaly], dim_campaign: pd.DataFrame) -> dict[str, str]:
    """SKUs whose conversion is disturbed by something other than the event, with the reason.

    Rules (never hard-coded IDs): an active stockout_risk on the SKU; its own conversion_drop; or a campaign
    promoting it with an active positive_spike (viral traffic changes its site conversion).
    """
    sku_of = dim_campaign.set_index("campaign_id")["sku_id"].to_dict()
    out: dict[str, str] = {}
    for a in anomalies:
        if a.kind == "stockout_risk":
            out.setdefault(a.entity_id, "active stockout_risk")
        elif a.kind == "conversion_drop" and a.entity_type == "sku":
            out.setdefault(a.entity_id, "own conversion_drop")
        elif a.kind == "positive_spike" and a.entity_type == "campaign" and a.entity_id in sku_of:
            out.setdefault(sku_of[a.entity_id], f"campaign {a.entity_id} has an active positive_spike")
    return out


def event_effect_details(event_id: str, anomalies: list[Anomaly] | None = None) -> dict:
    """Run the synthetic control for one price-change event and return everything worth persisting.

    Keys: result (M0 CausalResult), event_id, treated_sku, method, controls, weights (incl. "intercept"),
    excluded {sku: reason}, units_change_pct, pre_fit_rmse, mean_cvr_pre, n_pre, n_post, old_price, new_price.
    """
    events = read_table("events").set_index("event_id")
    if event_id not in events.index:
        raise KeyError(f"unknown event {event_id!r}; known events: {sorted(events.index)}")
    ev = events.loc[event_id]
    if ev["type"] not in SUPPORTED_EVENT_TYPES:
        raise NotImplementedError(
            f"event {event_id} has type {ev['type']!r}; M4b implements {SUPPORTED_EVENT_TYPES} only "
            f"(creative launches and competitor events are a documented extension)")
    treated, event_date = ev["entity"], ev["date"]

    sku = read_table("sku_daily")
    dates = sorted(sku["date"].unique())
    pre_dates, post_dates = [d for d in dates if d < event_date], [d for d in dates if d >= event_date]
    if len(pre_dates) < CAUSAL_MIN_PRE_DAYS:
        raise ValueError(f"{event_id}: only {len(pre_dates)} pre-period days, need {CAUSAL_MIN_PRE_DAYS}")
    if not post_dates:
        raise ValueError(f"{event_id}: no post-period days")

    sku = sku.assign(cvr=sku["units"] / sku["sessions"].clip(lower=1))
    cvr = sku.pivot(index="date", columns="sku_id", values="cvr").sort_index()
    t = sku[sku["sku_id"] == treated].set_index("date").sort_index()

    old_price, new_price = float(t.loc[pre_dates[-1], "unit_price"]), float(t.loc[event_date, "unit_price"])
    cogs = float(t["cogs"].mean())

    if anomalies is None:
        from backend.detection.detectors import detect_all

        anomalies = detect_all()
    excluded = disturbed_skus(anomalies, read_table("dim_campaign"))
    excluded.pop(treated, None)
    controls = [s for s in cvr.columns if s != treated and s not in excluded]
    if not controls:
        raise ValueError(f"{event_id}: no undisturbed control SKUs")

    # --- fit on the pre-period ---
    a_pre = np.column_stack([cvr.loc[pre_dates, controls].to_numpy(), np.ones(len(pre_dates))])
    y_pre = t.loc[pre_dates, "cvr"].to_numpy()
    w, _ = nnls(a_pre, y_pre)
    fitted_pre = a_pre @ w
    resid = y_pre - fitted_pre
    resid_sd = float(np.std(resid, ddof=1))
    pre_fit_rmse = float(np.sqrt(np.mean(resid ** 2)))

    # --- counterfactual in the post-period ---
    a_post = np.column_stack([cvr.loc[post_dates, controls].to_numpy(), np.ones(len(post_dates))])
    cf_rate = np.clip(a_post @ w, 0.0, None)
    sessions, units = t.loc[post_dates, "sessions"].to_numpy(float), t.loc[post_dates, "units"].to_numpy(float)
    cf_units = sessions * cf_rate
    actual_gm, cf_gm = units * (new_price - cogs), cf_units * (old_price - cogs)
    n_post = len(post_dates)
    effect_per_day = float(np.mean(actual_gm - cf_gm))
    total_effect = float(np.sum(actual_gm - cf_gm))
    half_width = CAUSAL_CI_Z * resid_sd * float(sessions.mean()) * (new_price - cogs) * float(np.sqrt(n_post))
    units_change_pct = float(units.sum() / cf_units.sum() - 1.0)

    # --- chart series: last N days, fitted value before the event, counterfactual after ---
    actual_all = t["cvr"].reindex(dates).to_numpy()
    cf_all = np.concatenate([fitted_pre, cf_rate])
    keep = range(max(0, len(dates) - CAUSAL_CHART_DAYS), len(dates))
    series = [{"date": dates[i], "actual": round(float(actual_all[i]), 6), "counterfactual": round(float(cf_all[i]), 6),
               "is_post": dates[i] >= event_date} for i in keep]

    result = CausalResult(event_id=event_id, description=ev["description"], effect_per_day=round(effect_per_day, 2),
                          total_effect=round(total_effect, 2), ci_low=round(total_effect - half_width, 2),
                          ci_high=round(total_effect + half_width, 2), series=series)
    return {
        "result": result, "event_id": event_id, "treated_sku": treated, "method": METHOD,
        "controls": controls, "weights": {**{c: round(float(x), 6) for c, x in zip(controls, w[:-1])},
                                          "intercept": round(float(w[-1]), 6)},
        "excluded": excluded, "units_change_pct": round(units_change_pct, 4), "pre_fit_rmse": round(pre_fit_rmse, 6),
        "mean_cvr_pre": round(float(np.mean(y_pre)), 6), "n_pre": len(pre_dates), "n_post": n_post,
        "old_price": old_price, "new_price": new_price,
    }


def event_effect(event_id: str, anomalies: list[Anomaly] | None = None) -> CausalResult:
    """The M0 CausalResult for a price-change event (see event_effect_details for the full picture)."""
    return event_effect_details(event_id, anomalies)["result"]


def compute_causal(anomalies: list[Anomaly]) -> dict[str, dict]:
    """Causal details for every conversion_drop whose detail names a supported event, keyed by event id."""
    out: dict[str, dict] = {}
    for a in anomalies:
        eid = a.detail.get("event_id") if a.kind == "conversion_drop" else None
        if eid and eid not in out:
            try:
                out[eid] = event_effect_details(eid, anomalies)
            except NotImplementedError:
                continue
    return out
