"""Module 9: the HTTP layer. FastAPI (TestClient) and the zero-dependency devserver run on a temporary pipeline;
the checks are the shared ones from backend.api.validate."""
import time

import pytest
from fastapi.testclient import TestClient

from backend.api import service, validate as v
from backend.api.main import app
from backend.core import config


@pytest.fixture(scope="module")
def ctx():
    c = v.Ctx()
    yield c
    c.close()


def _ok(result):
    ok, detail = result
    assert ok, detail


@pytest.mark.parametrize("name,fn", [(n, f) for n, f in v.CHECKS if n[:2] not in ("02", "18", "19")], ids=lambda x: x if isinstance(x, str) else "")
def test_validation_check(ctx, name, fn):
    _ok(fn(ctx))


def test_devserver_parity_subset(ctx):
    ctx.fresh()
    for p in ("/kpis", "/channels", "/anomalies", "/brain/snapshot", "/brain/nodes", "/recommendations", "/settings"):
        ctx.req("fa", "GET", p)
        a, b = ctx.req("fa", "GET", p), ctx.req("dev", "GET", p)
        assert a.status == b.status == 200
        assert v.first_diff(v.strip(a.data), v.strip(b.data)) is None, p


def test_cors_preflight_on_both(ctx):
    r = ctx.fa.options("/simulate", headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "POST"})
    assert r.status_code == 200 and r.headers["access-control-allow-origin"] in ("*", "http://localhost:3000")
    import http.client

    conn = http.client.HTTPConnection("127.0.0.1", ctx.port, timeout=10)
    conn.request("OPTIONS", "/simulate", headers={"Origin": "http://localhost:3000"})
    resp = conn.getresponse()
    resp.read()
    assert resp.status == 204 and resp.getheader("Access-Control-Allow-Origin") == "*"
    assert ctx.fa.get("/health", headers={"Origin": "http://x"}).headers["access-control-allow-origin"] == "*"


def test_lifespan_loop_runs_refresh_and_cancels(ctx, monkeypatch):
    calls = []
    monkeypatch.setattr(service, "refresh", lambda *a, **k: calls.append(1) or {"ok": True})
    monkeypatch.setattr(config, "REFRESH_MINUTES", 0.0002)  # ~12 ms
    with TestClient(app) as client:
        assert client.get("/health").json()["ok"]
        time.sleep(0.4)
        assert client.get("/settings").json()["next_refresh_at"] is not None
    assert len(calls) >= 1
    n = len(calls)
    time.sleep(0.2)
    assert len(calls) == n  # the task was cancelled on shutdown
    assert service.get_settings()["next_refresh_at"] is None


def test_no_refresh_at_startup(ctx, monkeypatch):
    calls = []
    monkeypatch.setattr(service, "refresh", lambda *a, **k: calls.append(1) or {"ok": True})
    monkeypatch.setattr(config, "REFRESH_MINUTES", 5)
    with TestClient(app) as client:
        client.get("/health")
        time.sleep(0.2)
    assert calls == []


def test_loop_swallows_refresh_errors(ctx, monkeypatch):
    calls = []

    def boom(*a, **k):
        calls.append(1)
        raise RuntimeError("scheduled failure")

    monkeypatch.setattr(service, "refresh", boom)
    monkeypatch.setattr(config, "REFRESH_MINUTES", 0.0002)
    with TestClient(app) as client:
        time.sleep(0.4)
        assert client.get("/health").json()["ok"]
    assert len(calls) >= 2  # kept going after the first failure
