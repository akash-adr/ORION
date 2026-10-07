"""M0 storage contract: SQLite tables, raw file names, state.json and the brain event log.

Paths are read from `config` at call time (never copied), so tests can monkeypatch
config.DB_PATH / config.STATE_PATH and every function follows.

Brain event emitters (the ONLY way any module fires a brain pulse is log_brain_event):
  M2  logs "ingest"          after loading data into SQLite
  M3  logs "anomaly"         once per detected anomaly
  M4  logs "diagnosis"       once per root-cause analysis
  M6  logs "recommendation"  once per generated recommendation
  approve / reject / rollback endpoints log "approval" / "rejection" / "rollback"
  auto-apply (autonomous mode) logs "auto_apply"
  outcome measurement logs "outcome"
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path
from typing import Any

import pandas as pd

from backend.core import config
from backend.core.schema import BrainEvent, to_dict

# ---------------------------------------------------------------------------
# 5.2 Table contract (written by M2, read by M3–M9). Extra columns are allowed.
# ---------------------------------------------------------------------------
TABLE_COLUMNS: dict[str, list[str]] = {
    "fact_daily": [  # campaign × day
        "date", "channel", "campaign_id", "sku_id", "audience", "creative_id", "spend", "impressions",
        "clicks", "frequency", "platform_conversions", "platform_revenue", "orders", "price", "cogs",
        "revenue", "gross_margin", "profit", "ctr", "cpc", "cpm", "cvr", "roas_platform", "roas_true",
        "poas", "campaign_name", "format",
    ],
    "sku_daily": [  # product × day
        "date", "sku_id", "orders_paid", "orders_organic", "unit_price", "units", "revenue", "on_hand",
        "inbound", "sessions", "pdp_views", "add_to_cart", "checkout", "purchases", "name", "cogs",
        "margin_pct", "units_7d", "days_cover",
    ],
    "reconciliation": [  # channel
        "channel", "platform_conversions", "store_orders", "platform_revenue", "true_revenue", "spend",
        "inflation_pct", "roas_platform", "roas_true", "trust_score", "last_synced",
    ],
    "feature_store": [  # campaign
        "campaign_id", "channel", "sku_id", "audience", "spend_7d", "spend_28d", "poas_7d", "poas_28d",
        "ctr_7d", "cvr_7d", "cpm_7d", "freq_7d", "profit_7d",
    ],
    "dim_sku": ["sku_id", "name", "category", "price", "cogs", "rating", "organic_per_day", "margin_pct"],
    "dim_campaign": [
        "campaign_id", "channel", "sku_id", "audience", "daily_budget", "sat_mult", "format", "campaign_name",
    ],
    "dim_creative": ["creative_id", "campaign_id", "format", "hook", "ugc", "launch_date"],
    "events": ["event_id", "date", "type", "entity", "description"],
    # --- added for M2 (additive): Neural Brain integration and data quality ---
    "neuron_metrics": [  # one row per brain neuron (26)
        "entity_id", "entity_type", "label", "cluster", "channel", "sku_id", "spend_7d", "spend_prev_7d",
        "poas_7d", "profit_7d", "change_pct", "roas_platform_7d", "roas_true_7d", "trust_score", "days_cover",
        "health", "size",
    ],
    "source_status": [  # one row per brain_manifest source (9)
        "source_id", "label", "kind", "connector", "file", "rows", "min_date", "max_date", "last_synced",
        "status", "trust_score", "inflation_pct", "detail",
    ],
    "data_quality": ["check", "status", "affected_rows", "detail", "action"],  # one row per check
    # --- added for M3 (additive): persisted detection results and Neural Brain alert targets ---
    "anomalies": [  # one row per current anomaly
        "id", "key", "kind", "entity_type", "entity_id", "label", "metric", "baseline", "recent", "change_pct",
        "z", "profit_impact", "severity", "direction", "detail_json", "detected_at",
    ],
    "brain_alerts": [  # one row per brain target currently alerting
        "target_id", "target_type", "anomaly_ids", "top_kind", "top_severity", "direction", "profit_impact",
        "stock_locked", "message",
    ],
}

# Raw files written by M1 into config.RAW_DIR
RAW_FILES: list[str] = [
    "ad_performance.csv",
    "store_orders_by_utm.csv",
    "orders.csv",
    "inventory.csv",
    "pricing.csv",
    "ga_events.csv",
    "sku_master.csv",
    "campaigns.csv",
    "creatives.csv",
    "events.csv",
    "ground_truth.json",
    "brain_manifest.json",
]

_TABLE_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _check_name(name: str) -> str:
    if not isinstance(name, str) or not _TABLE_NAME_RE.match(name):
        raise ValueError(f"Invalid table name {name!r}")
    return name


# ---------------------------------------------------------------------------
# 5.1 SQLite
# ---------------------------------------------------------------------------
def connect() -> sqlite3.Connection:
    """Open a connection to config.DB_PATH, creating its folder if missing. Caller must close it."""
    db_path = Path(config.DB_PATH)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(db_path)


def write_table(df: pd.DataFrame, name: str) -> None:
    """Replace table `name` with df (if_exists="replace", index=False)."""
    _check_name(name)
    with closing(connect()) as conn, conn:
        df.to_sql(name, conn, if_exists="replace", index=False)


def table_exists(name: str) -> bool:
    """True if table `name` exists in the database."""
    with closing(connect()) as conn:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
        ).fetchone()
    return row is not None


def list_tables() -> list[str]:
    """Names of all tables in the database, sorted."""
    with closing(connect()) as conn:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
    return [r[0] for r in rows]


def read_table(name: str) -> pd.DataFrame:
    """Read a whole table. Raises LookupError naming the table if it does not exist."""
    _check_name(name)
    if not table_exists(name):
        raise LookupError(
            f"Table '{name}' does not exist in {config.DB_PATH}. Has M2 (load) been run? "
            f"Existing tables: {list_tables()}"
        )
    with closing(connect()) as conn:
        return pd.read_sql_query(f'SELECT * FROM "{name}"', conn)


def query(sql: str, params: Any = None) -> pd.DataFrame:
    """Run a SQL query (with optional ? / :name params) and return a DataFrame."""
    with closing(connect()) as conn:
        return pd.read_sql_query(sql, conn, params=params)


def drop_table(name: str) -> None:
    """Drop table `name` if it exists."""
    _check_name(name)
    with closing(connect()) as conn, conn:
        conn.execute(f'DROP TABLE IF EXISTS "{name}"')


def validate_table(df: pd.DataFrame, name: str) -> None:
    """Raise ValueError if df lacks any column required by TABLE_COLUMNS[name]. Extra columns are fine."""
    if name not in TABLE_COLUMNS:
        raise ValueError(f"Unknown table '{name}'; known tables: {sorted(TABLE_COLUMNS)}")
    missing = [c for c in TABLE_COLUMNS[name] if c not in df.columns]
    if missing:
        raise ValueError(f"Table '{name}' is missing required columns: {missing}")


# ---------------------------------------------------------------------------
# 5.3 state.json
# ---------------------------------------------------------------------------
def default_state() -> dict:
    """A fresh default state dict (new objects every call, never shared)."""
    return {
        "decisions": [],
        "audit": [],
        "outcomes": [],
        "budget_overrides": {},
        "autonomy": config.DEFAULT_AUTONOMY,
        "objective": config.DEFAULT_OBJECTIVE,
        "calibration": {"factor": 1.0, "mape": None, "win_rate": None, "n": 0},
        "brain_events": [],
        "brain_event_seq": 0,
        "active_anomalies": {},  # stable key → {id, kind, entity_id, severity, first_seen, last_seen, profit_impact}
        "detection_quality": {},  # last evaluation against ground truth
    }


DEFAULT_STATE = default_state  # contract name; call it, never mutate a shared dict


def load_state() -> dict:
    """Load state.json. Missing or corrupt file → default_state(). Missing keys are merged in from defaults."""
    path = Path(config.STATE_PATH)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, UnicodeDecodeError, OSError):
        return default_state()
    if not isinstance(data, dict):
        return default_state()
    defaults = default_state()
    for key, value in defaults.items():
        if key not in data:
            data[key] = value
        elif isinstance(value, dict) and isinstance(data[key], dict):
            for sub_key, sub_value in value.items():
                data[key].setdefault(sub_key, sub_value)
    return data


def save_state(state: dict) -> None:
    """Write state.json atomically: temp file in the same folder, then os.replace."""
    path = Path(config.STATE_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(to_dict(state), indent=2, ensure_ascii=False)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".state-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def reset_state() -> None:
    """Delete state.json (resets the demo)."""
    Path(config.STATE_PATH).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# 5.4 Brain event log
# ---------------------------------------------------------------------------
def _seq(event_id: str) -> int:
    m = re.match(config.ID_PATTERNS["brain_event"], event_id or "")
    if not m:
        raise ValueError(f"Invalid brain event id {event_id!r}; expected BE-00000")
    return int(event_id[3:])


def log_brain_event(event: BrainEvent) -> BrainEvent:
    """Append event to state.json's brain_events (assigning BE-xxxxx if id is empty), trim history, save."""
    state = load_state()
    seq = int(state.get("brain_event_seq", 0)) + 1
    state["brain_event_seq"] = seq
    if not event.id:
        event.id = f"BE-{seq:05d}"
    events = list(state.get("brain_events", []))
    events.append(to_dict(event))
    limit = config.BRAIN_EVENT_HISTORY_LIMIT
    state["brain_events"] = events[-limit:] if limit > 0 else []
    save_state(state)
    return event


def read_brain_events(since_id: str | None = None, limit: int = 100) -> list[dict]:
    """Events after since_id (by sequence), oldest first, at most `limit`. since_id None → latest `limit`."""
    if limit <= 0:
        return []
    events = sorted(load_state().get("brain_events", []), key=lambda e: _seq(e.get("id", "")))
    if since_id is None:
        return events[-limit:]
    since = _seq(since_id)
    return [e for e in events if _seq(e["id"]) > since][:limit]


def clear_brain_events() -> None:
    """Empty brain_events and reset brain_event_seq to 0."""
    state = load_state()
    state["brain_events"] = []
    state["brain_event_seq"] = 0
    save_state(state)
