"""M9 service layer: EVERY engine capability as plain, JSON-ready Python, plus the closed loop that runs it all.

All business logic lives here (the FastAPI routes added next are one line each, so everything is testable without a
server). Conventions:
  * every public function returns data passed through `_clean` (numpy → Python, NaN / ±inf → None, dates → ISO);
  * an unknown id raises KeyError("Not found: …") (routes turn it into a 404); a blocked or already-executed action
    returns {"ok": False, "reason": …} (HTTP 200);
  * every function that MUTATES state.json or the tables runs inside STATE_LOCK, so the background loop and API
    requests never write state at the same time;
  * secrets are never returned: agent availability is reported as a boolean only.

The read-only helpers used by the M8 agent keep their names (`kpis`, `anomalies`, `diagnosis`, `causal`,
`channel_simulate`, `opportunities`, `reconciliation`, `learning`, `brain_targets_for`) and a new
`pending_recommendations()` keeps the agent's "recommendations" tool strictly read-only.
"""
from __future__ import annotations

import copy
import json
import logging
import os
import threading
import time
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any, Callable
from zoneinfo import ZoneInfo

import pandas as pd

from backend.core import config
from backend.core import metrics as m
from backend.core.config import (
    BASELINE_DAYS, BRAIN_MAX_NEURONS, BRAIN_MODE_WINDOW_SECONDS, CACHE_TTL_ANOMALIES, CACHE_TTL_OPPORTUNITIES,
    CACHE_TTL_RECOMMENDATIONS, CHANNEL_DISPLAY, CHANNELS, DEMO_MODE, EVENT_MODE, OBJECTIVES, RECENT_DAYS,
    REFRESH_MINUTES, SIMULATE_MAX_MS, STOCK_COVER_RISK_DAYS, SYNAPSE_BASE, TREND_DAYS_DEFAULT,
)
from backend.core.db import (
    load_state, log_brain_event, query, read_brain_events, read_table, reset_state, save_state, table_exists,
)
from backend.core.schema import make_brain_event, to_dict
from backend.decisions import engine as decisions_engine
from backend.detection.detectors import detect_all
from backend.detection.runner import change_text, run_detection
from backend.detection.store import load_manifest, targets_for
from backend.diagnosis.causal import event_effect_details
from backend.diagnosis.decompose import _top_factor, diagnose_all, lead_sentence
from backend.diagnosis.runner import run_diagnosis
from backend.ingest.pipeline import run_pipeline
from backend.learning import loop as learning_loop
from backend.learning.loop import _outcome_message, record_outcomes
from backend.optimizer import opportunity as opp
from backend.optimizer import optimize as optimizer
from backend.optimizer.curves import curve_points, fit_curves
from backend.optimizer.runner import headroom as headroom_class
from backend.optimizer.runner import run_optimizer

_log = logging.getLogger("engine.api")
IST = ZoneInfo("Asia/Kolkata")

# ---------------------------------------------------------------------------
# Infrastructure
# ---------------------------------------------------------------------------
STATE_LOCK = threading.RLock()  # serialises every writer: the background loop and API requests never write at once
_CACHE: dict[tuple, tuple[float, Any]] = {}
_CACHE_GUARD = threading.Lock()


def _clean(obj: Any) -> Any:
    """JSON-ready copy of anything: numpy → Python, NaN / ±inf → None, Timestamp / date → ISO, DataFrame → records,
    dataclasses via M0 `to_dict`."""
    return to_dict(obj)


def _cached(key: str, ttl: float, fn: Callable[[], Any]) -> Any:
    """In-memory TTL cache (keyed per database + state file, so separate environments never share entries).
    Returns a deep copy so callers can never corrupt a cached value."""
    full = (str(config.DB_PATH), str(config.STATE_PATH), key)
    now = time.monotonic()
    with _CACHE_GUARD:
        hit = _CACHE.get(full)
    if hit and hit[0] > now:
        return copy.deepcopy(hit[1])
    value = fn()
    with _CACHE_GUARD:
        _CACHE[full] = (now + ttl, value)
    return copy.deepcopy(value)


def invalidate(*prefixes: str) -> None:
    """Clear the whole cache, or only the entries whose key starts with one of the prefixes."""
    with _CACHE_GUARD:
        for k in [k for k in _CACHE if not prefixes or any(k[2].startswith(p) for p in prefixes)]:
            del _CACHE[k]


def _now() -> datetime:
    """Current IST time as a naive datetime (brain event timestamps are naive IST). Tests monkeypatch this."""
    return datetime.now(IST).replace(tzinfo=None)


def _ts() -> str:
    return _now().strftime("%Y-%m-%dT%H:%M:%S")


def _not_found(kind: str, ident: Any) -> KeyError:
    return KeyError(f"Not found: {kind} {ident!r}")


def _as_of() -> str:
    return str(query("SELECT MAX(date) AS d FROM fact_daily")["d"].iloc[0])


def _change(recent: float, previous: float) -> float | None:
    """(recent − previous) ÷ |previous|, via M0 change_pct (equal to it for a positive baseline; a loss that
    deepens still reads as negative)."""
    return m.change_pct(abs(previous) + (recent - previous), abs(previous))


def _rows(table: str) -> list[dict]:
    return _clean(read_table(table)) if table_exists(table) else []


def _alerts(target_type: str) -> dict[str, dict]:
    """brain_alerts rows for one target type, keyed by target id (anomaly_ids parsed, stock_locked as a bool)."""
    if not table_exists("brain_alerts"):
        return {}
    df = read_table("brain_alerts")
    out = {}
    for r in df[df["target_type"] == target_type].to_dict("records"):
        r["anomaly_ids"] = json.loads(r["anomaly_ids"])
        r["stock_locked"] = bool(r["stock_locked"])
        out[r["target_id"]] = _clean(r)
    return out


# ---------------------------------------------------------------------------
# Read functions
# ---------------------------------------------------------------------------
def kpis(period: int = 7) -> dict:
    """Headline KPIs for the last `period` days vs the `period` days before, anchored on the last data date.

    spend / revenue / profit are DAILY AVERAGES (₹/day); poas, roas_true, roas_platform are Σ ÷ Σ ratios; each is
    {value, change}. Also stock_at_risk, data_trust, as_of, last_synced.
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
    return _clean(out)


def trend(days: int = TREND_DAYS_DEFAULT) -> list[dict]:
    """Daily totals over all campaigns for the last `days` days: spend, revenue, platform_revenue, profit, poas (Σgm ÷ Σspend)."""
    fact = read_table("fact_daily")
    g = fact.groupby("date")[["spend", "revenue", "platform_revenue", "profit", "gross_margin"]].sum().sort_index().tail(days)
    return _clean([{"date": d, "spend": r.spend, "revenue": r.revenue, "platform_revenue": r.platform_revenue, "profit": r.profit,
                    "poas": m.poas(float(r.gross_margin), float(r.spend))} for d, r in g.iterrows()])


def channels() -> list[dict]:
    """Per channel over the last 7 days: spend / revenue / profit (₹/day), poas, roas_true, roas_platform, trust, inflation."""
    fact = read_table("fact_daily")
    last = fact[fact["date"].isin(sorted(fact["date"].unique())[-RECENT_DAYS:])]
    rec = read_table("reconciliation").set_index("channel")
    out = []
    for ch in CHANNELS:
        g = last[last["channel"] == ch]
        spend = float(g["spend"].sum())
        out.append({"channel": ch, "name": CHANNEL_DISPLAY[ch], "spend": spend / RECENT_DAYS, "revenue": float(g["revenue"].sum()) / RECENT_DAYS,
                    "profit": float(g["profit"].sum()) / RECENT_DAYS, "poas": m.poas(float(g["gross_margin"].sum()), spend),
                    "roas_true": m.roas_true(float(g["revenue"].sum()), spend),
                    "roas_platform": m.roas_platform(float(g["platform_revenue"].sum()), spend),
                    "trust_score": rec.at[ch, "trust_score"], "inflation_pct": rec.at[ch, "inflation_pct"]})
    return _clean(out)


def campaigns() -> list[dict]:
    """Per campaign: the feature-store vector joined with the response curve (marginal POAS, headroom, optimal spend,
    current spend incl. executed budget overrides), days of cover, name and channel display name."""
    fs = read_table("feature_store")
    names = read_table("dim_campaign").set_index("campaign_id")["campaign_name"]
    curves_df = fit_curves().set_index("campaign_id")
    out = []
    for r in fs.to_dict("records"):
        c = curves_df.loc[r["campaign_id"]]
        out.append({**r, "campaign_name": names[r["campaign_id"]], "channel_name": CHANNEL_DISPLAY[r["channel"]],
                    "current_spend": c["current_spend"], "marginal_poas": c["marginal_poas"], "optimal_spend": c["optimal_spend"],
                    "saturation_spend": c["saturation_spend"], "uncertainty": c["uncertainty"], "days_cover": c["days_cover"],
                    "headroom": headroom_class(c["marginal_poas"], c["days_cover"])})
    return _clean(out)


def anomalies() -> list[dict]:
    """The current ranked anomalies (M3), cached for CACHE_TTL_ANOMALIES seconds."""
    return _cached("anomalies", CACHE_TTL_ANOMALIES, lambda: _clean(detect_all()))


def _evidence_daily(a: dict, days: int = TREND_DAYS_DEFAULT) -> list[dict]:
    """Daily series of the anomaly's own entity, for the evidence chart."""
    if a["entity_type"] == "campaign":
        d = read_table("fact_daily")
        d = d[d["campaign_id"] == a["entity_id"]].sort_values("date").tail(days)
        return _clean(d[["date", "spend", "profit", "ctr", "cpc", "frequency"]])
    if a["entity_type"] == "channel":
        d = read_table("fact_daily")
        g = d[d["channel"] == a["entity_id"]].groupby("date")[["spend", "clicks", "profit"]].sum().sort_index().tail(days)
        return _clean([{"date": dt, "spend": r.spend, "cpc": m.cpc(float(r.spend), float(r.clicks)), "profit": r.profit} for dt, r in g.iterrows()])
    d = read_table("sku_daily")
    d = d[d["sku_id"] == a["entity_id"]].sort_values("date").tail(days)
    return _clean([{"date": r.date, "sessions": r.sessions, "site_cvr": m.site_cvr(float(r.purchases), float(max(r.sessions, 1))), "units": r.units,
                    "days_cover": r.days_cover, "unit_price": r.unit_price} for r in d.itertuples()])


def diagnosis(anomaly_id: str) -> dict:
    """{anomaly, root_cause, evidence} for one anomaly: the exact ₹/day waterfall plus evidence for the charts
    (daily series of the entity, the causal result when the anomaly names an event, labels of related anomalies)."""
    found = detect_all()
    for a, rc in zip(found, diagnose_all(found)):
        if a.id != anomaly_id:
            continue
        ad = _clean(a)
        causal_result = None
        if a.detail.get("event_id"):
            try:
                causal_result = causal(a.detail["event_id"])
            except (KeyError, NotImplementedError):
                causal_result = None
        labels = {f"{x.kind}:{x.entity_id}": x.label for x in found}
        related = [labels[k] for k in a.detail.get("related", []) if k in labels]
        return _clean({"anomaly": ad, "root_cause": rc, "evidence": {"daily": _evidence_daily(ad), "causal": causal_result, "related": related}})
    raise _not_found("anomaly", anomaly_id)


def causal(event_id: str | None = None) -> dict:
    """The M4b synthetic-control result for an event (default: the most recent price_change event).

    A superset of the M0 CausalResult: adds units_change_pct, n_post, controls, treated_sku, ci_includes_zero. NOTE
    ci_low / ci_high bound `total_effect` (₹ over the n_post post-period days), not ₹/day.
    """
    if event_id is None:
        ev = read_table("events")
        ev = ev[ev["type"] == "price_change"].sort_values("date")
        if ev.empty:
            raise _not_found("price_change event", None)
        event_id = str(ev["event_id"].iloc[-1])
    try:
        d = event_effect_details(event_id)
    except KeyError:
        raise _not_found("event", event_id) from None
    r = d["result"]
    return _clean({**_clean(r), "units_change_pct": d["units_change_pct"], "n_post": d["n_post"], "controls": d["controls"],
                   "treated_sku": d["treated_sku"], "ci_includes_zero": bool(r.ci_low < 0 < r.ci_high)})


def reconciliation() -> list[dict]:
    """Platform-claimed vs store-verified performance per channel (M2)."""
    return _clean(read_table("reconciliation"))


def sources() -> list[dict]:
    """source_status rows + `verified` (a store-verified conversion fix was applied to that channel) + any brain alert on the source."""
    fixes = load_state().get("data_fixes", {})
    channel_of = {s["id"]: s["channel"] for s in load_manifest()["sources"]}
    alerts = _alerts("source")
    return _clean([{**r, "verified": channel_of.get(r["source_id"]) in fixes, "alert": alerts.get(r["source_id"])} for r in _rows("source_status")])


def data_quality() -> list[dict]:
    """The data-quality check results (M2)."""
    return _rows("data_quality")


def audit() -> list[dict]:
    """The audit log, newest first (M6)."""
    return _clean(decisions_engine.get_audit())


def learning() -> dict:
    """M7's learning report. Read-only: an unseeded history is seeded in memory only (the loop seeds it for real)."""
    return _clean(learning_loop.preview_report())


# ---------------------------------------------------------------------------
# Decisions
# ---------------------------------------------------------------------------
def pending_recommendations() -> dict:
    """STRICTLY READ-ONLY inbox (used by the M8 agent): the pending decisions from state if any, else a fresh build
    that is never saved."""
    state = load_state()
    pending = [d for d in state["decisions"] if d["status"] == "pending"]
    if pending:
        recs, objective = pending, state.get("objective")
        summary = {"count": len(recs), "total_expected_profit_delta": round(sum(d["expected_profit_delta"] for d in recs), 2),
                   "needs_approval": sum(d["requires_approval"] and not d["blocked"] for d in recs),
                   "auto_eligible": sum(not d["requires_approval"] and not d["blocked"] for d in recs),
                   "blocked": sum(d["blocked"] for d in recs)}
    else:
        built = decisions_engine.build_recommendations()
        recs, objective, summary = _clean(built["recommendations"]), built["objective"], _clean(built["summary"])
    return _clean({"objective": objective, "summary": summary, "recommendations": recs})


def _decorate(d: dict, factor: float) -> dict:
    """UI helpers on a decision: formatted ₹, the calibration factor applied, and its brain targets."""
    return {**d, "expected_profit_delta_fmt": m.format_inr(d["expected_profit_delta"]), "calibration_factor": factor,
            "targets": d["action"].get("targets", [])}


def _inbox(objective: str) -> dict:
    with STATE_LOCK:
        state = load_state()
        if not state["decisions"]:
            decisions_engine.refresh_decisions(objective, emit_brain_events=True)  # the first build, once
            state = load_state()
        factor = float((state.get("calibration") or {}).get("factor") or 1.0)
        if objective != state.get("objective"):  # a preview under another objective: built, never saved
            built = decisions_engine.build_recommendations(objective)
            recs = [_decorate(d, factor) for d in _clean(built["recommendations"])]
            return _clean({"objective": objective, "preview": True, "summary": _clean(built["summary"]), "recommendations": recs,
                           "pending": recs, "history": [], "calibration_factor": factor})
        inbox = decisions_engine.inbox(objective)
    pending = [_decorate(d, factor) for d in inbox["pending"]]
    history = [_decorate(d, factor) for d in inbox["history"]]
    return _clean({"objective": objective, "preview": False, "summary": inbox["summary"], "recommendations": pending + history,
                   "pending": pending, "history": history, "calibration_factor": factor})


def recommendations(objective: str | None = None) -> dict:
    """The MERGED Decision Inbox (pending first by priority, then history newest first) + summary, cached per objective.

    The first call on a state with no decisions builds them once (M6 refresh_decisions). Asking for an objective other
    than the saved one returns a `preview` built under it, without saving anything.
    """
    objective = objective or load_state().get("objective")
    if objective not in OBJECTIVES:
        raise ValueError(f"unknown objective {objective!r}; expected one of {OBJECTIVES}")
    return _cached(f"recs:{objective}", CACHE_TTL_RECOMMENDATIONS, lambda: _inbox(objective))


def _require_decision(rec_id: str) -> None:
    if not any(d["id"] == rec_id for d in load_state()["decisions"]):
        raise _not_found("decision", rec_id)


def approve(rec_id: str) -> dict:
    """Approve (execute) a decision through M6's guardrails. A blocked / already-executed decision returns {ok: False, reason}.
    On success the M7 outcome recorded by the hook is attached as `outcome`."""
    with STATE_LOCK:
        _require_decision(rec_id)
        res = decisions_engine.approve(rec_id, approver="user")
        invalidate()
        if res.get("ok"):
            res["outcome"] = next((o for o in load_state()["outcomes"] if o["decision_id"] == rec_id), None)
        return _clean(res)


def reject(rec_id: str) -> dict:
    """Reject a pending decision (M6)."""
    with STATE_LOCK:
        _require_decision(rec_id)
        res = decisions_engine.reject(rec_id, approver="user")
        invalidate()
        return _clean(res)


def rollback(rec_id: str) -> dict:
    """Roll back an executed decision, restoring the exact previous budgets (M6; M7 forgets its outcome)."""
    with STATE_LOCK:
        _require_decision(rec_id)
        res = decisions_engine.rollback(rec_id, approver="user")
        invalidate()
        return _clean(res)


# ---------------------------------------------------------------------------
# Optimizer
# ---------------------------------------------------------------------------
def optimize_plan(objective: str = "max_profit", total_budget: float | None = None) -> dict:
    """The M5 budget plan for an objective. An infeasible budget returns {ok: False, reason}."""
    if objective not in OBJECTIVES:
        raise ValueError(f"unknown objective {objective!r}; expected one of {OBJECTIVES}")
    res = optimizer.optimize(objective, total_budget)
    if not res["solver"]["ok"] and "infeasible" in res["solver"]["message"]:
        return {"ok": False, "reason": res["solver"]["message"]}
    return _clean({"ok": True, **res})


def _known_campaigns() -> set[str]:
    return set(fit_curves()["campaign_id"])


def simulate(plan: dict) -> dict:
    """What-if for any {campaign_id: spend} plan (M5). NOT cached: it must stay under SIMULATE_MAX_MS."""
    unknown = sorted(set(plan) - _known_campaigns())
    if unknown:
        raise _not_found("campaign", unknown)
    return _clean(optimizer.simulate({k: float(v) for k, v in plan.items()}))


def channel_simulate(multipliers: dict) -> dict:
    """What-if by channel, e.g. {"google": 1.2} (M5 simulator). Read-only."""
    unknown = sorted(set(multipliers) - set(CHANNELS))
    if unknown:
        raise _not_found("channel", unknown)
    return _clean(optimizer.channel_simulate({k: float(v) for k, v in multipliers.items()}))


def curves() -> list[dict]:
    """Per campaign response curve: a, b, current / optimal / saturation spend, marginal POAS, headroom, uncertainty and the chart points."""
    df = fit_curves()
    out = []
    for _, r in df.iterrows():
        out.append({"campaign_id": r["campaign_id"], "name": r["name"], "channel": r["channel"], "sku_id": r["sku_id"], "audience": r["audience"],
                    "a": r["a"], "b": r["b"], "current_spend": r["current_spend"], "marginal_poas": r["marginal_poas"],
                    "headroom": headroom_class(r["marginal_poas"], r["days_cover"]), "optimal_spend": r["optimal_spend"],
                    "saturation_spend": r["saturation_spend"], "uncertainty": r["uncertainty"], "days_cover": r["days_cover"],
                    "points": curve_points(r)})
    return _clean(out)


def _opportunities() -> dict:
    if table_exists("opportunities") and table_exists("model_metrics"):
        rows = read_table("opportunities").to_dict("records")
        r2 = float(read_table("model_metrics")["r2_holdout"].iloc[0])
    else:
        trained = opp.train()
        rows, r2 = opp.scored_rows(trained=trained), float(trained["r2_holdout"])
    return {"model_r2_holdout": r2, "rows": rows}


def opportunities() -> dict:
    """{model_r2_holdout, opportunities}: ranked untested combinations with ghost flags and whether a test was launched.
    Cached for CACHE_TTL_OPPORTUNITIES seconds (the model changes slowly)."""
    base = _cached("opportunities", CACHE_TTL_OPPORTUNITIES, _opportunities)
    running = {(t["sku_id"], t["channel"], t["audience"]): t for t in load_state().get("launched_tests", []) if t["status"] == "running"}
    out = []
    for r in base["rows"]:
        t = running.get((r["sku_id"], r["channel"], r["audience"]))
        out.append({**r, "is_ghost": bool(r["is_ghost"]), "launched": t is not None, "test_campaign_id": t["test_campaign_id"] if t else None})
    return _clean({"model_r2_holdout": base["model_r2_holdout"], "opportunities": out})


# ---------------------------------------------------------------------------
# Settings and ask
# ---------------------------------------------------------------------------
_NEXT_REFRESH: dict[str, str | None] = {"at": None}


def schedule_next_refresh(delay_seconds: float | None) -> None:
    """Called by whichever server runs the background loop: records when the next scheduled refresh will happen (None = not scheduled)."""
    _NEXT_REFRESH["at"] = None if delay_seconds is None else (_now() + timedelta(seconds=delay_seconds)).strftime("%Y-%m-%dT%H:%M:%S")


def get_settings() -> dict:
    """Autonomy, objective and the options, the refresh interval, demo mode, whether Claude is available (a boolean, never the key) and the last refresh."""
    s = load_state()
    from backend.agent import agent  # local: the agent imports this module

    agent._load_env()
    return _clean({"autonomy": s["autonomy"], "objective": s["objective"], "autonomy_modes": list(config.AUTONOMY_MODES),
                   "objectives": list(OBJECTIVES), "refresh_minutes": REFRESH_MINUTES, "demo_mode": DEMO_MODE,
                   "agent": {"claude_available": bool(os.getenv("ANTHROPIC_API_KEY"))}, "last_refresh_at": s.get("last_refresh_at"), "next_refresh_at": _NEXT_REFRESH["at"]})


def update_settings(autonomy: str | None = None, objective: str | None = None) -> dict:
    """Change autonomy and / or objective (validated by M6). A new objective rebuilds the pending decisions so the inbox and the brain arrows follow it."""
    with STATE_LOCK:
        if autonomy is not None:
            decisions_engine.set_autonomy(autonomy)
        if objective is not None:
            changed = objective != load_state()["objective"]
            decisions_engine.set_objective(objective)
            if changed:
                decisions_engine.refresh_decisions(objective, emit_brain_events=True)
        invalidate()
        return get_settings()


def ask(question: str) -> dict:
    """Ask the AI agent (M8): Claude with the engine's tools if a key is set, otherwise the offline rules engine."""
    from backend.agent import agent

    return _clean(agent.answer(question))


# ---------------------------------------------------------------------------
# The closed loop
# ---------------------------------------------------------------------------
def refresh(emit_brain_events: bool = True) -> dict:
    """Run the whole engine once: ingest → detect → diagnose → optimise → decide → learn.

    Inside STATE_LOCK; each step is wrapped so one failure is logged and the rest still run. ok is True only if every
    step succeeded; errors are never raised.
    """
    started = time.perf_counter()
    steps: dict[str, dict] = {}
    results: dict[str, Any] = {}

    def step(name: str, fn: Callable[[], Any]) -> None:
        t0 = time.perf_counter()
        seq0 = load_state()["brain_event_seq"]
        try:
            results[name] = fn()
            steps[name] = {"ok": True, "duration_ms": round((time.perf_counter() - t0) * 1000, 1)}
        except Exception as exc:  # noqa: BLE001  one failing step must not stop the loop
            _log.exception("refresh step %s failed", name)
            steps[name] = {"ok": False, "duration_ms": round((time.perf_counter() - t0) * 1000, 1), "error": f"{type(exc).__name__}: {exc}"}
        steps[name]["events"] = load_state()["brain_event_seq"] - seq0

    with STATE_LOCK:
        seq_before = load_state()["brain_event_seq"]
        step("ingest", lambda: run_pipeline(verbose=False, emit_brain_events=emit_brain_events))
        invalidate()
        step("detect", lambda: run_detection(emit_brain_events=emit_brain_events, verbose=False))
        step("diagnose", lambda: run_diagnosis(emit_brain_events=emit_brain_events, verbose=False))
        step("optimize", lambda: run_optimizer(verbose=False))
        step("decide", lambda: decisions_engine.refresh_decisions(load_state()["objective"], emit_brain_events=emit_brain_events))
        step("learn", lambda: record_outcomes(emit_brain_events=emit_brain_events))
        invalidate()
        events = load_state()["brain_event_seq"] - seq_before
        decide = results.get("decide") or {}
        result = _clean({"ok": all(s["ok"] for s in steps.values()), "steps": steps, "auto_applied": decide.get("auto_applied", []),
                         "outcomes_measured": len(results.get("learn") or []), "events_logged": events,
                         "duration_ms": round((time.perf_counter() - started) * 1000, 1)})
        try:
            state = load_state()
            state["last_refresh_at"] = _ts()
            state["last_refresh"] = {"at": state["last_refresh_at"], **{k: result[k] for k in ("ok", "steps", "auto_applied", "outcomes_measured", "events_logged", "duration_ms")}}
            save_state(state)
        except Exception:  # noqa: BLE001
            _log.exception("could not record last_refresh")
    return result


def last_refresh() -> dict | None:
    """The compact summary of the most recent loop run (None if it never ran)."""
    return _clean(load_state().get("last_refresh"))


_CONFIG_GROUPS = {
    "detection": ("RECENT_DAYS", "BASELINE_DAYS", "Z_THRESHOLD", "MIN_PCT_CHANGE", "STOCK_COVER_RISK_DAYS", "SKU_RECENT_DAYS", "SKU_BASELINE_DAYS"),
    "guardrails": ("AUTO_APPLY_MAX_SHIFT", "DAILY_CHANGE_CAP", "STOCK_SPEND_CAP_MULT", "RISK_HIGH_SHIFT", "RISK_HIGH_IMPACT", "RISK_MEDIUM_SHIFT",
                   "CONFIDENCE_MIN", "CONFIDENCE_MAX"),
    "optimizer": ("OVERSTOCK_COVER_DAYS", "LAUNCH_TEST_RESERVE", "OPP_TEST_BUDGET"),
    "learning": ("CALIBRATION_WINDOW", "CALIBRATION_MIN", "CALIBRATION_MAX"),
}


def meta_config() -> dict:
    """Read-only, non-secret engine settings (thresholds the UI explains), grouped; never environment values other than the refresh interval."""
    out = {g: {k: getattr(config, k) for k in keys} for g, keys in _CONFIG_GROUPS.items()}
    out["loop"] = {"REFRESH_MINUTES": config.REFRESH_MINUTES}
    out["currency"] = config.CURRENCY
    return _clean(out)


# ---------------------------------------------------------------------------
# Brain
# ---------------------------------------------------------------------------
def brain_manifest() -> dict:
    """The static brain structure (sources, clusters, neurons, synapses, stimuli, scenario timeline, hero story)."""
    return _clean(load_manifest())


def _first_sentence_of_top_diagnosis(ids: list[str], impact: dict, kind: dict, narrative: dict) -> str | None:
    if not ids:
        return None
    top = max(ids, key=lambda i: abs(impact.get(i, 0.0)))
    if top not in narrative:
        return None
    return lead_sentence(SimpleNamespace(narrative=narrative[top]), kind.get(top, ""))


def brain_nodes() -> dict:
    """{as_of, objective, nodes}: the 26 neurons (M0 NeuronNode fields) enriched with alert, headroom, planned change,
    current spend and a one-line "why", sorted by 7-day spend, at most BRAIN_MAX_NEURONS."""
    state = load_state()
    objective = state["objective"]
    nm = read_table("neuron_metrics")
    alerts = _alerts("neuron")
    cur = fit_curves().set_index("campaign_id")
    sku_spend = cur.groupby("sku_id")["current_spend"].sum()
    plans = {}
    if table_exists("budget_plans"):
        bp = read_table("budget_plans")
        plans = bp[bp["objective"] == objective].set_index("campaign_id")["change_pct"].to_dict()
    an = {a["id"]: a for a in anomalies()}
    impact, kind = {i: a["profit_impact"] for i, a in an.items()}, {i: a["kind"] for i, a in an.items()}
    narrative = {r["anomaly_id"]: r["narrative"] for r in _rows("diagnoses")}
    nodes = []
    for r in nm.to_dict("records"):
        cid, is_campaign = r["entity_id"], r["entity_type"] == "campaign"
        al = alerts.get(cid)
        ids = al["anomaly_ids"] if al else []
        top_id = max(ids, key=lambda i: abs(impact.get(i, 0.0))) if ids else None
        node = {
            **{k: r[k] for k in ("entity_id", "entity_type", "label", "cluster", "channel", "sku_id", "spend_7d", "poas_7d", "profit_7d",
                                 "change_pct", "health", "size", "roas_platform_7d", "roas_true_7d", "trust_score", "days_cover")},
            "is_alerting": al is not None, "anomaly_id": top_id, "anomaly_ids": ids,
            "alert_kind": al["top_kind"] if al else None, "alert_severity": al["top_severity"] if al else None,
            "alert_direction": al["direction"] if al else None, "stock_locked": bool(al and al["stock_locked"]),
            "alert_message": al["message"] if al else None,
            "headroom": headroom_class(cur.at[cid, "marginal_poas"], cur.at[cid, "days_cover"]) if is_campaign else None,
            "marginal_poas": cur.at[cid, "marginal_poas"] if is_campaign else None,
            "planned_change_pct": plans.get(cid),
            "current_spend": cur.at[cid, "current_spend"] if is_campaign else float(sku_spend.get(cid, 0.0)),
            "why": _first_sentence_of_top_diagnosis(ids, impact, kind, narrative),
        }
        nodes.append(node)
    nodes.sort(key=lambda n: -n["spend_7d"])
    return _clean({"as_of": _as_of(), "objective": objective, "nodes": nodes[:BRAIN_MAX_NEURONS]})


def _counts(state: dict) -> dict:
    d = state["decisions"]
    return {"anomalies": len(anomalies()), "pending_decisions": sum(x["status"] == "pending" for x in d),
            "executed": sum(x["status"] == "executed" for x in d), "outcomes": len(state["outcomes"])}


def brain_snapshot() -> dict:
    """ONE call with everything the brain renders: nodes, clusters, sources, ghosts, synapses with learned strengths,
    the before / after headline and counts."""
    state = load_state()
    manifest = load_manifest()
    nodes = brain_nodes()
    cluster_alerts, source_alerts = _alerts("cluster"), _alerts("source")
    fixes = state.get("data_fixes", {})
    status = {r["source_id"]: r for r in _rows("source_status")}
    srcs = [{"id": s["id"], "label": s["label"], "kind": s["kind"], "channel": s["channel"], "status": status.get(s["id"], {}).get("status"),
             "trust_score": status.get(s["id"], {}).get("trust_score"), "inflation_pct": status.get(s["id"], {}).get("inflation_pct"),
             "verified": s["channel"] in fixes, "alert": source_alerts.get(s["id"])} for s in manifest["sources"]]
    clusters = [{"id": c["id"], "label": c["label"], "alert": cluster_alerts.get(c["id"])} for c in manifest["clusters"]]
    ghosts = [{"id": o["label"], "sku_id": o["sku_id"], "channel": o["channel"], "cluster": o["cluster"], "audience": o["audience"],
               "predicted_poas": o["predicted_poas"], "score": o["score"], "launched": o["launched"], "test_campaign_id": o["test_campaign_id"]}
              for o in opportunities()["opportunities"] if o["is_ghost"]]
    strength = state.get("synapse_strength", {})
    synapses = [{**e, "strength": strength.get(f"{e['source']}->{e['target']}", SYNAPSE_BASE)} for e in manifest["synapses"]]
    synapses += [{"source": t["test_campaign_id"], "target": t["sku_id"], "kind": "promotes", "test": True,
                  "strength": strength.get(f"{t['test_campaign_id']}->{t['sku_id']}", SYNAPSE_BASE)}
                 for t in state.get("launched_tests", []) if t["status"] == "running"]
    plan = next((r for r in _rows("plan_summaries") if r["objective"] == state["objective"]), None)
    headline = {"current_profit": plan["current_profit"] if plan else None, "planned_profit": plan["planned_profit"] if plan else None,
                "profit_delta": plan["profit_delta"] if plan else None, "data_trust": kpis()["data_trust"],
                "detection_quality": state.get("detection_quality") or None, "calibration": state.get("calibration")}
    return _clean({"as_of": nodes["as_of"], "objective": state["objective"], "autonomy": state["autonomy"], "nodes": nodes["nodes"],
                   "clusters": clusters, "sources": srcs, "ghosts": ghosts, "synapses": synapses, "headline": headline, "counts": _counts(state)})


def brain_events(since: str | None = None, limit: int = 100) -> dict:
    """{events, last_id}: the brain events after `since` (oldest first, at most `limit`); with no `since`, the latest `limit`."""
    events = read_brain_events(since_id=since, limit=limit)
    return _clean({"events": events, "last_id": events[-1]["id"] if events else since})


def brain_state() -> dict:
    """M0 BrainState: mode = EVENT_MODE of the latest event if it is newer than BRAIN_MODE_WINDOW_SECONDS, else "idle"."""
    latest = (read_brain_events(limit=1) or [None])[0]
    counts = _counts(load_state())
    mode, region = "idle", None
    if latest is not None:
        age = (_now() - datetime.strptime(latest["ts"], "%Y-%m-%dT%H:%M:%S")).total_seconds()
        if age <= BRAIN_MODE_WINDOW_SECONDS:
            mode, region = EVENT_MODE[latest["type"]], latest["region"]
    return _clean({"mode": mode, "active_region": region, "last_event_id": latest["id"] if latest else None,
                   "counts": {"anomalies": counts["anomalies"], "pending_decisions": counts["pending_decisions"], "outcomes": counts["outcomes"]}})


def brain_replay() -> dict:
    """Log a SCRIPTED sequence of fresh brain events (payload "replay": true) built from CURRENT data, without changing
    any decision: an ingest summary; per scenario in replay order its anomaly + diagnosis pulses; a recommendation
    pulse for each pending decision the hero story points at; and the latest real outcome. The UI plays them in id order."""
    manifest = load_manifest()
    channel_of = {n["entity_id"]: n["channel"] for n in manifest["neurons"] if n["channel"]}
    with STATE_LOCK:
        state = load_state()
        found = detect_all()
        roots = {a.id: rc for a, rc in zip(found, diagnose_all(found))}
        logged = []

        def emit(*args, **kw):
            logged.append(log_brain_event(make_brain_event(*args, **kw)))

        emit("ingest", severity="low", message=f"Ingestion complete · data trust {kpis()['data_trust']:.0%}",
             payload={"replay": True, "data_trust": kpis()["data_trust"]})
        timeline = {s["scenario"]: s for s in manifest["scenario_timeline"]}
        for sid in manifest["replay_order"]:
            sc = timeline[sid]
            if sc["expected_event_type"] != "anomaly":
                continue
            ent = set(sc["entities"]) | {channel_of[e] for e in sc["entities"] if e in channel_of}
            for a in (x for x in found if x.kind == sc["expected_kind"] and x.entity_id in ent):
                rc = roots[a.id]
                top = _top_factor(rc.factors, rc.total_change) if rc.factors else None
                emit("anomaly", entity_id=a.entity_id, ref_id=a.id, severity=a.severity, message=f"{a.label} — {change_text(a)}",
                     payload={"replay": True, "scenario": sid, "key": f"{a.kind}:{a.entity_id}", "kind": a.kind, "entity_type": a.entity_type,
                              "direction": a.detail["direction"], "change_pct": a.change_pct, "z": a.z, "profit_impact": a.profit_impact,
                              "targets": [t["target_id"] for t in targets_for(a, manifest)]})
                emit("diagnosis", entity_id=a.entity_id, ref_id=a.id, severity=a.severity, message=lead_sentence(rc, a.kind),
                     payload={"replay": True, "scenario": sid, "anomaly_key": f"{a.kind}:{a.entity_id}", "top_factor": top.name if top else None,
                              "top_factor_pct": top.pct if top else None, "total_change": rc.total_change,
                              "factors": [{"name": f.name, "impact": f.impact} for f in rc.factors], "related": a.detail.get("related", []),
                              "has_waterfall": bool(rc.factors)})
        pending = [d for d in state["decisions"] if d["status"] == "pending"]
        done = set()
        for st in manifest["hero_story"]["steps"]:
            focus = st["focus"]
            ghost = focus[len("ghost: "):] if focus.startswith("ghost: ") else None
            for d in pending:
                targets = d["action"].get("targets", [])
                hit = any(t["type"] == "ghost" and t["id"] == ghost for t in targets) if ghost else any(t["id"] == focus for t in targets)
                if hit and d["id"] not in done:
                    done.add(d["id"])
                    sev = "high" if d["risk"] == "high" or d["blocked"] else ("medium" if d["risk"] == "medium" else "low")
                    emit("recommendation", entity_id=targets[0]["id"] if targets else None, ref_id=d["id"], severity=sev,
                         message=f"{d['title']} — {m.format_inr(d['expected_profit_delta'])}/day · {round(d['confidence'] * 100)}% confidence",
                         payload={"replay": True, "step": st["step"], "rec_id": d["id"], "action_type": d["action"]["type"], "targets": targets,
                                  "expected_profit_delta": d["expected_profit_delta"], "confidence": d["confidence"], "risk": d["risk"],
                                  "requires_approval": d["requires_approval"], "blocked": d["blocked"], "campaigns": d["action"]["changes"]})
        real = [o for o in state["outcomes"] if not o.get("seeded")]
        if real:
            o = real[-1]
            emit("outcome", entity_id=(o["campaigns"] or [None])[0], ref_id=o["decision_id"], severity="low", message=_outcome_message(o),
                 payload={"replay": True, "decision_id": o["decision_id"], "predicted": o["predicted"], "actual": o["actual"],
                          "error_pct": o["error_pct"], "simulated": True, "measurable": o["measurable"]})
    return _clean({"ok": True, "events_queued": len(logged), "first_id": logged[0].id, "last_id": logged[-1].id})


def demo_reset() -> dict:
    """Demo only (DEMO_MODE): delete state.json, clear the caches and run the loop once for a clean demo with the seeded
    learning history and fresh pulses. Returns the refresh result."""
    if not DEMO_MODE:
        return {"ok": False, "reason": "Demo reset is disabled (set DEMO_MODE=true)"}
    with STATE_LOCK:
        reset_state()
        invalidate()
        return refresh()


# ---------------------------------------------------------------------------
# Helpers kept from M8
# ---------------------------------------------------------------------------
def brain_targets_for(entity_ids: list[str]) -> list[dict]:
    """Map entity ids to brain targets: campaign / SKU ids → neuron, channel names → cluster, ad source ids → source.

    Unknown ids are ignored; duplicates are removed (order kept).
    """
    manifest = load_manifest()
    neurons = {n["entity_id"] for n in manifest["neurons"]}
    clusters = {c["id"] for c in manifest["clusters"]}
    sources_ = {s["id"] for s in manifest["sources"]}
    display = {v.lower(): k for k, v in CHANNEL_DISPLAY.items()}
    out, seen = [], set()
    for raw in entity_ids:
        e = str(raw)
        for kind_, ok, tid in (("neuron", e in neurons, e), ("cluster", e in clusters or e.lower() in clusters, e.lower()),
                               ("cluster", e.lower() in display, display.get(e.lower())), ("source", e in sources_, e)):
            if ok and (kind_, tid) not in seen:
                seen.add((kind_, tid))
                out.append({"type": kind_, "id": tid})
                break
    return out


def json_safe(obj: Any) -> str:
    """json.dumps that can never fail (used by tests and the agent)."""
    return json.dumps(_clean(obj), allow_nan=False)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> None:
    import argparse

    p = argparse.ArgumentParser(description="M9 service layer")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--refresh", action="store_true", help="run the closed loop once")
    g.add_argument("--snapshot", action="store_true", help="print the brain snapshot as JSON")
    g.add_argument("--replay", action="store_true", help="log the scripted brain replay")
    g.add_argument("--reset", action="store_true", help="demo reset: delete state and refresh (DEMO_MODE only)")
    g.add_argument("--kpis", action="store_true", help="print the KPIs as JSON")
    args = p.parse_args(argv)
    if args.snapshot:
        print(json.dumps(brain_snapshot(), indent=2, ensure_ascii=False))
    elif args.kpis:
        print(json.dumps(kpis(), indent=2, ensure_ascii=False))
    elif args.replay:
        r = brain_replay()
        print(f"replay ok · {r['events_queued']} events · {r['first_id']} → {r['last_id']}")
    else:
        r = demo_reset() if args.reset else refresh()
        if not r["ok"] and "steps" not in r:
            print(f"reset refused · {r['reason']}")
            return
        print(f"{'reset + ' if args.reset else ''}refresh {'ok' if r['ok'] else 'FAILED'} · {len(r['steps'])} steps · events {r['events_logged']} · "
              f"{r['duration_ms'] / 1000:.1f}s")
        for name, s in r["steps"].items():
            print(f"  {name:<9}{'ok' if s['ok'] else 'FAILED'}  {s['duration_ms']:>7.0f} ms" + (f"  {s['error']}" if not s["ok"] else ""))
        print(f"  auto-applied: {r['auto_applied'] or 'none'} · outcomes measured: {r['outcomes_measured']}")


if __name__ == "__main__":
    main()
