"""Read-only service layer shared by the M8 AI agent and (later) the M9 HTTP API.

Every function returns JSON-safe data (M0 `to_dict`: NaN / ±inf → None) and NEVER writes: no state.json, no
database, no brain events. Execution (approve / reject / rollback) lives only in M6, behind its guardrails.
"""
from __future__ import annotations

import json
from typing import Any

import pandas as pd

from backend.core import metrics as m
from backend.core.config import CHANNEL_DISPLAY, STOCK_COVER_RISK_DAYS
from backend.core.db import load_state, read_table, table_exists
from backend.core.schema import to_dict
from backend.detection.detectors import detect_all
from backend.detection.store import load_manifest
from backend.diagnosis.causal import event_effect_details
from backend.diagnosis.decompose import diagnose_all
from backend.decisions.engine import build_recommendations
from backend.learning import loop as learning_loop
from backend.optimizer import opportunity as opp
from backend.optimizer.optimize import channel_simulate as _channel_simulate


def _change(recent: float, previous: float) -> float | None:
    """(recent − previous) ÷ |previous|, via M0 change_pct (equal to it for a positive baseline; a loss that
    deepens still reads as negative)."""
    return m.change_pct(abs(previous) + (recent - previous), abs(previous))


def kpis(period: int = 7) -> dict:
    """Headline KPIs for the last `period` days vs the `period` days before, anchored on the last data date.

    spend / revenue / profit are DAILY AVERAGES (₹/day); poas, roas_true, roas_platform are Σ ÷ Σ ratios.
    """
    fact = read_table("fact_daily")
    dates = sorted(fact["date"].unique())
    cur, prev = fact[fact["date"].isin(dates[-period:])], fact[fact["date"].isin(dates[-2 * period:-period])]

    def block(df: pd.DataFrame) -> dict:
        spend = float(df["spend"].sum())
        return {"spend": spend / period, "revenue": float(df["revenue"].sum()) / period, "profit": float(df["profit"].sum()) / period,
                "poas": m.poas(float(df["gross_margin"].sum()), spend), "roas_true": m.roas_true(float(df["revenue"].sum()), spend),
                "roas_platform": m.roas_platform(float(df["platform_revenue"].sum()), spend)}

    now, before = block(cur), block(prev)
    sku = read_table("sku_daily")
    latest = sku[sku["date"] == sku["date"].max()]
    names = read_table("dim_sku").set_index("sku_id")["name"]
    risk = latest[latest["days_cover"] < STOCK_COVER_RISK_DAYS].sort_values("days_cover")
    rec = read_table("reconciliation")
    trust = m.safe_div(float((rec["spend"] * rec["trust_score"]).sum()), float(rec["spend"].sum()))
    out = {k: {"value": v, "change": _change(v, before[k]) if before[k] is not None and v is not None else None} for k, v in now.items()}
    out.update({
        "period_days": period,
        "stock_at_risk": {"value": int(len(risk)), "skus": [{"sku_id": r.sku_id, "name": names[r.sku_id], "days_cover": float(r.days_cover)}
                                                            for r in risk.itertuples()]},
        "as_of": dates[-1], "last_synced": str(rec["last_synced"].iloc[0]), "data_trust": trust,
    })
    return to_dict(out)


def anomalies() -> list[dict]:
    """The current ranked anomalies (M3)."""
    return to_dict(detect_all())


def diagnosis(anomaly_id: str) -> dict:
    """{anomaly, root_cause} for one anomaly id (M4). KeyError with a clear message if there is no such anomaly."""
    found = detect_all()
    for a, rc in zip(found, diagnose_all(found)):
        if a.id == anomaly_id:
            return to_dict({"anomaly": a, "root_cause": rc})
    raise KeyError(f"Unknown anomaly {anomaly_id!r}; current anomalies: {', '.join(a.id for a in found)}")


def recommendations() -> dict:
    """{objective, summary, recommendations}: the pending decisions from state if any exist, else a fresh build
    (never saved)."""
    state = load_state()
    pending = [d for d in state["decisions"] if d["status"] == "pending"]
    if pending:
        recs, objective = pending, state.get("objective")
        summary = {"count": len(recs), "total_expected_profit_delta": round(sum(d["expected_profit_delta"] for d in recs), 2),
                   "needs_approval": sum(d["requires_approval"] and not d["blocked"] for d in recs),
                   "auto_eligible": sum(not d["requires_approval"] and not d["blocked"] for d in recs),
                   "blocked": sum(d["blocked"] for d in recs)}
    else:
        built = build_recommendations()
        recs, objective, summary = to_dict(built["recommendations"]), built["objective"], to_dict(built["summary"])
    return to_dict({"objective": objective, "summary": summary, "recommendations": recs})


def causal(event_id: str | None = None) -> dict:
    """The M4b synthetic-control result for an event (default: the most recent price_change event).

    A superset of the M0 CausalResult: adds units_change_pct, n_post, controls, treated_sku, ci_includes_zero. NOTE
    ci_low / ci_high bound `total_effect` (₹ over the n_post post-period days), not ₹/day.
    """
    if event_id is None:
        ev = read_table("events")
        ev = ev[ev["type"] == "price_change"].sort_values("date")
        if ev.empty:
            raise KeyError("No price_change event found")
        event_id = str(ev["event_id"].iloc[-1])
    d = event_effect_details(event_id)
    r = d["result"]
    return to_dict({**to_dict(r), "units_change_pct": d["units_change_pct"], "n_post": d["n_post"], "controls": d["controls"],
                    "treated_sku": d["treated_sku"], "ci_includes_zero": bool(r.ci_low < 0 < r.ci_high)})


def channel_simulate(multipliers: dict) -> dict:
    """What-if: scale every campaign of a channel (M5 simulator). Read-only."""
    return to_dict(_channel_simulate({k: float(v) for k, v in multipliers.items()}))


def opportunities() -> dict:
    """{model_r2_holdout, opportunities}: from the persisted tables if present, else scored on the fly."""
    if table_exists("opportunities") and table_exists("model_metrics"):
        rows = read_table("opportunities").to_dict("records")
        r2 = float(read_table("model_metrics")["r2_holdout"].iloc[0])
    else:
        trained = opp.train()
        rows, r2 = opp.scored_rows(trained=trained), float(trained["r2_holdout"])
    return to_dict({"model_r2_holdout": r2, "opportunities": rows})


def reconciliation() -> list[dict]:
    """Platform-claimed vs store-verified performance per channel (M2)."""
    return to_dict(read_table("reconciliation"))


def learning() -> dict:
    """M7's learning report, without writing state (an unseeded history is seeded in memory only)."""
    return to_dict(learning_loop.preview_report())


def brain_targets_for(entity_ids: list[str]) -> list[dict]:
    """Map entity ids to brain targets: campaign / SKU ids → neuron, channel names → cluster, ad source ids → source.

    Unknown ids are ignored; duplicates are removed (order kept).
    """
    manifest = load_manifest()
    neurons = {n["entity_id"] for n in manifest["neurons"]}
    clusters = {c["id"] for c in manifest["clusters"]}
    sources = {s["id"] for s in manifest["sources"]}
    display = {v.lower(): k for k, v in CHANNEL_DISPLAY.items()}
    out, seen = [], set()
    for raw in entity_ids:
        e = str(raw)
        for kind, ok, tid in (("neuron", e in neurons, e), ("cluster", e in clusters or e.lower() in clusters, e.lower()),
                              ("cluster", e.lower() in display, display.get(e.lower())), ("source", e in sources, e)):
            if ok and (kind, tid) not in seen:
                seen.add((kind, tid))
                out.append({"type": kind, "id": tid})
                break
    return out


def json_safe(obj: Any) -> str:
    """json.dumps that can never fail (used by tests and the agent)."""
    return json.dumps(to_dict(obj), allow_nan=False)
