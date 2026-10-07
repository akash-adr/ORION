# Frontend ↔ API notes (Module 9)

Base URL: `NEXT_PUBLIC_API_URL=http://localhost:8000` (put it in `frontend/.env.local`). CORS is open (`*`) for the demo.
Start the API with either server (identical routes and JSON):

```bash
uvicorn backend.api.main:app --port 8000        # FastAPI, docs at /docs
python -m backend.api.devserver --port 8000     # zero-dependency fallback
```

> The old setup scaffold in `backend/app/` also listens on :8000. Run only one of them at a time.

## Polling plan

| What | Endpoint | When |
|---|---|---|
| New brain pulses | `GET /brain/events?since=<last_id>` | every **2 s** (keep the returned `last_id`; first call without `since`) |
| Brain mode (idle / ingesting / thinking / deciding / learning) | `GET /brain/state` | every **2 s** |
| Whole brain picture | `GET /brain/snapshot` | every **10 s**, and right after any action |
| Dashboard numbers | `GET /kpis`, `GET /recommendations` | on load and after any action |
| Sliders (what-if) | `POST /simulate/channels`, `POST /simulate` | **debounce 250 ms** (calls take ~2 ms) |

Events arrive oldest-first; play them in `id` order. Replayed events carry `payload.replay = true`.

## Button → endpoint

| UI | Call |
|---|---|
| Approve | `POST /decisions/{id}/approve` → `{ok, api_calls, decision, outcome}` or `{ok:false, reason}` |
| Reject | `POST /decisions/{id}/reject` |
| Roll back | `POST /decisions/{id}/rollback` |
| Objective picker / autonomy toggle | `POST /settings` `{objective?, autonomy?}` then refetch snapshot + recommendations |
| What-if channel slider | `POST /simulate/channels` `{multipliers: {google: 1.2}}` |
| What-if campaign budgets | `POST /simulate` `{plan: {"CMP-01": 30000}}` |
| Optimise | `POST /optimize` `{objective, total_budget?}` |
| Ask the AI | `POST /ask` `{question}` → `{answer, engine, tools_used, highlights, note, duration_ms}`; light up `highlights` on the brain |
| Run the loop now | `POST /refresh` → `{ok, steps{name:{ok,duration_ms,events}}, auto_applied, outcomes_measured, events_logged, duration_ms}` |
| Play the demo story | `POST /brain/replay` (then poll events as usual) |
| Reset the demo | `POST /demo/reset` |
| Click a neuron / alert | `GET /anomalies/{id}/diagnosis` |
| Show the last loop run | `GET /loop/last` (same shape as `/refresh` plus `at`; `null` if the loop never ran) |
| Explain a threshold | `GET /meta/config` (read-only detection, guardrail, optimizer and learning settings) |

Errors are `{"detail": "..."}`: 404 unknown id, 400 invalid value, 422 malformed body, 500 never leaks internals. Blocked or duplicate
actions are **not** errors: they return 200 `{ok:false, reason}`; show the reason.

## Real example responses (trimmed)

### `GET /brain/snapshot`
```json
{
  "as_of": "2026-10-06",
  "objective": "max_profit",
  "autonomy": "supervised",
  "nodes": [
    {
      "entity_id": "SKU-A",
      "entity_type": "sku",
      "label": "Summer Sneakers",
      "cluster": "catalog",
      "channel": null,
      "spend_7d": 85732.19142857143,
      "poas_7d": 0.14065728336017275,
      "health": "losing",
      "is_alerting": false,
      "anomaly_id": null,
      "alert_kind": null,
      "planned_change_pct": null,
      "current_spend": 85732.19142857144,
      "why": null
    },
    "… 25 more"
  ],
  "clusters": [
    {
      "id": "meta",
      "label": "Meta",
      "alert": null
    },
    {
      "id": "google",
      "label": "Google",
      "alert": {
        "target_id": "google",
        "target_type": "cluster",
        "anomaly_ids": [
          "AN-004"
        ],
        "top_kind": "cpc_spike",
        "top_severity": "high",
        "direction": "loss",
        "profit_impact": -25736.43,
        "stock_locked": false,
        "message": "CPC spike · Google"
      }
    },
    "…"
  ],
  "sources": [
    {
      "id": "meta_ads",
      "label": "Meta Ads",
      "kind": "ad_platform",
      "channel": "meta",
      "status": "warn",
      "trust_score": 0.559063609063609,
      "inflation_pct": 0.22046819546819552,
      "verified": false,
      "alert": {
        "target_id": "meta_ads",
        "target_type": "source",
        "anomaly_ids": [
          "AN-008"
        ],
        "top_kind": "attribution_inflation",
        "top_severity": "medium",
        "direction": "loss",
        "profit_impact": 0.0,
        "stock_locked": false,
        "message": "Attribution inflation · Meta"
      }
    },
    "… 8 more"
  ],
  "ghosts": [
    {
      "id": "Trail Max · Google · retargeting",
      "sku_id": "SKU-C",
      "channel": "google",
      "cluster": "google",
      "audience": "retargeting",
      "predicted_poas": 5.5474129727186945,
      "score": 8.32111945907804,
      "launched": false,
      "test_campaign_id": null
    },
    "…"
  ],
  "synapses": [
    {
      "source": "meta_ads",
      "target": "CMP-01",
      "kind": "feeds",
      "strength": 1.0
    },
    "… 71 more"
  ],
  "headline": {
    "current_profit": -51688.20571428574,
    "planned_profit": 22629.050438532293,
    "profit_delta": 74317.25615281804,
    "data_trust": 0.7435452653752611
  },
  "counts": {
    "anomalies": 9,
    "pending_decisions": 11,
    "executed": 0,
    "outcomes": 12
  }
}
```

### `GET /brain/events?limit=2`
```json
{
  "events": [
    {
      "id": "BE-00039",
      "ts": "2026-10-07T14:39:49",
      "type": "recommendation",
      "region": "decide",
      "path": [
        "diagnose",
        "decide"
      ],
      "entity_id": "meta_ads",
      "ref_id": "REC-3dbeb0",
      "severity": "low",
      "message": "Optimise Meta on store-verified conversions — ₹0/day · 55% confidence",
      "payload": {
        "rec_id": "REC-3dbeb0",
        "action_type": "data_fix",
        "targets": [
          {
            "type": "source",
            "id": "meta_ads"
          }
        ],
        "anomaly_id": "AN-008",
        "related": [],
        "expected_profit_delta": 0.0,
        "confidence": 0.55,
        "risk": "low",
        "requires_approval": false,
        "blocked": false,
        "campaigns": []
      }
    },
    {
      "id": "BE-00040",
      "ts": "2026-10-07T14:39:49",
      "type": "recommendation",
      "region": "decide",
      "path": [
        "diagnose",
        "decide"
      ],
      "entity_id": "google_ads",
      "ref_id": "REC-f697a9",
      "severity": "low",
      "message": "Optimise Google on store-verified conversions — ₹0/day · 55% confidence",
      "payload": {
        "rec_id": "REC-f697a9",
        "action_type": "data_fix",
        "targets": [
          {
            "type": "source",
            "id": "google_ads"
          }
        ],
        "anomaly_id": "AN-009",
        "related": [],
        "expected_profit_delta": 0.0,
        "confidence": 0.55,
        "risk": "low",
        "requires_approval": false,
        "blocked": false,
        "campaigns": []
      }
    }
  ],
  "last_id": "BE-00040"
}
```

### `GET /recommendations`
```json
{
  "objective": "max_profit",
  "summary": {
    "pending": 11,
    "executed": 0,
    "rejected": 0,
    "rolled_back": 0,
    "total_expected_profit_delta": 152001.02,
    "needs_approval": 7,
    "auto_eligible": 4,
    "blocked": 0,
    "plan_profit_delta": null
  },
  "pending": [
    {
      "id": "REC-afd747",
      "title": "Refresh creative & trim budget · Meta · Summer Sneakers · broad",
      "issue": "Creative fatigue · Meta · Summer Sneakers · broad: frequency 1.9 → 3.7, CTR -36%",
      "action": {
        "changes": [
          {
            "campaign_id": "CMP-01",
            "name": "Meta · Summer Sneakers · broad",
            "channel": "meta",
            "from_budget": 50272.49,
            "to_budget": 25140.0
          }
        ],
        "targets": [
          {
            "type": "neuron",
            "id": "CMP-01"
          }
        ],
        "notes": [
          "Rotate in a UGC variant while the audience recovers from the tired creative"
        ],
        "related": [],
        "type": "creative_refresh",
        "creative_refresh": {
          "campaign_id": "CMP-01",
          "current_creative": "CR-01a",
          "suggested": "UGC testimonial variant"
        }
      },
      "expected_profit_delta_fmt": "₹24.2k",
      "confidence": 0.7419,
      "risk": "high",
      "requires_approval": true,
      "blocked": false,
      "anomaly_id": "AN-001",
      "status": "pending",
      "targets": [
        {
          "type": "neuron",
          "id": "CMP-01"
        }
      ]
    },
    "… 10 more"
  ],
  "calibration_factor": 1.0143
}
```

### `GET /anomalies/AN-001/diagnosis`
```json
{
  "anomaly": {
    "id": "AN-001",
    "kind": "creative_fatigue",
    "entity_type": "campaign",
    "entity_id": "CMP-01",
    "label": "Creative fatigue · Meta · Summer Sneakers · broad",
    "metric": "ctr",
    "baseline": 0.0087,
    "recent": 0.0055,
    "change_pct": -0.3598
  },
  "root_cause": {
    "anomaly_id": "AN-001",
    "entity_id": "CMP-01",
    "total_change": -2812.68,
    "factors": [
      {
        "name": "Budget change",
        "impact": 46.12,
        "pct": 0.0158
      },
      {
        "name": "Auction cost (CPM/CPC)",
        "impact": 10.36,
        "pct": 0.0035
      },
      "…"
    ],
    "funnel": [
      {
        "stage": "pdp_views",
        "from": "sessions",
        "baseline_rate": 0.72,
        "recent_rate": 0.72,
        "change_pct": 0.0,
        "baseline_count_per_day": 2660.29,
        "recent_count_per_day": 1891.57,
        "is_biggest_drop": false
      },
      {
        "stage": "add_to_cart",
        "from": "pdp_views",
        "baseline_rate": 0.0566,
        "recent_rate": 0.0622,
        "change_pct": 0.1002,
        "baseline_count_per_day": 150.48,
        "recent_count_per_day": 117.71,
        "is_biggest_drop": false
      },
      "…"
    ],
    "narrative": "Creative fatigue · Meta · Summer Sneakers · broad: daily profit fell by ₹2.8k. Largest driver: Click-through / creative (92% of the movement, ₹2.7k/day). Frequency rose from 1.9 to 3.7 and click-through fell 36% — the audience has seen this creative too often."
  },
  "evidence": {
    "daily": [
      {
        "date": "2026-08-23",
        "spend": 50719.1,
        "profit": -41290.1,
        "ctr": 0.008580844142126832,
        "cpc": 24.972476612506153,
        "frequency": 1.56
      },
      {
        "date": "2026-08-24",
        "spend": 61085.78,
        "profit": -52105.78,
        "ctr": 0.00805509743270313,
        "cpc": 26.83909490333919,
        "frequency": 1.68
      },
      "…"
    ],
    "causal": null,
    "related": [
      "…"
    ]
  }
}
```
