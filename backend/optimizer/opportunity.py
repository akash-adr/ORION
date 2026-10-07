"""M5b pre-spend opportunity scorer: which untested product × channel × audience combos are worth a test budget?

Model (log-additive, so effects multiply on the original scale and predictions can never go negative):
    log(orders per ₹1,000) = β·log(spend) + γ·rating + channel effect + audience effect
Features are product ATTRIBUTES (rating), channel and audience, never SKU ids, so the model can score a
combination it has never seen. Ridge regression keeps 7 correlated one-hot effects from over-fitting 16 campaigns.

Honest validation: GroupKFold grouped by campaign_id holds out WHOLE campaigns, which is exactly the "never seen
before" situation. A random KFold would leak each campaign's identity across folds and flatter the R². The expected
hold-out R² is low (≈ 0.16): this is a ranking signal for where to test first, not a precise forecast.

Scoring: predicted_poas = orders per ₹1k ÷ 1000 × unit margin; score = predicted_poas × stock factor. SKUs that are
about to sell out (cover < STOCK_COVER_RISK_DAYS) score 0 and drop out, so we never recommend buying demand we
cannot fulfil.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.metrics import r2_score
from sklearn.model_selection import GroupKFold

from backend.core.config import (
    AUDIENCES, CHANNEL_DISPLAY, CHANNELS, CV_FOLDS, OPP_GHOST_N, OPP_TEST_BUDGET, OPP_TOP_N, RIDGE_ALPHA,
    STOCK_COVER_RISK_DAYS, STOCK_FACTOR_MAX, STOCK_FACTOR_MIN, STOCK_FACTOR_PIVOT,
)
from backend.core.db import read_table
from backend.core.schema import Opportunity

TARGET_OFFSET = 0.5  # (orders + 0.5) avoids log(0) on zero-order days
FEATURE_NAMES = ["log_spend", "rating"] + [f"channel={c}" for c in CHANNELS] + [f"audience={a}" for a in AUDIENCES]


def _features(df: pd.DataFrame) -> np.ndarray:
    """Design matrix from columns spend, rating, channel, audience: log(spend), rating, one-hot channel and audience."""
    cols = [np.log(df["spend"].to_numpy(float)), df["rating"].to_numpy(float)]
    cols += [(df["channel"] == c).to_numpy(float) for c in CHANNELS]
    cols += [(df["audience"] == a).to_numpy(float) for a in AUDIENCES]
    return np.column_stack(cols)


def training_frame() -> pd.DataFrame:
    """Every campaign-day with spend > 0, with the SKU's rating and the target y = log((orders + 0.5) ÷ spend × 1000)."""
    fact, sku = read_table("fact_daily"), read_table("dim_sku")[["sku_id", "rating"]]
    df = fact[fact["spend"] > 0].merge(sku, on="sku_id", how="left").sort_values(["campaign_id", "date"]).reset_index(drop=True)
    df["y"] = np.log((df["orders"] + TARGET_OFFSET) / df["spend"] * 1000.0)
    return df


def cv_splits(df: pd.DataFrame, n_splits: int = CV_FOLDS):
    """GroupKFold splits grouped by campaign_id: no campaign is ever in both train and test of a fold."""
    return list(GroupKFold(n_splits=n_splits).split(df, groups=df["campaign_id"]))


def train() -> dict:
    """Cross-validate (GroupKFold by campaign), then fit the final Ridge on all rows.

    Returns {model, r2_holdout, r2_folds, n_rows, n_features, features, coefficients, intercept, alpha, cv}.
    """
    df = training_frame()
    x, y = _features(df), df["y"].to_numpy(float)
    folds = []
    for tr, te in cv_splits(df):
        fold_model = Ridge(alpha=RIDGE_ALPHA).fit(x[tr], y[tr])
        folds.append(float(r2_score(y[te], fold_model.predict(x[te]))))
    model = Ridge(alpha=RIDGE_ALPHA).fit(x, y)
    return {
        "model": model, "r2_holdout": float(np.mean(folds)), "r2_folds": folds, "n_rows": int(len(df)),
        "n_features": len(FEATURE_NAMES), "features": FEATURE_NAMES,
        "coefficients": {n: float(c) for n, c in zip(FEATURE_NAMES, model.coef_)}, "intercept": float(model.intercept_),
        "alpha": RIDGE_ALPHA, "cv": f"GroupKFold({CV_FOLDS}) by campaign_id",
    }


def stock_factor(cover: float) -> float:
    """0 if cover < STOCK_COVER_RISK_DAYS, else clip(cover ÷ STOCK_FACTOR_PIVOT, STOCK_FACTOR_MIN, STOCK_FACTOR_MAX)."""
    if cover < STOCK_COVER_RISK_DAYS:
        return 0.0
    return float(np.clip(cover / STOCK_FACTOR_PIVOT, STOCK_FACTOR_MIN, STOCK_FACTOR_MAX))


def scored_rows(top_n: int = OPP_TOP_N, trained: dict | None = None) -> list[dict]:
    """The ranked opportunities as dicts: the M0 Opportunity fields plus rank, sku_name, cluster, stock_factor,
    is_ghost and label (what persistence and the brain need)."""
    trained = trained or train()
    sku, camps, skud = read_table("dim_sku"), read_table("dim_campaign"), read_table("sku_daily")
    cover = skud[skud["date"] == skud["date"].max()].set_index("sku_id")["days_cover"]
    existing = set(zip(camps["sku_id"], camps["channel"], camps["audience"]))

    combos = [(r.sku_id, ch, aud) for r in sku.itertuples() for ch in CHANNELS for aud in AUDIENCES
              if (r.sku_id, ch, aud) not in existing]  # only combinations we have never run
    frame = pd.DataFrame(combos, columns=["sku_id", "channel", "audience"]).merge(
        sku[["sku_id", "name", "rating", "price", "cogs"]], on="sku_id")
    frame["spend"] = float(OPP_TEST_BUDGET)
    pred = trained["model"].predict(_features(frame))
    # undo the +0.5 offset in the target: orders per ₹1k = exp(ŷ) − 0.5 ÷ spend × 1000
    frame["orders_per_1k"] = np.maximum(np.exp(pred) - TARGET_OFFSET / OPP_TEST_BUDGET * 1000.0, 0.0)
    frame["unit_margin"] = frame["price"] - frame["cogs"]
    frame["predicted_poas"] = frame["orders_per_1k"] / 1000.0 * frame["unit_margin"]
    frame["stock_days"] = frame["sku_id"].map(cover).astype(float)
    frame["stock_factor"] = frame["stock_days"].map(stock_factor)
    frame["score"] = frame["predicted_poas"] * frame["stock_factor"]

    frame = frame[frame["score"] > 0]  # drops SKUs about to sell out
    frame = frame.sort_values(["score", "sku_id", "channel"], ascending=[False, True, True])
    frame = frame.drop_duplicates(["sku_id", "channel"], keep="first").head(top_n)  # best audience per SKU × channel
    rows = []
    for rank, r in enumerate(frame.itertuples(), start=1):
        rows.append({
            "rank": rank, "sku_id": r.sku_id, "sku_name": r.name, "channel": r.channel, "audience": r.audience,
            "cluster": r.channel, "predicted_conv_per_1k": float(r.orders_per_1k), "predicted_poas": float(r.predicted_poas),
            "unit_margin": float(r.unit_margin), "stock_days": float(r.stock_days), "stock_factor": float(r.stock_factor),
            "score": float(r.score), "test_budget": float(OPP_TEST_BUDGET), "is_ghost": rank <= OPP_GHOST_N,
            "label": f"{r.name} · {CHANNEL_DISPLAY[r.channel]} · {r.audience}",
        })
    return rows


def score_opportunities(top_n: int = OPP_TOP_N, trained: dict | None = None) -> list[Opportunity]:
    """The ranked opportunities as M0 `Opportunity` objects (exact fields), best first."""
    fields = ("sku_id", "channel", "audience", "predicted_conv_per_1k", "predicted_poas", "unit_margin", "stock_days",
              "score", "test_budget")
    return [Opportunity(**{k: r[k] for k in fields}) for r in scored_rows(top_n, trained)]
