"""M4 / M4b validation. Run from the project root:  python -m backend.diagnosis.validate

Runs diagnosis with emit_brain_events=False and prints a PASS/FAIL table; exit 1 on any failure.
Each check is `check_*(ctx) -> (ok, detail)` so tests/test_m4.py can reuse them.
"""
from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path
from typing import Callable

from backend.core import config
from backend.core.db import load_state, read_brain_events, read_table, validate_table
from backend.diagnosis import causal as causal_mod
from backend.diagnosis.decompose import AUCTION, CREATIVE, FACTOR_NAMES, FACTOR_ORDER, MARGIN, SITE_CVR, _top_factor
from backend.diagnosis.runner import run_diagnosis

FIXED_AS_OF = "2026-10-06T23:00:00"
MAX_RUNTIME_S = 1.5
UNITS_RANGE = (-0.35, -0.15)
MAX_RMSE_SHARE = 0.15
PLANTED = [("creative_fatigue", "CMP-01"), ("cpc_spike", "google"), ("positive_spike", "CMP-10"),
           ("conversion_drop", "SKU-D"), ("stockout_risk", "SKU-B")]


def build_context() -> dict:
    """Run diagnosis once without brain events; keep the objects and the written tables."""
    s = run_diagnosis(as_of=FIXED_AS_OF, emit_brain_events=False, verbose=False)
    anomalies, roots = s["_anomalies"], s["_roots"]
    return {"summary": s, "anomalies": anomalies, "roots": roots,
            "by_key": {(a.kind, a.entity_id): (a, rc) for a, rc in zip(anomalies, roots)},
            "causal": causal_mod.event_effect_details("EV-2", anomalies),
            "tables": {t: read_table(t) for t in ("diagnoses", "causal_results")}}


def _factor(rc, name):
    return next(f.impact for f in rc.factors if f.name == name)


def _level(a) -> str:
    return "sku" if a.entity_type == "sku" else "campaign"


# ---------------------------------------------------------------------------
def check_waterfall_sums(ctx):
    bad = [rc.anomaly_id for rc in ctx["roots"] if rc.factors
           and abs(sum(f.impact for f in rc.factors) - rc.total_change) > max(1.0, 0.01 * abs(rc.total_change))]
    n = sum(bool(rc.factors) for rc in ctx["roots"])
    return not bad, f"{n} waterfalls sum to their totals" if not bad else f"off: {bad}"


def check_factor_names(ctx):
    allowed = set(FACTOR_NAMES.values())
    names = {f.name for rc in ctx["roots"] for f in rc.factors}
    bad = [n for n in names if n not in allowed or "other" in n.lower() or "unexplained" in n.lower()]
    return not bad, f"{len(names)} distinct factor names, all in FACTOR_NAMES" if not bad else f"bad: {bad}"


def check_factor_order(ctx):
    bad = [rc.anomaly_id for a, rc in zip(ctx["anomalies"], ctx["roots"])
           if rc.factors and [f.name for f in rc.factors] != FACTOR_ORDER[_level(a)]]
    return not bad, "fixed order per level" if not bad else f"wrong order: {bad}"


def _top(ctx, kind, entity):
    a, rc = ctx["by_key"][(kind, entity)]
    f = _top_factor(rc.factors, rc.total_change)
    return f.name if f else None, f.pct if f else 0.0


def check_cpc_top(ctx):
    n, p = _top(ctx, "cpc_spike", "google")
    return n == AUCTION, f"{n} ({p:.0%})"


def check_fatigue_top(ctx):
    n, p = _top(ctx, "creative_fatigue", "CMP-01")
    return n == CREATIVE, f"{n} ({p:.0%})"


def check_viral_top(ctx):
    n, p = _top(ctx, "positive_spike", "CMP-10")
    return n == CREATIVE, f"{n} ({p:.0%})"


def check_price_tradeoff(ctx):
    _, rc = ctx["by_key"][("conversion_drop", "SKU-D")]
    site, margin = _factor(rc, SITE_CVR), _factor(rc, MARGIN)
    return site < 0 < margin, f"{SITE_CVR} {site:+,.0f}/day, {MARGIN} {margin:+,.0f}/day"


def check_narratives(ctx):
    errors = []
    for kind, entity in PLANTED:
        a, rc = ctx["by_key"][(kind, entity)]
        top = _top_factor(rc.factors, rc.total_change)
        if not top or top.name not in rc.narrative:
            errors.append(f"{kind}:{entity} narrative misses its top factor")
    for kind, entity in (("metric_shift", "CMP-02"), ("conversion_drop", "SKU-J")):
        if "Linked to:" not in ctx["by_key"][(kind, entity)][1].narrative:
            errors.append(f"{entity} narrative not linked")
    return not errors, "planted narratives name their driver; CMP-02 / SKU-J linked" if not errors else "; ".join(errors)


def check_narrative_direction(ctx):
    bad = []
    for a, rc in zip(ctx["anomalies"], ctx["roots"]):
        if not rc.factors:
            continue
        top = _top_factor(rc.factors, rc.total_change)
        word = "rose by" if rc.total_change > 0 else "fell by"
        if rc.total_change != 0 and (top is None or top.impact * rc.total_change <= 0 or word not in rc.narrative):
            bad.append(rc.anomaly_id)
    return not bad, "every narrative's driver and 'rose/fell' match the total's sign" if not bad else f"wrong: {bad}"


def check_attribution(ctx):
    rows = [(a, rc) for a, rc in zip(ctx["anomalies"], ctx["roots"]) if a.kind == "attribution_inflation"]
    ok = bool(rows) and all(not rc.factors and rc.total_change == 0 and "Platform ROAS" in rc.narrative
                            and "true" in rc.narrative for _, rc in rows)
    return ok, f"{len(rows)} attribution diagnoses: no factors, narrative cites platform vs true ROAS"


def check_funnels(ctx):
    errors = []
    for a, rc in zip(ctx["anomalies"], ctx["roots"]):
        if a.entity_type == "sku":
            if len(rc.funnel) != 4 or sum(s["is_biggest_drop"] for s in rc.funnel) != 1:
                errors.append(f"{a.entity_id} funnel")
        if a.kind == "cpc_spike":
            changes = [r["change"] for r in rc.funnel]
            if not rc.funnel or "campaign_id" not in rc.funnel[0] or changes != sorted(changes):
                errors.append("cpc_spike drill-down")
    return not errors, "SKU funnels: 4 steps, one biggest drop; channel drill-down worst-first" if not errors else "; ".join(errors)


def check_causal(ctx):
    c = ctx["causal"]
    r, errors = c["result"], []
    if {"SKU-D", "SKU-B", "SKU-J"} & set(c["controls"]):
        errors.append("controls include a disturbed/treated SKU")
    if any(w < 0 for w in c["weights"].values()):
        errors.append("negative weight")
    if not UNITS_RANGE[0] <= c["units_change_pct"] <= UNITS_RANGE[1]:
        errors.append(f"units {c['units_change_pct']:+.1%} out of range")
    if not r.ci_low < r.total_effect < r.ci_high:
        errors.append("CI does not bracket the effect")
    if len(r.series) != config.CAUSAL_CHART_DAYS or {s["is_post"] for s in r.series} != {True, False}:
        errors.append("series shape")
    share = c["pre_fit_rmse"] / c["mean_cvr_pre"]
    if share >= MAX_RMSE_SHARE:
        errors.append(f"pre-fit RMSE {share:.1%} of mean CVR")
    detail = (f"units {c['units_change_pct']:+.1%}, effect {r.effect_per_day:+,.0f}/day, total {r.total_effect:+,.0f} "
              f"(CI {r.ci_low:+,.0f} to {r.ci_high:+,.0f}), RMSE {share:.1%} of mean CVR, controls {len(c['controls'])}")
    return not errors, detail if not errors else f"{detail} · {errors}"


def check_tables(ctx):
    errors = []
    for name, df in ctx["tables"].items():
        try:
            validate_table(df, name)
        except ValueError as exc:
            errors.append(str(exc))
    d = ctx["tables"]["diagnoses"]
    if len(d) != len(ctx["anomalies"]) or d["anomaly_key"].nunique() != len(d):
        errors.append("one diagnoses row per anomaly expected")
    return not errors, f"{len(d)} diagnoses, {len(ctx['tables']['causal_results'])} causal row(s)" if not errors else "; ".join(errors)


def check_brain_events(ctx):
    original = config.STATE_PATH
    with tempfile.TemporaryDirectory() as tmp:
        config.STATE_PATH = Path(tmp) / "state.json"
        try:
            first = run_diagnosis(as_of=FIXED_AS_OF, emit_brain_events=True, verbose=False)
            events = read_brain_events(limit=config.BRAIN_EVENT_HISTORY_LIMIT)
            second = run_diagnosis(as_of=FIXED_AS_OF, emit_brain_events=True, verbose=False)
            active = len(load_state()["active_diagnoses"])
        finally:
            config.STATE_PATH = original
    n = len(ctx["anomalies"])
    ok = (len(events) == n + 1 and first["events_logged"] == n + 1 and second["events_logged"] == 0
          and active == n + 1 and all(e["type"] == "diagnosis" and e["region"] == "diagnose"
                                      and e["path"] == ["diagnose"] for e in events))
    return ok, f"run 1 logged {first['events_logged']} events ({n} diagnoses + 1 causal), run 2 logged {second['events_logged']}"


def check_deterministic(ctx):
    def sig():
        s = run_diagnosis(as_of=FIXED_AS_OF, emit_brain_events=False, verbose=False)
        return ([(rc.anomaly_id, rc.total_change, [(f.name, f.impact, f.pct) for f in rc.factors], rc.funnel,
                  rc.narrative) for rc in s["_roots"]],
                [(c["event_id"], c["effect_per_day"], c["ci_low"], c["ci_high"], c["weights"]) for c in s["causal"]])
    return sig() == sig(), "two runs identical (factors, funnels, narratives, causal)"


def check_runtime(ctx):
    t0 = time.perf_counter()
    run_diagnosis(as_of=FIXED_AS_OF, emit_brain_events=False, verbose=False)
    elapsed = time.perf_counter() - t0
    return elapsed < MAX_RUNTIME_S, f"detect + decompose + causal + persist {elapsed * 1000:.0f} ms"


CHECKS: list[tuple[str, Callable[[dict], tuple[bool, str]]]] = [
    ("1  waterfalls sum", check_waterfall_sums),
    ("2  factor names", check_factor_names),
    ("3  factor order", check_factor_order),
    ("4  CPC spike top factor", check_cpc_top),
    ("5  fatigue top factor", check_fatigue_top),
    ("6  viral top factor", check_viral_top),
    ("7  SKU-D trade-off signs", check_price_tradeoff),
    ("8  narratives", check_narratives),
    ("9  narrative direction", check_narrative_direction),
    ("10 attribution narrative", check_attribution),
    ("11 funnels / drill-down", check_funnels),
    ("12 causal EV-2", check_causal),
    ("13 tables", check_tables),
    ("14 brain events + dedupe", check_brain_events),
    ("15 deterministic", check_deterministic),
    ("16 runtime", check_runtime),
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
    print(f"M4 validation: {len(results) - failed}/{len(results)} PASS" + (f", {failed} FAIL" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
