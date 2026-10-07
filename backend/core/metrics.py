"""M0 metrics: the one definition of every formula in the engine.

Every function is pure and works on plain floats AND pandas Series (element-wise).
Division by zero never raises and never returns inf: floats → None, Series → NaN.
Missing scalar inputs (None / NaN) propagate as None.
"""
from __future__ import annotations

import math
from typing import Any, Callable

import numpy as np
import pandas as pd

from backend.core import config

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _is_vector(x: Any) -> bool:
    return isinstance(x, (pd.Series, np.ndarray))


def _as_series(x: Any) -> Any:
    return pd.Series(x, dtype="float64") if isinstance(x, np.ndarray) else x


def _missing(x: Any) -> bool:
    if x is None:
        return True
    try:
        return bool(isinstance(x, (float, np.floating)) and math.isnan(x))
    except TypeError:
        return False


def _clean_series(s: pd.Series) -> pd.Series:
    return s.astype("float64").replace([np.inf, -np.inf], np.nan)


def _clean_scalar(v: Any) -> float | None:
    if _missing(v):
        return None
    v = float(v)
    return v if math.isfinite(v) else None


def _apply(fn: Callable[..., Any], *args: Any) -> Any:
    """Run fn element-wise on Series, or on scalars with None propagation; strip inf."""
    if any(_is_vector(a) for a in args):
        args = tuple(_as_series(a) if _is_vector(a) else (np.nan if a is None else a) for a in args)
        with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
            return _clean_series(fn(*args))
    if any(_missing(a) for a in args):
        return None
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        return _clean_scalar(fn(*args))


def _map(fn: Callable[[Any], Any], x: Any) -> Any:
    """Apply a scalar-returning-label function to a scalar or each Series element."""
    if _is_vector(x):
        return _as_series(x).map(lambda v: fn(None if _missing(v) else v))
    return fn(x)


# ---------------------------------------------------------------------------
# Core ratios
# ---------------------------------------------------------------------------


def safe_div(a: Any, b: Any) -> Any:
    """a / b. Unitless ratio of the inputs. b == 0 → None (float) or NaN (Series), never inf."""
    if any(_is_vector(x) for x in (a, b)):
        a_ = _as_series(a) if _is_vector(a) else (np.nan if a is None else a)
        b_ = _as_series(b) if _is_vector(b) else (np.nan if b is None else b)
        with np.errstate(divide="ignore", invalid="ignore"):
            out = a_ / b_
        out = _clean_series(pd.Series(out) if not isinstance(out, pd.Series) else out)
        zero = (b_ == 0) if isinstance(b_, pd.Series) else pd.Series(b_ == 0, index=out.index)
        return out.mask(zero)
    if _missing(a) or _missing(b) or b == 0:
        return None
    return _clean_scalar(float(a) / float(b))


def ctr(clicks: Any, impressions: Any) -> Any:
    """CTR = clicks / impressions. Unit: fraction (0.012 = 1.2%)."""
    return safe_div(clicks, impressions)


def cpm(spend: Any, impressions: Any) -> Any:
    """CPM = spend / impressions * 1000. Unit: ₹ per 1,000 impressions."""
    return _apply(lambda r: r * 1000.0, safe_div(spend, impressions))


def cpc(spend: Any, clicks: Any) -> Any:
    """CPC = spend / clicks. Unit: ₹ per click."""
    return safe_div(spend, clicks)


def cvr(orders: Any, clicks: Any) -> Any:
    """CVR = store orders / clicks. Unit: fraction. Uses STORE orders, never platform conversions."""
    return safe_div(orders, clicks)


# ---------------------------------------------------------------------------
# Revenue and profit
# ---------------------------------------------------------------------------


def true_revenue(orders: Any, price: Any) -> Any:
    """True revenue = store orders * price. Unit: ₹ (per day when inputs are daily)."""
    return _apply(lambda o, p: o * p, orders, price)


def gross_margin(orders: Any, price: Any, cogs: Any) -> Any:
    """Gross margin = orders * (price - cogs). Unit: ₹ (per day when inputs are daily)."""
    return _apply(lambda o, p, c: o * (p - c), orders, price, cogs)


def contribution_profit(gross_margin: Any, spend: Any) -> Any:
    """Contribution profit = gross margin - ad spend. Unit: ₹ (per day when inputs are daily)."""
    return _apply(lambda g, s: g - s, gross_margin, spend)


def roas_platform(platform_revenue: Any, spend: Any) -> Any:
    """Platform ROAS = platform-reported revenue / spend. Unit: ₹ revenue per ₹ spend (inflated by attribution)."""
    return safe_div(platform_revenue, spend)


def roas_true(store_revenue: Any, spend: Any) -> Any:
    """True ROAS = store (reconciled) revenue / spend. Unit: ₹ revenue per ₹ spend."""
    return safe_div(store_revenue, spend)


def poas(gross_margin: Any, spend: Any) -> Any:
    """POAS = gross margin / spend. Unit: ₹ margin per ₹ spend (1.0 = break-even before fixed costs)."""
    return safe_div(gross_margin, spend)


# ---------------------------------------------------------------------------
# Attribution trust
# ---------------------------------------------------------------------------


def inflation_pct(platform_conversions: Any, store_orders: Any) -> Any:
    """Inflation = platform_conversions / store_orders - 1. Unit: fraction (0.30 = platform over-reports by 30%)."""
    return _apply(lambda r: r - 1.0, safe_div(platform_conversions, store_orders))


def trust_score(inflation: Any) -> Any:
    """Trust = clip(1 - 2 * max(inflation, 0), 0, 1). Unit: score in [0, 1] (1 = fully trustworthy)."""
    if _is_vector(inflation):
        s = _as_series(inflation).astype("float64")
        return (1.0 - 2.0 * s.clip(lower=0.0)).clip(0.0, 1.0)
    if _missing(inflation):
        return None
    return float(min(1.0, max(0.0, 1.0 - 2.0 * max(float(inflation), 0.0))))


# ---------------------------------------------------------------------------
# Inventory, site and change
# ---------------------------------------------------------------------------


def days_cover(on_hand: Any, units_7d_avg: Any) -> Any:
    """Days of cover = on_hand units / average daily units sold (7-day). Unit: days."""
    return safe_div(on_hand, units_7d_avg)


def site_cvr(purchases: Any, sessions: Any) -> Any:
    """Site CVR = purchases / sessions. Unit: fraction."""
    return safe_div(purchases, sessions)


def change_pct(recent: Any, baseline: Any) -> Any:
    """Change = recent / baseline - 1. Unit: fraction (-0.20 = down 20%)."""
    return _apply(lambda r: r - 1.0, safe_div(recent, baseline))


# ---------------------------------------------------------------------------
# Labels and sizing
# ---------------------------------------------------------------------------


def _neuron_health_scalar(p: Any) -> str:
    if _missing(p):
        return "weak"
    p = float(p)
    if p >= config.NEURON_POAS_GOOD:
        return "good"
    if p >= config.NEURON_POAS_WEAK:
        return "weak"
    return "losing"


def neuron_health(poas_value: Any) -> Any:
    """Health from POAS: >= NEURON_POAS_GOOD → "good"; >= NEURON_POAS_WEAK → "weak"; else "losing".
    None/NaN → "weak". Unit: label."""
    return _map(_neuron_health_scalar, poas_value)


def _severity_scalar(impact: Any) -> str:
    if _missing(impact) or float(impact) >= 0:
        return "low"
    loss = abs(float(impact))
    if loss > config.SEVERITY_HIGH_IMPACT:
        return "high"
    if loss > config.SEVERITY_MEDIUM_IMPACT:
        return "medium"
    return "low"


def severity_from_impact(profit_impact: Any) -> Any:
    """Severity from ₹/day profit impact. Loss = |negative impact|:
    loss > SEVERITY_HIGH_IMPACT → "high"; > SEVERITY_MEDIUM_IMPACT → "medium"; else "low".
    Positive impacts are always "low". Unit: label."""
    return _map(_severity_scalar, profit_impact)


def neuron_size(spend: Any, min_spend: float, max_spend: float) -> Any:
    """Size = NEURON_SIZE_MIN + (spend - min) / (max - min) * (NEURON_SIZE_MAX - NEURON_SIZE_MIN), clipped.
    If min == max → midpoint. Unit: relative node size."""
    lo, hi = config.NEURON_SIZE_MIN, config.NEURON_SIZE_MAX
    mid = (lo + hi) / 2.0
    if _missing(min_spend) or _missing(max_spend) or max_spend == min_spend:
        if _is_vector(spend):
            return pd.Series(mid, index=_as_series(spend).index, dtype="float64")
        return mid
    span = float(max_spend) - float(min_spend)
    if _is_vector(spend):
        s = _as_series(spend).astype("float64")
        return (lo + (s - min_spend) / span * (hi - lo)).clip(lo, hi).fillna(lo)
    if _missing(spend):
        return lo
    return float(min(hi, max(lo, lo + (float(spend) - min_spend) / span * (hi - lo))))


def _format_inr_scalar(value: Any) -> str:
    if _missing(value):
        return "—"
    v = float(value)
    if not math.isfinite(v):
        return "—"
    sign = "-" if v < 0 else ""
    a = abs(v)
    if a >= 1e7:
        body = f"{a / 1e7:.2f}Cr"
    elif a >= 1e5:
        body = f"{a / 1e5:.2f}L"
    elif a >= 1e3:
        body = f"{a / 1e3:.1f}k"
    else:
        body = f"{a:.0f}"
    return f"{sign}₹{body}"


def format_inr(value: Any) -> Any:
    """Display ₹: crores "₹1.20Cr", lakhs "₹1.23L", thousands "₹12.3k", below 1000 "₹850".
    Negatives "-₹12.3k"; None/NaN → "—". Unit: display string (UI only, never stored)."""
    return _map(_format_inr_scalar, value)
