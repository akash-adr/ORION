"""M3 entry point: detect → persist → map onto the brain → evaluate → pulse the Diagnose lobe.

run_detection() is what M9's /refresh calls. Brain events are deduplicated: an anomaly pulses only when
its key is new, its severity got worse, or its |₹ impact| grew by more than IMPACT_GROWTH since last seen.
"""
from __future__ import annotations

import time
from datetime import datetime
from zoneinfo import ZoneInfo

from backend.core.db import load_state, log_brain_event, save_state
from backend.core.schema import Anomaly, make_brain_event, to_dict
from backend.detection import store
from backend.detection.detectors import detect_all
from backend.detection.evaluate import evaluate

IMPACT_GROWTH = 0.25  # re-pulse when |profit_impact| grows by more than 25% since last seen
MINUS = "−"


def now_ist() -> str:
    """Current IST time as "YYYY-MM-DDTHH:MM:SS"."""
    return datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%dT%H:%M:%S")


def _pct(x: float) -> str:
    return f"{'+' if x >= 0 else MINUS}{abs(x):.0%}"


def change_text(a: Anomaly) -> str:
    """Short human text for the brain event, e.g. "CTR −37%"."""
    return {
        "creative_fatigue": lambda: f"CTR {_pct(a.change_pct)}",
        "metric_shift": lambda: f"profit {_pct(a.change_pct)}",
        "positive_spike": lambda: f"profit {_pct(a.change_pct)}",
        "cpc_spike": lambda: f"CPC {_pct(a.change_pct)}",
        "stockout_risk": lambda: f"{a.detail['days_cover']:.1f} days of cover left",
        "conversion_drop": lambda: f"site CVR {_pct(a.change_pct)}",
        "attribution_inflation": lambda: f"platform reports {_pct(a.change_pct)} conversions",
    }[a.kind]()


def should_pulse(a: Anomaly, previous: dict | None) -> bool:
    """New key, worse severity, or |impact| grown by more than IMPACT_GROWTH since last seen."""
    if previous is None:
        return True
    if store.SEVERITY_RANK[a.severity] > store.SEVERITY_RANK[previous["severity"]]:
        return True
    old = abs(previous.get("profit_impact", 0.0))
    return old > 0 and abs(a.profit_impact) > old * (1 + IMPACT_GROWTH)


def run_detection(as_of: str | None = None, emit_brain_events: bool = True, verbose: bool = True) -> dict:
    """Detect, persist the tables, evaluate against the answer key and (optionally) pulse the brain.

    emit_brain_events=False logs nothing and leaves state.json untouched (validation and tests use this).
    """
    start = time.perf_counter()
    as_of = as_of or now_ist()
    anomalies = detect_all()
    manifest = store.load_manifest()
    store.write_anomalies(anomalies, as_of)
    alerts = store.build_brain_alerts(anomalies, manifest)
    store.write_brain_alerts(alerts)
    quality = evaluate(anomalies, evaluated_at=as_of)

    logged, resolved = [], []
    if emit_brain_events:
        state = load_state()
        active = dict(state.get("active_anomalies", {}))
        current = {}
        for a in anomalies:  # ranked order
            key = store.anomaly_key(a)
            previous = active.get(key)
            if should_pulse(a, previous):
                targets = [t["target_id"] for t in store.targets_for(a, manifest)]
                ev = make_brain_event(
                    "anomaly", entity_id=a.entity_id, ref_id=a.id, severity=a.severity,
                    message=f"{a.label} — {change_text(a)}",
                    payload={"key": key, "kind": a.kind, "entity_type": a.entity_type,
                             "direction": a.detail["direction"], "change_pct": a.change_pct, "z": a.z,
                             "profit_impact": a.profit_impact, "targets": targets,
                             "related": a.detail.get("related", [])})
                logged.append(log_brain_event(ev))
            current[key] = {"id": a.id, "kind": a.kind, "entity_id": a.entity_id, "severity": a.severity,
                            "first_seen": previous["first_seen"] if previous else as_of, "last_seen": as_of,
                            "profit_impact": a.profit_impact}
        resolved = sorted(set(active) - set(current))
        # log_brain_event saved the event log; reload so those writes are kept, then update our keys
        state = load_state()
        state["active_anomalies"] = current
        state["detection_quality"] = quality
        save_state(state)

    severities = {s: sum(a.severity == s for a in anomalies) for s in ("high", "medium", "low")}
    directions = {d: sum(a.detail["direction"] == d for a in anomalies) for d in ("loss", "gain")}
    summary = {
        "anomalies": [to_dict(a) for a in anomalies],
        "counts": {"total": len(anomalies), "severity": severities, "direction": directions},
        "brain_alerts": int(len(alerts)),
        "events_logged": len(logged),
        "event_messages": [e.message for e in logged],
        "resolved": resolved,
        "quality": quality,
        "duration_ms": round((time.perf_counter() - start) * 1000, 1),
    }
    if verbose:
        print_report(summary)
    return summary


def print_report(s: dict) -> None:
    """The alert table plus the evaluation line."""
    from backend.core import metrics as m  # local: keeps module import light

    print(f"{'ID':<7}{'kind':<23}{'entity':<10}{'change':>9}{'stat':>10}{'₹/day':>11}  {'severity':<9}direction")
    for a in s["anomalies"]:
        stat = (f"t={a['z']:.2f}" if a["kind"] == "conversion_drop"
                else "—" if a["kind"] == "attribution_inflation" else f"z={a['z']:.2f}")
        print(f"{a['id']:<7}{a['kind']:<23}{a['entity_id']:<10}{a['change_pct']:>+9.1%}{stat:>10}"
              f"{m.format_inr(a['profit_impact']):>11}  {a['severity']:<9}{a['detail']['direction']}")
    c, q = s["counts"], s["quality"]
    print(f"M3 OK · {c['total']} anomalies · {c['severity']['high']} high · {c['severity']['medium']} medium · "
          f"{c['severity']['low']} low · {s['duration_ms'] / 1000:.1f}s")
    knock = ", ".join(k["entity_id"] for k in q["knock_on"]) or "none"
    print(f"Planted scenarios detected: {q['found']}/{q['expected']} · precision {q['precision']:.2f} · "
          f"knock-on: {knock} · false alarms: {len(q['false_alarms'])} · events logged: {s['events_logged']}")
