"""M4 / M4b entry point: diagnose → persist → pulse the Diagnose lobe's "thinking" step.

run_diagnosis() is what M9's /refresh calls after M3. Brain events are deduplicated: a diagnosis pulses only
when its anomaly key is new in state["active_diagnoses"] or its signature (top factor | total change rounded
to ₹100) changed. emit_brain_events=False logs nothing and leaves state.json untouched.
"""
from __future__ import annotations

import time
from datetime import datetime
from zoneinfo import ZoneInfo

from backend.core import metrics as m
from backend.core.db import load_state, log_brain_event, read_table, save_state
from backend.core.schema import Anomaly, RootCause, make_brain_event, to_dict
from backend.detection.detectors import detect_all
from backend.detection.store import anomaly_key
from backend.diagnosis import store
from backend.diagnosis.causal import compute_causal
from backend.diagnosis.decompose import _top_factor, causal_event_id, diagnose_all, lead_sentence, print_report


def now_ist() -> str:
    """Current IST time as "YYYY-MM-DDTHH:MM:SS"."""
    return datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%dT%H:%M:%S")


def signature(a: Anomaly, rc: RootCause) -> str:
    """f"{top_factor}|{round(total_change, -2)}": changes when the main cause or the size materially moves."""
    top = _top_factor(rc.factors, rc.total_change) if rc.factors else None
    return f"{top.name if top else None}|{round(rc.total_change, -2)}"


def causal_signature(d: dict) -> str:
    r = d["result"]
    return f"{round(d['units_change_pct'], 2)}|{round(r.effect_per_day, -2)}"


def causal_message(d: dict, sku_name: str) -> str:
    """"Causal proof · Casual X price rise: units −25% vs counterfactual, net margin ₹E/day (95% CI includes zero)"."""
    r = d["result"]
    rise = d["new_price"] >= d["old_price"]
    pct = f"{'+' if d['units_change_pct'] >= 0 else chr(0x2212)}{abs(d['units_change_pct']) * 100:.0f}%"
    ci = "includes zero" if r.ci_low < 0 < r.ci_high else "excludes zero"
    return (f"Causal proof · {sku_name} price {'rise' if rise else 'cut'}: units {pct} vs counterfactual, "
            f"net margin {m.format_inr(r.effect_per_day)}/day (95% CI {ci})")


def run_diagnosis(as_of: str | None = None, emit_brain_events: bool = True, verbose: bool = True) -> dict:
    """Diagnose every M3 anomaly, run M4b for price-driven conversion drops, persist and (optionally) pulse."""
    start = time.perf_counter()
    as_of = as_of or now_ist()
    anomalies = detect_all()
    causal = compute_causal(anomalies)
    roots = diagnose_all(anomalies, causal)
    store.write_diagnoses(anomalies, roots, as_of, causal)
    store.write_causal(list(causal.values()), as_of)
    sums_ok = sum(rc.check_sum(tol=max(1.0, abs(rc.total_change) * 0.01)) for rc in roots)

    logged, resolved = [], []
    if emit_brain_events:
        state = load_state()
        active = dict(state.get("active_diagnoses", {}))
        current: dict[str, str] = {}
        for a, rc in zip(anomalies, roots):  # ranked order
            key, sig = anomaly_key(a), signature(a, rc)
            current[key] = sig
            if active.get(key) == sig:
                continue
            top = _top_factor(rc.factors, rc.total_change) if rc.factors else None
            ev = make_brain_event(
                "diagnosis", entity_id=a.entity_id, ref_id=a.id, severity=a.severity,
                message=lead_sentence(rc, a.kind),
                payload={"anomaly_key": key, "top_factor": top.name if top else None,
                         "top_factor_pct": top.pct if top else None, "total_change": rc.total_change,
                         "factors": [{"name": f.name, "impact": f.impact} for f in rc.factors],
                         "related": a.detail.get("related", []), "causal_event_id": causal_event_id(a, causal),
                         "has_waterfall": bool(rc.factors)})
            logged.append(log_brain_event(ev))
        sku_names = read_table("dim_sku").set_index("sku_id")["name"]
        for eid, d in causal.items():  # one extra "causal proof" pulse per computed event
            key, sig = f"causal:{eid}", causal_signature(d)
            current[key] = sig
            if active.get(key) != sig:
                r = d["result"]
                ev = make_brain_event(
                    "diagnosis", entity_id=d["treated_sku"], ref_id=eid, severity="medium",
                    message=causal_message(d, sku_names[d["treated_sku"]]),
                    payload={"event_id": eid, "effect_per_day": r.effect_per_day, "total_effect": r.total_effect,
                             "ci_low": r.ci_low, "ci_high": r.ci_high, "units_change_pct": d["units_change_pct"]})
                logged.append(log_brain_event(ev))
        resolved = sorted(set(active) - set(current))
        state = load_state()  # log_brain_event saved the event log; reload so those writes are kept
        state["active_diagnoses"] = current
        save_state(state)

    summary = {
        "diagnoses": len(roots), "sum_checks_passed": int(sums_ok),
        "causal": [{"event_id": eid, "treated_sku": d["treated_sku"], "effect_per_day": d["result"].effect_per_day,
                    "total_effect": d["result"].total_effect, "ci_low": d["result"].ci_low,
                    "ci_high": d["result"].ci_high, "units_change_pct": d["units_change_pct"],
                    "controls": d["controls"], "weights": d["weights"], "excluded": d["excluded"],
                    "pre_fit_rmse": d["pre_fit_rmse"]} for eid, d in causal.items()],
        "events_logged": len(logged), "event_messages": [e.message for e in logged], "resolved": resolved,
        "duration_ms": round((time.perf_counter() - start) * 1000, 1),
        "_anomalies": anomalies, "_roots": roots,
    }
    if verbose:
        print_run(summary)
    return summary


def print_run(s: dict) -> None:
    """The decompose table, then the causal summary and the event count."""
    print_report(s["_anomalies"], s["_roots"], s["duration_ms"] / 1000)
    for c in s["causal"]:
        print(f"\nCausal {c['event_id']} ({c['treated_sku']}): units {c['units_change_pct']:+.1%} vs counterfactual · "
              f"net margin {m.format_inr(c['effect_per_day'])}/day · total {m.format_inr(c['total_effect'])} · "
              f"95% CI {m.format_inr(c['ci_low'])} to {m.format_inr(c['ci_high'])}")
        print(f"    controls: {', '.join(c['controls'])} · excluded: "
              f"{', '.join(f'{k} ({v})' for k, v in c['excluded'].items()) or 'none'}")
        print(f"    weights: {', '.join(f'{k} {v:.3f}' for k, v in c['weights'].items() if v > 0)} · "
              f"pre-fit RMSE {c['pre_fit_rmse']:.5f}")
    print(f"\nevents logged: {s['events_logged']}")


def main(argv: list[str] | None = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(description="M4 root-cause diagnosis + M4b causal analysis")
    parser.add_argument("--no-brain-events", action="store_true", help="do not log diagnosis brain events")
    args = parser.parse_args(argv)
    run_diagnosis(emit_brain_events=not args.no_brain_events)


if __name__ == "__main__":
    main()
