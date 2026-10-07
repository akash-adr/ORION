"""Module 9 validation: the whole loop over HTTP, against BOTH servers.

FastAPI (`backend.api.main`, through TestClient) and the zero-dependency `backend.api.devserver` (a real socket on a random
port, in a thread) are driven on a temporary pipeline (temp data dir, db and state), so the real data/state.json is never touched.
Run:  python -m backend.api.validate
"""
from __future__ import annotations

import http.client
import json
import logging
import os
import re
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, NamedTuple

from backend.core import config

VOLATILE = {"ts", "as_of", "duration_ms", "last_synced", "next_refresh_at", "last_refresh_at", "generated_at"}
SENTINEL_KEY = "sk-ant-VALIDATION-SENTINEL-0000"
QUESTION = "Why did ROAS drop for Summer Sneakers?"

# Every operation both servers must expose: (method, template)
ROUTES = [
    ("GET", "/health"), ("GET", "/kpis"), ("GET", "/trend"), ("GET", "/channels"), ("GET", "/campaigns"), ("GET", "/sources"),
    ("GET", "/data-quality"), ("GET", "/anomalies"), ("GET", "/anomalies/{x}/diagnosis"), ("GET", "/causal/{x}"),
    ("GET", "/reconciliation"), ("GET", "/recommendations"), ("POST", "/decisions/{x}/approve"), ("POST", "/decisions/{x}/reject"),
    ("POST", "/decisions/{x}/rollback"), ("GET", "/audit"), ("POST", "/optimize"), ("POST", "/simulate"), ("POST", "/simulate/channels"),
    ("GET", "/curves"), ("GET", "/opportunities"), ("GET", "/learning"), ("GET", "/brain/manifest"), ("GET", "/brain/nodes"),
    ("GET", "/brain/snapshot"), ("GET", "/brain/events"), ("GET", "/brain/state"), ("POST", "/brain/replay"), ("GET", "/settings"),
    ("POST", "/settings"), ("GET", "/meta/config"), ("GET", "/loop/last"), ("POST", "/ask"), ("POST", "/refresh"), ("POST", "/demo/reset"),
]


class R(NamedTuple):
    status: int
    data: Any
    text: str
    ms: float
    bad_json: bool


def _reject_const(name: str):
    raise ValueError(f"non-JSON constant {name}")


def strip(o: Any) -> Any:
    if isinstance(o, dict):
        return {k: strip(v) for k, v in o.items() if k not in VOLATILE}
    if isinstance(o, list):
        return [strip(v) for v in o]
    return o


def first_diff(a: Any, b: Any, path: str = "") -> str | None:
    if type(a) is not type(b):
        return f"{path or '/'}: {type(a).__name__} vs {type(b).__name__}"
    if isinstance(a, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b:
                return f"{path}/{k}: missing on one side"
            d = first_diff(a[k], b[k], f"{path}/{k}")
            if d:
                return d
    elif isinstance(a, list):
        if len(a) != len(b):
            return f"{path}: length {len(a)} vs {len(b)}"
        for i, (x, y) in enumerate(zip(a, b)):
            d = first_diff(x, y, f"{path}[{i}]")
            if d:
                return d
    elif a != b:
        return f"{path}: {a!r} vs {b!r}"
    return None


class Ctx:
    """A temp pipeline plus both servers."""

    def __init__(self) -> None:
        from fastapi.testclient import TestClient

        from backend.agent import agent
        from backend.api import devserver, service
        from backend.api.main import app
        from backend.generator import generate as gen

        self.service, self.agent, self.devserver = service, agent, devserver
        self.real_state = Path(config.STATE_PATH)
        self.real_state_bytes = self.real_state.read_bytes() if self.real_state.exists() else None
        self._saved = {k: getattr(config, k) for k in ("DATA_DIR", "RAW_DIR", "DB_PATH", "STATE_PATH")}
        self._tmp = tempfile.TemporaryDirectory(prefix="dq_m9_")
        root = Path(self._tmp.name)
        config.DATA_DIR, config.RAW_DIR = root, root / "raw"
        config.DB_PATH, config.STATE_PATH = root / "engine.db", root / "state.json"
        # a sentinel key proves it never leaks; the Claude call is stubbed to fail so the offline rules engine answers
        self._env = os.environ.get("ANTHROPIC_API_KEY")
        os.environ["ANTHROPIC_API_KEY"] = SENTINEL_KEY
        self._agent_saved = (agent._load_env, agent._claude)
        agent._load_env = lambda: None
        agent._claude = lambda q: (_ for _ in ()).throw(RuntimeError("simulated outage"))
        gen.main(quiet=True)
        self.fa = TestClient(app, raise_server_exceptions=False)  # no `with`: the lifespan loop is not started
        self.server, self.stop = devserver.make_server(0, loop=False)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.texts: list[str] = []
        self.lat: dict[str, dict[str, float]] = {}
        self._lock = threading.Lock()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.stop.set()
        self.agent._load_env, self.agent._claude = self._agent_saved
        if self._env is None:
            os.environ.pop("ANTHROPIC_API_KEY", None)
        else:
            os.environ["ANTHROPIC_API_KEY"] = self._env
        for k, v in self._saved.items():
            setattr(config, k, v)
        self._tmp.cleanup()

    # ------------------------------------------------------------------ requests
    def req(self, server: str, method: str, path: str, body: Any = None) -> R:
        t0 = time.perf_counter()
        if server == "fa":
            r = self.fa.request(method, path, json=body) if body is not None else self.fa.request(method, path)
            status, text = r.status_code, r.text
        else:
            conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=120)
            payload = json.dumps(body).encode() if body is not None else None
            conn.request(method, path, body=payload, headers={"Content-Type": "application/json"} if payload else {})
            resp = conn.getresponse()
            status, text = resp.status, resp.read().decode()
            conn.close()
        ms = (time.perf_counter() - t0) * 1000
        try:
            data, bad = json.loads(text, parse_constant=_reject_const), False
        except ValueError:
            data, bad = None, True
        with self._lock:
            self.texts.append(text if len(text) < 200_000 else text[:200_000])
        return R(status, data, text, ms, bad)

    def fresh(self) -> None:
        """Clean state, caches and one loop run (supervised, max_profit)."""
        from backend.core.db import reset_state

        with self.service.STATE_LOCK:
            reset_state()
            self.service.invalidate()
        res = self.service.refresh()
        assert res["ok"], f"fresh refresh failed: {res}"

    def pending(self, server: str = "fa") -> list[dict]:
        return self.req(server, "GET", "/recommendations").data["pending"]

    def nodes(self) -> dict[str, dict]:
        return {n["entity_id"]: n for n in self.req("fa", "GET", "/brain/nodes").data["nodes"]}

    def last_event_id(self) -> str | None:
        return self.req("fa", "GET", "/brain/events?limit=1").data["last_id"]


def _spend_decision(ctx: Ctx) -> dict:
    return next(d for d in ctx.pending() if d["action"]["changes"] and not d["blocked"])


# ====================================================================== the 20 checks
def get_cases(ctx: Ctx) -> list[str]:
    aid = ctx.req("fa", "GET", "/anomalies").data[0]["id"]
    eid = ctx.service.causal()["event_id"]
    return ["/health", "/kpis", "/kpis?period=30", "/trend", "/trend?days=14", "/channels", "/campaigns", "/sources", "/data-quality",
            "/anomalies", f"/anomalies/{aid}/diagnosis", f"/causal/{eid}", "/reconciliation", "/recommendations",
            "/recommendations?objective=clear_inventory", "/audit", "/curves", "/opportunities", "/learning", "/settings",
            "/brain/manifest", "/brain/nodes", "/brain/snapshot", "/brain/events", "/brain/events?limit=5", "/brain/state", "/meta/config", "/loop/last"]


def check_routes(ctx: Ctx):
    ctx.fresh()
    cases = [("GET", p, None) for p in get_cases(ctx)]
    cases += [("POST", "/optimize", None), ("POST", "/optimize", {"objective": "clear_inventory"}),
              ("POST", "/simulate", {"plan": {"CMP-01": 30000}}), ("POST", "/simulate/channels", {"multipliers": {"google": 1.2}}),
              ("POST", "/ask", {"question": QUESTION}), ("POST", "/settings", {}), ("POST", "/brain/replay", None)]
    ids = [d["id"] for d in ctx.pending()]
    cases += [("POST", f"/decisions/{ids[0]}/approve", None), ("POST", f"/decisions/{ids[1]}/reject", None),
              ("POST", f"/decisions/{ids[0]}/rollback", None), ("POST", "/refresh", None), ("POST", "/demo/reset", None)]
    bad, n = [], 0
    for method, path, body in cases:
        label = f"{method} {path.split('?')[0]}" + ("?" + path.split("?")[1] if "?" in path else "")
        for server in ("fa", "dev"):
            first = ctx.req(server, method, path, body)
            warm = ctx.req(server, method, path, body) if method == "GET" else first
            n += 1
            if not (200 <= first.status < 300) or first.bad_json or warm.bad_json:
                bad.append(f"{server} {label}: {first.status}{' bad json' if first.bad_json else ''}")
            slot = ctx.lat.setdefault(label, {})
            if server == "fa":
                slot.setdefault("fa_cold", first.ms)
                slot["fa_warm"] = warm.ms
            else:
                slot.setdefault("dev_warm", warm.ms)
    return not bad, f"{n} requests over {len(cases)} routes x 2 servers, all 2xx valid JSON" if not bad else "; ".join(bad[:5])


def check_parity(ctx: Ctx):
    ctx.fresh()
    cases = get_cases(ctx)
    for p in cases:  # warm: the first /recommendations call may build and persist decisions
        ctx.req("fa", "GET", p)
    diffs = []
    for p in cases:
        a, b = ctx.req("fa", "GET", p), ctx.req("dev", "GET", p)
        d = first_diff(strip(a.data), strip(b.data)) if a.status == b.status else f"status {a.status} vs {b.status}"
        if d:
            diffs.append(f"{p}: {d}")
    return not diffs, f"{len(cases)} GET routes identical on both servers (volatile fields stripped)" if not diffs else "; ".join(diffs[:3])


def check_docs(ctx: Ctx):
    docs, spec = ctx.req("fa", "GET", "/docs"), ctx.req("fa", "GET", "/openapi.json")
    ops = {(m.upper(), re.sub(r"\{[^}]+\}", "{x}", p)) for p, v in spec.data["paths"].items() for m in v}
    want = {(m, re.sub(r"\{[^}]+\}", "{x}", p)) for m, p in ROUTES}
    dev = {(m, re.sub(r"\(\?P<\w+>\[\^/\]\+\)", "{x}", p.pattern[1:-1])) for m, t in (("GET", ctx.devserver.GET), ("POST", ctx.devserver.POST)) for p, _ in t}
    ok = docs.status == 200 and "swagger" in docs.text.lower() and ops == want and dev == want
    return ok, f"/docs up, openapi lists {len(ops)} operations, devserver exposes the same {len(dev)}" if ok else f"openapi-only {sorted(ops - want)}, missing {sorted(want - ops)}, dev diff {sorted(dev ^ want)}"


def check_errors(ctx: Ctx):
    cases = [("GET", "/nope", None, 404, ""), ("GET", "/anomalies/NOPE/diagnosis", None, 404, "Not found"),
             ("GET", "/causal/EV-999", None, 404, "Not found"), ("POST", "/decisions/REC-nope/approve", None, 404, "Not found"),
             ("POST", "/simulate", {"plan": {"CMP-XX": 100}}, 404, "Not found"),
             ("POST", "/settings", {"autonomy": "reckless"}, 400, ""), ("POST", "/settings", {"objective": "world_domination"}, 400, ""),
             ("POST", "/ask", {}, 422, ""), ("POST", "/simulate/channels", {"multipliers": {"mars": 2}}, 404, "Not found")]
    bad = []
    for server in ("fa", "dev"):
        for method, path, body, status, frag in cases:
            r = ctx.req(server, method, path, body)
            if r.status != status or frag not in r.text or r.bad_json:
                bad.append(f"{server} {method} {path}: {r.status} {r.text[:60]}")
    return not bad, f"{len(cases) * 2} error cases return the right status with a JSON body" if not bad else "; ".join(bad[:4])


def check_approve(ctx: Ctx):
    ctx.fresh()
    d = _spend_decision(ctx)
    cid = d["action"]["changes"][0]["campaign_id"]
    n0, sn0 = ctx.nodes(), ctx.req("fa", "GET", "/brain/snapshot").data
    audit0, out0, ev0 = len(ctx.req("fa", "GET", "/audit").data), len(ctx.req("fa", "GET", "/learning").data["outcomes"]), ctx.last_event_id()
    res = ctx.req("fa", "POST", f"/decisions/{d['id']}/approve")
    n1, sn1 = ctx.nodes(), ctx.req("fa", "GET", "/brain/snapshot").data
    learning = ctx.req("fa", "GET", "/learning").data
    types = [e["type"] for e in ctx.req("fa", "GET", f"/brain/events?since={ev0}").data["events"]]
    s0 = {(s["source"], s["target"]): s["strength"] for s in sn0["synapses"]}
    moved = [k for s in sn1["synapses"] if s0.get((k := (s["source"], s["target"]))) not in (None, s["strength"])]
    ok = (res.data.get("ok") is True and len(ctx.req("fa", "GET", "/audit").data) > audit0
          and len(learning["outcomes"]) == out0 + 1 and any(o["decision_id"] == d["id"] for o in learning["outcomes"])
          and "approval" in types and "outcome" in types and abs(n1[cid]["current_spend"] - n0[cid]["current_spend"]) > 1
          and bool(moved) and d["id"] not in [p["id"] for p in ctx.pending()])
    return ok, (f"{d['id']} approved: audit +1, outcome logged, events {types}, {cid} spend {n0[cid]['current_spend']:.0f}→{n1[cid]['current_spend']:.0f}, "
                f"{len(moved)} synapses strengthened")


def check_approve_again(ctx: Ctx):
    ctx.fresh()
    d = _spend_decision(ctx)
    ctx.req("fa", "POST", f"/decisions/{d['id']}/approve")
    again = ctx.req("fa", "POST", f"/decisions/{d['id']}/approve")
    ok = again.status == 200 and again.data.get("ok") is False and bool(again.data.get("reason"))
    return ok, f"second approve → ok:false, reason '{again.data.get('reason')}'"


def check_rollback(ctx: Ctx):
    ctx.fresh()
    d = _spend_decision(ctx)
    cid = d["action"]["changes"][0]["campaign_id"]
    before = ctx.nodes()[cid]["current_spend"]
    ctx.req("fa", "POST", f"/decisions/{d['id']}/approve")
    moved = ctx.nodes()[cid]["current_spend"]
    rb = ctx.req("fa", "POST", f"/decisions/{d['id']}/rollback")
    after = ctx.nodes()[cid]["current_spend"]
    again = ctx.req("fa", "POST", f"/decisions/{d['id']}/rollback")
    summary = ctx.req("fa", "GET", "/recommendations").data["summary"]
    ok = (rb.data.get("ok") is True and abs(moved - before) > 1 and abs(after - before) < 0.01 and again.data.get("ok") is False
          and summary["rolled_back"] == 1)
    return ok, f"{cid} spend {before:.0f} → {moved:.0f} → {after:.0f} after rollback; a second rollback is refused"


def check_blocked(ctx: Ctx):
    from backend.core.db import load_state, save_state

    ctx.fresh()
    base = ctx.nodes()["CMP-03"]["current_spend"]
    change = {"campaign_id": "CMP-03", "name": "Meta · Running Pro · lookalike", "channel": "meta", "from_budget": base, "to_budget": round(base * 1.2, 2)}
    fake = {"id": "REC-bad001", "title": "Test: raise Running Pro", "issue": "", "cause": "", "expected_profit_delta": 1.0, "confidence": 0.9,
            "risk": "low", "requires_approval": False, "blocked": False, "priority": 1.0, "evidence": [], "anomaly_id": None, "status": "pending",
            "action": {"type": "scale_up", "changes": [change], "targets": [], "notes": []}}
    with ctx.service.STATE_LOCK:
        st = load_state()
        st["decisions"].append(fake)
        save_state(st)
    r1 = ctx.req("fa", "POST", "/decisions/REC-bad001/approve")
    with ctx.service.STATE_LOCK:
        st = load_state()
        st["decisions"][-1]["blocked"] = True
        save_state(st)
    r2 = ctx.req("fa", "POST", "/decisions/REC-bad001/approve")
    unchanged = abs(ctx.nodes()["CMP-03"]["current_spend"] - base) < 0.01
    ok = all(r.status == 200 and r.data["ok"] is False and "Blocked by guardrail" in r.data["reason"] for r in (r1, r2)) and unchanged
    return ok, f"raising low-stock CMP-03 refused twice ({r2.data['reason']}); spend unchanged"


def check_autonomous(ctx: Ctx):
    from backend.core.db import load_state

    ctx.fresh()
    ctx.req("fa", "POST", "/settings", {"autonomy": "autonomous"})
    res = ctx.req("fa", "POST", "/refresh")
    st = load_state()
    ran = [d for d in st["decisions"] if d["status"] == "executed"]
    pend = [d for d in st["decisions"] if d["status"] == "pending"]
    approvers = {a["approver"] for a in st["audit"] if a["action"] == "execute"}
    ok = (res.data["ok"] and bool(ran) and all(d["risk"] == "low" and not d["blocked"] and not d["requires_approval"] for d in ran)
          and approvers == {"autopilot"} and all(d["requires_approval"] or d["blocked"] for d in pend)
          and any(d["risk"] == "high" for d in pend))
    return ok, f"autopilot executed {len(ran)} low-risk unblocked items; {len(pend)} (all high/medium risk) still wait for a human"


def check_objective(ctx: Ctx):
    ctx.fresh()
    before = {k: v["planned_change_pct"] for k, v in ctx.nodes().items()}
    recs0 = ctx.req("fa", "GET", "/recommendations").data
    res = ctx.req("fa", "POST", "/settings", {"objective": "clear_inventory"})
    after = {k: v["planned_change_pct"] for k, v in ctx.nodes().items()}
    recs1 = ctx.req("fa", "GET", "/recommendations").data
    changed = [k for k in before if before[k] != after[k]]
    ok = (res.data["objective"] == "clear_inventory" and recs1["objective"] == "clear_inventory" and bool(changed)
          and recs1["summary"]["total_expected_profit_delta"] != recs0["summary"]["total_expected_profit_delta"])
    return ok, f"clear_inventory changed planned_change_pct on {len(changed)} neurons and the inbox total ({recs0['summary']['total_expected_profit_delta']:.0f} → {recs1['summary']['total_expected_profit_delta']:.0f})"


def check_simulate(ctx: Ctx):
    ctx.fresh()
    base = ctx.nodes()["CMP-03"]["current_spend"]
    body = {"plan": {"CMP-03": round(base * 1.5, 2)}}
    runs = [ctx.req(s, "POST", "/simulate", body) for s in ("fa", "dev") for _ in range(3)]
    worst = max(r.ms for r in runs)
    warned = all("CMP-03" in (r.data["summary"].get("stock_warnings") or []) for r in runs)
    return worst < 300 and warned and all(r.status == 200 for r in runs), f"+50% on low-stock CMP-03 flags a stock warning; slowest of 6 calls {worst:.0f} ms (<300)"


def check_ask(ctx: Ctx):
    ctx.fresh()
    r = ctx.req("fa", "POST", "/ask", {"question": QUESTION})
    hl = {"type": "neuron", "id": "CMP-01"} in r.data["highlights"]
    return r.status == 200 and hl and len(r.data["answer"]) > 20, f"engine={r.data['engine']}, answer {len(r.data['answer'])} chars, highlights {r.data['highlights']}"


def check_snapshot(ctx: Ctx):
    ctx.fresh()
    r = ctx.req("fa", "GET", "/brain/snapshot")
    s = r.data
    channel_clusters = [c for c in s["clusters"] if c["id"] in config.CHANNELS]
    ok = (len(s["nodes"]) == 26 and len(channel_clusters) == 5 and len(s["sources"]) == 9 and len(s["ghosts"]) >= 1
          and len(s["synapses"]) >= 72 and isinstance(s["headline"]["current_profit"], (int, float))
          and isinstance(s["headline"]["planned_profit"], (int, float)) and r.ms < 500)
    return ok, (f"{len(s['nodes'])} nodes, {len(channel_clusters)} channel clusters ({len(s['clusters'])} total), {len(s['sources'])} sources, "
                f"{len(s['ghosts'])} ghosts, {len(s['synapses'])} synapses, headline ok, first call {r.ms:.0f} ms (<500)")


def check_brain_state(ctx: Ctx):
    ctx.fresh()
    real_now = ctx.service._now
    from datetime import timedelta

    ctx.service._now = lambda: real_now() + timedelta(hours=1)
    try:
        idle = ctx.req("fa", "GET", "/brain/state").data
    finally:
        ctx.service._now = real_now
    rep = ctx.req("fa", "POST", "/brain/replay").data
    st = ctx.req("fa", "GET", "/brain/state").data
    ok = idle["mode"] == "idle" and st["mode"] != "idle" and st["last_event_id"] == rep["last_id"]
    return ok, f"no recent events → '{idle['mode']}'; after replay → '{st['mode']}' (region {st['active_region']}, last {st['last_event_id']})"


def check_replay(ctx: Ctx):
    ctx.fresh()
    ev0 = ctx.last_event_id()
    snap = lambda: (ctx.req("fa", "GET", "/recommendations").data["pending"], ctx.req("fa", "GET", "/audit").data)  # noqa: E731
    before = snap()
    rep = ctx.req("fa", "POST", "/brain/replay").data
    events = ctx.req("fa", "GET", f"/brain/events?since={ev0}&limit=1000").data["events"]
    ok = (rep["ok"] and len(events) == rep["events_queued"] > 0 and all(e["payload"].get("replay") is True for e in events)
          and snap() == before)
    return ok, f"{len(events)} replay events, every payload has replay:true, pending decisions and audit unchanged"


def check_events_since(ctx: Ctx):
    ctx.fresh()
    allev = ctx.req("fa", "GET", "/brain/events?limit=1000").data
    ids = [e["id"] for e in allev["events"]]
    mid = ids[len(ids) // 2]
    after = ctx.req("fa", "GET", f"/brain/events?since={mid}&limit=1000").data
    page = ctx.req("fa", "GET", f"/brain/events?since={ids[0]}&limit=3").data
    tail = ctx.req("fa", "GET", "/brain/events?limit=5").data
    empty = ctx.req("fa", "GET", f"/brain/events?since={ids[-1]}").data
    ok = (ids == sorted(ids) and len(set(ids)) == len(ids) and [e["id"] for e in after["events"]] == ids[len(ids) // 2 + 1:]
          and [e["id"] for e in page["events"]] == ids[1:4] and [e["id"] for e in tail["events"]] == ids[-5:]
          and empty["events"] == [] and empty["last_id"] == ids[-1] and allev["last_id"] == ids[-1])
    return ok, f"{len(ids)} events strictly ascending; since / limit paging and the empty tail behave"


def check_demo_reset(ctx: Ctx):
    ctx.fresh()
    d = _spend_decision(ctx)
    ctx.req("fa", "POST", f"/decisions/{d['id']}/approve")
    res = ctx.req("fa", "POST", "/demo/reset")
    summary = ctx.req("fa", "GET", "/recommendations").data["summary"]
    audit = ctx.req("fa", "GET", "/audit").data
    seeded = ctx.req("fa", "GET", "/learning").data["outcomes"]
    ctx.req("fa", "POST", f"/decisions/{ctx.pending()[0]['id']}/approve")
    audit_before = len(ctx.req("fa", "GET", "/audit").data)
    ctx.service.DEMO_MODE = False
    try:
        off = ctx.req("fa", "POST", "/demo/reset")
    finally:
        ctx.service.DEMO_MODE = config.DEMO_MODE
    ok = (res.data["ok"] and summary["executed"] == 0 and audit == [] and len(seeded) > 0 and off.status == 200 and off.data["ok"] is False
          and len(ctx.req("fa", "GET", "/audit").data) == audit_before)
    return ok, f"reset wiped the executed decision and audit, kept {len(seeded)} seeded outcomes; with DEMO_MODE off → ok:false and nothing wiped"


def check_resilience(ctx: Ctx):
    ctx.fresh()
    saved = ctx.service.run_detection
    ctx.service.run_detection = lambda **kw: (_ for _ in ()).throw(RuntimeError("boom"))
    try:
        results = [ctx.req(s, "POST", "/refresh") for s in ("fa", "dev")]
    finally:
        ctx.service.run_detection = saved
    health = [ctx.req(s, "GET", "/health") for s in ("fa", "dev")]
    ok = all(r.status == 200 and r.data["ok"] is False and r.data["steps"]["detect"]["ok"] is False
             and all(r.data["steps"][k]["ok"] for k in ("ingest", "diagnose", "optimize", "decide", "learn")) for r in results)
    ok = ok and all(h.status == 200 and h.data["ok"] for h in health)
    return ok, "one step raised → ok:false with the others still run on both servers; /health still fine"


def check_concurrency(ctx: Ctx):
    ctx.fresh()
    ids = [d["id"] for d in ctx.pending()][:4]
    out: list[tuple[str, R]] = []
    lock = threading.Lock()

    def hit(kind: str, method: str, path: str) -> None:
        r = ctx.req("dev", method, path)
        with lock:
            out.append((kind, r))

    jobs = [("refresh", "POST", "/refresh")] * 2 + [("approve", "POST", f"/decisions/{i}/approve") for i in ids] + [("snap", "GET", "/brain/snapshot")] * 3
    threads = [threading.Thread(target=hit, args=j) for j in jobs]
    [t.start() for t in threads]
    [t.join(120) for t in threads]
    state_ok = True
    try:
        json.loads(Path(config.STATE_PATH).read_text())
    except ValueError:
        state_ok = False
    approved = sum(1 for k, r in out if k == "approve" and r.data and r.data.get("ok"))
    executed = ctx.req("fa", "GET", "/recommendations").data["summary"]["executed"]
    ok = (len(out) == len(jobs) and all(r.status < 500 and not r.bad_json for _, r in out) and state_ok
          and all(r.data["ok"] for k, r in out if k == "refresh") and executed == approved)
    return ok, f"{len(jobs)} simultaneous requests (2 refreshes, {len(ids)} approvals, 3 snapshots): no 5xx, state.json valid JSON, {approved} approved = {executed} executed"


def check_no_leaks(ctx: Ctx):
    saved = ctx.service.kpis
    ctx.service.kpis = lambda period=7: (_ for _ in ()).throw(RuntimeError(f"secret detail {SENTINEL_KEY}"))
    try:
        errs = [ctx.req(s, "GET", "/kpis") for s in ("fa", "dev")]
    finally:
        ctx.service.kpis = saved
    settings = ctx.req("fa", "GET", "/settings").data
    blob = "\n".join(ctx.texts)
    ok = (all(e.status == 500 and e.data == {"detail": "Internal server error"} for e in errs)
          and settings["agent"]["claude_available"] is True and SENTINEL_KEY not in blob and "sk-ant" not in blob
          and "Traceback" not in blob and 'File "' not in blob)
    return ok, f"{len(ctx.texts)} response bodies scanned: no API key, no traceback; a forced 500 returns only 'Internal server error'"


CHECKS = [
    ("01 routes 2xx + valid JSON", check_routes), ("02 GET parity (both servers)", check_parity), ("03 /docs + openapi", check_docs),
    ("04 error statuses", check_errors), ("05 approve flow", check_approve), ("06 approve again", check_approve_again),
    ("07 rollback restores", check_rollback), ("08 blocked decision", check_blocked), ("09 autonomous refresh", check_autonomous),
    ("10 objective switch", check_objective), ("11 simulate speed + stock", check_simulate), ("12 ask highlights", check_ask),
    ("13 brain snapshot", check_snapshot), ("14 brain state idle/replay", check_brain_state), ("15 replay is safe", check_replay),
    ("16 events since", check_events_since), ("17 demo reset", check_demo_reset), ("18 loop resilience", check_resilience),
    ("19 concurrency", check_concurrency), ("20 no secrets / tracebacks", check_no_leaks),
]


def run_checks(ctx: Ctx) -> list[tuple[str, bool, str]]:
    results = []
    for name, fn in CHECKS:
        try:
            ok, detail = fn(ctx)
        except Exception as exc:  # a crashing check is a failing check
            ok, detail = False, f"error: {type(exc).__name__}: {exc}"
        results.append((name, bool(ok), detail))
    return results


def latency_table(ctx: Ctx) -> None:
    w = max(len(k) for k in ctx.lat)
    print(f"\n{'route'.ljust(w)}  FastAPI cold  FastAPI warm  devserver")
    print("-" * (w + 40))
    for label, v in ctx.lat.items():
        print(f"{label.ljust(w)}  {v.get('fa_cold', 0):>9.1f} ms  {v.get('fa_warm', 0):>9.1f} ms  {v.get('dev_warm', 0):>7.1f} ms")


def main() -> int:
    logging.disable(logging.CRITICAL)  # the checks force failures on purpose; keep their expected log lines off the console
    ctx = Ctx()
    try:
        results = run_checks(ctx)
        width = max(len(n) for n, _, _ in results)
        print(f"{'check'.ljust(width)}  result  detail")
        print("-" * (width + 100))
        for name, ok, detail in results:
            print(f"{name.ljust(width)}  {'PASS' if ok else 'FAIL'}    {detail}")
        failed = sum(not ok for _, ok, _ in results)
        latency_table(ctx)
        after = ctx.real_state.read_bytes() if ctx.real_state.exists() else None
        untouched = after == ctx.real_state_bytes
        print("-" * (width + 100))
        print(f"M9 validation: {len(results) - failed}/{len(results)} PASS" + (f", {failed} FAIL" if failed else "")
              + ("  (real data/state.json untouched)" if untouched else "  (WARNING: real state.json CHANGED)"))
        return 1 if (failed or not untouched) else 0
    finally:
        ctx.close()


if __name__ == "__main__":
    sys.exit(main())
