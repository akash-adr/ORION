"""M6 recommendation builder: the Neural Brain's "Decide" lobe.

Turns M3 alerts, M4 causes, M5 budget plans and M5b opportunities into ranked, executable decisions in the M0
`Recommendation` shape, each with a calibrated ₹/day impact, confidence, risk, approval tier and block status.

Run from the project root:  python -m backend.decisions.engine

build_recommendations() only BUILDS: it never saves state. The second half of this module merges the inbox with
state (refresh_decisions), executes / rejects / rolls back decisions through a mock ad API, runs the autopilot,
keeps the audit log and emits the Decide-lobe brain events.

GUARDRAILS (five layers, innermost first):
  1. optimizer bounds   ±50% per day, the stock guard, and the total budget (backend/optimizer)
  2. risk tiers         only a LOW-risk move smaller than AUTO_APPLY_MAX_SHIFT is ever auto-eligible
  3. hard block         raising spend on a near-stockout SKU can never execute, even if approved; it is
                        re-checked against CURRENT data at execution time
  4. autonomy mode      advisory never executes; supervised needs a human; autonomous auto-applies only
                        low-risk, unblocked, approval-free items
  5. audit + rollback   every action is logged with the exact previous budgets and reverses in one call

DECISION LIFECYCLE: pending → executed → rolled_back; pending → rejected; executed → (M7: outcome measured).
Executed / rejected / rolled-back decisions keep their status: a refresh never recreates them as pending duplicates.

Rules are processed in a fixed order, 1 → 10. A COVERED set guarantees a campaign appears in only ONE
recommendation's budget changes, so the earlier (more specific, more urgent) rule wins a conflict.

Titles are STABLE: built only from entity names and fixed wording (never ₹ amounts or counts), because a
recommendation's id is the md5 of its title and must survive refreshes.
"""
from __future__ import annotations

import re
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from backend.core import metrics as m
from backend.core.config import (
    AUTO_APPLY_MAX_SHIFT, AUTONOMY_MODES, CHANNEL_DISPLAY, CONF_BASE, CONF_MAPE_WEIGHT, CONF_UNC_WEIGHT, CONF_Z_CAP, CONF_Z_WEIGHT,
    CONFIDENCE_MAX, CONFIDENCE_MIN, DEFAULT_OBJECTIVE, OBJECTIVES, OPP_IMPACT_HAIRCUT, OPP_LAUNCH_N, OPP_TEST_BUDGET,
    PLAN_CUT_THRESHOLD, PLAN_SCALE_THRESHOLD, POSITIVE_SCALE_UP, RISK_HIGH_IMPACT, RISK_HIGH_SHIFT, RISK_MEDIUM_SHIFT,
    STOCK_COVER_RISK_DAYS, STOCKOUT_AD_CUT, STOCKOUT_HORIZON_DAYS, URGENCY_BONUS,
)
from backend.core.db import load_state, log_brain_event, read_table, save_state
from backend.core.schema import Anomaly, Recommendation, make_brain_event, to_dict
from backend.decisions import hooks
from backend.decisions.ads_api import MockAdsAPI
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
        action = {"changes": [], "targets": [], "notes": [], "related": [], **action}
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
              {"type": "scale_up", "changes": changes, "targets": b.targets([a.entity_id]), "notes": notes,
               "related": [anomaly_key(knock)] if knock is not None else []},
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
               "targets": b.targets([c["campaign_id"] for c in changes], cluster=a.entity_id), "notes": notes,
               "related": [anomaly_key(k) for k in knock_ons]},
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
# Clock (injectable so tests are deterministic)
# ---------------------------------------------------------------------------
_CLOCK = None


def set_clock(fn) -> None:
    """Inject a zero-argument callable returning a datetime (None restores the real IST clock)."""
    global _CLOCK
    _CLOCK = fn


def _now_dt() -> datetime:
    return _CLOCK() if _CLOCK else datetime.now(ZoneInfo("Asia/Kolkata"))


def _now() -> str:
    return _now_dt().strftime("%Y-%m-%dT%H:%M:%S")


def _api() -> MockAdsAPI:
    return MockAdsAPI(clock=_now_dt)


# ---------------------------------------------------------------------------
# Brain events (Decide lobe)
# ---------------------------------------------------------------------------
def _severity(d: dict) -> str:
    """high if the decision is high-risk or blocked, medium if medium-risk, else low."""
    return "high" if d["risk"] == "high" or d["blocked"] else ("medium" if d["risk"] == "medium" else "low")


def _signature(d: dict) -> str:
    """What makes a pending decision worth pulsing again: its size, risk, block and approval tier."""
    return f"{round(d['expected_profit_delta'], -2)}|{d['risk']}|{d['blocked']}|{d['requires_approval']}"


def _first_target(d: dict) -> str | None:
    t = d["action"].get("targets") or []
    return t[0]["id"] if t else None


def _emit(event_type: str, d: dict, message: str, payload: dict) -> None:
    log_brain_event(make_brain_event(event_type, entity_id=_first_target(d), ref_id=d["id"], severity=_severity(d),
                                     message=message, payload=payload))


def _recommendation_events(pending: list[dict]) -> int:
    """One "recommendation" pulse per pending decision whose id is new or whose signature changed."""
    state = load_state()
    sigs, n = state.get("rec_signatures", {}), 0
    for d in pending:  # ranked order
        sig = _signature(d)
        if sigs.get(d["id"]) == sig:
            continue
        msg = f"{d['title']} — {m.format_inr(d['expected_profit_delta'])}/day · {round(d['confidence'] * 100)}% confidence"
        _emit("recommendation", d, msg + (" · BLOCKED" if d["blocked"] else ""), {
            "rec_id": d["id"], "action_type": d["action"]["type"], "targets": d["action"]["targets"],
            "anomaly_id": d["anomaly_id"], "related": d["action"].get("related", []),
            "expected_profit_delta": d["expected_profit_delta"], "confidence": d["confidence"], "risk": d["risk"],
            "requires_approval": d["requires_approval"], "blocked": d["blocked"], "campaigns": d["action"]["changes"]})
        n += 1
    state = load_state()  # log_brain_event saved the event log; reload so those writes are kept
    state["rec_signatures"] = {d["id"]: _signature(d) for d in pending}  # ids no longer pending are dropped
    save_state(state)
    return n


def _synapses(changes: list[dict]) -> list[dict]:
    """campaign → SKU `promotes` edges of the brain manifest for every changed campaign."""
    changed = {c["campaign_id"] for c in changes}
    return [{"source": e["source"], "target": e["target"]} for e in load_manifest()["synapses"]
            if e["kind"] == "promotes" and e["source"] in changed]


# ---------------------------------------------------------------------------
# State merge
# ---------------------------------------------------------------------------
HISTORY_STATUSES = ("executed", "rejected", "rolled_back")


def _history_key(d: dict) -> str:
    return d.get("updated_at") or ""


def refresh_decisions(objective: str | None = None, emit_brain_events: bool = True) -> dict:
    """Rebuild the inbox and merge it with state["decisions"] by id (ids are stable md5s of titles).

    Executed / rejected / rolled-back decisions KEEP their status and stored details (never regenerated as a new
    pending duplicate); pending decisions are REBUILT from fresh data; pending ones no longer generated are dropped.
    In autonomous mode the autopilot then applies every low-risk, unblocked, approval-free pending decision.
    """
    built = build_recommendations(objective)
    state = load_state()
    history = [d for d in state["decisions"] if d["status"] in HISTORY_STATUSES]
    seen = {d["id"] for d in history}
    pending = [to_dict(r) for r in built["recommendations"] if r.id not in seen]
    state["decisions"] = history + pending
    state["last_build_at"] = _now()
    save_state(state)

    events = _recommendation_events(pending) if emit_brain_events else 0
    auto = auto_apply(emit_brain_events=emit_brain_events) if state.get("autonomy") == "autonomous" else []
    return inbox(built["objective"], built["summary"], events, auto)


def inbox(objective: str, build_summary: dict | None = None, events_logged: int = 0, auto_applied: list | None = None) -> dict:
    """The merged inbox: pending first (by priority), then history newest first, with a summary."""
    decisions = load_state()["decisions"]
    pending = [d for d in decisions if d["status"] == "pending"]
    history = sorted((d for d in decisions if d["status"] != "pending"), key=_history_key, reverse=True)
    summary = {
        "pending": len(pending), "executed": sum(d["status"] == "executed" for d in decisions),
        "rejected": sum(d["status"] == "rejected" for d in decisions),
        "rolled_back": sum(d["status"] == "rolled_back" for d in decisions),
        "total_expected_profit_delta": round(sum(d["expected_profit_delta"] for d in pending), 2),
        "needs_approval": sum(d["requires_approval"] and not d["blocked"] for d in pending),
        "auto_eligible": sum(not d["requires_approval"] and not d["blocked"] for d in pending),
        "blocked": sum(d["blocked"] for d in pending),
        "plan_profit_delta": (build_summary or {}).get("plan_profit_delta"),
    }
    return {"objective": objective, "summary": summary, "pending": pending, "history": history,
            "decisions": pending + history, "events_logged": events_logged, "auto_applied": auto_applied or []}


# ---------------------------------------------------------------------------
# Execute / reject / rollback
# ---------------------------------------------------------------------------
def _find(state: dict, rec_id: str) -> dict | None:
    return next((d for d in state["decisions"] if d["id"] == rec_id), None)


def _refuse(reason: str) -> dict:
    return {"ok": False, "reason": reason}


def _blocked_reason(changes: list[dict], curves: pd.DataFrame) -> str | None:
    """The guardrail message for the first change that raises spend on a SKU under STOCK_COVER_RISK_DAYS of cover."""
    names = read_table("dim_sku").set_index("sku_id")["name"]
    for c in changes:
        row = curves.loc[c["campaign_id"]]
        if c["to_budget"] > c["from_budget"] and row["days_cover"] < STOCK_COVER_RISK_DAYS:
            return (f"Blocked by guardrail: would raise spend on {names[row['sku_id']]} with "
                    f"{row['days_cover']:.0f} days of stock")
    return None


def _finish_state_change(state: dict) -> None:
    """Persist, then re-fit the M5 curves so executed budgets become the new current spend (the closed loop)."""
    save_state(state)
    fit_curves(refresh=True)


def approve(rec_id: str, approver: str = "user", emit_brain_events: bool = True) -> dict:
    """A human approves a pending decision: same as execute()."""
    return execute(rec_id, approver, emit_brain_events)


def execute(rec_id: str, approver: str = "user", emit_brain_events: bool = True) -> dict:
    """Apply a pending decision through the (mock) ad APIs. Returns {"ok", "api_calls", "decision"} or {"ok": False, "reason"}."""
    state = load_state()
    d = _find(state, rec_id)
    if d is None:
        return _refuse(f"Unknown decision {rec_id}")
    if d["status"] != "pending":
        return _refuse({"executed": "Already executed", "rejected": "Decision was rejected",
                        "rolled_back": "Decision was rolled back"}[d["status"]])
    curves = fit_curves().set_index("campaign_id")
    changes = d["action"].get("changes", [])
    if d["blocked"]:
        return _refuse(_blocked_reason(changes, curves) or "Blocked by guardrail")
    if state.get("autonomy") == "advisory":
        return _refuse("Advisory mode: decisions are never executed")
    now_blocked = _blocked_reason(changes, curves)  # re-checked against CURRENT data at execution time
    if now_blocked:
        return _refuse(now_blocked)

    api, calls, rollback, ts = _api(), [], [], _now()
    for c in changes:  # budget changes
        cid = c["campaign_id"]
        previous = round(float(curves.loc[cid, "current_spend"]), 2)  # the override if present, else the curve's spend
        state["budget_overrides"][cid] = float(c["to_budget"])
        calls.append(api.update_budget(cid, c["channel"], c["to_budget"]))
        rollback.append({"type": "budget", "campaign_id": cid, "channel": c["channel"], "budget": previous})
    if "creative_refresh" in d["action"]:
        cr = d["action"]["creative_refresh"]
        calls.append(api.rotate_creative(cr["campaign_id"], curves.loc[cr["campaign_id"], "channel"], cr["suggested"]))
    launched = None
    if "launch" in d["action"]:
        ln = d["action"]["launch"]
        call = api.create_test_campaign(ln["sku_id"], ln["channel"], ln["audience"], ln["daily_budget"])
        calls.append(call)
        launched = {"rec_id": d["id"], "test_campaign_id": call["campaign_id"], "sku_id": ln["sku_id"],
                    "channel": ln["channel"], "audience": ln["audience"], "daily_budget": ln["daily_budget"],
                    "launched_at": ts, "status": "running"}
        state["launched_tests"].append(launched)
        rollback.append({"type": "launch", "test_campaign_id": call["campaign_id"], "channel": ln["channel"]})
    fixed = None
    if "settings" in d["action"]:
        st = d["action"]["settings"]
        calls.append(api.set_conversion_source(st["channel"], "server_side"))
        fixed = {"conversion_source": "server_side", "applied_at": ts, "rec_id": d["id"]}
        state["data_fixes"][st["channel"]] = fixed
        rollback.append({"type": "setting", "channel": st["channel"], "conversion_source": "platform"})

    d.update(status="executed", executed_at=ts, approver=approver, updated_at=ts)
    entry = {"ts": ts, "decision_id": d["id"], "title": d["title"], "action": "execute", "approver": approver,
             "api_calls": calls, "rollback": rollback, "expected_profit_delta": d["expected_profit_delta"],
             "confidence": d["confidence"]}
    state["audit"].append(entry)
    _finish_state_change(state)
    if emit_brain_events:
        auto = approver == "autopilot"
        _emit("auto_apply" if auto else "approval", d,
              f"{'Autopilot applied' if auto else 'Approved'} · {d['title']} — {len(calls)} API call(s)",
              {"rec_id": d["id"], "approver": approver, "targets": d["action"]["targets"], "changes": changes,
               "api_calls_count": len(calls), "synapses": _synapses(changes), "launched_test": launched,
               "data_fix": ({"channel": d["action"]["settings"]["channel"], **fixed} if fixed else None)})
    try:  # M7 measures the outcome AFTER the approval pulse (decide → learn); a hook failure never breaks execution
        with hooks.emitting(emit_brain_events):
            hooks.on_executed(d, entry)
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True, "api_calls": calls, "decision": to_dict(d)}


def reject(rec_id: str, approver: str = "user", reason: str | None = None, emit_brain_events: bool = True) -> dict:
    """Reject a pending decision (it is not re-proposed on refresh)."""
    state = load_state()
    d = _find(state, rec_id)
    if d is None:
        return _refuse(f"Unknown decision {rec_id}")
    if d["status"] != "pending":
        return _refuse(f"Only pending decisions can be rejected (this one is {d['status']})")
    ts = _now()
    d.update(status="rejected", rejected_at=ts, approver=approver, reject_reason=reason, updated_at=ts)
    state["audit"].append({"ts": ts, "decision_id": d["id"], "title": d["title"], "action": "reject", "approver": approver,
                           "api_calls": [], "reason": reason, "expected_profit_delta": d["expected_profit_delta"],
                           "confidence": d["confidence"]})
    save_state(state)
    if emit_brain_events:
        _emit("rejection", d, f"Rejected · {d['title']}", {"rec_id": d["id"], "approver": approver, "reason": reason,
                                                           "targets": d["action"]["targets"]})
    return {"ok": True}


def rollback(rec_id: str, approver: str = "user", emit_brain_events: bool = True) -> dict:
    """Undo an executed decision from its last execute audit entry, restoring the exact previous budgets."""
    state = load_state()
    d = _find(state, rec_id)
    if d is None:
        return _refuse(f"Unknown decision {rec_id}")
    if d["status"] != "executed":
        return _refuse(f"Only executed decisions can be rolled back (this one is {d['status']})")
    entry = next((e for e in reversed(state["audit"]) if e["decision_id"] == rec_id and e["action"] == "execute"), None)
    if entry is None:
        return _refuse("No execute audit entry found for this decision")

    curves = fit_curves().set_index("campaign_id")
    api, calls, restored = _api(), [], []
    for r in entry["rollback"]:
        if r["type"] == "budget":
            cid, prev = r["campaign_id"], r["budget"]
            if abs(prev - float(curves.loc[cid, "spend_7d"])) < 0.01:  # it was the original spend: drop the override
                state["budget_overrides"].pop(cid, None)
            else:
                state["budget_overrides"][cid] = prev
            calls.append(api.update_budget(cid, r["channel"], prev))
            restored.append({"campaign_id": cid, "budget": prev})
        elif r["type"] == "launch":
            calls.append(api.pause_test_campaign(r["test_campaign_id"], r["channel"]))
            for t in state["launched_tests"]:
                if t["test_campaign_id"] == r["test_campaign_id"] and t["rec_id"] == rec_id:
                    t["status"] = "paused"
        elif r["type"] == "setting":
            calls.append(api.set_conversion_source(r["channel"], r["conversion_source"]))
            state["data_fixes"].pop(r["channel"], None)
    ts = _now()
    d.update(status="rolled_back", rolled_back_at=ts, updated_at=ts)
    back = {"ts": ts, "decision_id": rec_id, "title": d["title"], "action": "rollback", "approver": approver,
            "api_calls": calls, "restored": restored, "expected_profit_delta": d["expected_profit_delta"],
            "confidence": d["confidence"]}
    state["audit"].append(back)
    _finish_state_change(state)
    if emit_brain_events:
        _emit("rollback", d, f"Rolled back · {d['title']}", {"rec_id": rec_id, "approver": approver, "restored": restored,
                                                            "api_calls_count": len(calls), "targets": d["action"]["targets"]})
    try:
        with hooks.emitting(emit_brain_events):
            hooks.on_rolled_back(d, back)
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True, "api_calls": calls}


def auto_apply(emit_brain_events: bool = True) -> list[str]:
    """Autopilot: only in autonomous mode, execute every pending decision that is unblocked AND needs no approval."""
    state = load_state()
    if state.get("autonomy") != "autonomous":
        return []
    ids = [d["id"] for d in state["decisions"] if d["status"] == "pending" and not d["blocked"] and not d["requires_approval"]]
    return [i for i in ids if execute(i, "autopilot", emit_brain_events)["ok"]]


# ---------------------------------------------------------------------------
# Settings and audit
# ---------------------------------------------------------------------------
def get_settings() -> dict:
    s = load_state()
    return {"autonomy": s["autonomy"], "objective": s["objective"], "autonomy_modes": list(AUTONOMY_MODES),
            "objectives": list(OBJECTIVES)}


def set_autonomy(mode: str) -> dict:
    """Set the autonomy mode (advisory | supervised | autonomous)."""
    if mode not in AUTONOMY_MODES:
        raise ValueError(f"unknown autonomy mode {mode!r}; expected one of {AUTONOMY_MODES}")
    state = load_state()
    state["autonomy"] = mode
    save_state(state)
    return get_settings()


def set_objective(objective: str) -> dict:
    """Set the optimizer objective used by the next refresh."""
    if objective not in OBJECTIVES:
        raise ValueError(f"unknown objective {objective!r}; expected one of {OBJECTIVES}")
    state = load_state()
    state["objective"] = objective
    save_state(state)
    return get_settings()


def get_audit() -> list[dict]:
    """The audit log, newest first."""
    return list(reversed(load_state()["audit"]))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def approval_label(r) -> str:
    """"BLOCKED" / "yes" (needs a human) / "auto" (autopilot-eligible); works on Recommendation or decision dict."""
    get = (lambda k: r[k]) if isinstance(r, dict) else (lambda k: getattr(r, k))
    return "BLOCKED" if get("blocked") else ("yes" if get("requires_approval") else "auto")


def print_inbox(result: dict, elapsed: float | None = None) -> None:
    """The merged inbox (works on build_recommendations() output or refresh_decisions() output)."""
    rows = result["decisions"] if "decisions" in result else [to_dict(r) for r in result["recommendations"]]
    print(f"{'#':<3}{'id':<12}{'title':<58}{'₹/day':>9}{'conf':>6}  {'risk':<7}{'approval':<9}{'action':<18}{'status':<12}campaigns")
    for i, r in enumerate(rows, start=1):
        ids = [c["campaign_id"] for c in r["action"]["changes"]]
        print(f"{i:<3}{r['id']:<12}{r['title']:<58}{m.format_inr(r['expected_profit_delta']):>9}{r['confidence']:>6.0%}  "
              f"{r['risk']:<7}{approval_label(r):<9}{r['action']['type']:<18}{r['status']:<12}{', '.join(ids) or '—'}")
    s = result["summary"]
    pending = s.get("pending", s.get("count"))
    total = s["total_expected_profit_delta"]
    print(f"\nM6 OK · {pending} pending · {m.format_inr(total)}/day expected · {s['needs_approval']} need approval · "
          f"{s['auto_eligible']} auto-eligible" + (f" · {s.get('executed', 0)} executed" if "executed" in s else "")
          + (f" · {elapsed:.1f}s" if elapsed is not None else ""))


def main(argv: list[str] | None = None) -> None:
    import argparse

    p = argparse.ArgumentParser(description="M6 decision engine")
    p.add_argument("--no-brain-events", action="store_true", help="do not log brain events")
    p.add_argument("--approve", metavar="REC-ID")
    p.add_argument("--reject", metavar="REC-ID")
    p.add_argument("--rollback", metavar="REC-ID")
    p.add_argument("--autonomy", choices=AUTONOMY_MODES)
    p.add_argument("--auto-apply", action="store_true", help="run the autopilot once (autonomous mode only)")
    args = p.parse_args(argv)
    emit = not args.no_brain_events

    if args.autonomy:
        print("settings:", set_autonomy(args.autonomy))
    for flag, fn in (("approve", approve), ("reject", reject), ("rollback", rollback)):
        rec_id = getattr(args, flag)
        if rec_id:
            res = fn(rec_id, emit_brain_events=emit)
            print(f"{flag} {rec_id}: {'OK' if res['ok'] else 'REFUSED — ' + res['reason']}")
            for c in res.get("api_calls", []):
                print(f"    {c['method']} {c['endpoint']}  {c['status']}")
    if args.auto_apply:
        print("autopilot executed:", auto_apply(emit_brain_events=emit) or "nothing")

    t0 = time.perf_counter()
    result = refresh_decisions(emit_brain_events=emit)
    print()
    print_inbox(result, time.perf_counter() - t0)
    if result["events_logged"]:
        print(f"brain events logged: {result['events_logged']}")


if __name__ == "__main__":
    main()
