"""M8 AI agent: the Neural Brain's voice. It answers questions with the engine's OWN tools and tells the UI which
brain nodes the answer is about so they can light up.

Run from the project root:
  python -m backend.agent.agent "Why did Summer Sneakers drop?"
  python -m backend.agent.agent --demo [--rules]

TRUST DESIGN
  * The LLM never computes or estimates numbers: every figure comes from a tool result.
  * The tools are READ-ONLY (backend/api/service.py): the agent can explain and simulate, never execute, approve,
    reject or roll back anything (execution stays in M6, behind its guardrails).
  * Nothing here writes state.json or logs brain events.
  * The demo must never break: any failure (no key, no network, rate limit, bad response) falls back to the rules
    engine, and the UI never sees an error message. Which engine answered is always reported.
  * The API key lives only in the git-ignored .env; it is never logged or returned.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from types import SimpleNamespace

from dotenv import load_dotenv

from backend.api import service
from backend.core import config
from backend.core import metrics as m
from backend.core.config import (
    AGENT_MAX_STEPS, AGENT_MAX_TOKENS, AGENT_MAX_WORDS, AGENT_TOOL_RESULT_MAX_CHARS, CHANNEL_DISPLAY, CHANNELS,
    CLAUDE_MODEL_DEFAULT, RECON_GAP_THRESHOLD, STOCK_COVER_RISK_DAYS,
)
from backend.core.schema import to_dict
from backend.diagnosis.decompose import lead_sentence

SYSTEM = ("You are the reasoning layer of a D2C advertising decision engine. Use tools for every number; never estimate or "
          "invent figures. Be concise (at most 120 words), lead with the answer, cite ₹ impacts per day, and end with one "
          "recommended action. Currency is INR (use ₹ with lakh/thousand formatting as given by the tools). You cannot "
          "execute changes; recommend that the user approve them in the Decision Inbox.")
NOTE = "Every number comes from an engine tool call."
BRIEF_QUESTION = "Give me today's brief: what changed, why, and the top 3 actions."
DEMO_QUESTIONS = ["Why did ROAS drop for Summer Sneakers?", "Is our ROAS real?", "What if Google +20%?", "Where should I scale next?",
                  "Give me today's brief", "Is Running Pro going to sell out?", "Did the Casual X price rise work?"]
MAX_HIGHLIGHTS = 6
CLAUDE_TIMEOUT_S = 15.0  # a dead network must fall back quickly, not hang the demo
DEFAULT_SIMULATION_PCT = 20.0


# ---------------------------------------------------------------------------
# Tools (all READ-ONLY): compact views of the service layer so results fit AGENT_TOOL_RESULT_MAX_CHARS
# ---------------------------------------------------------------------------
def _compact_anomaly(a: dict) -> dict:
    return {k: a[k] for k in ("id", "kind", "entity_type", "entity_id", "label", "change_pct", "z", "profit_impact", "severity")} | {
        "direction": a["detail"]["direction"], "related": a["detail"].get("related", [])}


def t_get_kpis() -> dict:
    return service.kpis()


def t_list_anomalies() -> list[dict]:
    return [_compact_anomaly(a) for a in service.anomalies()]


def t_explain_anomaly(anomaly_id: str) -> dict:
    d = service.diagnosis(anomaly_id)
    rc = d["root_cause"]
    return {"anomaly": _compact_anomaly(d["anomaly"]),
            "root_cause": {"total_change": rc["total_change"], "factors": rc["factors"], "narrative": rc["narrative"]}}


def t_get_recommendations() -> dict:
    r = service.pending_recommendations()  # strictly read-only: the agent never builds or saves decisions
    recs = [{"id": d["id"], "title": d["title"], "action_type": d["action"]["type"], "expected_profit_delta": d["expected_profit_delta"],
             "confidence": d["confidence"], "risk": d["risk"], "requires_approval": d["requires_approval"], "blocked": d["blocked"],
             "anomaly_id": d["anomaly_id"], "status": d["status"],
             "campaigns": [{"campaign_id": c["campaign_id"], "name": c["name"], "from_budget": c["from_budget"], "to_budget": c["to_budget"]}
                           for c in d["action"]["changes"]],
             "targets": d["action"]["targets"], "notes": d["action"].get("notes", [])} for d in r["recommendations"]]
    return {"objective": r["objective"], "summary": r["summary"], "recommendations": recs}


def t_causal_price_effect(event_id: str | None = None) -> dict:
    c = service.causal(event_id)
    c.pop("series", None)
    return c


def t_simulate_channel_budget(multipliers: dict) -> dict:
    bad = {k: v for k, v in multipliers.items() if k not in CHANNELS or not isinstance(v, (int, float)) or v < 0}
    if bad:
        raise ValueError(f"multipliers must map channels {list(CHANNELS)} to non-negative numbers; got {bad}")
    r = service.channel_simulate(multipliers)
    moved = [c for c in r["campaigns"] if c["new_spend"] != c["current_spend"]]
    return {"summary": r["summary"], "campaigns": [{k: c[k] for k in ("campaign_id", "name", "current_spend", "new_spend", "current_profit", "new_profit", "stock_warning")}
                                                   for c in moved]}


def t_get_opportunities() -> dict:
    o = service.opportunities()
    keep = ("rank", "label", "sku_id", "channel", "audience", "predicted_poas", "predicted_conv_per_1k", "stock_days", "score", "is_ghost")
    return {"model_r2_holdout": o["model_r2_holdout"], "opportunities": [{k: r[k] for k in keep} for r in o["opportunities"]]}


def t_get_reconciliation() -> list[dict]:
    keep = ("channel", "platform_conversions", "store_orders", "inflation_pct", "roas_platform", "roas_true", "trust_score", "spend")
    return [{k: r[k] for k in keep} for r in service.reconciliation()]


TOOLS = {
    "get_kpis": {"fn": t_get_kpis, "input_schema": {"type": "object", "properties": {}},
                 "description": "Headline KPIs for the last 7 days vs the 7 before: spend, revenue, profit (₹ per day), POAS, true and "
                                "platform ROAS with changes, SKUs at stockout risk, data trust. Use for overview or stock questions."},
    "list_anomalies": {"fn": t_list_anomalies, "input_schema": {"type": "object", "properties": {}},
                       "description": "All current anomalies ranked by ₹/day impact (id, kind, entity, label, change, severity, related). "
                                      "Use first to find what is wrong or to find an anomaly id."},
    "explain_anomaly": {"fn": t_explain_anomaly, "input_schema": {"type": "object", "properties": {"anomaly_id": {"type": "string", "description": "e.g. AN-001"}},
                                                                   "required": ["anomaly_id"]},
                        "description": "Root cause of one anomaly: the exact ₹/day waterfall (factors with impact and share) and a plain-English narrative. "
                                       "Use after list_anomalies to explain why something moved."},
    "get_recommendations": {"fn": t_get_recommendations, "input_schema": {"type": "object", "properties": {}},
                            "description": "The pending Decision Inbox: ranked recommendations with expected ₹/day, confidence, risk, approval need, "
                                           "campaigns changed. Use to say what to do next."},
    "causal_price_effect": {"fn": t_causal_price_effect, "input_schema": {"type": "object", "properties": {"event_id": {"type": "string", "description": "e.g. EV-2; default: the latest price change"}}},
                            "description": "Synthetic-control causal result for a price change: units vs counterfactual, net margin effect per day and a 95% interval. "
                                           "Use to say whether a price change worked."},
    "simulate_channel_budget": {"fn": t_simulate_channel_budget,
                                "input_schema": {"type": "object", "properties": {"multipliers": {"type": "object", "description": 'channel → multiplier, e.g. {"google": 1.2} for +20%',
                                                                                                  "additionalProperties": {"type": "number"}}}, "required": ["multipliers"]},
                                "description": "What-if on the response curves: scales every campaign of a channel and returns profit, revenue, POAS before and after plus stock "
                                               "warnings. Read-only: nothing is changed."},
    "get_opportunities": {"fn": t_get_opportunities, "input_schema": {"type": "object", "properties": {}},
                          "description": "Untested product × channel × audience combinations ranked by predicted POAS, with the model's honest hold-out R². "
                                         "Use for where to grow next."},
    "get_reconciliation": {"fn": t_get_reconciliation, "input_schema": {"type": "object", "properties": {}},
                           "description": "Platform-reported vs store-verified conversions and ROAS per channel, with over-reporting and a trust score. "
                                          "Use for questions about whether ROAS is real."},
}
TOOL_SPECS = [{"name": n, "description": t["description"], "input_schema": t["input_schema"]} for n, t in TOOLS.items()]


def _serialise(result) -> str:
    """JSON for a tool result, truncated to AGENT_TOOL_RESULT_MAX_CHARS."""
    text = json.dumps(to_dict(result), ensure_ascii=False)
    suffix = "…[truncated]"
    return text if len(text) <= AGENT_TOOL_RESULT_MAX_CHARS else text[: AGENT_TOOL_RESULT_MAX_CHARS - len(suffix)] + suffix


def run_tool(name: str, args: dict | None = None):
    """Run one read-only tool locally. Unknown tools raise KeyError (callers turn that into a tool error)."""
    return TOOLS[name]["fn"](**(args or {}))


# ---------------------------------------------------------------------------
# Number traceability: every ₹ amount / % / decimal in a rules answer goes through the formatter
# ---------------------------------------------------------------------------
TOKEN = re.compile(r"-?₹[\d,]+(?:\.\d+)?(?:Cr|L|k)?|[+-]?\d+(?:\.\d+)?%|(?<![\w.])\d+\.\d+(?![\w])")


def numeric_tokens(text: str) -> set[str]:
    """The ₹ amounts, percentages and decimals in a piece of text."""
    return set(TOKEN.findall(text))


class Fmt:
    """Formats values taken from tool outputs and records every numeric token it emits (the traceability registry)."""

    def __init__(self) -> None:
        self.registry: set[str] = set()

    def _reg(self, s: str) -> str:
        self.registry |= numeric_tokens(s)
        return s

    def money(self, x: float) -> str:
        """₹ with lakh / thousand formatting (M0 format_inr)."""
        return self._reg(m.format_inr(x))

    def pct(self, x: float, signed: bool = False) -> str:
        """A fraction as a whole-number percentage (display only)."""
        return self._reg(f"{x * 100:+.0f}%" if signed else f"{x * 100:.0f}%")

    def num(self, x: float, nd: int = 1) -> str:
        return self._reg(f"{x:.{nd}f}")

    def text(self, s: str) -> str:
        """Text that came verbatim from a tool result (titles, narrative sentences): its numbers are registered."""
        return self._reg(s)


_LAST: Fmt | None = None


def last_registry() -> set[str]:
    """The numeric tokens the most recent rules answer was built from (for the validator)."""
    return set(_LAST.registry) if _LAST else set()


# ---------------------------------------------------------------------------
# Claude tool-calling loop
# ---------------------------------------------------------------------------
class AgentStepLimit(RuntimeError):
    """Claude kept calling tools past AGENT_MAX_STEPS without answering."""


def _load_env() -> None:
    load_dotenv(config.ROOT / ".env", override=False)


def _make_client(api_key: str):
    import anthropic

    return anthropic.Anthropic(api_key=api_key, timeout=CLAUDE_TIMEOUT_S, max_retries=0)


def _ids_from(name: str, args: dict, result) -> list[str]:
    """Entity ids a tool result is about (anomalies, campaigns, SKUs, channels, sources) for the brain highlights."""
    ids: list[str] = []
    try:
        if name == "list_anomalies":
            ids += [a["entity_id"] for a in result[:3]]
        elif name == "explain_anomaly":
            ids.append(result["anomaly"]["entity_id"])
        elif name == "get_recommendations":
            for r in result["recommendations"][:3]:
                ids += [t["id"] for t in r["targets"] if t["type"] != "ghost"]
        elif name == "causal_price_effect":
            ids.append(result["treated_sku"])
        elif name == "simulate_channel_budget":
            ids += list(args.get("multipliers", {}))
        elif name == "get_opportunities":
            ids += [o["sku_id"] for o in result["opportunities"][:3]]
        elif name == "get_reconciliation":
            ids += [_source_for(r["channel"]) for r in result if abs(r["inflation_pct"] or 0) > RECON_GAP_THRESHOLD]
        elif name == "get_kpis":
            ids += [s["sku_id"] for s in result["stock_at_risk"]["skus"]]
    except (KeyError, TypeError, IndexError):
        pass
    return ids


def _source_for(channel: str) -> str:
    return "programmatic" if channel == "programmatic" else f"{channel}_ads"


def _claude(question: str, client=None) -> dict:
    """Answer with Claude using the tools. Raises on ANY failure so answer() can fall back to the rules engine."""
    _load_env()
    key = os.getenv("ANTHROPIC_API_KEY")
    client = client or _make_client(key)
    model = os.getenv("CLAUDE_MODEL") or CLAUDE_MODEL_DEFAULT
    messages = [{"role": "user", "content": question}]
    tools_used, ids, steps = [], [], 0

    def call():
        return client.messages.create(model=model, max_tokens=AGENT_MAX_TOKENS, system=SYSTEM, tools=TOOL_SPECS, messages=messages)

    resp = call()
    while resp.stop_reason == "tool_use" and steps < AGENT_MAX_STEPS:
        steps += 1
        results = []
        for block in resp.content:
            if getattr(block, "type", None) != "tool_use":
                continue
            args = dict(block.input or {})
            tools_used.append({"name": block.name, "input": args})
            try:
                out = run_tool(block.name, args)
                ids += _ids_from(block.name, args, out)
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": _serialise(out)})
            except Exception as exc:  # noqa: BLE001  a failing tool is reported to the model, never raised
                results.append({"type": "tool_result", "tool_use_id": block.id, "is_error": True,
                                "content": json.dumps({"error": f"{type(exc).__name__}: {exc}"})})
        messages.append({"role": "assistant", "content": resp.content})
        messages.append({"role": "user", "content": results})
        resp = call()
    if resp.stop_reason == "tool_use":
        raise AgentStepLimit(f"no answer after {AGENT_MAX_STEPS} tool rounds")
    text = "".join(getattr(b, "text", "") for b in resp.content if getattr(b, "type", None) == "text").strip()
    if not text:
        raise RuntimeError("empty answer")
    return {"answer": text, "engine": "claude", "tools_used": tools_used, "ids": ids}


# ---------------------------------------------------------------------------
# Rules engine (offline fallback): keyword intents → the same tools → templated answers
# ---------------------------------------------------------------------------
def _recs(tools_used: list, cache: dict) -> dict:
    if "recs" not in cache:
        cache["recs"] = run_tool("get_recommendations")
        tools_used.append({"name": "get_recommendations", "input": {}})
    return cache["recs"]


def _entity_candidates(a: dict) -> list[str]:
    """Strings a user might use for an anomaly: the label parts after the kind (channel, product, audience) + the id."""
    parts = [p.strip() for p in a["label"].split(" · ")][1:]
    return [c.lower() for c in parts + [a["entity_id"]] if c]


def match_anomaly(question: str, anomalies: list[dict]) -> dict:
    """The anomaly the question is about: score = length of the longest candidate string found in the question.

    Ties go to a ROOT cause over a knock-on (one with `related`), then to the larger |₹ impact|. No match at all →
    the largest loss.
    """
    q = question.lower()
    best, best_key = None, None
    for a in anomalies:
        score = max((len(c) for c in _entity_candidates(a) if c in q), default=0)
        if score:
            key = (score, not a["related"], abs(a["profit_impact"]))
            if best_key is None or key > best_key:
                best, best_key = a, key
    return best or min(anomalies, key=lambda a: a["profit_impact"])


def _rules_explain(question, f, tools_used, cache):
    anomalies = run_tool("list_anomalies")
    tools_used.append({"name": "list_anomalies", "input": {}})
    a = match_anomaly(question, anomalies)
    d = run_tool("explain_anomaly", {"anomaly_id": a["id"]})
    tools_used.append({"name": "explain_anomaly", "input": {"anomaly_id": a["id"]}})
    rc = d["root_cause"]
    lead = lead_sentence(SimpleNamespace(narrative=rc["narrative"]), a["kind"])
    rest = rc["narrative"][len(lead):].strip()
    sentences = [s for s in re.split(r"(?<=[.!?])\s+(?=[A-Z₹])", rest) if s and not s.startswith(("Partly offset", "Linked to", "See causal"))]
    parts = [f.text(lead)]
    top = sorted((x for x in rc["factors"] if x["impact"]), key=lambda x: -abs(x["impact"]))[:3]
    if top:
        parts.append("Top factors: " + ", ".join(f"{x['name']} {f.money(x['impact'])}/day ({f.pct(x['pct'])})" for x in top) + ".")
    if sentences:
        parts.append(f.text(sentences[0]))
    recs = _recs(tools_used, cache)["recommendations"]
    rec = next((r for r in recs if r["anomaly_id"] == a["id"]), recs[0] if recs else None)
    if rec:
        parts.append(f"Recommended: {f.text(rec['title'])} ({f.money(rec['expected_profit_delta'])}/day) — approve it in the Decision Inbox.")
    return " ".join(parts), [a["entity_id"]]


def _rules_scale(question, f, tools_used, cache):
    recs = _recs(tools_used, cache)["recommendations"]
    opps = run_tool("get_opportunities")
    tools_used.append({"name": "get_opportunities", "input": {}})
    parts, ids = [], []
    for r in [x for x in recs if x["action_type"] == "scale_up"][:2]:
        moves = "; ".join(f"{f.text(c['name'])} {f.pct(c['to_budget'] / c['from_budget'] - 1, signed=True)}" for c in r["campaigns"] if c["from_budget"])
        parts.append(f"{f.text(r['title'])}: {moves} ({f.money(r['expected_profit_delta'])}/day).")
        ids += [c["campaign_id"] for c in r["campaigns"]]
    top = opps["opportunities"][:3]
    if top:
        parts.append("Test next: " + "; ".join(f"{f.text(o['label'])} (predicted POAS {f.num(o['predicted_poas'], 2)})" for o in top) + ".")
        ids += [o["sku_id"] for o in top]
    parts.append(f"The model is a ranking signal, not a forecast (hold-out R² {f.num(opps['model_r2_holdout'], 2)}).")
    launch = next((r for r in recs if r["action_type"] == "launch_test"), None)
    if launch:
        parts.append(f"Recommended: {f.text(launch['title'])} ({f.money(launch['expected_profit_delta'])}/day) from the Decision Inbox.")
    return " ".join(parts), ids


def _rules_stock(question, f, tools_used, cache):
    k = run_tool("get_kpis")
    tools_used.append({"name": "get_kpis", "input": {}})
    risk = k["stock_at_risk"]["skus"]
    if not risk:
        return f"No SKU is below {STOCK_COVER_RISK_DAYS} days of cover, so no stockout action is needed.", []
    parts = [" ".join(f"{s['name']} has {f.num(s['days_cover'])} days of cover left." for s in risk) + " Ads are still sending demand to it."]
    recs = _recs(tools_used, cache)["recommendations"]
    rec = next((r for r in recs if r["action_type"] == "inventory_protect"), None)
    if rec:
        parts.append(f"Recommended: {f.text(rec['title'])} ({f.money(rec['expected_profit_delta'])}/day) — approve it in the Decision Inbox; "
                     "budget increases stay blocked until stock recovers.")
    return " ".join(parts), [s["sku_id"] for s in risk]


def _rules_reconciliation(question, f, tools_used, cache):
    rows = run_tool("get_reconciliation")
    tools_used.append({"name": "get_reconciliation", "input": {}})
    k = run_tool("get_kpis")
    tools_used.append({"name": "get_kpis", "input": {}})
    over = [r for r in rows if (r["inflation_pct"] or 0) > RECON_GAP_THRESHOLD]
    ok = [r for r in rows if r not in over]
    parts = [f"{CHANNEL_DISPLAY[r['channel']]}: platform ROAS {f.num(r['roas_platform'], 2)} vs true {f.num(r['roas_true'], 2)} "
             f"(over-reports conversions by {f.pct(r['inflation_pct'])})." for r in over]
    if ok:
        names = ", ".join(CHANNEL_DISPLAY[r["channel"]] for r in ok)
        parts.append(f"{names} match store orders.")
    parts.append(f"Overall data trust is {f.pct(k['data_trust'])}.")
    parts.append("Recommended: optimise the over-reporting channels on store-verified conversions (data-fix items in the Decision Inbox).")
    return " ".join(parts), [_source_for(r["channel"]) for r in over]


def _rules_price(question, f, tools_used, cache):
    c = run_tool("causal_price_effect")
    tools_used.append({"name": "causal_price_effect", "input": {}})
    zero = "includes zero" if c["ci_includes_zero"] else "excludes zero"
    parts = [f"Units moved {f.pct(c['units_change_pct'], signed=True)} vs what would have happened anyway (synthetic control).",
             f"Net margin effect is {f.money(c['effect_per_day'])}/day ({f.money(c['total_effect'])} over {c['n_post']} days; "
             f"{f.text('95%')} interval {f.money(c['ci_low'])} to {f.money(c['ci_high'])}, {zero})."]
    parts.append("So the price rise has not demonstrably earned more profit." if c["ci_includes_zero"] else "The effect is statistically distinguishable from zero.")
    recs = _recs(tools_used, cache)["recommendations"]
    rec = next((r for r in recs if r["action_type"] == "price_review"), None)
    if rec:
        parts.append(f"Recommended: {f.text(rec['title'])} ({f.money(rec['expected_profit_delta'])}/day) in the Decision Inbox.")
    return " ".join(parts), [c["treated_sku"]]


def parse_simulation(question: str) -> tuple[dict, float, bool]:
    """(multipliers, percentage, applied_to_all_channels) from a what-if question.

    Channels: any of meta / google / amazon / tiktok / programmatic named; none named → every channel.
    Percentage: "+30%", "30 percent", "-10%" (default +20%); a cut / reduce / decrease / lower makes an unsigned number negative.
    """
    q = question.lower()
    found = [ch for ch in CHANNELS if re.search(rf"\b{ch}\b", q) or re.search(rf"\b{CHANNEL_DISPLAY[ch].lower()}\b", q)]
    pm = re.search(r"([+-]?\d+(?:\.\d+)?)\s*(?:%|percent)", q)
    pct = float(pm.group(1)) if pm else DEFAULT_SIMULATION_PCT
    if pm and not pm.group(1).startswith(("+", "-")) and re.search(r"\b(cut|reduce|decrease|lower|trim)\b", q):
        pct = -pct
    mult = max(0.0, 1 + pct / 100)
    all_channels = not found
    return {ch: mult for ch in (found or CHANNELS)}, pct / 100, all_channels


def _rules_simulate(question, f, tools_used, cache):
    mult, pct, everything = parse_simulation(question)
    r = run_tool("simulate_channel_budget", {"multipliers": mult})
    tools_used.append({"name": "simulate_channel_budget", "input": {"multipliers": mult}})
    s = r["summary"]
    scope = "All channels" if everything else " and ".join(CHANNEL_DISPLAY[c] for c in mult)
    parts = [f"{scope} {f.text(f.pct(pct, signed=True))}: spend {f.money(s['spend_delta'])}/day, profit {f.money(s['current']['profit'])} → "
             f"{f.money(s['simulated']['profit'])}/day ({f.money(s['profit_delta'])}), POAS {f.num(s['current']['poas'], 2)} → {f.num(s['simulated']['poas'], 2)}."]
    if s["stock_warnings"]:
        parts.append("Stock warning: this raises spend on " + ", ".join(s["stock_warnings"]) + " where cover is short, so those increases would be blocked.")
    else:
        parts.append("No stock warnings.")
    verdict = "reduces" if s["profit_delta"] < 0 else "improves"
    parts.append(f"Recommended: do not apply this blindly — it {verdict} profit; compare it with the Decision Inbox plan.")
    return " ".join(parts), list(mult)


def _rules_brief(question, f, tools_used, cache):
    k = run_tool("get_kpis")
    tools_used.append({"name": "get_kpis", "input": {}})
    recs = _recs(tools_used, cache)["recommendations"][:3]
    p = k["profit"]
    parts = [f"Last {f.num(k['period_days'], 0)} days: profit {f.money(p['value'])}/day ({f.pct(p['change'], signed=True)} vs the prior period), "
             f"POAS {f.num(k['poas']['value'], 2)}, data trust {f.pct(k['data_trust'])}."]
    risk = k["stock_at_risk"]["skus"]
    if risk:
        parts.append("Stock at risk: " + ", ".join(f"{s['name']} ({f.num(s['days_cover'])} days)" for s in risk) + ".")
    parts.append("Top actions: " + "; ".join(f"{f.text(r['title'])} ({f.money(r['expected_profit_delta'])}/day)" for r in recs) + ".")
    ids = [t["id"] for r in recs for t in r["targets"] if t["type"] != "ghost"][:4] + [s["sku_id"] for s in risk]
    return " ".join(parts), ids


INTENTS = [
    (("why", "drop", "fall", "fell", "explain", "cause", "down"), _rules_explain),
    (("scale", "next", "invest", "opportunit", "grow", "where should"), _rules_scale),
    (("stock", "inventory", "sell out", "stockout"), _rules_stock),
    (("roas", "double", "attribution", "trust", "real"), _rules_reconciliation),
    (("price",), _rules_price),
]


def _route(q: str):
    if "brief" in q:  # an explicit request for the brief wins (the brief question itself contains "why")
        return _rules_brief
    for keywords, handler in INTENTS:
        if any(k in q for k in keywords):
            return handler
    if any(k in q for k in ("what if", "simulate", "increase")) or re.search(r"[+-]\s*\d+\s*%", q):
        return _rules_simulate
    return _rules_brief


def limit_words(text: str, n: int = AGENT_MAX_WORDS) -> str:
    """Trim to at most n words, dropping whole sentences from the end (a lone over-long sentence is cut at n words)."""
    if len(text.split()) <= n:
        return text
    sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z₹])", text)
    while len(sentences) > 1 and len(" ".join(sentences).split()) > n:
        sentences.pop()
    out = " ".join(sentences)
    return out if len(out.split()) <= n else " ".join(out.split()[:n]).rstrip(",;:") + "…"


def _fallback(question: str, reason: str | None = None) -> dict:
    """The offline rules engine: keyword intent → the same read-only tools → a templated answer built from tool values."""
    global _LAST
    f = _LAST = Fmt()
    tools_used: list = []
    handler = _route(question.lower())
    text, ids = handler(question, f, tools_used, {})
    engine = f"fallback ({reason})" if reason else "rules"
    return {"answer": limit_words(text), "engine": engine, "tools_used": tools_used, "ids": ids}


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------
def answer(question: str, force_rules: bool = False) -> dict:
    """Answer a question. Never raises, never returns an error message: Claude if a key is set and it works,
    otherwise the rules engine (engine "rules", or "fallback (<ExceptionClass>)" when Claude failed)."""
    start = time.perf_counter()
    question = (question or "").strip() or BRIEF_QUESTION
    _load_env()
    try:
        if os.getenv("ANTHROPIC_API_KEY") and not force_rules:
            try:
                result = _claude(question)
            except Exception as exc:  # noqa: BLE001  ANY failure falls back; the reason is only the class name
                result = _fallback(question, type(exc).__name__)
        else:
            result = _fallback(question)
    except Exception as exc:  # noqa: BLE001  even the rules engine must not break the UI
        result = {"answer": "The engine could not assemble that answer right now; try the daily brief or open the Decision Inbox.",
                  "engine": f"rules (degraded: {type(exc).__name__})", "tools_used": [], "ids": []}
    ids = result.pop("ids", [])
    result["highlights"] = service.brain_targets_for(ids)[:MAX_HIGHLIGHTS] if ids else []
    result["note"] = NOTE
    result["duration_ms"] = round((time.perf_counter() - start) * 1000, 1)
    return result


def morning_brief() -> dict:
    """The daily brief: what changed, why, and the top actions."""
    return answer(BRIEF_QUESTION)


def print_answer(question: str, r: dict) -> None:
    print(f"\nQ: {question}")
    print(f"A: {r['answer']}")
    used = ", ".join(t["name"] + (f"({json.dumps(t['input'])})" if t["input"] else "") for t in r["tools_used"]) or "—"
    hl = ", ".join(f"{h['type']}:{h['id']}" for h in r["highlights"]) or "—"
    print(f"   engine: {r['engine']} · tools: {used} · highlights: {hl} · {r['duration_ms']:.0f} ms")


def main(argv: list[str] | None = None) -> None:
    import argparse

    p = argparse.ArgumentParser(description="M8 AI agent")
    p.add_argument("question", nargs="?", help="a question in plain English")
    p.add_argument("--demo", action="store_true", help="run the demo questions")
    p.add_argument("--rules", action="store_true", help="force the offline rules engine")
    args = p.parse_args(argv)
    questions = DEMO_QUESTIONS if args.demo else [args.question or BRIEF_QUESTION]
    for q in questions:
        print_answer(q, answer(q, force_rules=args.rules))


if __name__ == "__main__":
    main(sys.argv[1:])
