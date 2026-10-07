"""M5 response curves: how gross margin responds to spend (diminishing returns).

Model (Michaelis–Menten / Hill with n = 1):     GM(s) = a · s ÷ (b + s)
  a = the most gross margin per day the campaign can ever make; b = the spend that reaches half of a.
Marginal POAS(s) = dGM/ds = a·b ÷ (b + s)²   (> 1: scaling adds profit; < 1: the next rupee loses money)
Profit(s) = GM(s) − s;   it peaks where marginal POAS = 1, at s* = √(a·b) − b.

"Shape from history, level from now": (a, b) are fitted on all 90 days, then `a` is RE-ANCHORED so the curve
passes through the last 7 days' actual average margin at the last 7 days' average spend. That keeps the long
history's learned saturation but picks up recent changes (creative fatigue, CPC spikes). M1's weekly budget
tests (±40% in the first 55 days) spread each campaign's spend over a range, which is what makes b learnable.

Reads only SQLite tables (fact_daily, sku_daily) and state.json's budget_overrides. Fitted curves are cached in
memory (invalidated when the database or state file changes, or with refresh=True) so the simulator is instant.
"""
from __future__ import annotations

import os
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import OptimizeWarning, curve_fit

from backend.core import config
from backend.core import metrics as m
from backend.core.config import (
    CURVE_B_MAX_MULT, CURVE_B_MIN_MULT, CURVE_POINTS, RECENT_DAYS, SATURATION_MULT,
)
from backend.core.db import load_state, read_table

REV_WINDOW_DAYS = 28  # revenue-per-margin ratio window
TINY_A = 1e-6  # ceiling for `a` when the recent margin is not positive
A_MAX_MULT, A_MAX_PAD = 20.0, 1.0  # a ∈ [0, 20 × max daily GM + 1]
UNCERTAINTY_MAX, UNCERTAINTY_DEFAULT = 2.0, 1.0
FIT_MAXFEV = 10000

CURVE_COLUMNS = ["campaign_id", "channel", "sku_id", "audience", "name", "a", "b", "rev_per_gm", "current_spend",
                 "days_cover", "uncertainty", "marginal_poas", "saturation_spend", "optimal_spend", "gm_7d",
                 "spend_7d", "fit_ok", "flags"]

_CACHE: dict = {"key": None, "df": None}


def hill(s, a, b):
    """GM(s) = a·s ÷ (b + s). Works on floats and numpy arrays."""
    return a * s / (b + s)


def marginal_poas(s, a, b):
    """dGM/ds = a·b ÷ (b + s)²: the gross margin the next ₹1 of spend adds."""
    return a * b / (b + s) ** 2


def optimal_spend(a: float, b: float) -> float:
    """Spend where marginal POAS = 1 (profit peaks): √(a·b) − b, floored at 0."""
    return max(0.0, float(np.sqrt(a * b) - b))


def _fit_one(spend: np.ndarray, gm: np.ndarray) -> tuple[float, float, float, bool, list[str]]:
    """Fit (a, b) for one campaign. Returns (a, b, uncertainty, fit_ok, flags)."""
    mean_s, mean_gm, max_gm = float(spend.mean()), float(gm.mean()), float(gm.max())
    b_lo, b_hi = CURVE_B_MIN_MULT * mean_s, CURVE_B_MAX_MULT * mean_s
    flags: list[str] = []
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", OptimizeWarning)
            popt, pcov = curve_fit(
                hill, spend, gm, p0=[max(2 * max_gm, 1e-3), mean_s],
                bounds=([0.0, b_lo], [A_MAX_MULT * max_gm + A_MAX_PAD, b_hi]), maxfev=FIT_MAXFEV)
        a, b = float(popt[0]), float(popt[1])
        with np.errstate(invalid="ignore"):
            rel = float(np.sqrt(pcov[1, 1]) / b)
        uncertainty = float(np.clip(rel, 0.0, UNCERTAINTY_MAX)) if np.isfinite(rel) else UNCERTAINTY_DEFAULT
        if b <= b_lo * 1.001:
            flags.append("b_at_lower_bound")
        if b >= b_hi * 0.999:
            flags.append("b_at_upper_bound")
        return a, b, uncertainty, True, flags
    except (RuntimeError, ValueError):
        return max(2 * mean_gm, TINY_A), mean_s, UNCERTAINTY_DEFAULT, False, ["fit_failed"]


def _cache_key() -> tuple:
    def stamp(p) -> int | None:
        p = Path(p)
        return os.stat(p).st_mtime_ns if p.exists() else None
    return (str(config.DB_PATH), str(config.STATE_PATH), stamp(config.DB_PATH), stamp(config.STATE_PATH))


def fit_curves(as_of: str | None = None, refresh: bool = False) -> pd.DataFrame:
    """One fitted, re-anchored response curve per campaign (campaign_id order).

    `as_of` is accepted for symmetry with the other modules; windows are always anchored on the last date in the
    data, never on the wall clock. refresh=True re-fits and replaces the in-memory cache.
    """
    key = _cache_key()
    if not refresh and _CACHE["key"] == key and _CACHE["df"] is not None:
        return _CACHE["df"].copy()

    fact, sku, camps = read_table("fact_daily"), read_table("sku_daily"), read_table("dim_campaign")
    overrides = load_state().get("budget_overrides", {})
    dates = sorted(fact["date"].unique())
    d7, d28 = dates[-RECENT_DAYS:], dates[-REV_WINDOW_DAYS:]
    cover = sku[sku["date"] == dates[-1]].set_index("sku_id")["days_cover"]
    overall_rev = m.safe_div(fact[fact["date"].isin(d28)]["revenue"].sum(), fact[fact["date"].isin(d28)]["gross_margin"].sum())

    rows = []
    for c in camps.sort_values("campaign_id").itertuples(index=False):
        g = fact[fact["campaign_id"] == c.campaign_id].sort_values("date")
        spend, gm = g["spend"].to_numpy(float), g["gross_margin"].to_numpy(float)
        a, b, uncertainty, fit_ok, flags = _fit_one(spend, gm)

        recent = g[g["date"].isin(d7)]
        spend_7d, gm_7d = float(recent["spend"].sum()) / RECENT_DAYS, float(recent["gross_margin"].sum()) / RECENT_DAYS
        if gm_7d > 0 and spend_7d > 0:
            a = gm_7d * (b + spend_7d) / spend_7d  # the curve now passes through the last 7 days
        else:
            a = min(a, TINY_A)
            flags.append("negative_recent_margin")

        w28 = g[g["date"].isin(d28)]
        rev_per_gm = m.safe_div(w28["revenue"].sum(), w28["gross_margin"].sum()) or overall_rev or 1.0
        current = float(overrides[c.campaign_id]) if c.campaign_id in overrides else spend_7d
        rows.append({
            "campaign_id": c.campaign_id, "channel": c.channel, "sku_id": c.sku_id, "audience": c.audience,
            "name": c.campaign_name, "a": a, "b": b, "rev_per_gm": float(rev_per_gm), "current_spend": current,
            "days_cover": float(cover.get(c.sku_id, np.nan)), "uncertainty": uncertainty,
            "marginal_poas": float(marginal_poas(current, a, b)), "saturation_spend": SATURATION_MULT * b,
            "optimal_spend": optimal_spend(a, b), "gm_7d": gm_7d, "spend_7d": spend_7d, "fit_ok": fit_ok, "flags": flags,
        })
    df = pd.DataFrame(rows, columns=CURVE_COLUMNS)
    _CACHE["key"], _CACHE["df"] = key, df
    return df.copy()


def unanchored_marginal(campaign_id: str) -> dict:
    """Diagnostic: the fitted (a, b) BEFORE re-anchoring and the marginal POAS they imply at current spend."""
    fact = read_table("fact_daily")
    g = fact[fact["campaign_id"] == campaign_id]
    a, b, *_ = _fit_one(g["spend"].to_numpy(float), g["gross_margin"].to_numpy(float))
    row = fit_curves().set_index("campaign_id").loc[campaign_id]
    return {"a_fit": a, "b": b, "marginal_poas_unanchored": float(marginal_poas(row["current_spend"], a, b)),
            "current_spend": float(row["current_spend"])}


def curve_points(row, n: int = CURVE_POINTS) -> list[dict]:
    """n evenly spaced points from 0 to max(2.5 × current, 1.2 × saturation) for the UI chart."""
    top = max(2.5 * row["current_spend"], 1.2 * row["saturation_spend"])
    s = np.linspace(0.0, top, n)
    gm = hill(s, row["a"], row["b"])
    return [{"spend": round(float(x), 2), "gross_margin": round(float(g), 2), "profit": round(float(g - x), 2),
             "marginal_poas": round(float(marginal_poas(x, row["a"], row["b"])), 4)} for x, g in zip(s, gm)]
