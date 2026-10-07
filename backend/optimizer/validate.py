"""M5 / M5b validation. Run from the project root:  python -m backend.optimizer.validate

Runs the optimizer pipeline and prints a PASS / WARN / FAIL table; exit 1 on any FAIL (WARN does not fail).
Each check is `check_*(ctx) -> (status, detail)` with status True (PASS), False (FAIL) or "WARN".
"""
from __future__ import annotations

import json
import math
import sys
import time
from typing import Callable

import numpy as np

from backend.core import config
from backend.core.config import (
    CHANNELS, CURVE_B_MAX_MULT, CURVE_B_MIN_MULT, CURVE_POINTS, CV_FOLDS, DAILY_CHANGE_CAP, LAUNCH_TEST_RESERVE,
    OBJECTIVES, OPP_GHOST_N, OPP_TOP_N, SIMULATE_MAX_MS, STOCK_COVER_RISK_DAYS, STOCK_SPEND_CAP_MULT,
)
from backend.core.db import read_table, validate_table
from backend.optimizer.curves import fit_curves, unanchored_marginal
from backend.optimizer.optimize import channel_simulate, optimize, simulate
from backend.optimizer.runner import run_optimizer

FIXED_AS_OF = "2026-10-06T23:00:00"
LOSS_MAKERS = ("CMP-11", "CMP-12", "CMP-15", "CMP-16")
SCALE_CANDIDATES = ("CMP-06", "CMP-07")
LOW_STOCK_CAMPAIGNS = ("CMP-03", "CMP-04", "CMP-05")
ROUND_TOL = 10.5  # ₹: plans are rounded to ₹10
NEW_TABLES = ("curves", "budget_plans", "plan_summaries", "opportunities", "model_metrics")


def build_context() -> dict:
    s = run_optimizer(as_of=FIXED_AS_OF, verbose=False)
    return {"summary": s, "curves": s["_curves"].set_index("campaign_id"), "results": s["_results"], "rows": s["_rows"],
            "trained": s["_trained"], "tables": {t: read_table(t) for t in NEW_TABLES}}


def _rows(r):
    return {c["campaign_id"]: c for c in r["campaigns"]}


# ---------------------------------------------------------------------------
def check_curves(ctx):
    c, fact = ctx["curves"], read_table("fact_daily")
    mean_spend = fact.groupby("campaign_id")["spend"].mean()
    bad = [cid for cid, r in c.iterrows() if not (r["a"] > 0 and CURVE_B_MIN_MULT * mean_spend[cid] * 0.999 <= r["b"]
                                                  <= CURVE_B_MAX_MULT * mean_spend[cid] * 1.001
                                                  and 0 <= r["uncertainty"] <= 2)]
    return len(c) == 16 and not bad, f"{len(c)} curves, a > 0, b within bounds, uncertainty in [0, 2]" + (f" · bad {bad}" if bad else "")


def check_loss_makers(ctx):
    mp = {k: ctx["curves"].at[k, "marginal_poas"] for k in LOSS_MAKERS}
    return all(v < 1 for v in mp.values()), ", ".join(f"{k} {v:.2f}" for k, v in mp.items())


def check_scale_candidates(ctx):
    c = ctx["curves"]
    mp = {k: c.at[k, "marginal_poas"] for k in SCALE_CANDIDATES}
    if all(v > 1 for v in mp.values()):
        return True, ", ".join(f"{k} {v:.2f}" for k, v in mp.items())
    parts = []
    for k in SCALE_CANDIDATES:
        u = unanchored_marginal(k)
        parts.append(f"{k}: a={c.at[k, 'a']:,.0f} b={c.at[k, 'b']:,.0f} gm_7d={c.at[k, 'gm_7d']:,.0f} spend_7d={c.at[k, 'spend_7d']:,.0f} "
                     f"marginal={mp[k]:.2f} (un-anchored {u['marginal_poas_unanchored']:.2f})")
    return "WARN", " | ".join(parts)


def check_max_profit_improves(ctx):
    d = ctx["results"]["max_profit"]["summary"]["profit_delta"]
    return d > 0, f"max_profit profit_delta {d:+,.0f}/day"


def check_no_low_stock_increase(ctx):
    bad = [(o, k) for o, r in ctx["results"].items() for k, c in _rows(r).items()
           if c["days_cover"] < STOCK_COVER_RISK_DAYS and c["planned_spend"] > c["current_spend"] + 1e-6]
    return not bad, "no objective increases spend on a low-stock SKU's campaigns" if not bad else f"increases: {bad}"


def check_change_cap(ctx):
    """±DAILY_CHANGE_CAP except overstock_boost (clear_inventory) and stock_guard (held at STOCK_SPEND_CAP_MULT × current)."""
    bad = []
    for o, r in ctx["results"].items():
        for k, c in _rows(r).items():
            reasons, cur, new = c["bound_reasons"], c["current_spend"], c["planned_spend"]
            if "stock_guard" in reasons:
                ok = new <= cur * STOCK_SPEND_CAP_MULT + ROUND_TOL
            elif "overstock_boost" in reasons:
                ok = new <= cur * config.OVERSTOCK_UPPER_MULT + ROUND_TOL and new >= cur * (1 - DAILY_CHANGE_CAP) - ROUND_TOL
            else:
                ok = abs(new - cur) <= cur * DAILY_CHANGE_CAP + ROUND_TOL
            if not ok:
                bad.append((o, k))
    return not bad, "every plan within ±50% (stock-guarded campaigns held at 40% of current; overstock boost to 2×)" if not bad else f"out of bounds: {bad}"


def check_budget(ctx):
    bad = []
    for o, r in ctx["results"].items():
        cap = r["total_budget"] * (1 - (LAUNCH_TEST_RESERVE if o == "launch_sku" else 0))
        if r["summary"]["planned"]["spend"] > cap + 1e-6:
            bad.append(o)
    return not bad, "Σ planned spend ≤ budget for every objective (launch_sku ≤ 95%)" if not bad else f"over budget: {bad}"


def check_revenue_target(ctx):
    s = ctx["results"]["revenue_target"]["summary"]
    return s["planned"]["profit"] >= s["current"]["profit"] - 1.0, (
        f"profit {s['current']['profit']:+,.0f} → {s['planned']['profit']:+,.0f}; revenue Δ {s['revenue_delta']:+,.0f}")


def check_clear_inventory(ctx):
    a, b = ctx["results"]["clear_inventory"]["plan"]["CMP-14"], ctx["results"]["max_profit"]["plan"]["CMP-14"]
    return a >= b, f"Kids Glow (CMP-14): clear_inventory {a:,.0f} vs max_profit {b:,.0f}"


def check_solvers(ctx):
    bad = [o for o, r in ctx["results"].items() if not r["solver"]["ok"]]
    return not bad, "all 4 objectives solved" if not bad else f"solver failed: {bad}"


def check_simulator(ctx):
    fit_curves()  # warm the cache
    t0 = time.perf_counter()
    simulate({"CMP-06": 12000.0})
    t_sim = (time.perf_counter() - t0) * 1000
    t0 = time.perf_counter()
    g = channel_simulate({"google": 1.2})
    t_ch = (time.perf_counter() - t0) * 1000
    ok = t_sim < SIMULATE_MAX_MS and t_ch < SIMULATE_MAX_MS and g["summary"]["profit_delta"] < 0
    return ok, f"simulate {t_sim:.1f} ms, channel_simulate {t_ch:.1f} ms, Google +20% profit {g['summary']['profit_delta']:+,.0f}/day"


def check_stock_warning(ctx):
    cur = ctx["curves"].at["CMP-03", "current_spend"]
    s = simulate({"CMP-03": cur * 1.2})["summary"]
    ok = "CMP-03" in s["stock_warnings"] and not simulate({"CMP-03": cur * 0.8})["summary"]["stock_warnings"]
    return ok, f"increase on CMP-03 flagged: {s['stock_warnings']}"


def check_opportunities(ctx):
    rows = ctx["rows"]
    camps = read_table("dim_campaign")
    existing = set(zip(camps["sku_id"], camps["channel"], camps["audience"]))
    errors = []
    if any((r["sku_id"], r["channel"], r["audience"]) in existing for r in rows):
        errors.append("matches an existing campaign")
    if any(r["stock_days"] < STOCK_COVER_RISK_DAYS for r in rows):
        errors.append("low-stock SKU present")
    scores = [r["score"] for r in rows]
    if scores != sorted(scores, reverse=True):
        errors.append("not sorted")
    if len(rows) > OPP_TOP_N or sum(r["is_ghost"] for r in rows) != min(OPP_GHOST_N, len(rows)):
        errors.append("count / ghosts")
    return not errors, f"{len(rows)} opportunities, {sum(r['is_ghost'] for r in rows)} ghosts, top: {rows[0]['label']}" if not errors else "; ".join(errors)


def check_model_metrics(ctx):
    t = ctx["tables"]["model_metrics"].iloc[0]
    folds = json.loads(t["r2_folds_json"])
    ok = "GroupKFold" in t["cv"] and f"({CV_FOLDS})" in t["cv"] and len(folds) == CV_FOLDS and not math.isnan(t["r2_holdout"])
    return ok, f"{t['cv']} · R² holdout {t['r2_holdout']:.3f} · folds {[round(x, 2) for x in folds]}"


def check_tables(ctx):
    errors = []
    for name, df in ctx["tables"].items():
        try:
            validate_table(df, name)
        except ValueError as exc:
            errors.append(str(exc))
    pts = [len(json.loads(p)) for p in ctx["tables"]["curves"]["points_json"]]
    if set(pts) != {CURVE_POINTS}:
        errors.append("curves.points_json size")
    return not errors, f"5 tables valid; {len(pts)} curves × {CURVE_POINTS} points" if not errors else "; ".join(errors)


def check_deterministic(ctx):
    def sig():
        s = run_optimizer(as_of=FIXED_AS_OF, verbose=False)
        return (s["_curves"].drop(columns=["flags"]).round(8).to_dict("records"),
                {o: r["plan"] for o, r in s["_results"].items()}, s["_rows"], s["r2_holdout"])
    return sig() == sig(), "two runs identical (curves, plans, opportunities, R²)"


CHECKS: list[tuple[str, Callable[[dict], tuple]]] = [
    ("1  16 curves in bounds", check_curves),
    ("2  loss-makers marginal < 1", check_loss_makers),
    ("3  CMP-06/07 marginal > 1", check_scale_candidates),
    ("4  max_profit improves", check_max_profit_improves),
    ("5  no low-stock increase", check_no_low_stock_increase),
    ("6  change cap", check_change_cap),
    ("7  budget respected", check_budget),
    ("8  revenue_target holds profit", check_revenue_target),
    ("9  clear_inventory boosts CMP-14", check_clear_inventory),
    ("10 solvers ok", check_solvers),
    ("11 simulator speed + sign", check_simulator),
    ("12 stock warning", check_stock_warning),
    ("13 opportunities", check_opportunities),
    ("14 model metrics (GroupKFold)", check_model_metrics),
    ("15 tables", check_tables),
    ("16 deterministic", check_deterministic),
]


def run_checks(ctx: dict) -> list[tuple[str, str, str]]:
    """[(name, "PASS" | "WARN" | "FAIL", detail)]."""
    results = []
    for name, fn in CHECKS:
        try:
            status, detail = fn(ctx)
        except Exception as exc:  # a crashing check is a failing check
            status, detail = False, f"error: {exc!r}"
        results.append((name, "WARN" if status == "WARN" else ("PASS" if status else "FAIL"), detail))
    return results


def main() -> int:
    results = run_checks(build_context())
    width = max(len(n) for n, _, _ in results)
    print(f"{'check'.ljust(width)}  result  detail")
    print("-" * (width + 70))
    for name, status, detail in results:
        print(f"{name.ljust(width)}  {status:<6}  {detail}")
    fails, warns = sum(s == "FAIL" for _, s, _ in results), sum(s == "WARN" for _, s, _ in results)
    print("-" * (width + 70))
    print(f"M5 validation: {len(results) - fails - warns}/{len(results)} PASS" + (f", {warns} WARN" if warns else "")
          + (f", {fails} FAIL" if fails else ""))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
