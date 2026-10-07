"""M4 persistence: the `diagnoses` and `causal_results` tables."""
from __future__ import annotations

import json

import pandas as pd

from backend.core.db import TABLE_COLUMNS, validate_table, write_table
from backend.core.schema import Anomaly, RootCause, to_dict
from backend.detection.store import anomaly_key
from backend.diagnosis.decompose import _top_factor, causal_event_id


def diagnoses_frame(anomalies: list[Anomaly], roots: list[RootCause], diagnosed_at: str,
                    causal: dict | None = None) -> pd.DataFrame:
    """One row per anomaly. top_factor / top_factor_pct = the largest factor in the direction of total_change
    (None for attribution_inflation, which has no waterfall)."""
    rows = []
    for a, rc in zip(anomalies, roots):
        top = _top_factor(rc.factors, rc.total_change) if rc.factors else None
        rows.append({
            "anomaly_key": anomaly_key(a), "anomaly_id": a.id, "entity_type": a.entity_type, "entity_id": a.entity_id,
            "kind": a.kind, "total_change": rc.total_change,
            "top_factor": top.name if top else None, "top_factor_pct": top.pct if top else None,
            "factors_json": json.dumps(to_dict(rc.factors)), "funnel_json": json.dumps(to_dict(rc.funnel)),
            "narrative": rc.narrative, "related_json": json.dumps(to_dict(a.detail.get("related", []))),
            "causal_event_id": causal_event_id(a, causal), "diagnosed_at": diagnosed_at,
        })
    return pd.DataFrame(rows, columns=TABLE_COLUMNS["diagnoses"])


def write_diagnoses(anomalies: list[Anomaly], roots: list[RootCause], diagnosed_at: str,
                    causal: dict | None = None) -> pd.DataFrame:
    """Replace the `diagnoses` table (validated first)."""
    df = diagnoses_frame(anomalies, roots, diagnosed_at, causal)
    validate_table(df, "diagnoses")
    write_table(df, "diagnoses")
    return df


def causal_frame(details: list[dict], computed_at: str) -> pd.DataFrame:
    """One row per computed event."""
    rows = []
    for d in details:
        r = d["result"]
        rows.append({
            "event_id": r.event_id, "description": r.description, "treated_sku": d["treated_sku"],
            "method": d["method"], "effect_per_day": r.effect_per_day, "total_effect": r.total_effect,
            "ci_low": r.ci_low, "ci_high": r.ci_high, "units_change_pct": d["units_change_pct"],
            "pre_fit_rmse": d["pre_fit_rmse"], "controls_json": json.dumps(d["controls"]),
            "weights_json": json.dumps(d["weights"]), "series_json": json.dumps(to_dict(r.series)),
            "computed_at": computed_at,
        })
    return pd.DataFrame(rows, columns=TABLE_COLUMNS["causal_results"])


def write_causal(details: list[dict], computed_at: str) -> pd.DataFrame:
    """Replace the `causal_results` table (validated first)."""
    df = causal_frame(details, computed_at)
    validate_table(df, "causal_results")
    write_table(df, "causal_results")
    return df
