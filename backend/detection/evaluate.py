"""M3 evaluation against the M1 answer key.

Compares the alerts with data/raw/ground_truth.json (and the manifest's scenario timeline) and returns
recall, precision and an itemised list of extras. The result is stored in state["detection_quality"]
and powers the "7/7 detected" badge.

M3-detectable scenarios: S1, S2, S3, S5 (two channels), S6, S7 = 7 expected (kind, entity) pairs.
S4 (under-funded) and S8 (untested opportunity) belong to the optimiser (M5 / M5b).
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from backend.core import config
from backend.core.schema import Anomaly
from backend.detection.store import load_manifest

# ground-truth scenario type → (anomaly kind it should produce, which ground-truth field names the entity)
SCENARIO_KIND = {
    "creative_fatigue": "creative_fatigue",
    "stockout_risk": "stockout_risk",
    "cpc_spike": "cpc_spike",
    "double_counting": "attribution_inflation",
    "price_change": "conversion_drop",
    "positive_spike": "positive_spike",
}
KNOCK_ON_SCENARIO = "S3"  # Google CPC spike: profit shifts on Google campaigns are a known consequence


def load_ground_truth() -> dict:
    path = Path(config.RAW_DIR) / "ground_truth.json"
    if not path.exists():
        raise FileNotFoundError(f"missing {path}. Run `python -m backend.generator.generate` first.")
    return json.loads(path.read_text(encoding="utf-8"))


def expected_pairs(truth: dict) -> dict[str, list[tuple[str, str]]]:
    """scenario id → the (kind, entity_id) pairs M3 must raise for it."""
    pairs: dict[str, list[tuple[str, str]]] = {}
    for sid, sc in truth.items():
        kind = SCENARIO_KIND.get(sc["type"])
        if kind is None:
            continue  # S4 / S8: not an M3 job
        if "channels" in sc:
            entities = list(sc["channels"])
        else:
            entities = [sc.get("campaign") or sc.get("sku") or sc.get("channel")]
        pairs[sid] = [(kind, e) for e in entities]
    return pairs


def _brief(a: Anomaly) -> dict:
    return {"id": a.id, "kind": a.kind, "entity_id": a.entity_id, "label": a.label}


def evaluate(anomalies: list[Anomaly], evaluated_at: str | None = None) -> dict:
    """Score alerts against the answer key. precision = (found + knock_on) ÷ total anomalies."""
    truth, manifest = load_ground_truth(), load_manifest()
    by_pair = {(a.kind, a.entity_id): a for a in anomalies}
    pairs = expected_pairs(truth)
    expected_all = [p for ps in pairs.values() for p in ps]

    per_scenario, missed = {}, []
    for sid, ps in pairs.items():
        hits = [by_pair[p] for p in ps if p in by_pair]
        missed += [{"kind": k, "entity_id": e} for k, e in ps if (k, e) not in by_pair]
        per_scenario[sid] = {
            "found": len(hits) == len(ps),
            "anomaly_id": hits[0].id if hits else None,
            "anomaly_ids": [h.id for h in hits],
            "label": " | ".join(h.label for h in hits) if hits else None,
        }
    found = sum(p in by_pair for p in expected_all)

    # Known knock-on effects: profit drops on Google campaigns inside the S3 window.
    s3 = next((s for s in manifest["scenario_timeline"] if s["scenario"] == KNOCK_ON_SCENARIO), None)
    channel_of = {n["entity_id"]: n["channel"] for n in manifest["neurons"] if n["entity_type"] == "campaign"}
    extras = [a for a in anomalies if (a.kind, a.entity_id) not in set(expected_all)]
    knock_on, false_alarms = [], []
    for a in extras:
        window = a.detail.get("window", {})
        inside = bool(s3 and window.get("recent_end") and s3["start_date"] <= window["recent_end"] <= s3["end_date"])
        if a.kind == "metric_shift" and channel_of.get(a.entity_id) == truth[KNOCK_ON_SCENARIO]["channel"] and inside:
            knock_on.append({**_brief(a), "reason": "knock-on of S3"})
        else:
            false_alarms.append(_brief(a))

    total = len(anomalies)
    return {
        "expected": len(expected_all), "found": found, "missed": missed,
        "recall": round(found / len(expected_all), 4) if expected_all else 1.0,
        "precision": round((found + len(knock_on)) / total, 4) if total else 1.0,
        "extra_alerts": [_brief(a) for a in extras], "knock_on": knock_on, "false_alarms": false_alarms,
        "per_scenario": per_scenario,
        "evaluated_at": evaluated_at or datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
    }
