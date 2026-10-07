"""M3 validation. Run from the project root:  python -m backend.detection.validate

Runs detection with emit_brain_events=False on the current data and prints a PASS/FAIL table; exit 1 on
any failure. Each check is `check_*(ctx) -> (ok, detail)` so tests/test_m3.py can reuse them.
"""
from __future__ import annotations

import json
import re
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable

from backend.core import config
from backend.core.config import ANOMALY_KINDS, ENTITY_TYPES, ID_PATTERNS, SEVERITIES
from backend.core.db import load_state, read_brain_events, read_table, validate_table
from backend.detection.detectors import detect_all
from backend.detection.evaluate import evaluate, expected_pairs, load_ground_truth
from backend.detection.runner import run_detection

FIXED_AS_OF = "2026-10-06T23:00:00"
MAX_FALSE_ALARMS = 0  # every extra alert must be a classified knock-on
MAX_RUNTIME_S = 1.0
CPC_RANGE = (0.45, 0.75)
PRICE_CHANGE_TARGET, PRICE_CHANGE_TOL = 0.15, 0.02


def build_context() -> dict:
    """Run detection once without brain events; keep the alert dicts and the written tables."""
    result = run_detection(as_of=FIXED_AS_OF, emit_brain_events=False, verbose=False)
    return {"result": result, "alerts": result["anomalies"],
            "tables": {t: read_table(t) for t in ("anomalies", "brain_alerts")}}


def _find(ctx: dict, kind: str, entity: str) -> dict | None:
    return next((a for a in ctx["alerts"] if a["kind"] == kind and a["entity_id"] == entity), None)


# ---------------------------------------------------------------------------
def check_planted_detected(ctx):
    pairs = [p for ps in expected_pairs(load_ground_truth()).values() for p in ps]
    missing = [p for p in pairs if _find(ctx, *p) is None]
    return not missing, f"{len(pairs) - len(missing)}/{len(pairs)} planted pairs" + (f" · missing {missing}" if missing else "")


def check_false_alarms(ctx):
    q = ctx["result"]["quality"]
    fa = q["false_alarms"]
    names = ", ".join(f"{a['kind']}:{a['entity_id']}" for a in fa) or "none"
    knock = ", ".join(f"{k['entity_id']} ({k['scenario']})" for k in q["knock_on"]) or "none"
    return len(fa) <= MAX_FALSE_ALARMS, f"{len(fa)} false alarms ({names}) · knock-on: {knock}"


def check_sorted(ctx):
    impacts = [abs(a["profit_impact"]) for a in ctx["alerts"]]
    return impacts == sorted(impacts, reverse=True), "sorted by |₹ impact| descending"


def check_shapes(ctx):
    bad = []
    for a in ctx["alerts"]:
        ok = (a["kind"] in ANOMALY_KINDS and a["entity_type"] in ENTITY_TYPES and a["severity"] in SEVERITIES
              and re.match(ID_PATTERNS["anomaly"], a["id"]) and a["detail"].get("direction") in ("loss", "gain")
              and set(a["detail"].get("window", {})) == {"recent_start", "recent_end", "baseline_start", "baseline_end"})
        if not ok:
            bad.append(a["id"])
    return not bad, f"{len(ctx['alerts'])} alerts valid" if not bad else f"invalid: {bad}"


def check_severities(ctx):
    sb = _find(ctx, "stockout_risk", "SKU-B")
    attr = [_find(ctx, "attribution_inflation", ch) for ch in ("meta", "google")]
    ok = sb and sb["severity"] == "high" and all(a and a["severity"] == "medium" for a in attr)
    return bool(ok), "SKU-B stockout high · meta/google attribution medium"


def check_directions(ctx):
    bad = [a["id"] for a in ctx["alerts"]
           if a["detail"]["direction"] != ("gain" if (a["kind"], a["entity_id"]) == ("positive_spike", "CMP-10") else "loss")]
    spike = _find(ctx, "positive_spike", "CMP-10")
    return not bad and spike is not None, "CMP-10 gain, all others loss" if not bad else f"wrong: {bad}"


def check_fatigue_dedupe(ctx):
    fatigue = _find(ctx, "creative_fatigue", "CMP-01")
    dup = _find(ctx, "metric_shift", "CMP-01")
    return fatigue is not None and dup is None, "fatigue present, no duplicate metric_shift for CMP-01"


def check_price_link(ctx):
    a = _find(ctx, "conversion_drop", "SKU-D")
    if not a:
        return False, "no conversion_drop SKU-D"
    pc, ev = a["detail"]["price_change"], a["detail"]["event_id"]
    ok = abs(pc - PRICE_CHANGE_TARGET) <= PRICE_CHANGE_TOL and ev == "EV-2" and a["detail"]["test"] == "welch_t"
    return ok, f"price_change {pc:+.1%}, event {ev}, t={a['z']:.2f}"


def check_new_creative(ctx):
    a = _find(ctx, "positive_spike", "CMP-10")
    return bool(a and a["detail"]["new_creative"]), f"new_creative={a['detail']['new_creative'] if a else None}, creatives {a['detail']['creative_ids_recent'] if a else ''}"


def check_cpc_range(ctx):
    a = _find(ctx, "cpc_spike", "google")
    ok = bool(a and CPC_RANGE[0] <= a["change_pct"] <= CPC_RANGE[1])
    return ok, f"Google CPC {a['change_pct']:+.1%}" if a else "no cpc_spike google"


def check_deterministic(ctx):
    sig = lambda: [(a.id, a.kind, a.entity_id, a.baseline, a.recent, a.change_pct, a.z, a.profit_impact, a.severity,
                    json.dumps(a.detail, sort_keys=True)) for a in detect_all()]  # noqa: E731
    return sig() == sig(), "two runs identical (ids, order, values)"


def check_runtime(ctx):
    t0 = time.perf_counter()
    detect_all()
    elapsed = time.perf_counter() - t0
    return elapsed < MAX_RUNTIME_S, f"detect_all {elapsed * 1000:.0f} ms"


def check_tables(ctx):
    errors = []
    for name, df in ctx["tables"].items():
        try:
            validate_table(df, name)
        except ValueError as exc:
            errors.append(str(exc))
    ba = ctx["tables"]["brain_alerts"].set_index(["target_type", "target_id"])
    for key in [("cluster", "google"), ("source", "meta_ads"), ("source", "google_ads"), ("neuron", "SKU-B")]:
        if key not in ba.index:
            errors.append(f"missing target {key}")
    for cid in ("CMP-03", "CMP-04", "CMP-05"):
        if ("neuron", cid) not in ba.index or not bool(ba.loc[("neuron", cid)]["stock_locked"]):
            errors.append(f"{cid} not stock_locked")
    return not errors, f"{len(ba)} brain targets, {len(ctx['tables']['anomalies'])} anomalies" if not errors else "; ".join(errors)


def check_brain_events(ctx):
    original = config.STATE_PATH
    with tempfile.TemporaryDirectory() as tmp:
        config.STATE_PATH = Path(tmp) / "state.json"
        try:
            first = run_detection(as_of=FIXED_AS_OF, emit_brain_events=True, verbose=False)
            events = read_brain_events(limit=config.BRAIN_EVENT_HISTORY_LIMIT)
            second = run_detection(as_of=FIXED_AS_OF, emit_brain_events=True, verbose=False)
            active = len(load_state()["active_anomalies"])
        finally:
            config.STATE_PATH = original
    n = len(ctx["alerts"])
    sku_j = next((e for e in events if e["payload"]["key"] == "conversion_drop:SKU-J"), {})
    related_ok = (sku_j.get("payload", {}).get("related") == ["positive_spike:CMP-10"]
                  and not any("Tiktok" in e["message"] for e in events))
    ok = (related_ok and len(events) == n and first["events_logged"] == n and second["events_logged"] == 0 and active == n
          and all(e["type"] == "anomaly" and e["region"] == "diagnose" and e["path"] == ["ingest", "diagnose"] for e in events))
    return ok, (f"run 1 logged {first['events_logged']}/{n} diagnose events, run 2 logged "
                f"{second['events_logged']}; SKU-J payload related={sku_j.get('payload', {}).get('related')}")


def check_sku_j_knock_on(ctx):
    a = _find(ctx, "conversion_drop", "SKU-J")
    knock = {k["entity_id"]: k for k in ctx["result"]["quality"]["knock_on"]}
    ok = (a is not None and a["detail"]["related"] == ["positive_spike:CMP-10"] and "SKU-J" in knock
          and knock["SKU-J"]["scenario"] == "S7" and "CMP-02" in knock)
    return ok, "SKU-J conversion_drop = knock-on of S7, related " + (str(a["detail"]["related"]) if a else "—")


def check_gain_severity(ctx):
    a = _find(ctx, "positive_spike", "CMP-10")
    return bool(a and a["severity"] == "medium"), f"CMP-10 +₹{a['profit_impact']:,.0f}/day → {a['severity'] if a else '—'}"


def check_related_links(ctx):
    cmp02 = _find(ctx, "metric_shift", "CMP-02")
    others = [a["id"] for a in ctx["alerts"] if a["detail"]["related"] and (a["kind"], a["entity_id"]) not in
              {("metric_shift", "CMP-02"), ("conversion_drop", "SKU-J")}]
    ok = bool(cmp02 and cmp02["detail"]["related"] == ["cpc_spike:google"]) and not others
    return ok, f"CMP-02 → {cmp02['detail']['related'] if cmp02 else '—'}; no other alert has a cause link"


def check_no_cmp06_expectation(ctx):
    """CMP-06 must NOT be flagged: its profit drop is real but too noisy to pass the significance gate."""
    flagged = _find(ctx, "metric_shift", "CMP-06")
    return flagged is None, "CMP-06 not flagged (two-gate rule: z ≈ −1.08 < 2.5)"


def check_precision(ctx):
    q = ctx["result"]["quality"]
    return q["precision"] == 1.0, f"precision {q['precision']:.2f} ({q['found']} found + {len(q['knock_on'])} knock-on of {len(ctx['alerts'])} alerts)"


def check_display_names(ctx):
    texts = [a["label"] for a in ctx["alerts"]] + list(ctx["tables"]["brain_alerts"]["message"])
    bad = [t for t in texts if "Tiktok" in t]
    has_tiktok = any("TikTok" in t for t in texts)
    return not bad and has_tiktok, f"{len(texts)} labels/messages, none say 'Tiktok'" if not bad else f"bad: {bad}"


def check_recall(ctx):
    q = evaluate(detect_all(), FIXED_AS_OF)
    return q["recall"] == 1.0, f"recall {q['recall']:.2f} · precision {q['precision']:.2f} · knock-on {[k['entity_id'] for k in q['knock_on']]}"


CHECKS: list[tuple[str, Callable[[dict], tuple[bool, str]]]] = [
    ("1  planted pairs detected", check_planted_detected),
    ("2  false alarms == 0", check_false_alarms),
    ("3  sorted by impact", check_sorted),
    ("4  M0 shape", check_shapes),
    ("5  severities", check_severities),
    ("6  directions", check_directions),
    ("7  fatigue dedupe", check_fatigue_dedupe),
    ("8  SKU-D price + EV-2", check_price_link),
    ("9  CMP-10 new creative", check_new_creative),
    ("10 Google CPC range", check_cpc_range),
    ("11 deterministic", check_deterministic),
    ("12 runs under 1s", check_runtime),
    ("13 anomalies + brain_alerts", check_tables),
    ("14 brain events + dedupe", check_brain_events),
    ("15 recall == 1.0", check_recall),
    ("16 SKU-J knock-on of S7", check_sku_j_knock_on),
    ("17 gain severity (CMP-10)", check_gain_severity),
    ("18 related links", check_related_links),
    ("19 CMP-06 not expected", check_no_cmp06_expectation),
    ("20 precision == 1.00", check_precision),
    ("21 display names", check_display_names),
]


def run_checks(ctx: dict) -> list[tuple[str, bool, str]]:
    results = []
    for name, fn in CHECKS:
        try:
            ok, detail = fn(ctx)
        except Exception as exc:  # a crashing check is a failing check
            ok, detail = False, f"error: {exc!r}"
        results.append((name, bool(ok), detail))
    return results


def main() -> int:
    results = run_checks(build_context())
    width = max(len(n) for n, _, _ in results)
    print(f"{'check'.ljust(width)}  result  detail")
    print("-" * (width + 70))
    for name, ok, detail in results:
        print(f"{name.ljust(width)}  {'PASS' if ok else 'FAIL'}    {detail}")
    failed = sum(not ok for _, ok, _ in results)
    print("-" * (width + 70))
    print(f"M3 validation: {len(results) - failed}/{len(results)} PASS" + (f", {failed} FAIL" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
