"""M6 recommendation builder: the Neural Brain's "Decide" lobe.

Turns M3 alerts, M4 causes, M5 budget plans and M5b opportunities into ranked, executable decisions in the M0
`Recommendation` shape, each with a calibrated ₹/day impact, confidence, risk, approval tier and block status.

Run from the project root:  python -m backend.decisions.engine

This module BUILDS recommendations only. It does not save state, execute, audit, roll back or emit brain events
(that is the next step: merge with state, executor, rollback, autopilot and the "recommendation" pulses).

Rules are processed in a fixed order, 1 → 10. A COVERED set guarantees a campaign appears in only ONE
recommendation's budget changes, so the earlier (more specific, more urgent) rule wins a conflict.

Titles are STABLE: built only from entity names and fixed wording (never ₹ amounts or counts), because a
recommendation's id is the md5 of its title and must survive refreshes.
"""
from __future__ import annotations

import time

import numpy as np
import pandas as pd

from backend.core import metrics as m
from backend.core.config import (
    AUTO_APPLY_MAX_SHIFT, CHANNEL_DISPLAY, CONF_BASE, CONF_MAPE_WEIGHT, CONF_UNC_WEIGHT, CONF_Z_CAP, CONF_Z_WEIGHT,
    CONFIDENCE_MAX, CONFIDENCE_MIN, DEFAULT_OBJECTIVE, OBJECTIVES, OPP_IMPACT_HAIRCUT, OPP_LAUNCH_N, OPP_TEST_BUDGET,
    PLAN_CUT_THRESHOLD, PLAN_SCALE_THRESHOLD, POSITIVE_SCALE_UP, RISK_HIGH_IMPACT, RISK_HIGH_SHIFT, RISK_MEDIUM_SHIFT,
    STOCK_COVER_RISK_DAYS, STOCKOUT_AD_CUT, STOCKOUT_HORIZON_DAYS, URGENCY_BONUS,
)
from backend.core.db import load_state, read_table
from backend.core.schema import Anomaly, Recommendation
from backend.detection.detectors import detect_all
from backend.detection.store import anomaly_key, load_manifest
from backend.diagnosis.causal import compute_causal
from backend.diagnosis.decompose import diagnose_all
from backend.optimizer import opportunity as opp
from backend.optimizer.curves import fit_curves, hill
from backend.optimizer.optimize import _bounds, optimize

ROUND_TO = 10  # budgets are proposed in ₹10 steps
MIN_CHANGE = 0.5  # ₹: smaller moves are not worth a recommendation line
CREATIVE_SUGGESTION = "UGC testimonial variant"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _profit_at(row, s: float) -> float:
    """Contribution profit of a campaign at daily spend s on its response curve: hill(s, a, b) − s."""
    return float(hill(s, row["a"], row["b"]) - s)


def _curve_delta(curves: pd.DataFrame, changes: list[dict]) -> float:
    """₹/day profit change of a set of budget changes: Σ profit_at(new) − profit_at(current)."""
    return float(sum(_profit_at(curves.loc[c["campaign_id"]], c["to_budget"]) - _profit_at(curves.loc[c["campaign_id"]], c["from_budget"])
                   for c in changes))


def _confidence(z: float, uncertainty: float, mape: float | None) -> float:
    """clip((base + z weight × min(|z|, cap) − uncertainty weight × curve uncertainty) × (1 − MAPE weight × MAPE), min, max).

    A stronger signal earns confidence, a poorly-determined curve loses it, and once M7 has measured how wrong
    we were (MAPE) every confidence is scaled down by that error. MAPE None counts as 0.
    """
    raw = (CONF_BASE + CONF_Z_WEIGHT * min(abs(z), CONF_Z_CAP) - CONF_UNC_WEIGHT * uncertainty) * (1 - CONF_MAPE_WEIGHT * (mape or 0.0))
    return float(np.clip(raw, CONFIDENCE_MIN, CONFIDENCE_MAX))


def _shift(changes: list[dict], brand_total_spend: float) -> float:
    """Size of the budget move as a fraction: |Σ new − Σ current| ÷ Σ current of the changed campaigns.

    New campaigns (launch tests, current spend 0) use Σ new ÷ brand total spend; no budget changes → 0.
    """
    if not changes:
        return 0.0
    cur, new = sum(c["from_budget"] for c in changes), sum(c["to_budget"] for c in changes)
    if cur > 0:
        return abs(new - cur) / cur
    return new / brand_total_spend if brand_total_spend > 0 else 0.0


def _risk(shift: float, impact: float) -> str:
    """high if the move is bigger than RISK_HIGH_SHIFT or |impact| exceeds RISK_HIGH_IMPACT; medium above RISK_MEDIUM_SHIFT."""
    if shift > RISK_HIGH_SHIFT or abs(impact) > RISK_HIGH_IMPACT:
        return "high"
    return "medium" if shift > RISK_MEDIUM_SHIFT else "low"


def _requires_approval(risk: str, shift: float) -> bool:
    """Only a low-risk move smaller than AUTO_APPLY_MAX_SHIFT may be applied without a human."""
    return not (risk == "low" and shift < AUTO_APPLY_MAX_SHIFT)


def _blocked(changes: list[dict], curves: pd.DataFrame) -> bool:
    """True if any change RAISES spend on a campaign whose SKU has fewer than STOCK_COVER_RISK_DAYS of cover."""
    return any(c["to_budget"] > c["from_budget"] and curves.loc[c["campaign_id"], "days_cover"] < STOCK_COVER_RISK_DAYS
               for c in changes)


def _priority(impact: float, confidence: float, risk: str) -> float:
    """max(impact, 0) × confidence, plus URGENCY_BONUS for high-risk (urgent) items."""
    return max(impact, 0.0) * confidence + (URGENCY_BONUS if risk == "high" else 0.0)


def _stockout_value(gm0: float, s0: float, gm1: float, s1: float, cover: float) -> float:
    """₹/day value of cutting ads when stock is about to run out (over a STOCKOUT_HORIZON_DAYS horizon).

    Keeping ads: the stock sells out after `cover` days, then every rupee of spend lands on an empty page.
    Cutting ads: sales slow, so stock lasts longer (`last` days), and the wasted post-stockout spend shrinks.
    Returns (cut − keep) ÷ horizon: the money saved by not paying for clicks that cannot convert.
    """
    h = float(STOCKOUT_HORIZON_DAYS)
    cover = min(cover, h)
    keep = cover * (gm0 - s0) + (h - cover) * (-s0)
    last = h if (gm1 <= 0 or gm0 <= 0) else min(cover / (gm1 / gm0), h)
    cut = last * (gm1 - s1) + (h - last) * (-s1)
    return (cut - keep) / h


def _round_budget(x: float) -> float:
    return float(max(0.0, round(x / ROUND_TO) * ROUND_TO))


def _pct(x: float) -> str:
    return f"{round(abs(x) * 100):.0f}%"


# ---------------------------------------------------------------------------
# The builder
# ---------------------------------------------------------------------------
class _Builder:
    """Holds the inputs and the growing recommendation list; `add()` is where every number is derived."""

    def __init__(self, objective: str):
        self.objective = objective
        self.state = load_state()
        cal = self.state.get("calibration", {})
        self.factor = float(cal.get("factor") or 1.0)
        self.mape = cal.get("mape")  # None until M7 has measured accuracy → treated as 0
        self.curves = fit_curves().set_index("campaign_id")
        self.brand_total = float(self.curves["current_spend"].sum())
        self.plan_result = optimize(objective)
        self.plan = self.plan_result["plan"]
        self.sku_names = read_table("dim_sku").set_index("sku_id")["name"].to_dict()
        self.sources = {s["channel"]: s["id"] for s in load_manifest()["sources"] if s["kind"] == "ad_platform"}
        self.recs: list[Recommendation] = []
        self.covered: dict[str, str] = {}

    # --- inputs -------------------------------------------------------------------------------------------------
    def uncovered(self, mask) -> list[str]:
        """Campaign ids matching the mask that no recommendation has claimed yet."""
        return [cid for cid in self.curves.index[mask] if cid not in self.covered]

    def change(self, cid: str, to: float) -> dict:
        r = self.curves.loc[cid]
        return {"campaign_id": cid, "name": r["name"], "channel": r["channel"],
                "from_budget": round(float(r["current_spend"]), 2), "to_budget": _round_budget(to)}

    def plan_changes(self, cids: list[str], only: str = "any") -> list[dict]:
        """Changes moving each campaign to its optimizer plan. only: "cut" (plan < current), "scale" or "any"."""
        out = []
        for cid in cids:
            cur, new = float(self.curves.loc[cid, "current_spend"]), float(self.plan[cid])
            if only == "cut" and not new < cur - MIN_CHANGE:
                continue
            if only == "scale" and not new > cur + MIN_CHANGE:
                continue
            if only == "any" and abs(new - cur) <= MIN_CHANGE:
                continue
            out.append(self.change(cid, new))
        return out

    def mean_uncertainty(self, cids: list[str]) -> float:
        return float(self.curves.loc[cids, "uncertainty"].mean()) if cids else 1.0

    def targets(self, cids=(), cluster: str | None = None, skus=(), source: str | None = None, ghost: str | None = None) -> list[dict]:
        t = [{"type": "neuron", "id": s} for s in skus] + [{"type": "neuron", "id": c} for c in cids]
        if cluster:
            t.append({"type": "cluster", "id": cluster})
        if source:
            t.append({"type": "source", "id": source})
        if ghost:
            t.append({"type": "ghost", "id": ghost})
        return t

    # --- the one place numbers are derived ----------------------------------------------------------------------
    def add(self, title: str, issue: str, cause: str, action: dict, raw_impact: float, z: float, uncertainty: float,
            anomaly_id: str | None, evidence: list[str], shift: float | None = None) -> Recommendation:
        """Build one Recommendation, claim its campaigns, and append it. `shift` overrides the computed budget shift
        (launch tests have no changes but a known size)."""
        action = {"changes": [], "targets": [], "notes": [], **action}
        changes = action["changes"]
        impact = raw_impact * self.factor  # calibrated by what M7 has learned (default factor 1.0)
        shift = _shift(changes, self.brand_total) if shift is None else shift
        confidence = _confidence(z, uncertainty, self.mape)
        risk = _risk(shift, impact)
        rec = Recommendation(
            id=Recommendation.make_recommendation_id(title), title=title, issue=issue, cause=cause, action=action,
            expected_profit_delta=round(impact, 2), confidence=round(confidence, 4), risk=risk,
            requires_approval=_requires_approval(risk, shift), blocked=_blocked(changes, self.curves),
            priority=round(_priority(impact, confidence, risk), 2), evidence=evidence, anomaly_id=anomaly_id,
            status="pending")
        if any(r.id == rec.id for r in self.recs):
            raise ValueError(f"duplicate recommendation title {title!r}")
        for c in changes:
            self.covered[c["campaign_id"]] = rec.id
        self.recs.append(rec)
        return rec


def _issue(a: Anomaly) -> str:
    """One-line statement of the problem for the inbox."""
    d = a.detail
    return {
        "stockout_risk": lambda: f"{a.label}: {d['days_cover']:.1f} days of cover left while {m.format_inr(d['spend_per_day'])}/day of ads still run",
        "creative_fatigue": lambda: f"{a.label}: frequency {d['frequency_baseline']:.1f} → {d['frequency_recent']:.1f}, CTR {a.change_pct:+.0%}",
        "conversion_drop": lambda: f"{a.label}: site conversion {a.change_pct:+.0%}" + (f" after the price moved {_price(d['price_start'])} → {_price(d['price_end'])}" if d.get("price_change") else ""),
        "positive_spike": lambda: f"{a.label}: profit {a.change_pct:+.0%}, a winner worth scaling",
        "cpc_spike": lambda: f"{a.label}: clicks {a.change_pct:+.0%} more expensive",
        "metric_shift": lambda: f"{a.label}: profit {a.change_pct:+.0%}",
        "attribution_inflation": lambda: f"{a.label}: platform reports {a.change_pct:+.0%} more conversions than the store",
    }[a.kind]()


def _price(x: float) -> str:
    return f"₹{x:,.0f}"


# ---------------------------------------------------------------------------
# build_recommendations
# ---------------------------------------------------------------------------
def build_recommendations(objective: str | None = None) -> dict:
    """Run rules 1–10 and return the ranked inbox. Does not save state (the next step merges and persists).

    Returns {objective, summary, recommendations: [Recommendation], covered: {campaign_id: rec_id}}.
    """
    state_objective = load_state().get("objective", DEFAULT_OBJECTIVE)
    objective = objective or state_objective
    if objective not in OBJECTIVES:
        raise ValueError(f"unknown objective {objective!r}; expected one of {OBJECTIVES}")
    b = _Builder(objective)
    curves = b.curves

    anomalies = detect_all()
    causal = compute_causal(anomalies)
    roots = {a.id: rc for a, rc in zip(anomalies, diagnose_all(anomalies, causal))}
    by_key = {anomaly_key(a): a for a in anomalies}
    campaign_sku = curves["sku_id"].to_dict()

    # remembered for rule 4: a conversion_drop that is only a knock-on of a viral positive_spike (rule 3b)
    viral_knock_on = {a.entity_id: a for a in anomalies if a.kind == "conversion_drop"
                      and any(k.startswith("positive_spike:") for k in a.detail.get("related", []))}

    # 1. stockout_risk → inventory_protect ---------------------------------------------------------------------------
    for a in (x for x in anomalies if x.kind == "stockout_risk"):
        cids = b.uncovered(curves["sku_id"] == a.entity_id)
        if not cids:
            continue
        changes = [b.change(c, curves.loc[c, "current_spend"] * (1 - STOCKOUT_AD_CUT)) for c in cids]
        gm0 = float(sum(hill(curves.loc[c, "current_spend"], curves.loc[c, "a"], curves.loc[c, "b"]) for c in cids))
        gm1 = float(sum(hill(ch["to_budget"], curves.loc[ch["campaign_id"], "a"], curves.loc[ch["campaign_id"], "b"]) for ch in changes))
        value = _stockout_value(gm0, sum(ch["from_budget"] for ch in changes), gm1, sum(ch["to_budget"] for ch in changes), a.detail["days_cover"])
        sku = b.sku_names[a.entity_id]
        b.add(f"Protect stock · cut ads on {sku} by {STOCKOUT_AD_CUT:.0%}", _issue(a), roots[a.id].narrative,
              {"type": "inventory_protect", "changes": changes, "targets": b.targets(cids, skus=[a.entity_id]),
               "notes": ["Spend increases on this SKU stay blocked until stock recovers"]},
              value, a.z, b.mean_uncertainty(cids), a.id, ["stock_cover", "curve"])

    # 2. creative_fatigue → creative_refresh ---------------------------------------------------------------------------
    for a in (x for x in anomalies if x.kind == "creative_fatigue"):
        if a.entity_id in b.covered:
            continue
        cur = float(curves.loc[a.entity_id, "current_spend"])
        changes = [b.change(a.entity_id, min(float(b.plan[a.entity_id]), cur))]  # trim to plan, never raise
        b.add(f"Refresh creative & trim budget · {curves.loc[a.entity_id, 'name']}", _issue(a), roots[a.id].narrative,
              {"type": "creative_refresh", "changes": changes, "targets": b.targets([a.entity_id]),
               "creative_refresh": {"campaign_id": a.entity_id, "current_creative": a.detail["creative_id"],
                                    "suggested": CREATIVE_SUGGESTION},
               "notes": ["Rotate in a UGC variant while the audience recovers from the tired creative"]},
              _curve_delta(curves, changes), a.z, b.mean_uncertainty([a.entity_id]), a.id,
              ["ctr_trend", "waterfall", "curve"])

    # 3. conversion_drop: (a) price change → price_review; (b) viral knock-on → remembered for rule 4 --------------------
    for a in (x for x in anomalies if x.kind == "conversion_drop"):
        eid = a.detail.get("event_id")
        if not eid or eid not in causal:
            continue  # (b) knock-ons and drops with no price event get no recommendation of their own
        cids = b.uncovered(curves["sku_id"] == a.entity_id)
        changes = b.plan_changes(cids, only="cut")
        if not changes:
            continue
        c = causal[eid]
        summary = {"effect_per_day": c["result"].effect_per_day, "ci_low": c["result"].ci_low,
                   "ci_high": c["result"].ci_high, "units_change_pct": c["units_change_pct"]}
        sku = b.sku_names[a.entity_id]
        b.add(f"Review price & trim ads · {sku}", _issue(a), roots[a.id].narrative,
              {"type": "price_review", "changes": changes, "targets": b.targets([x["campaign_id"] for x in changes], skus=[a.entity_id]),
               "price_review": {"sku_id": a.entity_id, "price_from": a.detail["price_start"], "price_to": a.detail["price_end"],
                                "event_id": eid, "causal": summary},
               "notes": [f"Causal check: units {c['units_change_pct']:+.0%} vs counterfactual; the net margin effect is not "
                         f"statistically distinguishable from zero" if c["result"].ci_low < 0 < c["result"].ci_high
                         else f"Causal check: units {c['units_change_pct']:+.0%} vs counterfactual"]},
              _curve_delta(curves, changes), a.z, b.mean_uncertainty([x["campaign_id"] for x in changes]), a.id,
              ["funnel", "causal", "waterfall"])

    # 4. positive_spike → scale_up ------------------------------------------------------------------------------------
    for a in (x for x in anomalies if x.kind == "positive_spike" and x.entity_type == "campaign"):
        if a.entity_id in b.covered:
            continue
        row, notes = curves.loc[a.entity_id], []
        scale = POSITIVE_SCALE_UP
        knock = viral_knock_on.get(campaign_sku[a.entity_id])
        if knock is not None:
            scale = POSITIVE_SCALE_UP / 2
            notes.append(f"Scale carefully: viral traffic converts {_pct(knock.change_pct)} worse (site CVR)")
        upper = _bounds(row, objective)[1]
        new = min(float(row["current_spend"]) * (1 + scale), upper)
        if new <= float(row["current_spend"]) + MIN_CHANGE:
            continue  # bounded out (e.g. a stock guard): nothing safe to scale
        changes = [b.change(a.entity_id, new)]
        b.add(f"Scale winner · {row['name']}", _issue(a), roots[a.id].narrative,
              {"type": "scale_up", "changes": changes, "targets": b.targets([a.entity_id]), "notes": notes},
              _curve_delta(curves, changes), a.z, b.mean_uncertainty([a.entity_id]), a.id,
              ["waterfall", "curve", "funnel"])

    # 5. cpc_spike → bid_cap (covers the knock-on profit drops it caused) ---------------------------------------------
    for a in (x for x in anomalies if x.kind == "cpc_spike"):
        key = anomaly_key(a)
        knock_ons = [k for k in anomalies if k.kind == "metric_shift" and key in k.detail.get("related", [])]
        cids = b.uncovered(curves["channel"] == a.entity_id)
        changes = b.plan_changes(cids, only="any")
        if not changes:
            continue
        name = CHANNEL_DISPLAY[a.entity_id]
        notes = ["Rebalance toward campaigns whose next rupee still returns more than a rupee while auctions are expensive"]
        if knock_ons:
            notes.append(f"Also addresses the knock-on profit drops: {', '.join(k.id for k in knock_ons)}")
        b.add(f"Rebalance {name} while auction prices are high", _issue(a), roots[a.id].narrative,
              {"type": "bid_cap", "changes": changes,
               "targets": b.targets([c["campaign_id"] for c in changes], cluster=a.entity_id), "notes": notes},
              _curve_delta(curves, changes), a.z, b.mean_uncertainty([c["campaign_id"] for c in changes]), a.id,
              ["waterfall", "curve"])

    # 6. attribution_inflation → data_fix (one per channel) -----------------------------------------------------------
    for a in (x for x in anomalies if x.kind == "attribution_inflation"):
        name = CHANNEL_DISPLAY[a.entity_id]
        source = b.sources[a.entity_id]
        b.add(f"Optimise {name} on store-verified conversions", _issue(a), roots[a.id].narrative,
              {"type": "data_fix", "targets": b.targets(source=source),
               "settings": {"channel": a.entity_id, "conversion_source": "server_side",
                            "reason": f"platform reports {_pct(a.change_pct)} more conversions than the store"},
               "notes": [a.detail["recommended_fix"]]},
              0.0, a.z, 0.0, a.id, ["reconciliation"])

    # 7. standalone metric_shift (not a knock-on) → budget_cut -----------------------------------------------------------
    for a in (x for x in anomalies if x.kind == "metric_shift" and x.entity_type == "campaign"):
        if any(k in by_key and by_key[k].kind == "cpc_spike" for k in a.detail.get("related", [])):
            continue  # a knock-on: rule 5 owns it
        if a.entity_id in b.covered:
            continue
        changes = b.plan_changes([a.entity_id], only="cut")
        if not changes:
            continue
        b.add(f"Trim budget · {curves.loc[a.entity_id, 'name']}", _issue(a), roots[a.id].narrative,
              {"type": "budget_cut", "changes": changes, "targets": b.targets([a.entity_id])},
              _curve_delta(curves, changes), a.z, b.mean_uncertainty([a.entity_id]), a.id, ["waterfall", "curve"])

    # 8. optimizer cuts → one "Trim loss-making campaigns" ---------------------------------------------------------------
    plan_ratio = pd.Series({cid: b.plan[cid] / curves.loc[cid, "current_spend"] for cid in curves.index})
    cids = b.uncovered(plan_ratio.reindex(curves.index) < PLAN_CUT_THRESHOLD)
    changes = b.plan_changes(cids, only="cut")
    if changes:
        ids = [c["campaign_id"] for c in changes]
        worst = curves.loc[ids, "marginal_poas"]
        b.add("Trim loss-making campaigns",
              f"{len(ids)} campaigns return less than ₹1 on the next rupee (marginal POAS {worst.min():.2f} to {worst.max():.2f})",
              "Their response curves are past the point of diminishing returns: the optimizer cuts each toward the spend "
              "where the next rupee earns a rupee",
              {"type": "budget_cut", "changes": changes, "targets": b.targets(ids)},
              _curve_delta(curves, changes), 0.0, b.mean_uncertainty(ids), None, ["curve"])

    # 9. optimizer scale-ups → one "Scale under-funded high-margin campaigns" ----------------------------------------------
    cids = b.uncovered(plan_ratio.reindex(curves.index) > PLAN_SCALE_THRESHOLD)
    changes = b.plan_changes(cids, only="scale")
    if changes:
        ids = [c["campaign_id"] for c in changes]
        assert not any(curves.loc[i, "days_cover"] < STOCK_COVER_RISK_DAYS for i in ids), "scale-up on a low-stock SKU"
        best = curves.loc[ids, "marginal_poas"]
        b.add("Scale under-funded high-margin campaigns",
              f"{len(ids)} campaign(s) earn more than ₹1 on the next rupee (marginal POAS {best.min():.2f} to {best.max():.2f}) and have stock",
              "Their response curves still have headroom: the optimizer moves budget toward them",
              {"type": "scale_up", "changes": changes, "targets": b.targets(ids)},
              _curve_delta(curves, changes), 0.0, b.mean_uncertainty(ids), None, ["curve"])

    # 10. top opportunities → launch_test --------------------------------------------------------------------------------
    trained = opp.train()
    uncertainty = 1 - max(trained["r2_holdout"], 0.0)
    for r in opp.scored_rows(trained=trained)[:OPP_LAUNCH_N]:
        name, channel = CHANNEL_DISPLAY[r["channel"]], r["channel"]
        b.add(f"Launch test · {r['sku_name']} on {name} ({r['audience']})",
              f"No campaign has ever run {r['label']}; the model predicts POAS {r['predicted_poas']:.1f} ({r['stock_days']:.0f} days of cover)",
              f"Scored before any spend from product rating, channel and audience effects (hold-out R² {trained['r2_holdout']:.2f}: "
              f"a ranking signal, not a forecast)",
              {"type": "launch_test", "targets": b.targets(ghost=r["label"], skus=[r["sku_id"]]),
               "launch": {"sku_id": r["sku_id"], "channel": channel, "audience": r["audience"], "daily_budget": float(OPP_TEST_BUDGET),
                          "predicted_poas": round(r["predicted_poas"], 4), "predicted_conv_per_1k": round(r["predicted_conv_per_1k"], 4)},
               "notes": ["A small test budget; scale only if the measured POAS confirms the prediction"]},
              (r["predicted_poas"] - 1) * OPP_TEST_BUDGET * OPP_IMPACT_HAIRCUT, 0.0, uncertainty, None, ["opportunity"],
              shift=OPP_TEST_BUDGET / b.brand_total)

    recs = sorted(b.recs, key=lambda r: (-r.priority, r.id))
    by_risk = {k: sum(r.risk == k for r in recs) for k in ("low", "medium", "high")}
    summary = {
        "count": len(recs), "total_expected_profit_delta": round(sum(r.expected_profit_delta for r in recs), 2),
        "by_risk": by_risk, "needs_approval": sum(r.requires_approval and not r.blocked for r in recs),
        "auto_eligible": sum(not r.requires_approval and not r.blocked for r in recs),
        "blocked": sum(r.blocked for r in recs), "plan_profit_delta": b.plan_result["summary"]["profit_delta"],
    }
    return {"objective": objective, "summary": summary, "recommendations": recs, "covered": dict(b.covered)}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def approval_label(r: Recommendation) -> str:
    return "BLOCKED" if r.blocked else ("yes" if r.requires_approval else "auto")


def print_inbox(result: dict, elapsed: float | None = None) -> None:
    print(f"{'#':<3}{'title':<58}{'₹/day':>9}{'conf':>6}  {'risk':<7}{'approval':<9}{'action':<18}campaigns")
    for i, r in enumerate(result["recommendations"], start=1):
        ids = [c["campaign_id"] for c in r.action["changes"]]
        target = ", ".join(ids) if ids else "—"
        print(f"{i:<3}{r.title:<58}{m.format_inr(r.expected_profit_delta):>9}{r.confidence:>6.0%}  {r.risk:<7}{approval_label(r):<9}"
              f"{r.action['type']:<18}{target}")
    s = result["summary"]
    print(f"\nM6 OK · {s['count']} recommendations · {m.format_inr(s['total_expected_profit_delta'])}/day expected · "
          f"{s['needs_approval']} need approval · {s['auto_eligible']} auto-eligible"
          + (f" · {elapsed:.1f}s" if elapsed is not None else ""))


def main() -> None:
    t0 = time.perf_counter()
    result = build_recommendations()
    print_inbox(result, time.perf_counter() - t0)


if __name__ == "__main__":
    main()
