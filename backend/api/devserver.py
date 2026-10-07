"""DataQuest 3.0 — zero-dependency fallback server (Module 9).

Standard library only. Same routes, same service functions, same JSON and status codes as `backend.api.main`, so the
demo cannot fail on an installation problem.   Run:  python -m backend.api.devserver [--port 8000]
No business logic here: each route maps to one `backend.api.service` call.
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from backend.api import service
from backend.core import config

VERSION = "3.0.0"
_log = logging.getLogger("engine.devserver")


class HttpError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status, self.detail = status, detail


# --------------------------------------------------------------------------- parameter helpers (mirror the Pydantic models)
def _int(q: dict, name: str, default: int) -> int:
    try:
        return int(q[name]) if name in q else default
    except ValueError:
        raise HttpError(422, f"{name} must be an integer")


def _opt(q: dict, name: str) -> str | None:
    return q.get(name)


def _str(body: dict, name: str, required: bool = False) -> str | None:
    v = body.get(name)
    if v is None:
        if required:
            raise HttpError(422, f"{name} is required")
        return None
    if not isinstance(v, str):
        raise HttpError(422, f"{name} must be a string")
    return v


def _num_map(body: dict, name: str) -> dict[str, float]:
    v = body.get(name)
    if not isinstance(v, dict) or any(isinstance(x, bool) or not isinstance(x, (int, float)) for x in v.values()):
        raise HttpError(422, f"{name} must be an object of numbers")
    return {k: float(x) for k, x in v.items()}


def _total_budget(body: dict) -> float | None:
    v = body.get("total_budget")
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise HttpError(422, "total_budget must be a number")
    return float(v)


# --------------------------------------------------------------------------- route tables: (regex, handler(match, query, body))
GET: list[tuple[re.Pattern, Callable[..., Any]]] = []
POST: list[tuple[re.Pattern, Callable[..., Any]]] = []


def _route(table: list, pattern: str):
    def deco(fn):
        table.append((re.compile(f"^{pattern}$"), fn))
        return fn
    return deco


def get(pattern): return _route(GET, pattern)
def post(pattern): return _route(POST, pattern)


@get("/health")
def _health(m, q, b): return {"ok": True, "version": VERSION}
@get("/kpis")
def _kpis(m, q, b): return service.kpis(_int(q, "period", 7))
@get("/trend")
def _trend(m, q, b): return service.trend(_int(q, "days", 45))
@get("/channels")
def _channels(m, q, b): return service.channels()
@get("/campaigns")
def _campaigns(m, q, b): return service.campaigns()
@get("/sources")
def _sources(m, q, b): return service.sources()
@get("/data-quality")
def _data_quality(m, q, b): return service.data_quality()
@get("/anomalies")
def _anomalies(m, q, b): return service.anomalies()
@get("/anomalies/(?P<id>[^/]+)/diagnosis")
def _diagnosis(m, q, b): return service.diagnosis(m["id"])
@get("/causal/(?P<id>[^/]+)")
def _causal(m, q, b): return service.causal(m["id"])
@get("/reconciliation")
def _reconciliation(m, q, b): return service.reconciliation()
@get("/recommendations")
def _recommendations(m, q, b): return service.recommendations(_opt(q, "objective"))
@post("/decisions/(?P<id>[^/]+)/approve")
def _approve(m, q, b): return service.approve(m["id"])
@post("/decisions/(?P<id>[^/]+)/reject")
def _reject(m, q, b): return service.reject(m["id"])
@post("/decisions/(?P<id>[^/]+)/rollback")
def _rollback(m, q, b): return service.rollback(m["id"])
@get("/audit")
def _audit(m, q, b): return service.audit()
@post("/optimize")
def _optimize(m, q, b): return service.optimize_plan(_str(b, "objective") or "max_profit", _total_budget(b))
@post("/simulate")
def _simulate(m, q, b): return service.simulate(_num_map(b, "plan"))
@post("/simulate/channels")
def _simulate_channels(m, q, b): return service.channel_simulate(_num_map(b, "multipliers"))
@get("/curves")
def _curves(m, q, b): return service.curves()
@get("/opportunities")
def _opportunities(m, q, b): return service.opportunities()
@get("/learning")
def _learning(m, q, b): return service.learning()
@get("/brain/manifest")
def _brain_manifest(m, q, b): return service.brain_manifest()
@get("/brain/nodes")
def _brain_nodes(m, q, b): return service.brain_nodes()
@get("/brain/snapshot")
def _brain_snapshot(m, q, b): return service.brain_snapshot()
@get("/brain/events")
def _brain_events(m, q, b): return service.brain_events(_opt(q, "since"), _int(q, "limit", 100))
@get("/brain/state")
def _brain_state(m, q, b): return service.brain_state()
@post("/brain/replay")
def _brain_replay(m, q, b): return service.brain_replay()
@get("/settings")
def _get_settings(m, q, b): return service.get_settings()
@post("/settings")
def _update_settings(m, q, b): return service.update_settings(_str(b, "autonomy"), _str(b, "objective"))
@get("/meta/config")
def _meta_config(m, q, b): return service.meta_config()
@post("/ask")
def _ask(m, q, b): return service.ask(_str(b, "question", required=True))
@get("/loop/last")
def _loop_last(m, q, b): return service.last_refresh()
@post("/refresh")
def _refresh(m, q, b): return service.refresh()
@post("/demo/reset")
def _demo_reset(m, q, b): return service.demo_reset()


# --------------------------------------------------------------------------- HTTP handler
class Server(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 128  # the default backlog of 5 resets connections when a page fires many requests at once


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "DataQuestDev/3.0"

    def log_message(self, fmt, *args):  # quiet: no per-request stderr noise
        _log.debug("%s - %s", self.address_string(), fmt % args)

    def _send(self, status: int, payload: Any) -> None:
        data = json.dumps(payload, allow_nan=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()
        self.wfile.write(data)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        if not raw.strip():
            return {}
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            raise HttpError(422, "Request body is not valid JSON")
        if not isinstance(body, dict):
            raise HttpError(422, "Request body must be a JSON object")
        return body

    def _dispatch(self, table: list) -> None:
        url = urlparse(self.path)
        try:
            body = self._body() if table is POST else {}
            query = {k: v[0] for k, v in parse_qs(url.query).items()}
            for pattern, fn in table:
                match = pattern.match(url.path)
                if match:
                    return self._send(200, fn(match, query, body))
            other = POST if table is GET else GET
            if any(p.match(url.path) for p, _ in other):
                raise HttpError(405, "Method Not Allowed")
            raise HttpError(404, "Not Found")
        except HttpError as exc:
            self._send(exc.status, {"detail": exc.detail})
        except KeyError as exc:
            self._send(404, {"detail": str(exc.args[0]) if exc.args else "Not found"})
        except ValueError as exc:
            self._send(400, {"detail": str(exc)})
        except Exception:  # noqa: BLE001
            _log.exception("unhandled error on %s", self.path)
            self._send(500, {"detail": "Internal server error"})

    def do_GET(self): self._dispatch(GET)
    def do_POST(self): self._dispatch(POST)

    def do_OPTIONS(self):  # CORS preflight
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Content-Length", "0")
        self.end_headers()


# --------------------------------------------------------------------------- background loop + entry point
def _refresh_thread(stop: threading.Event) -> None:
    """Daemon thread: every REFRESH_MINUTES run the closed loop; errors swallowed; no refresh at startup."""
    while True:
        delay = max(config.REFRESH_MINUTES * 60, 0.01)
        service.schedule_next_refresh(delay)
        if stop.wait(delay):
            return
        try:
            service.refresh()
        except Exception:  # noqa: BLE001
            _log.exception("scheduled refresh failed")


def make_server(port: int = 0, host: str = "127.0.0.1", loop: bool = True) -> tuple[ThreadingHTTPServer, threading.Event]:
    server = Server((host, port), Handler)
    stop = threading.Event()
    if loop:
        threading.Thread(target=_refresh_thread, args=(stop,), daemon=True, name="refresh-loop").start()
    return server, stop


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Zero-dependency DataQuest 3.0 API server")
    ap.add_argument("--port", type=int, default=config.API_PORT)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args(argv)
    server, stop = make_server(args.port, args.host)
    print(f"DataQuest devserver on http://{args.host}:{server.server_address[1]}  (refresh every {config.REFRESH_MINUTES} min) — Ctrl+C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        server.server_close()


if __name__ == "__main__":
    main()
