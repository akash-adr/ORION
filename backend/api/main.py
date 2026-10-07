"""DataQuest 3.0 — FastAPI app (Module 9).

A thin HTTP layer: every route is one line that calls `backend.api.service`. No business logic lives here.
Run:  uvicorn backend.api.main:app --port 8000
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any, Callable

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from backend.api import service
from backend.core import config

VERSION = "3.0.0"
_log = logging.getLogger("engine.api")


# --------------------------------------------------------------------------- request bodies
class AskBody(BaseModel):
    question: str


class PlanBody(BaseModel):
    plan: dict[str, float]


class ChannelBody(BaseModel):
    multipliers: dict[str, float]


class OptimizeBody(BaseModel):
    objective: str = "max_profit"
    total_budget: float | None = None


class SettingsBody(BaseModel):
    autonomy: str | None = None
    objective: str | None = None


# --------------------------------------------------------------------------- error mapping
def guard(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Call a service function; KeyError → 404, ValueError → 400, anything else → logged 500 with no internals leaked."""
    try:
        return fn(*args, **kwargs)
    except KeyError as exc:
        msg = exc.args[0] if exc.args else "Not found"
        return JSONResponse({"detail": str(msg)}, status_code=404)
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    except Exception:  # noqa: BLE001
        _log.exception("unhandled error in %s", getattr(fn, "__name__", fn))
        return JSONResponse({"detail": "Internal server error"}, status_code=500)


# --------------------------------------------------------------------------- background loop
async def _refresh_loop() -> None:
    """Every REFRESH_MINUTES run the closed loop in a worker thread. Errors are swallowed; no refresh at startup."""
    while True:
        delay = max(config.REFRESH_MINUTES * 60, 0.01)
        service.schedule_next_refresh(delay)
        await asyncio.sleep(delay)
        try:
            await asyncio.to_thread(service.refresh)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            _log.exception("scheduled refresh failed")


@asynccontextmanager
async def lifespan(_: FastAPI):
    task = asyncio.create_task(_refresh_loop())
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        service.schedule_next_refresh(None)


app = FastAPI(title="DataQuest 3.0 Engine API", version=VERSION, lifespan=lifespan,
              description="Autonomous D2C advertising decision engine: ingest, detect, diagnose, decide, act, learn.")
# Demo: open CORS so the Next.js dev server can call us. In production, restrict allow_origins to the real frontend origin(s).
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# --------------------------------------------------------------------------- Health
@app.get("/health", tags=["Health"])
def health(): return {"ok": True, "version": VERSION}


# --------------------------------------------------------------------------- KPIs & Data
@app.get("/kpis", tags=["KPIs & Data"])
def kpis(period: int = 7): return guard(service.kpis, period)
@app.get("/trend", tags=["KPIs & Data"])
def trend(days: int = 45): return guard(service.trend, days)
@app.get("/channels", tags=["KPIs & Data"])
def channels(): return guard(service.channels)
@app.get("/campaigns", tags=["KPIs & Data"])
def campaigns(): return guard(service.campaigns)
@app.get("/sources", tags=["KPIs & Data"])
def sources(): return guard(service.sources)
@app.get("/data-quality", tags=["KPIs & Data"])
def data_quality(): return guard(service.data_quality)


# --------------------------------------------------------------------------- Detection & Diagnosis
@app.get("/anomalies", tags=["Detection & Diagnosis"])
def anomalies(): return guard(service.anomalies)
@app.get("/anomalies/{anomaly_id}/diagnosis", tags=["Detection & Diagnosis"])
def diagnosis(anomaly_id: str): return guard(service.diagnosis, anomaly_id)
@app.get("/causal/{event_id}", tags=["Detection & Diagnosis"])
def causal(event_id: str): return guard(service.causal, event_id)
@app.get("/reconciliation", tags=["Detection & Diagnosis"])
def reconciliation(): return guard(service.reconciliation)


# --------------------------------------------------------------------------- Decisions
@app.get("/recommendations", tags=["Decisions"])
def recommendations(objective: str | None = None): return guard(service.recommendations, objective)
@app.post("/decisions/{rec_id}/approve", tags=["Decisions"])
def approve(rec_id: str): return guard(service.approve, rec_id)
@app.post("/decisions/{rec_id}/reject", tags=["Decisions"])
def reject(rec_id: str): return guard(service.reject, rec_id)
@app.post("/decisions/{rec_id}/rollback", tags=["Decisions"])
def rollback(rec_id: str): return guard(service.rollback, rec_id)
@app.get("/audit", tags=["Decisions"])
def audit(): return guard(service.audit)


# --------------------------------------------------------------------------- Optimizer
@app.post("/optimize", tags=["Optimizer"])
def optimize(body: OptimizeBody = OptimizeBody()): return guard(service.optimize_plan, body.objective, body.total_budget)
@app.post("/simulate", tags=["Optimizer"])
def simulate(body: PlanBody): return guard(service.simulate, body.plan)
@app.post("/simulate/channels", tags=["Optimizer"])
def simulate_channels(body: ChannelBody): return guard(service.channel_simulate, body.multipliers)
@app.get("/curves", tags=["Optimizer"])
def curves(): return guard(service.curves)
@app.get("/opportunities", tags=["Optimizer"])
def opportunities(): return guard(service.opportunities)


# --------------------------------------------------------------------------- Learning
@app.get("/learning", tags=["Learning"])
def learning(): return guard(service.learning)


# --------------------------------------------------------------------------- Brain
@app.get("/brain/manifest", tags=["Brain"])
def brain_manifest(): return guard(service.brain_manifest)
@app.get("/brain/nodes", tags=["Brain"])
def brain_nodes(): return guard(service.brain_nodes)
@app.get("/brain/snapshot", tags=["Brain"])
def brain_snapshot(): return guard(service.brain_snapshot)
@app.get("/brain/events", tags=["Brain"])
def brain_events(since: str | None = None, limit: int = 100): return guard(service.brain_events, since, limit)
@app.get("/brain/state", tags=["Brain"])
def brain_state(): return guard(service.brain_state)
@app.post("/brain/replay", tags=["Brain"])
def brain_replay(): return guard(service.brain_replay)


# --------------------------------------------------------------------------- Settings / Agent / Loop
@app.get("/settings", tags=["Settings"])
def get_settings(): return guard(service.get_settings)
@app.post("/settings", tags=["Settings"])
def update_settings(body: SettingsBody): return guard(service.update_settings, body.autonomy, body.objective)
@app.post("/ask", tags=["Agent"])
def ask(body: AskBody): return guard(service.ask, body.question)
@app.post("/refresh", tags=["Loop"])
def refresh(): return guard(service.refresh)
@app.post("/demo/reset", tags=["Loop"])
def demo_reset(): return guard(service.demo_reset)
