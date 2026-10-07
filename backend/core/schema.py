"""M0 schema: the data shapes passed between modules.

Field NAMES and ORDER are the contract. Add new fields at the end with defaults; never rename.
"""
from __future__ import annotations

import dataclasses
import datetime as _dt
import hashlib
import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from backend.core import config

TS_FORMAT = "%Y-%m-%dT%H:%M:%S"  # timestamp format used everywhere


# ---------------------------------------------------------------------------
# 4.1 Anomaly (M3 → M4, M6, M8, M10)
# ---------------------------------------------------------------------------
@dataclass
class Anomaly:
    id: str  # AN-001
    kind: str  # one of ANOMALY_KINDS
    entity_type: str  # one of ENTITY_TYPES
    entity_id: str  # CMP-01 / SKU-A / channel name
    label: str  # human-readable title
    metric: str  # metric that moved, e.g. "cpc"
    baseline: float  # baseline value of the metric
    recent: float  # recent value of the metric
    change_pct: float  # recent / baseline - 1 (fraction)
    z: float  # z-score of recent vs baseline
    profit_impact: float  # ₹/day, negative = loss
    severity: str  # one of SEVERITIES
    detail: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 4.2 Factor and RootCause (M4 → M6, M8, M10)
# ---------------------------------------------------------------------------
@dataclass
class Factor:
    name: str  # driver name, e.g. "cpc", "cvr", "price"
    impact: float  # ₹/day contribution to the total change
    pct: float  # share of the total change (fraction)


@dataclass
class RootCause:
    anomaly_id: str
    entity_id: str
    total_change: float  # ₹/day change being explained
    factors: list[Factor] = field(default_factory=list)
    funnel: list[dict] = field(default_factory=list)
    narrative: str = ""

    def check_sum(self, tol: float = 1.0) -> bool:
        """True if the factor impacts add up to total_change within tol (₹/day)."""
        total = sum(float(f.impact if isinstance(f, Factor) else f["impact"]) for f in self.factors)
        return abs(total - float(self.total_change)) <= tol


# ---------------------------------------------------------------------------
# 4.3 CausalResult (M4b → M6, M10)
# ---------------------------------------------------------------------------
@dataclass
class CausalResult:
    event_id: str  # EV-n
    description: str
    effect_per_day: float  # ₹/day
    total_effect: float  # ₹ total over the post-event window
    ci_low: float  # ₹/day lower bound
    ci_high: float  # ₹/day upper bound
    series: list[dict] = field(default_factory=list)  # each {date, actual, counterfactual}


# ---------------------------------------------------------------------------
# 4.4 Recommendation (M6 → M7, M8, M9, M10)
# ---------------------------------------------------------------------------
@dataclass
class Recommendation:
    id: str  # REC-xxxxxx
    title: str
    issue: str
    cause: str
    action: dict  # {"type": ACTION_TYPES, "changes": [{campaign_id, name, channel, from_budget, to_budget}] | settings dicts}
    expected_profit_delta: float  # ₹/day
    confidence: float  # fraction, CONFIDENCE_MIN..CONFIDENCE_MAX
    risk: str  # one of RISK_LEVELS
    requires_approval: bool
    blocked: bool  # True when a guardrail blocks it
    priority: float
    evidence: list[str] = field(default_factory=list)
    anomaly_id: str | None = None
    status: str = "pending"  # one of DECISION_STATUSES

    @staticmethod
    def make_recommendation_id(title: str) -> str:
        """"REC-" + first 6 hex chars of md5(title). Stable across runs."""
        return "REC-" + hashlib.md5(title.encode()).hexdigest()[:6]


# ---------------------------------------------------------------------------
# 4.5 Opportunity (M5b → M6, M10)
# ---------------------------------------------------------------------------
@dataclass
class Opportunity:
    sku_id: str
    channel: str
    audience: str
    predicted_conv_per_1k: float  # orders per ₹1,000 spend
    predicted_poas: float
    unit_margin: float  # ₹ per unit
    stock_days: float  # days of cover
    score: float
    test_budget: float  # ₹/day


# ---------------------------------------------------------------------------
# 4.6 NeuronNode (M9 → M10 brain)
# ---------------------------------------------------------------------------
@dataclass
class NeuronNode:
    entity_id: str  # CMP-01 or SKU-A
    entity_type: str  # "campaign" or "sku"
    label: str
    cluster: str  # channel for campaigns, "catalog" for SKUs
    channel: str | None
    sku_id: str | None
    spend_7d: float  # ₹ total over 7 days
    poas_7d: float | None
    profit_7d: float  # ₹ total over 7 days
    change_pct: float | None  # fraction
    health: str  # metrics.neuron_health(poas_7d)
    size: float  # metrics.neuron_size(spend_7d, ...)
    is_alerting: bool = False  # True when an open anomaly references this entity
    anomaly_id: str | None = None


# ---------------------------------------------------------------------------
# 4.7 BrainEvent (every engine module → state.json → M9 → M10 brain)
# ---------------------------------------------------------------------------
@dataclass
class BrainEvent:
    id: str  # BE-00001 ("" until db.log_brain_event assigns it)
    ts: str  # YYYY-MM-DDTHH:MM:SS
    type: str  # one of BRAIN_EVENT_TYPES
    region: str  # EVENT_REGION[type]
    path: list[str]  # PULSE_PATHS[type]
    entity_id: str | None
    ref_id: str | None  # AN-001, REC-567405, decision id, outcome id
    severity: str  # one of SEVERITIES
    message: str  # short human-readable line
    payload: dict = field(default_factory=dict)


def make_brain_event(
    type: str,
    entity_id: str | None = None,
    ref_id: str | None = None,
    severity: str = "low",
    message: str = "",
    payload: dict | None = None,
    event_id: str | None = None,
    ts: str | None = None,
) -> BrainEvent:
    """Build a BrainEvent with region, path and ts filled from config. Raises ValueError on unknown type."""
    if type not in config.BRAIN_EVENT_TYPES:
        raise ValueError(f"Unknown brain event type {type!r}; expected one of {config.BRAIN_EVENT_TYPES}")
    if severity not in config.SEVERITIES:
        raise ValueError(f"Unknown severity {severity!r}; expected one of {config.SEVERITIES}")
    return BrainEvent(
        id=event_id or "",
        ts=ts or _dt.datetime.now().strftime(TS_FORMAT),
        type=type,
        region=config.EVENT_REGION[type],
        path=list(config.PULSE_PATHS[type]),
        entity_id=entity_id,
        ref_id=ref_id,
        severity=severity,
        message=message,
        payload=dict(payload) if payload else {},
    )


# ---------------------------------------------------------------------------
# 4.8 BrainState (M9 → M10)
# ---------------------------------------------------------------------------
@dataclass
class BrainState:
    mode: str  # one of BRAIN_MODES
    active_region: str | None
    last_event_id: str | None
    counts: dict = field(default_factory=dict)  # e.g. {"anomalies": 3, "pending_decisions": 2, "outcomes": 5}


# ---------------------------------------------------------------------------
# 4.9 to_dict
# ---------------------------------------------------------------------------
def to_dict(obj: Any) -> Any:
    """Convert any (nested) dataclass / list / tuple / dict / numpy / pandas value into JSON-safe Python.

    NaN and ±inf → None; numpy scalars → Python; Timestamp/datetime/date → ISO string;
    DataFrame → list of records; Series/ndarray → list. Unknown objects fall back to str().
    """
    if obj is None or isinstance(obj, (str, bool)):
        return obj
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return to_dict(dataclasses.asdict(obj))
    if isinstance(obj, dict):
        return {str(k) if not isinstance(k, str) else k: to_dict(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set, frozenset)):
        return [to_dict(v) for v in obj]
    if isinstance(obj, pd.DataFrame):
        return to_dict(obj.to_dict(orient="records"))
    if isinstance(obj, (pd.Series, pd.Index)):
        return to_dict(obj.tolist())
    if isinstance(obj, np.ndarray):
        return to_dict(obj.tolist())
    if obj is pd.NaT:
        return None
    if isinstance(obj, np.datetime64):
        return None if np.isnat(obj) else to_dict(pd.Timestamp(obj))
    if isinstance(obj, (pd.Timestamp, _dt.datetime)):
        return obj.strftime(TS_FORMAT)
    if isinstance(obj, _dt.date):
        return obj.isoformat()
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, (float, np.floating)):
        v = float(obj)
        return v if math.isfinite(v) else None
    if isinstance(obj, int):
        return obj
    try:
        if pd.isna(obj):
            return None
    except (TypeError, ValueError):
        pass
    return str(obj)
