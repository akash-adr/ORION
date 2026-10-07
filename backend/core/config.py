"""M0 shared configuration: the single source of every setting, threshold and vocabulary.

No other module may hard-code any of these values; import them from here.
Units: percentages are fractions (0.15 == 15%), money is float INR per day unless named otherwise.
"""
from pathlib import Path

# ---------------------------------------------------------------------------
# 2.1 Paths
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[2]  # project root (folder containing backend/)
DATA_DIR = ROOT / "data"  # all runtime data lives here
RAW_DIR = DATA_DIR / "raw"  # raw CSV/JSON files written by M1
DB_PATH = DATA_DIR / "engine.db"  # SQLite database written by M2, read by M3–M9
STATE_PATH = DATA_DIR / "state.json"  # mutable engine state (decisions, audit, brain events)

# ---------------------------------------------------------------------------
# 2.2 Data generation
# ---------------------------------------------------------------------------
SEED = 42  # global random seed so every run produces identical synthetic data
N_DAYS = 90  # number of days of history generated
END_DATE = "2026-10-06"  # last day of generated history (YYYY-MM-DD)
CURRENCY = "INR"  # all money values are Indian rupees

# ---------------------------------------------------------------------------
# 2.3 Vocabulary
# ---------------------------------------------------------------------------
CHANNELS = ("meta", "google", "amazon", "tiktok", "programmatic")  # ad platforms
AUDIENCES = ("broad", "lookalike", "interest", "retargeting")  # targeting types
OBJECTIVES = ("max_profit", "revenue_target", "clear_inventory", "launch_sku")  # optimizer goals
AUTONOMY_MODES = ("advisory", "supervised", "autonomous")  # how much the engine may act alone
ANOMALY_KINDS = (  # every anomaly type M3 can emit
    "metric_shift",
    "creative_fatigue",
    "stockout_risk",
    "cpc_spike",
    "positive_spike",
    "conversion_drop",
    "attribution_inflation",
)
ENTITY_TYPES = ("campaign", "sku", "channel")  # what an anomaly can be about
SEVERITIES = ("low", "medium", "high")  # anomaly severity levels
RISK_LEVELS = ("low", "medium", "high")  # recommendation risk levels
ACTION_TYPES = (  # every action a recommendation can propose
    "creative_refresh",
    "inventory_protect",
    "bid_cap",
    "scale_up",
    "budget_cut",
    "price_review",
    "data_fix",
    "launch_test",
)
DECISION_STATUSES = ("pending", "executed", "rejected", "rolled_back")  # recommendation lifecycle
DEFAULT_AUTONOMY = "supervised"  # autonomy mode on a fresh state
DEFAULT_OBJECTIVE = "max_profit"  # optimizer objective on a fresh state

# ---------------------------------------------------------------------------
# 2.4 Detection thresholds (used by M3)
# ---------------------------------------------------------------------------
RECENT_DAYS = 7  # window (days) compared against the baseline
BASELINE_DAYS = 21  # window (days) before the recent window used as "normal"
Z_THRESHOLD = 2.5  # |z-score| of recent vs baseline needed to flag an anomaly
MIN_PCT_CHANGE = 0.15  # minimum relative change (fraction) to flag, filters tiny-but-stable shifts
STOCK_COVER_RISK_DAYS = 7  # SKUs with fewer days of cover than this are at stockout risk

# ---------------------------------------------------------------------------
# 2.5 Severity and risk cut-offs
# ---------------------------------------------------------------------------
SEVERITY_HIGH_IMPACT = 25000  # ₹/day loss above this = high
SEVERITY_MEDIUM_IMPACT = 8000  # ₹/day loss above this = medium
RISK_HIGH_SHIFT = 0.40  # budget shift above 40% = high risk
RISK_HIGH_IMPACT = 40000  # |impact| above ₹40k/day = high risk
CONFIDENCE_MIN = 0.45  # floor for any recommendation confidence (fraction)
CONFIDENCE_MAX = 0.95  # ceiling for any recommendation confidence (fraction), never claim certainty

# ---------------------------------------------------------------------------
# 2.6 Guardrails (used by M5, M6)
# ---------------------------------------------------------------------------
AUTO_APPLY_MAX_SHIFT = 0.10  # in autonomous mode, only budget shifts up to 10% apply without approval
DAILY_CHANGE_CAP = 0.50  # no campaign budget may change more than 50% in one day
POAS_FLOOR = 0.0  # never scale a campaign whose POAS is at or below this
STOCK_SPEND_CAP_MULT = 0.4  # campaigns on SKUs under STOCK_COVER_RISK_DAYS are capped at 40% of current spend; increases blocked

# ---------------------------------------------------------------------------
# 2.7 ID formats (regex strings, for validation and tests)
# ---------------------------------------------------------------------------
ID_PATTERNS = {  # canonical ID shape for every object type
    "campaign": r"^CMP-\d{2}$",
    "sku": r"^SKU-[A-J]$",
    "creative": r"^CR-\d{2}[a-z]$",
    "event": r"^EV-\d+$",
    "anomaly": r"^AN-\d{3}$",
    "recommendation": r"^REC-[0-9a-f]{6}$",
    "brain_event": r"^BE-\d{5}$",
}

# ---------------------------------------------------------------------------
# 2.8 Neural Brain settings
# ---------------------------------------------------------------------------
BRAIN_REGIONS = ("ingest", "diagnose", "decide", "learn")  # the four brain regions in the UI
BRAIN_MODES = ("idle", "ingesting", "anomaly", "deciding", "learning")  # UI animation modes
BRAIN_EVENT_TYPES = (  # every event that fires a pulse through the brain
    "ingest",
    "anomaly",
    "diagnosis",
    "recommendation",
    "approval",
    "rejection",
    "rollback",
    "auto_apply",
    "outcome",
)

# Which region each event type lights up
EVENT_REGION = {
    "ingest": "ingest", "anomaly": "diagnose", "diagnosis": "diagnose",
    "recommendation": "decide", "approval": "decide", "rejection": "decide",
    "rollback": "decide", "auto_apply": "decide", "outcome": "learn",
}

# The path a pulse travels through the brain for each event type
PULSE_PATHS = {
    "ingest": ["ingest"],
    "anomaly": ["ingest", "diagnose"],
    "diagnosis": ["diagnose"],
    "recommendation": ["diagnose", "decide"],
    "approval": ["decide", "learn"],
    "rejection": ["decide"],
    "rollback": ["learn", "decide"],
    "auto_apply": ["decide", "learn"],
    "outcome": ["learn"],
}

# Brain mode the UI switches into when this event arrives
EVENT_MODE = {
    "ingest": "ingesting", "anomaly": "anomaly", "diagnosis": "anomaly",
    "recommendation": "deciding", "approval": "deciding", "rejection": "deciding",
    "rollback": "deciding", "auto_apply": "deciding", "outcome": "learning",
}

NEURON_HEALTH_LEVELS = ("good", "weak", "losing")  # neuron colour states in the brain
NEURON_POAS_GOOD = 1.2  # POAS >= 1.2 → good
NEURON_POAS_WEAK = 0.8  # 0.8 <= POAS < 1.2 → weak; below 0.8 → losing
BRAIN_MAX_NEURONS = 40  # max campaign + SKU neurons sent to the UI
BRAIN_EVENT_HISTORY_LIMIT = 500  # oldest brain events dropped beyond this
NEURON_SIZE_MIN = 0.6  # relative node size for the smallest spender
NEURON_SIZE_MAX = 2.0  # relative node size for the biggest spender


def validate_config() -> None:
    """Assert the brain/vocabulary settings are internally consistent. Called by tests, not at import."""
    for event_type, region in EVENT_REGION.items():
        assert event_type in BRAIN_EVENT_TYPES, f"EVENT_REGION has unknown event type {event_type!r}"
        assert region in BRAIN_REGIONS, f"EVENT_REGION[{event_type!r}] = {region!r} is not a brain region"
    for event_type, path in PULSE_PATHS.items():
        assert event_type in BRAIN_EVENT_TYPES, f"PULSE_PATHS has unknown event type {event_type!r}"
        for region in path:
            assert region in BRAIN_REGIONS, f"PULSE_PATHS[{event_type!r}] contains invalid region {region!r}"
    for event_type, mode in EVENT_MODE.items():
        assert event_type in BRAIN_EVENT_TYPES, f"EVENT_MODE has unknown event type {event_type!r}"
        assert mode in BRAIN_MODES, f"EVENT_MODE[{event_type!r}] = {mode!r} is not a brain mode"
    for mapping_name, mapping in (("EVENT_REGION", EVENT_REGION), ("PULSE_PATHS", PULSE_PATHS), ("EVENT_MODE", EVENT_MODE)):
        missing = set(BRAIN_EVENT_TYPES) - set(mapping)
        assert not missing, f"{mapping_name} is missing event types {sorted(missing)}"
    assert DEFAULT_AUTONOMY in AUTONOMY_MODES, "DEFAULT_AUTONOMY must be one of AUTONOMY_MODES"
    assert DEFAULT_OBJECTIVE in OBJECTIVES, "DEFAULT_OBJECTIVE must be one of OBJECTIVES"
    assert NEURON_POAS_WEAK < NEURON_POAS_GOOD, "NEURON_POAS_WEAK must be below NEURON_POAS_GOOD"

# ---------------------------------------------------------------------------
# 2.9 Ingestion (added for M2, additive)
# ---------------------------------------------------------------------------
RECON_GAP_THRESHOLD = 0.10  # |inflation_pct| above 10% = reconciliation gap; M3 raises attribution_inflation, M6 recommends server-side tracking
REFRESH_MINUTES = 5  # auto-refresh interval for the demo loop
FRESHNESS_WARN_MINUTES = 15  # last_synced older than this → stale warning badge

# ---------------------------------------------------------------------------
# 2.10 Detection (added for M3, additive)
# ---------------------------------------------------------------------------
FATIGUE_FREQ_UP = 0.30  # creative fatigue: frequency up more than 30%
FATIGUE_CTR_DOWN = 0.20  # ... AND CTR down more than 20%
CPC_SPIKE_MIN = 0.25  # channel CPC up more than 25%
SKU_RECENT_DAYS = 14  # site-conversion checks use 14 recent days (slow-moving web behaviour; keeps a price change out of the baseline)
SKU_BASELINE_DAYS = 28  # ... vs the 28 days before that
PROFIT_BASE_FLOOR = 0.10  # % change base for profit = max(|baseline profit|, 10% of baseline spend)
MAD_SCALE = 1.4826  # MAD → standard-deviation equivalent

# ---------------------------------------------------------------------------
# 2.11 Display names (added for M1–M3 labels, additive)
# ---------------------------------------------------------------------------
CHANNEL_DISPLAY = {"meta": "Meta", "google": "Google", "amazon": "Amazon", "tiktok": "TikTok", "programmatic": "Programmatic"}  # human-readable channel names for every label (never str.title(): it yields "Tiktok")

# ---------------------------------------------------------------------------
# 2.12 Causal analysis (added for M4b, additive)
# ---------------------------------------------------------------------------
CAUSAL_CHART_DAYS = 45  # days of actual vs counterfactual returned for the chart
CAUSAL_CI_Z = 1.96  # 95% interval
CAUSAL_MIN_PRE_DAYS = 21  # minimum pre-period days to fit weights

# ---------------------------------------------------------------------------
# 2.13 Optimizer & simulator (added for M5, additive)
# ---------------------------------------------------------------------------
CURVE_POINTS = 40  # points returned per curve for the UI chart
CURVE_B_MIN_MULT = 0.05  # b lower bound = 5% of mean spend
CURVE_B_MAX_MULT = 50.0  # b upper bound = 50× mean spend
SATURATION_MULT = 3.0  # saturation spend ≈ 3b
OPTIMIZER_MAX_ITER = 500  # SLSQP iteration limit
OVERSTOCK_COVER_DAYS = 60  # clear_inventory: SKUs above 60 days of cover may grow to 2×
OVERSTOCK_UPPER_MULT = 2.0  # ... that upper multiple of current spend
CLEAR_INV_PIVOT_DAYS = 30  # clear_inventory weight = 1 + clip((cover − 30)/30, 0, 1.5)
CLEAR_INV_MAX_BONUS = 1.5  # ... capped at this bonus
LAUNCH_TEST_RESERVE = 0.05  # launch_sku: 5% of budget reserved for M5b tests
SIMULATE_MAX_MS = 300  # simulator must answer within 300 ms

# ---------------------------------------------------------------------------
# 2.14 Opportunity scorer and headroom (added for M5b, additive)
# ---------------------------------------------------------------------------
OPP_TEST_BUDGET = 5000  # ₹/day test budget used to score untested combos
OPP_TOP_N = 10  # opportunities kept
OPP_GHOST_N = 5  # top opportunities shown as ghost neurons in the brain
RIDGE_ALPHA = 1.0  # Ridge regularisation strength
CV_FOLDS = 4  # GroupKFold folds (grouped by campaign)
STOCK_FACTOR_PIVOT = 30  # stock factor = clip(cover/30, 0.5, 1.5); 0 if cover < STOCK_COVER_RISK_DAYS
STOCK_FACTOR_MIN = 0.5  # ... lower clip
STOCK_FACTOR_MAX = 1.5  # ... upper clip
HEADROOM_SCALE_POAS = 1.1  # marginal POAS above this → "scale"
HEADROOM_CUT_POAS = 0.9  # below this → "cut"; between → "hold"

# ---------------------------------------------------------------------------
# 2.15 Recommendations (added for M6, additive)
# ---------------------------------------------------------------------------
CONF_BASE = 0.55  # confidence before any evidence
CONF_Z_WEIGHT = 0.08  # + per unit of |z| (capped), a stronger signal earns more confidence
CONF_Z_CAP = 4.0  # |z| beyond this adds nothing
CONF_UNC_WEIGHT = 0.15  # − per unit of curve uncertainty (a poorly-determined response curve earns less)
CONF_MAPE_WEIGHT = 0.5  # confidence is scaled by (1 − 0.5 × MAPE) once M7 has measured how wrong we were
RISK_MEDIUM_SHIFT = 0.10  # budget shift above 10% = medium risk
URGENCY_BONUS = 5000  # added to priority for high-risk (urgent) items
STOCKOUT_HORIZON_DAYS = 14  # inventory_protect values ad spend over this horizon
STOCKOUT_AD_CUT = 0.60  # inventory_protect cuts SKU ads by 60%
POSITIVE_SCALE_UP = 0.30  # scale winners +30% (bounded by optimizer bounds)
PLAN_SCALE_THRESHOLD = 1.15  # optimizer plan > 115% of current → scale_up
PLAN_CUT_THRESHOLD = 0.85  # optimizer plan < 85% of current → budget_cut
OPP_LAUNCH_N = 2  # top opportunities turned into launch tests
OPP_IMPACT_HAIRCUT = 0.6  # expected test value = (pred POAS − 1) × budget × 0.6

# ---------------------------------------------------------------------------
# 2.16 Closed-loop learning (added for M7, additive)
# ---------------------------------------------------------------------------
MEASURE_WINDOW_DAYS = 7  # production: wait 7 days after execution before measuring
OUTCOME_BIAS_MEAN = -0.05  # demo: predictions are slightly optimistic
OUTCOME_NOISE_SD = 0.12  # demo: spread of simulated outcomes around the prediction
CALIBRATION_WINDOW = 8  # the last 8 measurable outcomes drive calibration
ROLLING_WINDOW = 4  # rolling MAPE window for the accuracy chart
CALIBRATION_MIN = 0.6  # the calibration factor never leaves [0.6, 1.2]
CALIBRATION_MAX = 1.2
SEED_HISTORY_N = 12  # seeded historical outcomes (so the brain starts with memory)
SEED_PRED_MIN = 4000  # seeded predictions ₹/day ~ U(min, max)
SEED_PRED_MAX = 22000
SEED_ERR_SD0 = 0.35  # seeded forecast error SD for the oldest outcome ...
SEED_ERR_DECAY = 0.85  # ... shrinking by this factor per outcome (the engine "gets better")
SEED_BIAS0 = -0.10  # seeded optimism bias for the oldest outcome ...
SEED_BIAS_DECAY = 0.8  # ... shrinking by this factor per outcome
SYNAPSE_BASE = 1.0  # starting synapse strength in the brain
SYNAPSE_GAIN = 0.25  # a good outcome strengthens the campaign→SKU synapse
SYNAPSE_DECAY = 0.15  # a loss-making outcome weakens it
SYNAPSE_MIN = 0.5
SYNAPSE_MAX = 3.0
SYNAPSE_GOOD_ERROR = 0.25  # "good" = actual > 0 and |error| ≤ 25%

# ---------------------------------------------------------------------------
# 2.17 AI agent (added for M8, additive)
# ---------------------------------------------------------------------------
AGENT_MAX_STEPS = 6  # tool-calling rounds before the agent gives up and falls back
AGENT_MAX_TOKENS = 700  # per Claude response
AGENT_TOOL_RESULT_MAX_CHARS = 12000  # tool results are truncated to this many characters
AGENT_MAX_WORDS = 120  # rules-engine answers are trimmed to this many words
CLAUDE_MODEL_DEFAULT = "claude-sonnet-5-5"  # used when the CLAUDE_MODEL environment variable is not set
