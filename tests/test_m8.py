"""M8 tests: the read-only service layer, the rules engine, the Claude tool loop (mocked) and the safety guarantees.

M1 → M7 run inside a pytest temp folder. The Claude path is only ever exercised with scripted fake clients, so these
tests need no network and no API key, and a developer's real .env can never leak into them.
"""
import json
from types import SimpleNamespace

import pytest

from backend.agent import agent
from backend.agent import validate as v
from backend.api import service
from backend.core import config
from backend.core.db import load_state
from backend.detection.runner import run_detection
from backend.generator import generate as gen
from backend.ingest.pipeline import run_pipeline
from backend.optimizer.runner import run_optimizer

AS_OF = "2026-10-06T23:00:00"


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    root = tmp_path_factory.mktemp("m8")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(config, "DATA_DIR", root)
        mp.setattr(config, "RAW_DIR", root / "raw")
        mp.setattr(config, "DB_PATH", root / "engine.db")
        mp.setattr(config, "STATE_PATH", root / "state.json")
        gen.main(quiet=True)
        run_pipeline(as_of=AS_OF, verbose=False, emit_brain_events=False)
        run_detection(as_of=AS_OF, emit_brain_events=False, verbose=False)
        run_optimizer(as_of=AS_OF, verbose=False)
        yield root


@pytest.fixture(autouse=True)
def isolated(env, monkeypatch):
    """No real .env, no key, a clean answer cache, and a registry we can trust."""
    monkeypatch.setattr(agent, "_load_env", lambda: None)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("CLAUDE_MODEL", raising=False)
    v._CACHE.clear()


def _ok(result):
    ok, detail = result
    assert ok, detail


# ---------------------------------------------------------------- one test per validation check (no network)
def test_v01_demo_answers():
    _ok(v.check_demo_answers())


def test_v02_fatigue():
    _ok(v.check_fatigue())


def test_v03_other_whys():
    _ok(v.check_other_whys())


def test_v04_roas_real():
    _ok(v.check_roas_real())


def test_v05_simulation():
    _ok(v.check_simulation())


def test_v06_scale():
    _ok(v.check_scale())


def test_v07_price():
    _ok(v.check_price())


def test_v08_traceability():
    _ok(v.check_traceability())


def test_v09_invalid_key_falls_back_without_network(monkeypatch):
    """A bad key (here: a client whose first call fails like a 401) → a rules answer labelled "fallback (...)"."""
    class Boom:
        class messages:  # noqa: N801
            @staticmethod
            def create(**kw):
                raise PermissionError("401 invalid x-api-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "invalid-key-for-test")
    monkeypatch.setattr(agent, "_make_client", lambda key: Boom())
    r = agent.answer("Is our ROAS real?")
    assert r["engine"] == "fallback (PermissionError)" and "Meta" in r["answer"] and len(r["answer"]) > 20


def test_v10_no_secrets_or_traces(monkeypatch):
    secret = "sk-ant-test-secret-9876543210"

    class Leaky:
        class messages:  # noqa: N801
            @staticmethod
            def create(**kw):
                raise RuntimeError(f"auth failed for key {secret}")  # an exception message that contains the key
    monkeypatch.setenv("ANTHROPIC_API_KEY", secret)
    monkeypatch.setattr(agent, "_make_client", lambda key: Leaky())
    outs = [agent.answer(q) for q in agent.DEMO_QUESTIONS]
    blob = json.dumps(outs)
    assert secret not in blob and "Traceback" not in blob and 'File "' not in blob
    assert all(o["engine"] == "fallback (RuntimeError)" for o in outs)  # only the class name, never the message


def test_v11_tools_are_read_only():
    _ok(v.check_read_only_tools())


def test_v12_word_limit():
    _ok(v.check_word_limit())


def test_v13_speed():
    _ok(v.check_speed())


# ---------------------------------------------------------------- entity matching and intent routing
def anomalies():
    return agent.run_tool("list_anomalies")


def test_entity_matching_picks_the_longest_match():
    a = agent.match_anomaly("Why did Summer Sneakers drop on Meta?", anomalies())
    assert a["kind"] == "creative_fatigue" and a["entity_id"] == "CMP-01"  # "summer sneakers" (15) beats "meta" (4)
    assert agent.match_anomaly("what happened to CMP-10?", anomalies())["entity_id"] == "CMP-10"
    assert agent.match_anomaly("why is Running Pro in trouble", anomalies())["entity_id"] == "SKU-B"


def test_ties_prefer_the_root_cause_over_a_knock_on():
    google = agent.match_anomaly("Why is Google down?", anomalies())
    assert google["kind"] == "cpc_spike"  # CMP-02 (a knock-on profit drop) also contains "Google"
    sneakers = agent.match_anomaly("Why did Summer Sneakers drop?", anomalies())
    assert sneakers["kind"] == "creative_fatigue"  # not CMP-02 (Google · Summer Sneakers), which is a knock-on


def test_unmatched_why_question_explains_the_largest_loss():
    items = anomalies()
    worst = min(items, key=lambda a: a["profit_impact"])
    assert agent.match_anomaly("why is everything terrible", items)["id"] == worst["id"]
    r = agent.answer("why is everything terrible", force_rules=True)
    assert worst["label"] in r["answer"] and r["tools_used"][1]["input"] == {"anomaly_id": worst["id"]}


@pytest.mark.parametrize("question,handler", [
    ("Why did X fall", agent._rules_explain), ("explain the cause", agent._rules_explain), ("what is down", agent._rules_explain),
    ("where should I invest", agent._rules_scale), ("any opportunity?", agent._rules_scale),
    ("will we hit a stockout", agent._rules_stock), ("inventory status", agent._rules_stock),
    ("is attribution trustworthy", agent._rules_reconciliation), ("what is our real roas", agent._rules_reconciliation),
    ("how did the price change go", agent._rules_price),
    ("what if we simulate meta", agent._rules_simulate), ("increase budget", agent._rules_simulate), ("google +15%", agent._rules_simulate),
    ("give me the summary", agent._rules_brief), ("hello", agent._rules_brief)])
def test_intent_routing(question, handler):
    assert agent._route(question.lower()) is handler


def test_first_matching_intent_wins():
    assert agent._route("why did the price drop") is agent._rules_explain  # "why" beats "price"
    assert agent._route("is the roas real price check") is agent._rules_reconciliation  # roas beats price


@pytest.mark.parametrize("question,mult,pct,all_channels", [
    ("What if Google +30%?", {"google": 1.3}, 0.30, False),
    ("what if google 30 percent", {"google": 1.3}, 0.30, False),
    ("what if google -10%", {"google": 0.9}, -0.10, False),
    ("what if we cut meta by 25%", {"meta": 0.75}, -0.25, False),
    ("simulate tiktok and amazon +50%", {"tiktok": 1.5, "amazon": 1.5}, 0.50, False),
    ("what if Google", {"google": 1.2}, 0.20, False),  # default +20%
    ("what if we increase budget 10%", dict.fromkeys(config.CHANNELS, 1.1), 0.10, True),
])
def test_percentage_and_channel_parsing(question, mult, pct, all_channels):
    got, p, everything = agent.parse_simulation(question)
    assert got == pytest.approx(mult) and p == pytest.approx(pct) and everything is all_channels


def test_simulation_answer_for_a_cut_and_for_all_channels():
    cut = agent.answer("what if google -10%", force_rules=True)["answer"]
    assert cut.startswith("Google -10%") and "profit" in cut
    allc = agent.answer("what if we increase budget 10%", force_rules=True)["answer"]
    assert allc.startswith("All channels +10%")


def test_stock_warning_names_the_blocked_campaign():
    r = agent.answer("what if Meta +30%", force_rules=True)
    assert "Stock warning" in r["answer"] and "CMP-03" in r["answer"]  # Meta runs a Running Pro campaign


def test_the_brief_question_routes_to_the_brief_not_to_explain():
    assert agent._route(agent.BRIEF_QUESTION.lower()) is agent._rules_brief  # it contains "why", but "brief" wins
    assert agent._route("why did profit fall today") is agent._rules_explain


def test_empty_question_returns_the_brief():
    for q in ("", "   ", None):
        r = agent.answer(q, force_rules=True)
        assert r["answer"].startswith("Last 7 days:") and r["engine"] == "rules"
    assert agent.morning_brief()["answer"].startswith("Last 7 days:")


def test_answers_have_the_ui_fields():
    r = agent.answer("Is our ROAS real?", force_rules=True)
    assert set(r) == {"answer", "engine", "tools_used", "highlights", "note", "duration_ms"}
    assert r["note"] == "Every number comes from an engine tool call." and r["duration_ms"] > 0
    assert len(r["highlights"]) <= agent.MAX_HIGHLIGHTS and all(set(h) == {"type", "id"} for h in r["highlights"])
    assert all(set(t) == {"name", "input"} for t in r["tools_used"])


# ---------------------------------------------------------------- service layer
def test_service_functions_are_json_serialisable():
    outputs = [service.kpis(), service.kpis(period=14), service.anomalies(), service.diagnosis("AN-001"), service.pending_recommendations(),
               service.causal(), service.causal("EV-2"), service.channel_simulate({"google": 1.2}), service.opportunities(),
               service.reconciliation(), service.learning()]
    for o in outputs:
        json.dumps(o, allow_nan=False)  # never raises: NaN / inf are already None


def test_kpis_shape_and_values():
    k = service.kpis()
    assert {"spend", "revenue", "profit", "poas", "roas_true", "roas_platform"} <= set(k)
    assert all(set(k[x]) == {"value", "change"} for x in ("spend", "revenue", "profit", "poas", "roas_true", "roas_platform"))
    assert k["roas_platform"]["value"] > k["roas_true"]["value"]  # platforms over-report
    assert k["stock_at_risk"]["value"] == 1 and k["stock_at_risk"]["skus"][0]["sku_id"] == "SKU-B"
    assert k["as_of"] == "2026-10-06" and 0.7 < k["data_trust"] < 0.8 and k["period_days"] == 7
    assert service.kpis(period=14)["period_days"] == 14


def test_diagnosis_and_unknown_anomaly():
    d = service.diagnosis("AN-004")
    assert d["anomaly"]["kind"] == "cpc_spike" and d["root_cause"]["factors"] and "Auction cost" in d["root_cause"]["narrative"]
    with pytest.raises(KeyError, match="Not found: anomaly 'AN-999'"):
        service.diagnosis("AN-999")


def test_recommendations_use_pending_state_or_a_fresh_build():
    r = service.pending_recommendations()  # fresh state: built, never saved
    assert r["objective"] == "max_profit" and r["summary"]["count"] == 11 and r["recommendations"][0]["action"]["type"] == "inventory_protect"
    assert not load_state()["decisions"]  # building did not write state


def test_causal_default_event_and_unsupported_event():
    c = service.causal()
    assert c["event_id"] == "EV-2" and c["treated_sku"] == "SKU-D" and c["ci_includes_zero"] is True and c["n_post"] == 14
    with pytest.raises(NotImplementedError):
        service.causal("EV-4")


def test_opportunities_from_tables_and_from_the_model(monkeypatch):
    service.invalidate()
    from_tables = service.opportunities()
    monkeypatch.setattr(service, "table_exists", lambda name: False)
    service.invalidate()
    from_model = service.opportunities()
    assert from_tables["opportunities"][0]["label"] == from_model["opportunities"][0]["label"] == "Trail Max · Google · retargeting"
    assert from_tables["model_r2_holdout"] == pytest.approx(from_model["model_r2_holdout"], abs=1e-6)


def test_brain_targets_mapping():
    got = service.brain_targets_for(["CMP-01", "SKU-B", "google", "Google", "meta_ads", "programmatic", "nope", "CMP-01"])
    assert got == [{"type": "neuron", "id": "CMP-01"}, {"type": "neuron", "id": "SKU-B"}, {"type": "cluster", "id": "google"},
                   {"type": "source", "id": "meta_ads"}, {"type": "cluster", "id": "programmatic"}]
    assert service.brain_targets_for([]) == [] and service.brain_targets_for(["tiktok"]) == [{"type": "cluster", "id": "tiktok"}]


def test_service_never_writes_state(env):
    before = config.STATE_PATH.read_bytes() if config.STATE_PATH.exists() else None
    service.learning()  # an unseeded history is seeded in memory only
    service.pending_recommendations()
    for q in agent.DEMO_QUESTIONS:
        agent.answer(q, force_rules=True)
    after = config.STATE_PATH.read_bytes() if config.STATE_PATH.exists() else None
    assert before == after and not load_state()["outcomes"]


# ---------------------------------------------------------------- tools and formatting
def test_tool_specs_are_valid_claude_tools():
    assert len(agent.TOOL_SPECS) == 8 == len(agent.TOOLS)
    for s in agent.TOOL_SPECS:
        assert set(s) == {"name", "description", "input_schema"} and s["input_schema"]["type"] == "object" and len(s["description"]) > 40
    assert agent.TOOLS["explain_anomaly"]["input_schema"]["required"] == ["anomaly_id"]
    assert agent.TOOLS["simulate_channel_budget"]["input_schema"]["required"] == ["multipliers"]


def test_every_tool_runs_and_serialises():
    args = {"explain_anomaly": {"anomaly_id": "AN-001"}, "simulate_channel_budget": {"multipliers": {"google": 1.2}}}
    for name in agent.TOOLS:
        text = agent._serialise(agent.run_tool(name, args.get(name)))
        assert 0 < len(text) <= config.AGENT_TOOL_RESULT_MAX_CHARS and json.loads(text)


def test_simulate_tool_rejects_bad_input():
    for bad in ({"myspace": 2}, {"google": -1}, {"google": "lots"}):
        with pytest.raises(ValueError):
            agent.run_tool("simulate_channel_budget", {"multipliers": bad})


def test_tool_results_are_truncated(monkeypatch):
    monkeypatch.setattr(agent, "AGENT_TOOL_RESULT_MAX_CHARS", 200)
    text = agent._serialise({"x": "y" * 1000})
    assert len(text) == 200 and text.endswith("…[truncated]")


def test_limit_words_trims_at_a_sentence_boundary():
    text = "First sentence here. Second sentence follows. " + "Filler words " * 60 + "end. Last one."
    out = agent.limit_words(text, 120)
    assert len(out.split()) <= 120 and out.startswith("First sentence here. Second sentence follows.") and out.endswith(".")
    assert "Last one." not in out
    assert agent.limit_words("short answer.", 120) == "short answer."


def test_limit_words_hard_caps_a_lone_overlong_sentence():
    out = agent.limit_words("word " * 200, 120)
    assert len(out.split()) == 120 and out.endswith("…")


def test_formatter_registry_and_token_regex():
    f = agent.Fmt()
    s = f"{f.money(-3300)} {f.money(53565)} {f.pct(0.22)} {f.pct(-0.218, signed=True)} {f.num(2.4, 2)} {f.text('went from 1.9 to 3.7')}"
    assert agent.numeric_tokens(s) <= f.registry
    assert agent.numeric_tokens("a made-up ₹99.9k and 42% and 7.77") - f.registry == {"₹99.9k", "42%", "7.77"}  # untraced numbers are caught
    assert agent.numeric_tokens("CMP-01 and EV-3 and 60 days") == set()  # ids and bare integers are not numbers to trace


# ---------------------------------------------------------------- the Claude loop (scripted fake client)
def block(kind, **kw):
    return SimpleNamespace(type=kind, **kw)


class FakeClient:
    """Plays back scripted responses and records every request."""

    def __init__(self, responses):
        self.responses, self.calls = list(responses), []
        self.messages = self

    def create(self, **kw):
        self.calls.append({**kw, "messages": [dict(m) for m in kw["messages"]]})
        return self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]


def tool_use(name, input_, id_="tu1"):
    return SimpleNamespace(stop_reason="tool_use", content=[block("tool_use", id=id_, name=name, input=input_)])


def text(t):
    return SimpleNamespace(stop_reason="end_turn", content=[block("text", text=t)])


def test_claude_loop_executes_tools_and_returns_the_answer():
    client = FakeClient([tool_use("get_reconciliation", {}), text("Meta over-reports by 22%; approve the data fixes.")])
    r = agent._claude("Is our ROAS real?", client=client)
    assert r["engine"] == "claude" and r["answer"] == "Meta over-reports by 22%; approve the data fixes."
    assert r["tools_used"] == [{"name": "get_reconciliation", "input": {}}]
    assert {"meta_ads", "google_ads"} <= set(r["ids"])
    first, second = client.calls
    assert first["system"] == agent.SYSTEM and first["tools"] == agent.TOOL_SPECS and first["max_tokens"] == config.AGENT_MAX_TOKENS
    assert first["model"] == config.CLAUDE_MODEL_DEFAULT and "temperature" not in first
    result_msg = second["messages"][-1]
    assert result_msg["role"] == "user" and result_msg["content"][0]["type"] == "tool_result" and result_msg["content"][0]["tool_use_id"] == "tu1"
    payload = json.loads(result_msg["content"][0]["content"])  # the real tool result went back to the model
    assert {p["channel"] for p in payload} == set(config.CHANNELS) and "roas_true" in payload[0]
    assert second["messages"][-2]["role"] == "assistant"


def test_claude_answer_goes_through_answer_with_highlights(monkeypatch):
    client = FakeClient([tool_use("explain_anomaly", {"anomaly_id": "AN-001"}), text("Creative fatigue on Meta; refresh the creative.")])
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("CLAUDE_MODEL", "claude-test-model")
    monkeypatch.setattr(agent, "_make_client", lambda key: client)
    r = agent.answer("Why did Summer Sneakers drop?")
    assert r["engine"] == "claude" and r["highlights"] == [{"type": "neuron", "id": "CMP-01"}] and r["note"]
    assert client.calls[0]["model"] == "claude-test-model"  # CLAUDE_MODEL overrides the default


def test_a_failing_tool_is_reported_to_the_model_not_raised():
    client = FakeClient([tool_use("explain_anomaly", {"anomaly_id": "AN-999"}), text("I could not find that anomaly.")])
    r = agent._claude("explain AN-999", client=client)
    result = client.calls[1]["messages"][-1]["content"][0]
    assert result["is_error"] is True and "Not found: anomaly" in json.loads(result["content"])["error"]
    assert r["engine"] == "claude" and r["ids"] == []


def test_unknown_tool_name_is_a_tool_error():
    client = FakeClient([tool_use("execute_decision", {"rec_id": "REC-567405"}), text("I cannot execute decisions.")])
    r = agent._claude("approve everything", client=client)
    result = client.calls[1]["messages"][-1]["content"][0]
    assert result["is_error"] is True and "KeyError" in result["content"] and r["answer"] == "I cannot execute decisions."


def test_the_loop_stops_after_the_step_limit(monkeypatch):
    client = FakeClient([tool_use("get_kpis", {})])  # never answers
    with pytest.raises(agent.AgentStepLimit):
        agent._claude("loop forever", client=client)
    assert len(client.calls) == config.AGENT_MAX_STEPS + 1
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(agent, "_make_client", lambda key: FakeClient([tool_use("get_kpis", {})]))
    r = agent.answer("loop forever")
    assert r["engine"] == "fallback (AgentStepLimit)" and r["answer"].startswith("Last 7 days:")  # still a good answer


def test_a_client_that_raises_triggers_the_fallback(monkeypatch):
    class Down:
        messages = SimpleNamespace(create=lambda **kw: (_ for _ in ()).throw(ConnectionError("network down")))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(agent, "_make_client", lambda key: Down())
    r = agent.answer("Is Running Pro going to sell out?")
    assert r["engine"] == "fallback (ConnectionError)" and "5.0 days" in r["answer"] and "network down" not in json.dumps(r)


def test_an_empty_claude_answer_falls_back(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(agent, "_make_client", lambda key: FakeClient([SimpleNamespace(stop_reason="end_turn", content=[])]))
    assert agent.answer("hi")["engine"] == "fallback (RuntimeError)"


def test_force_rules_ignores_the_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(agent, "_make_client", lambda key: (_ for _ in ()).throw(AssertionError("must not be called")))
    assert agent.answer("Is our ROAS real?", force_rules=True)["engine"] == "rules"


def test_even_a_broken_rules_engine_never_raises(monkeypatch):
    monkeypatch.setattr(agent, "_route", lambda q: (_ for _ in ()).throw(ValueError("bug")))
    r = agent.answer("anything", force_rules=True)
    assert r["engine"] == "rules (degraded: ValueError)" and "could not assemble" in r["answer"] and r["highlights"] == []


# ---------------------------------------------------------------- CLI
def test_cli_prints_answers(capsys):
    agent.main(["Is our ROAS real?", "--rules"])
    out = capsys.readouterr().out
    assert "Q: Is our ROAS real?" in out and "engine: rules" in out and "source:meta_ads" in out
    agent.main(["--demo", "--rules"])
    out = capsys.readouterr().out
    assert out.count("engine: rules") == 7 and "Trail Max" in out
