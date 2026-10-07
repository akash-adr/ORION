"""M5 / M5b entry point: fit curves → optimise every objective → score opportunities → persist, brain-ready.

DESIGN NOTE: M5 emits NO brain events. It produces analysis; M6 turns the max_profit plan, the opportunities and the
anomalies into Recommendations and emits the "recommendation" pulses into the Decide lobe. This module never writes
state.json (it only reads budget_overrides to know the current spend).

The tables below are what the brain (via M9) renders:
  curves.headroom          halo on campaign neurons: scale = outward glow, cut = dim inward ring, hold = none, locked = lock icon
  budget_plans             planned-change arrows on neurons (change_pct) for the objective chosen in settings (default max_profit)
  opportunities (is_ghost) dashed ghost neurons in cluster = channel, linked by a dashed synapse to the SKU neuron
  plan_summaries           before / after headline ("current profit → planned profit per day")
  model_metrics.r2_holdout honesty badge on the Opportunities panel
"""
from __future__ import annotations

import json
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from backend.core import metrics as m
from backend.core.config import (
    HEADROOM_CUT_POAS, HEADROOM_SCALE_POAS, OBJECTIVES, OPP_GHOST_N, STOCK_COVER_RISK_DAYS,
)
from backend.core.db import TABLE_COLUMNS, validate_table, write_table
from backend.optimizer import opportunity as opp
from backend.optimizer.curves import curve_points, fit_curves
from backend.optimizer.optimize import objective_table, optimize, print_curves, print_plan, channel_simulate


def now_ist() -> str:
    """Current IST time as "YYYY-MM-DDTHH:MM:SS"."""
    return datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%dT%H:%M:%S")


def headroom(marginal_poas: float, days_cover: float) -> str:
    """locked (stock guard) regardless of POAS; else scale if marginal POAS > 1.1, cut if < 0.9, otherwise hold."""
    if days_cover < STOCK_COVER_RISK_DAYS:
        return "locked"
    if marginal_poas > HEADROOM_SCALE_POAS:
        return "scale"
    if marginal_poas < HEADROOM_CUT_POAS:
        return "cut"
    return "hold"


def curves_frame(curves: pd.DataFrame, fitted_at: str) -> pd.DataFrame:
    df = curves.copy()
    df["headroom"] = [headroom(r.marginal_poas, r.days_cover) for r in df.itertuples()]
    df["points_json"] = [json.dumps(curve_points(r)) for _, r in df.iterrows()]
    df["flags"] = df["flags"].map(",".join)
    df["fitted_at"] = fitted_at
    return df[TABLE_COLUMNS["curves"]]


def plans_frames(results: dict[str, dict], planned_at: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    plan_rows, sum_rows = [], []
    for obj, r in results.items():
        for c in r["campaigns"]:
            plan_rows.append({
                "objective": obj, "campaign_id": c["campaign_id"], "current_spend": c["current_spend"],
                "planned_spend": c["planned_spend"], "change_pct": c["change_pct"], "current_profit": c["current_profit"],
                "planned_profit": c["planned_profit"], "marginal_poas_current": c["marginal_poas_current"],
                "marginal_poas_planned": c["marginal_poas_planned"], "bound_reasons": ",".join(c["bound_reasons"]),
                "stock_locked": c["stock_locked"], "solver_ok": r["solver"]["ok"], "planned_at": planned_at})
        s = r["summary"]
        sum_rows.append({
            "objective": obj, "current_spend": s["current"]["spend"], "planned_spend": s["planned"]["spend"],
            "current_profit": s["current"]["profit"], "planned_profit": s["planned"]["profit"],
            "profit_delta": s["profit_delta"], "current_revenue": s["current"]["revenue"],
            "planned_revenue": s["planned"]["revenue"], "revenue_delta": s["revenue_delta"],
            "current_poas": s["current"]["poas"], "planned_poas": s["planned"]["poas"],
            "reserved_test_budget": r.get("reserved_test_budget", 0.0), "solver_ok": r["solver"]["ok"],
            "planned_at": planned_at})
    return (pd.DataFrame(plan_rows, columns=TABLE_COLUMNS["budget_plans"]),
            pd.DataFrame(sum_rows, columns=TABLE_COLUMNS["plan_summaries"]))


def run_optimizer(as_of: str | None = None, verbose: bool = True) -> dict:
    """Run the whole M5 / M5b pipeline and persist the five tables. Emits no brain events (see the module docstring)."""
    start = time.perf_counter()
    as_of = as_of or now_ist()
    curves = fit_curves(refresh=True)
    results = {obj: optimize(obj) for obj in OBJECTIVES}
    trained = opp.train()
    rows = opp.scored_rows(trained=trained)

    cdf = curves_frame(curves, as_of)
    plans, summaries = plans_frames(results, as_of)
    odf = pd.DataFrame([{**r, "scored_at": as_of} for r in rows], columns=TABLE_COLUMNS["opportunities"])
    mdf = pd.DataFrame([{
        "model": "ridge", "target": "log(orders per ₹1k spend)", "n_rows": trained["n_rows"],
        "n_features": trained["n_features"], "cv": trained["cv"], "r2_holdout": trained["r2_holdout"],
        "r2_folds_json": json.dumps(trained["r2_folds"]), "alpha": trained["alpha"],
        "features_json": json.dumps({**trained["coefficients"], "intercept": trained["intercept"]}),
        "trained_at": as_of}], columns=TABLE_COLUMNS["model_metrics"])
    for name, df in (("curves", cdf), ("budget_plans", plans), ("plan_summaries", summaries),
                     ("opportunities", odf), ("model_metrics", mdf)):
        validate_table(df, name)
        write_table(df, name)

    summary = {
        "curves": int(len(cdf)), "headroom": cdf["headroom"].value_counts().reindex(["scale", "hold", "cut", "locked"],
                                                                                       fill_value=0).to_dict(),
        "objectives": {o: r["summary"]["profit_delta"] for o, r in results.items()},
        "opportunities": len(rows), "ghosts": sum(r["is_ghost"] for r in rows), "r2_holdout": trained["r2_holdout"],
        "duration_ms": round((time.perf_counter() - start) * 1000, 1),
        "_curves": curves, "_results": results, "_rows": rows, "_trained": trained,
    }
    if verbose:
        print_run(summary)
    return summary


def print_opportunities(rows: list[dict], trained: dict) -> None:
    print(f"{'#':<3}{'opportunity':<44}{'ord/₹1k':>9}{'pred. POAS':>11}{'stock days':>11}{'score':>7}  ghost")
    for r in rows:
        print(f"{r['rank']:<3}{r['label']:<44}{r['predicted_conv_per_1k']:>9.2f}{r['predicted_poas']:>11.2f}"
              f"{r['stock_days']:>11.0f}{r['score']:>7.2f}  {'●' if r['is_ghost'] else ''}")
    print(f"R² holdout = {trained['r2_holdout']:.2f} (GroupKFold by campaign; folds "
          f"{', '.join(f'{x:.2f}' for x in trained['r2_folds'])})")


def print_run(s: dict) -> None:
    """Everything from the M5 CLI, plus headroom counts and the opportunity table."""
    print("RESPONSE CURVES (marginal POAS at current spend)")
    print_curves(s["_curves"])
    print(f"headroom: {s['headroom']}")
    print("\nOBJECTIVES")
    print("\n".join(objective_table(s["_results"])))
    print("\nMAX_PROFIT PLAN")
    print_plan(s["_results"]["max_profit"])
    t0 = time.perf_counter()
    g = channel_simulate({"google": 1.2})["summary"]
    print(f"\nGOOGLE +20%: spend {m.format_inr(g['spend_delta'])}/day · profit {m.format_inr(g['profit_delta'])}/day · "
          f"{(time.perf_counter() - t0) * 1000:.1f} ms")
    print(f"\nOPPORTUNITIES (untested combos, scored before any spend; top {OPP_GHOST_N} become ghost neurons)")
    print_opportunities(s["_rows"], s["_trained"])
    print(f"\nM5b OK · {s['curves']} curves · {s['opportunities']} opportunities ({s['ghosts']} ghosts) · "
          f"R² holdout {s['r2_holdout']:.2f} · max_profit {m.format_inr(s['objectives']['max_profit'])}/day · "
          f"{s['duration_ms']:.0f} ms")


def main() -> None:
    run_optimizer()


if __name__ == "__main__":
    main()
