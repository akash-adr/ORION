"""M5 optimizer and what-if simulator: where does the next rupee earn the most?

Decision variables: the daily spend of each campaign. Each campaign's gross margin follows its fitted response
curve GM_i(s) = a·s ÷ (b + s) (see curves.py); contribution profit = GM − spend.

Bounds per campaign (see _bounds): a daily change cap (±DAILY_CHANGE_CAP), a stock guard (campaigns on SKUs with
fewer than STOCK_COVER_RISK_DAYS of cover are capped at STOCK_SPEND_CAP_MULT × current, increases blocked) and, for
clear_inventory only, an overstock boost (SKUs above OVERSTOCK_COVER_DAYS may grow to OVERSTOCK_UPPER_MULT ×).
Shared constraint: Σ spend ≤ budget B (default: today's total spend); under-spending is allowed.

Objectives (M0 OBJECTIVES):
  max_profit       maximise Σ (GM_i − s_i)
  revenue_target   maximise Σ rev_per_gm_i × GM_i, keeping total profit at least today's (or the best achievable)
  clear_inventory  maximise Σ (w_i × GM_i − s_i), w_i = 1 + clip((cover − 30) ÷ 30, 0, 1.5): push overstocked SKUs
  launch_sku       max_profit on (1 − LAUNCH_TEST_RESERVE) × B; the reserve is left for M5b tests

Solver: scipy SLSQP on spend ÷ current (well-scaled), with analytic gradients.
"""
from __future__ import annotations

import time

import numpy as np
from scipy.optimize import minimize

from backend.core import metrics as m
from backend.core.config import (
    CHANNELS, CLEAR_INV_MAX_BONUS, CLEAR_INV_PIVOT_DAYS, DAILY_CHANGE_CAP, LAUNCH_TEST_RESERVE, OBJECTIVES,
    OPTIMIZER_MAX_ITER, OVERSTOCK_COVER_DAYS, OVERSTOCK_UPPER_MULT, SIMULATE_MAX_MS, STOCK_COVER_RISK_DAYS,
    STOCK_SPEND_CAP_MULT,
)
from backend.optimizer.curves import fit_curves, hill, marginal_poas

ROUND_TO = 10  # plan values are rounded to ₹10
FTOL = 1e-6


# ---------------------------------------------------------------------------
# Bounds
# ---------------------------------------------------------------------------
def _bounds(row, objective: str) -> tuple[float, float, list[str]]:
    """(lo, hi, reasons) for one campaign row and objective.

    change cap: [cur × (1 − cap), cur × (1 + cap)]. Stock guard: hi = min(hi, cur × STOCK_SPEND_CAP_MULT) and
    lo = min(lo, hi), so demand is never pushed into a stockout (increases blocked). Overstock boost (clear_inventory
    only): hi = cur × OVERSTOCK_UPPER_MULT.
    """
    cur, cover = float(row["current_spend"]), float(row["days_cover"])
    lo, hi, reasons = cur * (1 - DAILY_CHANGE_CAP), cur * (1 + DAILY_CHANGE_CAP), ["change_cap"]
    if cover < STOCK_COVER_RISK_DAYS:
        hi = min(hi, cur * STOCK_SPEND_CAP_MULT)
        lo = min(lo, hi)
        reasons.append("stock_guard")
    elif objective == "clear_inventory" and cover > OVERSTOCK_COVER_DAYS:
        hi = cur * OVERSTOCK_UPPER_MULT
        reasons.append("overstock_boost")
    return lo, hi, reasons


def _inventory_weight(cover: np.ndarray) -> np.ndarray:
    """clear_inventory weight: 1 + clip((cover − pivot) ÷ pivot, 0, max bonus)."""
    return 1.0 + np.clip((cover - CLEAR_INV_PIVOT_DAYS) / CLEAR_INV_PIVOT_DAYS, 0.0, CLEAR_INV_MAX_BONUS)


def _summary_block(spend: np.ndarray, a: np.ndarray, b: np.ndarray, rpg: np.ndarray) -> dict:
    gm = hill(spend, a, b)
    return {"spend": float(spend.sum()), "gross_margin": float(gm.sum()), "revenue": float((rpg * gm).sum()),
            "profit": float((gm - spend).sum()), "poas": m.poas(float(gm.sum()), float(spend.sum()))}


# ---------------------------------------------------------------------------
# Solver
# ---------------------------------------------------------------------------
def _solve(objective: str, curves, budget: float, lo: np.ndarray, hi: np.ndarray, profit_floor: float | None):
    """Maximise the objective with SLSQP. Returns (spend vector, solver info dict)."""
    cur = curves["current_spend"].to_numpy(float)
    a, b, rpg = (curves[k].to_numpy(float) for k in ("a", "b", "rev_per_gm"))
    cover = curves["days_cover"].to_numpy(float)
    coef = {"revenue_target": rpg, "clear_inventory": _inventory_weight(cover)}.get(objective, np.ones_like(cur))
    lin = np.zeros_like(cur) if objective == "revenue_target" else np.ones_like(cur)
    norm = max(float(cur.sum()), 1.0)

    def f(x):
        s = x * cur
        return -(np.sum(coef * hill(s, a, b)) - np.sum(lin * s)) / norm

    def grad(x):
        s = x * cur
        return -(coef * marginal_poas(s, a, b) - lin) * cur / norm

    cons = [{"type": "ineq", "fun": lambda x: (budget - np.sum(cur * x)) / norm, "jac": lambda x: -cur / norm}]
    if profit_floor is not None:
        cons.append({"type": "ineq", "fun": lambda x: (np.sum(hill(x * cur, a, b) - x * cur) - profit_floor) / norm,
                     "jac": lambda x: (marginal_poas(x * cur, a, b) - 1.0) * cur / norm})
    bnds = list(zip(lo / cur, hi / cur))

    def run(x0):
        return minimize(f, x0, jac=grad, method="SLSQP", bounds=bnds, constraints=cons,
                        options={"maxiter": OPTIMIZER_MAX_ITER, "ftol": FTOL})

    res = run(np.clip(cur, lo, hi) / cur)
    if not res.success:
        res = run((lo + hi) / 2 / cur)  # one retry from the bounds midpoint
    s = np.clip(res.x * cur, lo, hi)
    if s.sum() > budget:  # best feasible point: scale the spend that is above the lower bounds down to the budget
        room = s - lo
        s = lo + room * max(0.0, (budget - lo.sum())) / max(room.sum(), 1e-9)
    return s, {"ok": bool(res.success), "iterations": int(res.nit), "message": str(res.message)}


def _round_plan(s: np.ndarray, lo: np.ndarray, hi: np.ndarray, budget: float) -> np.ndarray:
    """Round to ₹10 inside the bounds (lo rounded up, hi rounded down) and keep Σ ≤ budget."""
    lo10, hi10 = np.ceil(lo / ROUND_TO) * ROUND_TO, np.floor(hi / ROUND_TO) * ROUND_TO
    lo10 = np.minimum(lo10, hi10)  # a squeezed range (stock guard) takes its cap
    out = np.clip(np.round(s / ROUND_TO) * ROUND_TO, lo10, hi10)
    while out.sum() > budget + 1e-6:  # rounding must never break the budget
        i = int(np.argmax(out - lo10))
        if out[i] - ROUND_TO < lo10[i]:
            break
        out[i] -= ROUND_TO
    return out


def optimize(objective: str = "max_profit", total_budget: float | None = None) -> dict:
    """Reallocate budget for one objective. See the module docstring for the objectives and bounds."""
    if objective not in OBJECTIVES:
        raise ValueError(f"unknown objective {objective!r}; expected one of {OBJECTIVES}")
    curves = fit_curves()
    cur = curves["current_spend"].to_numpy(float)
    a, b, rpg = (curves[k].to_numpy(float) for k in ("a", "b", "rev_per_gm"))
    budget = float(total_budget) if total_budget is not None else float(cur.sum())
    reserved = LAUNCH_TEST_RESERVE * budget if objective == "launch_sku" else 0.0
    spendable = budget - reserved

    bounds = [_bounds(r, objective) for _, r in curves.iterrows()]
    lo, hi = np.array([x[0] for x in bounds]), np.array([x[1] for x in bounds])

    floor, floor_note = None, ""
    if objective == "revenue_target":
        today = float(np.sum(hill(cur, a, b) - cur))
        best, _ = _solve("max_profit", curves, spendable, lo, hi, None)
        best_profit = float(np.sum(hill(best, a, b) - best))
        # Hold today's profit, with a buffer for rounding the plan to ₹10 (at most ROUND_TO ÷ 2 per campaign), or the best
        # achievable profit if the guards make that impossible.
        buffer = len(cur) * ROUND_TO / 2
        floor = min(today + buffer, best_profit - 1.0)
        if floor < today:
            floor_note = f" (profit floor lowered from {today:,.0f} to the best achievable {floor:,.0f})"
    s, solver = _solve(objective, curves, spendable, lo, hi, floor)
    plan = _round_plan(s, lo, hi, spendable)
    solver["message"] += floor_note

    rows = []
    for i, (_, r) in enumerate(curves.iterrows()):
        reasons = bounds[i][2]
        rows.append({
            "campaign_id": r["campaign_id"], "name": r["name"], "channel": r["channel"], "sku_id": r["sku_id"],
            "current_spend": round(float(cur[i]), 2), "planned_spend": float(plan[i]),
            "change_pct": round(float(plan[i] / cur[i] - 1.0), 4),
            "current_profit": round(float(hill(cur[i], a[i], b[i]) - cur[i]), 2),
            "planned_profit": round(float(hill(plan[i], a[i], b[i]) - plan[i]), 2),
            "marginal_poas_current": round(float(marginal_poas(cur[i], a[i], b[i])), 4),
            "marginal_poas_planned": round(float(marginal_poas(plan[i], a[i], b[i])), 4),
            "bound_reasons": reasons, "days_cover": float(r["days_cover"]),
            "stock_locked": "stock_guard" in reasons,
        })
    now, planned = _summary_block(cur, a, b, rpg), _summary_block(plan, a, b, rpg)
    out = {
        "objective": objective, "total_budget": round(budget, 2),
        "plan": {r["campaign_id"]: r["planned_spend"] for r in rows},
        "summary": {"current": now, "planned": planned, "profit_delta": planned["profit"] - now["profit"],
                    "revenue_delta": planned["revenue"] - now["revenue"], "spend_delta": planned["spend"] - now["spend"]},
        "campaigns": rows, "solver": solver,
    }
    if objective == "launch_sku":
        out["reserved_test_budget"] = round(reserved, 2)
    return out


# ---------------------------------------------------------------------------
# Simulator
# ---------------------------------------------------------------------------
def simulate(plan: dict) -> dict:
    """What-if: apply any {campaign_id: spend} plan (campaigns not in it keep their current spend)."""
    curves = fit_curves()
    unknown = sorted(set(plan) - set(curves["campaign_id"]))
    if unknown:
        raise ValueError(f"unknown campaign ids in plan: {unknown}")
    cur = curves["current_spend"].to_numpy(float)
    a, b, rpg = (curves[k].to_numpy(float) for k in ("a", "b", "rev_per_gm"))
    new = np.array([float(plan.get(cid, c)) for cid, c in zip(curves["campaign_id"], cur)])
    if (new < 0).any():
        raise ValueError("spend cannot be negative")
    gm0, gm1 = hill(cur, a, b), hill(new, a, b)
    cover = curves["days_cover"].to_numpy(float)
    warn = (new > cur + 1e-9) & (cover < STOCK_COVER_RISK_DAYS)
    rows = [{
        "campaign_id": cid, "name": nm, "channel": ch, "current_spend": round(float(cur[i]), 2),
        "new_spend": round(float(new[i]), 2), "current_profit": round(float(gm0[i] - cur[i]), 2),
        "new_profit": round(float(gm1[i] - new[i]), 2), "current_gross_margin": round(float(gm0[i]), 2),
        "new_gross_margin": round(float(gm1[i]), 2), "current_revenue": round(float(rpg[i] * gm0[i]), 2),
        "new_revenue": round(float(rpg[i] * gm1[i]), 2),
        "marginal_poas_current": round(float(marginal_poas(cur[i], a[i], b[i])), 4),
        "marginal_poas_new": round(float(marginal_poas(new[i], a[i], b[i])), 4), "stock_warning": bool(warn[i]),
    } for i, (cid, nm, ch) in enumerate(zip(curves["campaign_id"], curves["name"], curves["channel"]))]
    now, sim = _summary_block(cur, a, b, rpg), _summary_block(new, a, b, rpg)
    return {"summary": {"current": now, "simulated": sim, "profit_delta": sim["profit"] - now["profit"],
                        "revenue_delta": sim["revenue"] - now["revenue"], "spend_delta": sim["spend"] - now["spend"],
                        "stock_warnings": [r["campaign_id"] for r in rows if r["stock_warning"]]},
            "campaigns": rows}


def channel_simulate(multipliers: dict) -> dict:
    """What-if by channel: {"google": 1.2} scales every Google campaign's spend by 1.2, then simulates."""
    unknown = sorted(set(multipliers) - set(CHANNELS))
    if unknown:
        raise ValueError(f"unknown channels {unknown}; expected a subset of {CHANNELS}")
    curves = fit_curves()
    plan = {r["campaign_id"]: r["current_spend"] * multipliers[r["channel"]]
            for _, r in curves.iterrows() if r["channel"] in multipliers}
    return simulate(plan)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def objective_table(results: dict[str, dict]) -> list[str]:
    lines = [f"{'objective':<17}{'spend/day':>11}{'revenue/day':>13}{'profit/day':>12}{'POAS':>7}{'profit Δ':>11}  solver"]
    for obj, r in results.items():
        p = r["summary"]["planned"]
        lines.append(f"{obj:<17}{m.format_inr(p['spend']):>11}{m.format_inr(p['revenue']):>13}{m.format_inr(p['profit']):>12}"
                     f"{p['poas']:>7.2f}{m.format_inr(r['summary']['profit_delta']):>11}  {'ok' if r['solver']['ok'] else 'FAILED'}")
    return lines


def print_curves(curves) -> None:
    print(f"{'campaign':<9}{'current':>10}{'marg. POAS':>12}{'saturation':>12}{'optimal':>10}{'uncert.':>9}  flags")
    for _, r in curves.iterrows():
        print(f"{r['campaign_id']:<9}{m.format_inr(r['current_spend']):>10}{r['marginal_poas']:>12.2f}"
              f"{m.format_inr(r['saturation_spend']):>12}{m.format_inr(r['optimal_spend']):>10}{r['uncertainty']:>9.2f}  "
              f"{','.join(r['flags']) or '—'}")


def print_plan(r: dict) -> None:
    print(f"{'campaign':<9}{'name':<42}{'current':>10}{'planned':>10}{'change':>9}  bound reasons")
    for c in sorted(r["campaigns"], key=lambda c: c["change_pct"]):
        print(f"{c['campaign_id']:<9}{c['name']:<42}{m.format_inr(c['current_spend']):>10}"
              f"{m.format_inr(c['planned_spend']):>10}{c['change_pct']:>+9.0%}  {', '.join(c['bound_reasons'])}")


def main() -> None:
    curves = fit_curves(refresh=True)
    print("RESPONSE CURVES (marginal POAS at current spend)")
    print_curves(curves)
    results = {obj: optimize(obj) for obj in OBJECTIVES}
    print("\nOBJECTIVES")
    print("\n".join(objective_table(results)))
    print("\nMAX_PROFIT PLAN")
    print_plan(results["max_profit"])
    t0 = time.perf_counter()
    sim = channel_simulate({"google": 1.2})
    ms = (time.perf_counter() - t0) * 1000
    s = sim["summary"]
    print(f"\nGOOGLE +20%: spend {m.format_inr(s['spend_delta'])}/day · revenue {m.format_inr(s['revenue_delta'])}/day · "
          f"profit {m.format_inr(s['profit_delta'])}/day · {ms:.1f} ms")
    print(f"\nM5 OK · {len(curves)} curves · {len(results)} objectives · max_profit "
          f"{m.format_inr(results['max_profit']['summary']['profit_delta'])}/day · simulate {ms:.0f}ms")


if __name__ == "__main__":
    main()
