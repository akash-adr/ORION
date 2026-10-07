"""M3 persistence and Neural Brain mapping.

- stable keys: f"{kind}:{entity_id}" (AN-NNN ids change between runs; the key does not)
- `anomalies` table: one row per current anomaly
- `brain_alerts` table: one row per brain target (neuron / cluster / source) currently alerting
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from backend.core import config
from backend.core.db import TABLE_COLUMNS, validate_table, write_table
from backend.core.schema import Anomaly, to_dict

SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2}  # higher = worse


def anomaly_key(a: Anomaly) -> str:
    """Stable identity of an anomaly across runs."""
    return f"{a.kind}:{a.entity_id}"


def load_manifest() -> dict:
    """Read data/raw/brain_manifest.json (RAW_DIR resolved at call time)."""
    path = Path(config.RAW_DIR) / "brain_manifest.json"
    if not path.exists():
        raise FileNotFoundError(f"missing {path}. Run `python -m backend.generator.generate` first.")
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# anomalies table
# ---------------------------------------------------------------------------
def anomalies_frame(anomalies: list[Anomaly], detected_at: str) -> pd.DataFrame:
    """The `anomalies` table rows (detail serialised to JSON, direction lifted out of detail)."""
    rows = [{
        "id": a.id, "key": anomaly_key(a), "kind": a.kind, "entity_type": a.entity_type, "entity_id": a.entity_id,
        "label": a.label, "metric": a.metric, "baseline": a.baseline, "recent": a.recent,
        "change_pct": a.change_pct, "z": a.z, "profit_impact": a.profit_impact, "severity": a.severity,
        "direction": a.detail["direction"], "detail_json": json.dumps(to_dict(a.detail)), "detected_at": detected_at,
    } for a in anomalies]
    return pd.DataFrame(rows, columns=TABLE_COLUMNS["anomalies"])


def write_anomalies(anomalies: list[Anomaly], detected_at: str) -> pd.DataFrame:
    """Replace the `anomalies` table with the current detection results."""
    df = anomalies_frame(anomalies, detected_at)
    validate_table(df, "anomalies")
    write_table(df, "anomalies")
    return df


# ---------------------------------------------------------------------------
# brain targets
# ---------------------------------------------------------------------------
def _source_for_channel(manifest: dict, channel: str) -> str:
    for src in manifest["sources"]:
        if src["kind"] == "ad_platform" and src["channel"] == channel:
            return src["id"]
    raise ValueError(f"no manifest source for channel {channel!r}")


def targets_for(a: Anomaly, manifest: dict) -> list[dict]:
    """Brain targets one anomaly lights up.

    Each target: {target_id, target_type, stock_locked, propagated}. `propagated` marks the stock-lock
    copies on promoting campaigns (they carry the lock but no ₹ impact, so impact is never triple-counted).
    """
    if a.kind == "cpc_spike":  # the whole channel cluster glows
        return [{"target_id": a.entity_id, "target_type": "cluster", "stock_locked": False, "propagated": False}]
    if a.kind == "attribution_inflation":  # a data issue: the source stream, never individual neurons
        return [{"target_id": _source_for_channel(manifest, a.entity_id), "target_type": "source",
                 "stock_locked": False, "propagated": False}]
    targets = [{"target_id": a.entity_id, "target_type": "neuron", "stock_locked": False, "propagated": False}]
    if a.kind == "stockout_risk":  # budget increases blocked on every promoting campaign
        for cid in a.detail.get("campaigns", []):
            targets.append({"target_id": cid, "target_type": "neuron", "stock_locked": True, "propagated": True})
    return targets


def validate_targets(targets: list[dict], manifest: dict) -> None:
    """Raise if any target id is not a manifest neuron, cluster or source."""
    valid = {
        "neuron": {n["entity_id"] for n in manifest["neurons"]},
        "cluster": {c["id"] for c in manifest["clusters"]},
        "source": {s["id"] for s in manifest["sources"]},
    }
    for t in targets:
        if t["target_id"] not in valid[t["target_type"]]:
            raise ValueError(f"brain target {t['target_type']} {t['target_id']!r} is not in brain_manifest.json")


def build_brain_alerts(anomalies: list[Anomaly], manifest: dict | None = None) -> pd.DataFrame:
    """One row per brain target currently alerting, merging every anomaly that hits it.

    top = the anomaly with the largest |profit_impact| (a stock lock always wins: it is high severity and
    the lock icon must show); top_severity = the highest severity; direction = top's direction;
    profit_impact = sum of the target's own anomalies; stock_locked = any lock; message = top's label.
    """
    manifest = manifest or load_manifest()
    merged: dict[tuple[str, str], list[tuple[Anomaly, dict]]] = {}
    for a in anomalies:
        for t in targets_for(a, manifest):
            validate_targets([t], manifest)
            merged.setdefault((t["target_type"], t["target_id"]), []).append((a, t))
    rows = []
    for (target_type, target_id), items in merged.items():
        lock = [a for a, t in items if t["stock_locked"]]
        top = (lock[0] if lock else max((a for a, _ in items), key=lambda x: abs(x.profit_impact)))
        own = [a for a, t in items if not t["propagated"]]
        rows.append({
            "target_id": target_id, "target_type": target_type,
            "anomaly_ids": json.dumps([a.id for a, _ in items]),
            "top_kind": top.kind,
            "top_severity": max((a.severity for a, _ in items), key=SEVERITY_RANK.get),
            "direction": top.detail["direction"],
            "profit_impact": round(sum(a.profit_impact for a in own), 2),
            "stock_locked": bool(lock), "message": top.label,
        })
    order = {"cluster": 0, "source": 1, "neuron": 2}
    rows.sort(key=lambda r: (order[r["target_type"]], r["target_id"]))
    return pd.DataFrame(rows, columns=TABLE_COLUMNS["brain_alerts"])


def write_brain_alerts(df: pd.DataFrame) -> None:
    """Replace the `brain_alerts` table."""
    validate_table(df, "brain_alerts")
    write_table(df, "brain_alerts")
