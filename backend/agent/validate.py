"""M8 validation. Run from the project root:  python -m backend.agent.validate

Runs the rules engine (no network for the answers), read-only: state.json must be byte-identical afterwards.
Prints PASS / FAIL; exit 1 on any FAIL. If a real ANTHROPIC_API_KEY is in .env it also runs the demo questions
through Claude and REPORTS (never fails on) the result.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Callable

from backend.agent import agent
from backend.api import service
from backend.core import config
from backend.core import metrics as m
from backend.core.config import AGENT_MAX_WORDS
from backend.core.db import log_brain_event, save_state, write_table
from backend.decisions import engine as engine

MAX_ANSWER_S = 1.5
FAKE_KEY = "sk-ant-validation-secret-0123456789"
FORBIDDEN = ("execute", "approve", "reject", "rollback", "auto_apply", "refresh_decisions", "set_autonomy", "set_objective")
_CACHE: dict[str, dict] = {}


def ask(q: str) -> dict:
    """A rules-engine answer, cached per question so every check sees the same one."""
    if q not in _CACHE:
        r = agent.answer(q, force_rules=True)
        r["registry"] = agent.last_registry()
        _CACHE[q] = r
    return _CACHE[q]


def _explained(r: dict) -> dict:
    """The anomaly the answer explained (from its explain_anomaly tool call)."""
    aid = next(t["input"]["anomaly_id"] for t in r["tools_used"] if t["name"] == "explain_anomaly")
    return next(a for a in service.anomalies() if a["id"] == aid)


def _hl(r: dict, kind: str, ident: str) -> bool:
    return {"type": kind, "id": ident} in r["highlights"]


# ---------------------------------------------------------------------------
def check_demo_answers():
    bad = [q for q in agent.DEMO_QUESTIONS if len(ask(q)["answer"]) <= 20 or ask(q)["engine"] != "rules"]
    return not bad, f"{len(agent.DEMO_QUESTIONS)} demo questions answered by the rules engine" if not bad else f"bad: {bad}"


def check_fatigue():
    r = ask("Why did ROAS drop for Summer Sneakers?")
    a = _explained(r)
    ok = a["kind"] == "creative_fatigue" and a["entity_id"] == "CMP-01" and _hl(r, "neuron", "CMP-01") and "Creative fatigue" in r["answer"]
    return ok, f"explained {a['kind']} on {a['entity_id']}; highlights {r['highlights']}"


def check_other_whys():
    r1, r2 = ask("Why did Casual X drop?"), ask("Why is Google down?")
    a1, a2 = _explained(r1), _explained(r2)
    ok = (a1["kind"] == "conversion_drop" and a1["entity_id"] == "SKU-D" and a2["kind"] == "cpc_spike" and a2["entity_id"] == "google"
          and _hl(r1, "neuron", "SKU-D") and _hl(r2, "cluster", "google"))
    return ok, f"Casual X → {a1['kind']}:{a1['entity_id']}; Google → {a2['kind']} (cluster google lit)"


def check_roas_real():
    r = ask("Is our ROAS real?")
    rows = {x["channel"]: x for x in service.reconciliation()}
    need = [f"{rows[c]['roas_platform']:.2f}" for c in ("meta", "google")] + [f"{rows[c]['roas_true']:.2f}" for c in ("meta", "google")] \
        + [f"{round(rows[c]['inflation_pct'] * 100)}%" for c in ("meta", "google")]
    ok = all(n in r["answer"] for n in need) and "Meta" in r["answer"] and "Google" in r["answer"] and _hl(r, "source", "meta_ads") and _hl(r, "source", "google_ads")
    return ok, f"cites {', '.join(need)}; sources meta_ads and google_ads lit"


def check_simulation():
    r = ask("What if Google +20%?")
    s = service.channel_simulate({"google": 1.2})["summary"]
    need = [m.format_inr(s["current"]["profit"]), m.format_inr(s["simulated"]["profit"]), m.format_inr(s["profit_delta"])]
    return all(n in r["answer"] for n in need) and _hl(r, "cluster", "google"), f"profit {need[0]} → {need[1]}/day ({need[2]}) matches the simulator"


def check_scale():
    r = ask("Where should I scale next?")
    return "Trail Max" in r["answer"] and "Running Pro" not in r["answer"], "mentions Trail Max; Running Pro never appears"


def check_price():
    r = ask("Did the Casual X price rise work?")
    c = service.causal()
    units = f"{c['units_change_pct'] * 100:+.0f}%"
    ok = units in r["answer"] and ("includes zero" in r["answer"] or "excludes zero" in r["answer"]) and "interval" in r["answer"]
    return ok, f"units {units}, net margin {m.format_inr(c['effect_per_day'])}/day, interval statement present"


def check_traceability():
    bad = []
    for q in agent.DEMO_QUESTIONS:
        r = ask(q)
        stray = agent.numeric_tokens(r["answer"]) - r["registry"]
        if stray:
            bad.append((q, sorted(stray)))
    n = sum(len(agent.numeric_tokens(ask(q)["answer"])) for q in agent.DEMO_QUESTIONS)
    return not bad, f"{n} ₹/%/decimal tokens across {len(agent.DEMO_QUESTIONS)} answers, every one produced by the formatter from tool values" if not bad else f"untraced: {bad}"


def check_invalid_key_falls_back():
    saved = os.environ.get("ANTHROPIC_API_KEY")
    os.environ["ANTHROPIC_API_KEY"] = "invalid-key-for-validation"
    try:
        t0 = time.perf_counter()
        r = agent.answer("Is our ROAS real?")
        elapsed = time.perf_counter() - t0
    finally:
        os.environ.pop("ANTHROPIC_API_KEY", None) if saved is None else os.environ.__setitem__("ANTHROPIC_API_KEY", saved)
    ok = r["engine"].startswith("fallback (") and len(r["answer"]) > 20 and "Meta" in r["answer"]
    return ok, f"engine {r['engine']!r}, answered in {elapsed:.1f}s with no exception"


def check_no_secrets_or_traces():
    saved = os.environ.get("ANTHROPIC_API_KEY")
    os.environ["ANTHROPIC_API_KEY"] = FAKE_KEY
    try:
        outs = [agent.answer(q) for q in agent.DEMO_QUESTIONS[:3]]
    finally:
        os.environ.pop("ANTHROPIC_API_KEY", None) if saved is None else os.environ.__setitem__("ANTHROPIC_API_KEY", saved)
    blob = json.dumps(outs) + "".join(ask(q)["answer"] for q in agent.DEMO_QUESTIONS)
    bad = [k for k in (FAKE_KEY, "Traceback", 'File "', "sk-ant") if k in blob]
    return not bad, "no API key and no stack trace in any answer or engine label" if not bad else f"leaked: {bad}"


def check_read_only_tools():
    import inspect

    bad = []
    for name, tool in agent.TOOLS.items():
        fn = tool["fn"]
        hit = set(fn.__code__.co_names) & set(FORBIDDEN)
        if hit or fn.__module__ != "backend.agent.agent":
            bad.append((name, sorted(hit)))
    writers = [getattr(engine, n) for n in FORBIDDEN] + [save_state, log_brain_event, write_table]
    for module in (agent, service):
        for obj in vars(module).values():
            if any(obj is w for w in writers):
                bad.append((module.__name__, getattr(obj, "__name__", "?")))
    src = inspect.getsource(service) + inspect.getsource(agent)
    bad += [f"source mentions {n}(" for n in ("engine.execute", "engine.approve", "engine.rollback", "engine.reject") if n in src]
    return not bad, f"{len(agent.TOOLS)} tools, none can reach execute / approve / reject / rollback or any state write" if not bad else f"reachable: {bad}"


def check_word_limit():
    longest = max((len(ask(q)["answer"].split()), q) for q in agent.DEMO_QUESTIONS)
    return longest[0] <= AGENT_MAX_WORDS, f"longest answer {longest[0]} words (limit {AGENT_MAX_WORDS})"


def check_speed():
    slow = [(q, ask(q)["duration_ms"]) for q in agent.DEMO_QUESTIONS if ask(q)["duration_ms"] / 1000 >= MAX_ANSWER_S]
    worst = max(ask(q)["duration_ms"] for q in agent.DEMO_QUESTIONS)
    return not slow, f"slowest rules answer {worst:.0f} ms (limit {MAX_ANSWER_S * 1000:.0f} ms)"


CHECKS: list[tuple[str, Callable[[], tuple[bool, str]]]] = [
    ("1  7 demo answers", check_demo_answers),
    ("2  Summer Sneakers → fatigue", check_fatigue),
    ("3  Casual X / Google whys", check_other_whys),
    ("4  ROAS real? (Meta, Google)", check_roas_real),
    ("5  what-if matches simulator", check_simulation),
    ("6  scale: Trail Max only", check_scale),
    ("7  price: causal + CI", check_price),
    ("8  number traceability", check_traceability),
    ("9  invalid key → fallback", check_invalid_key_falls_back),
    ("10 no key / stack trace", check_no_secrets_or_traces),
    ("11 tools are read-only", check_read_only_tools),
    ("12 ≤ 120 words", check_word_limit),
    ("13 speed", check_speed),
]


def run_checks() -> list[tuple[str, bool, str]]:
    results = []
    for name, fn in CHECKS:
        try:
            ok, detail = fn()
        except Exception as exc:  # a crashing check is a failing check
            ok, detail = False, f"error: {type(exc).__name__}: {exc}"
        results.append((name, bool(ok), detail))
    return results


def claude_report() -> None:
    """If a real key is configured, run the 5 core questions through Claude. Reported, never failed on."""
    agent._load_env()
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("\nClaude: no ANTHROPIC_API_KEY in .env, so only the offline rules engine was exercised.")
        return
    print("\nClaude (real key present):")
    for q in agent.DEMO_QUESTIONS[:5]:
        r = agent.answer(q)
        print(f"  {'✔' if r['engine'] == 'claude' else '✘'} engine={r['engine']} cites ₹={'₹' in r['answer']} · {q}")


def main() -> int:
    state = Path(config.STATE_PATH)
    before = state.read_bytes() if state.exists() else None
    results = run_checks()
    width = max(len(n) for n, _, _ in results)
    print(f"{'check'.ljust(width)}  result  detail")
    print("-" * (width + 90))
    for name, ok, detail in results:
        print(f"{name.ljust(width)}  {'PASS' if ok else 'FAIL'}    {detail}")
    failed = sum(not ok for _, ok, _ in results)
    after = state.read_bytes() if state.exists() else None
    untouched = before == after
    print("-" * (width + 90))
    print(f"M8 validation: {len(results) - failed}/{len(results)} PASS" + (f", {failed} FAIL" if failed else "")
          + ("  (state.json byte-identical: read-only)" if untouched else "  (WARNING: state.json CHANGED)"))
    claude_report()
    return 1 if (failed or not untouched) else 0


if __name__ == "__main__":
    sys.exit(main())
