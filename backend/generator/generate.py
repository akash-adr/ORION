"""M1 Synthetic Data Generator.

90 days of fully linked data for a fictional Indian footwear D2C brand: ads, store orders,
prices, inventory, GA4 funnel, creatives and events, with 8 planted scenarios and an answer key.

Run from the project root:  python -m backend.generator.generate

Determinism: ALL randomness comes from one numpy Generator seeded with M0's SEED, and every
loop runs in a fixed order (campaigns in ID order, then days in date order; SKUs in ID order,
then days), so repeated runs are byte-identical. M1 only writes files into RAW_DIR.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from backend.core.config import AUDIENCES, CHANNELS, END_DATE, N_DAYS, RAW_DIR, SEED
from backend.core.metrics import format_inr

T = N_DAYS  # shorthand used in scenario windows

# ---------------------------------------------------------------------------
# 1. Products: sku_id, name, category, list price ₹, cogs ₹, rating, organic orders/day
# ---------------------------------------------------------------------------
SKU_ROWS = [
    ("SKU-A", "Summer Sneakers", "lifestyle", 2499, 2050, 4.0, 12),  # low margin, heavily advertised → fatigue
    ("SKU-B", "Running Pro", "running", 3999, 2360, 4.6, 18),  # best seller → stockout risk
    ("SKU-C", "Trail Max", "running", 4499, 2250, 4.5, 6),  # high margin, under-funded
    ("SKU-D", "Casual X", "lifestyle", 1999, 1200, 4.2, 14),  # price hike → conversion drop
    ("SKU-E", "Kids Glow", "kids", 1499, 750, 4.4, 8),  # overstocked
    ("SKU-F", "Office Loafer", "formal", 2999, 1800, 4.1, 7),  # programmatic loss-maker
    ("SKU-G", "Slide Comfort", "casual", 899, 450, 4.0, 20),  # cheap, weak on TikTok
    ("SKU-H", "Hiking Boot", "outdoor", 5499, 3300, 4.3, 4),  # premium, Amazon
    ("SKU-I", "Sock Pack", "accessories", 499, 200, 4.2, 25),  # low-price add-on
    ("SKU-J", "Gym Flex", "training", 2799, 1500, 4.4, 9),  # viral TikTok creative
]

# ---------------------------------------------------------------------------
# 2. Channel and audience economics
# ---------------------------------------------------------------------------
CPM = {"meta": 220, "google": 600, "amazon": 450, "tiktok": 150, "programmatic": 110}  # ₹ per 1,000 impressions
CTR = {"meta": 0.012, "google": 0.035, "amazon": 0.020, "tiktok": 0.010, "programmatic": 0.004}  # base click-through (fraction)
CH_CVR = {"meta": 1.00, "google": 1.15, "amazon": 1.30, "tiktok": 0.80, "programmatic": 0.70}  # channel CVR multiplier
OVERLAP = {"meta": 1.22, "google": 1.15, "amazon": 1.00, "tiktok": 1.00, "programmatic": 1.00}  # platform over-reporting (S5)
CVR_AUD = {"broad": 0.010, "lookalike": 0.014, "interest": 0.012, "retargeting": 0.028}  # base CVR by audience (fraction)
CVR_SCALE = 1.0  # single global calibration knob, multiplies every CVR
ELASTICITY = -2.5  # price elasticity of conversion: cvr ∝ (price / list_price) ^ ELASTICITY
RATING_REF = 4.3  # rating at which the rating multiplier is 1.0
MAX_CVR = 0.5  # cap on per-click conversion probability

for _ch in (*CPM, *CTR, *CH_CVR, *OVERLAP):
    assert _ch in CHANNELS, f"unknown channel {_ch!r}"
for _aud in CVR_AUD:
    assert _aud in AUDIENCES, f"unknown audience {_aud!r}"

# ---------------------------------------------------------------------------
# 3. Campaigns: campaign_id, channel, sku_id, audience, daily_budget ₹, sat_mult, format
# ---------------------------------------------------------------------------
CAMPAIGN_ROWS = [
    ("CMP-01", "meta", "SKU-A", "broad", 50000, 0.6, "static"),  # S1 creative fatigue; over-saturated
    ("CMP-02", "google", "SKU-A", "interest", 25000, 1.0, "search_text"),  # ROAS ~1.9 but loses money
    ("CMP-03", "meta", "SKU-B", "lookalike", 40000, 1.2, "video"),  # S2 stockout
    ("CMP-04", "google", "SKU-B", "interest", 30000, 1.2, "search_text"),  # S2 + S3
    ("CMP-05", "amazon", "SKU-B", "retargeting", 20000, 1.0, "sponsored"),  # S2; most efficient
    ("CMP-06", "google", "SKU-C", "interest", 8000, 4.0, "search_text"),  # S4 under-funded
    ("CMP-07", "meta", "SKU-C", "lookalike", 6000, 4.0, "video"),  # S4 under-funded
    ("CMP-08", "meta", "SKU-D", "broad", 25000, 1.0, "carousel"),  # S6 price hike
    ("CMP-09", "amazon", "SKU-D", "interest", 15000, 1.0, "sponsored"),  # S6
    ("CMP-10", "tiktok", "SKU-J", "broad", 15000, 1.5, "video"),  # S7 viral UGC
    ("CMP-11", "tiktok", "SKU-G", "interest", 10000, 1.0, "video"),  # loss-maker
    ("CMP-12", "programmatic", "SKU-F", "broad", 18000, 0.8, "display"),  # loss-maker
    ("CMP-13", "amazon", "SKU-H", "interest", 15000, 1.0, "sponsored"),  # profitable
    ("CMP-14", "meta", "SKU-E", "retargeting", 8000, 1.5, "carousel"),  # room to grow
    ("CMP-15", "google", "SKU-I", "interest", 6000, 1.0, "search_text"),  # loss-maker
    ("CMP-16", "programmatic", "SKU-A", "retargeting", 10000, 1.0, "display"),  # loss-maker
]

# ---------------------------------------------------------------------------
# 4. Calendar and simulation knobs
# ---------------------------------------------------------------------------
WEEKEND_MULT = 1.10  # demand multiplier on Saturday and Sunday
SALE_MULT = 1.30  # demand multiplier during the Independence Day sale (EV-1)
SALE_DAYS = ((8, 14), (8, 15), (8, 16))  # (month, day) of the sale in END_DATE's year
TEST_PERIOD_END = T - 35  # weekly budget tests only before this day index (makes response curves learnable)
TEST_MULT_RANGE = (0.6, 1.4)  # weekly budget test multiplier range
SPEND_NOISE = (0.95, 1.05)  # daily spend jitter
CPM_NOISE = (0.93, 1.07)  # daily CPM jitter
CLICK_NOISE = (0.95, 1.05)  # daily expected-click jitter
OVERLAP_NOISE = (0.97, 1.03)  # daily platform over-reporting jitter
FREQ_BASE = 1.6  # normal ad frequency
FREQ_SD = 0.05  # frequency noise (std dev)
COMPETITOR_BASE, COMPETITOR_AMP, COMPETITOR_PERIOD = 0.97, 0.04, 11  # competitor price = list × (base + amp·sin(t/period))

# ---------------------------------------------------------------------------
# 6. Planted scenarios
# ---------------------------------------------------------------------------
S1_CAMPAIGN, S1_START = "CMP-01", T - 14  # creative fatigue window
S1_FREQ_FROM, S1_FREQ_TO, S1_CTR_DROP = 1.8, 4.2, 0.5  # frequency ramp and max CTR loss (fraction)
S3_CHANNEL, S3_START, S3_CPM_MULT = "google", T - 7, 1.6  # Google CPC spike (EV-3)
S6_SKU, S6_START, S6_NEW_PRICE = "SKU-D", T - 14, 2299  # price hike (EV-2)
S7_CAMPAIGN, S7_START, S7_CTR_MULT = "CMP-10", T - 7, 2.2  # viral UGC creative (EV-4)
S7_CREATIVE = "CR-10b"

# 7.3 inventory targets (days of cover)
S2_SKU, S2_DECLINE_START = "SKU-B", 60  # SKU-B cover: 40 until t = 60, then falls linearly to S2_END_COVER
S2_COVER, S2_END_COVER = 40.0, 5.0
OVERSTOCK_SKU, OVERSTOCK_FROM, OVERSTOCK_TO = "SKU-E", 95.0, 77.0  # SKU-E cover falls 95 → 77 across all days
COVER_BASE, COVER_AMP, COVER_PERIOD, COVER_PHASE_STEP = 35.0, 15.0, 45.0, 0.7  # seasonal wave for other SKUs
INBOUND_DAYS = 10  # inbound = 10 days of demand on order

# 7.4 GA4 funnel ratios
SESSIONS_PER_PAID_CLICK = 0.9
SESSIONS_PER_ORGANIC_ORDER = 25
PDP_PER_SESSION = 0.72
CHECKOUT_TO_PURCHASE = 0.62
CART_TO_CHECKOUT = 0.55


def _r(x: float) -> int:
    """Round half-to-even to a non-negative int (stable across platforms)."""
    return max(0, int(np.round(x)))


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------
def build_dates() -> pd.DatetimeIndex:
    """N_DAYS consecutive days ending on END_DATE; day index t = position (0..N_DAYS-1)."""
    return pd.date_range(end=END_DATE, periods=N_DAYS, freq="D")


def build_skus() -> pd.DataFrame:
    """SKU master with margin_pct = (price - cogs) / price as a fraction (4 dp)."""
    df = pd.DataFrame(SKU_ROWS, columns=["sku_id", "name", "category", "price", "cogs", "rating", "organic_per_day"])
    df["margin_pct"] = ((df["price"] - df["cogs"]) / df["price"]).round(4)
    return df


def build_campaigns(skus: pd.DataFrame) -> pd.DataFrame:
    """Campaign table with campaign_name = "<Channel> · <SKU name> · <audience>"."""
    df = pd.DataFrame(
        CAMPAIGN_ROWS,
        columns=["campaign_id", "channel", "sku_id", "audience", "daily_budget", "sat_mult", "format"],
    )
    names = skus.set_index("sku_id")["name"]
    df["campaign_name"] = [f"{c.title()} · {names[s]} · {a}" for c, s, a in zip(df["channel"], df["sku_id"], df["audience"])]
    return df.sort_values("campaign_id", kind="stable").reset_index(drop=True)


def build_prices(dates: pd.DatetimeIndex, skus: pd.DataFrame) -> dict[str, np.ndarray]:
    """Selling price per SKU per day: list price, except SKU-D at S6_NEW_PRICE from S6_START (EV-2)."""
    prices = {}
    for sku_id, list_price in zip(skus["sku_id"], skus["price"]):
        p = np.full(len(dates), float(list_price))
        if sku_id == S6_SKU:
            p[S6_START:] = S6_NEW_PRICE
        prices[sku_id] = p
    return prices


def calendar_multipliers(dates: pd.DatetimeIndex) -> tuple[np.ndarray, np.ndarray]:
    """(weekday, sale) multiplier arrays: weekends × WEEKEND_MULT, sale days × SALE_MULT."""
    weekday = np.where(dates.dayofweek >= 5, WEEKEND_MULT, 1.0)
    year = pd.Timestamp(END_DATE).year
    sale_dates = {pd.Timestamp(year=year, month=m, day=d) for m, d in SALE_DAYS}
    sale = np.array([SALE_MULT if d in sale_dates else 1.0 for d in dates])
    return weekday, sale


def simulate_campaigns(
    rng: np.random.Generator,
    dates: pd.DatetimeIndex,
    skus: pd.DataFrame,
    campaigns: pd.DataFrame,
    prices: dict[str, np.ndarray],
    weekday: np.ndarray,
    sale: np.ndarray,
) -> pd.DataFrame:
    """Simulate every campaign × day (campaigns in ID order, then days in order).

    Returns one row per campaign-day with ad-platform fields plus true `orders` and `price`.
    """
    sku = skus.set_index("sku_id")
    weeks = dates.to_period("W")
    rows = []
    for c in campaigns.itertuples(index=False):
        sat = c.daily_budget * c.sat_mult
        list_price = float(sku.at[c.sku_id, "price"])
        rating = float(sku.at[c.sku_id, "rating"])
        week_mult: dict = {}
        for t, date in enumerate(dates):
            if t < TEST_PERIOD_END:
                if weeks[t] not in week_mult:
                    week_mult[weeks[t]] = rng.uniform(*TEST_MULT_RANGE)
                m = week_mult[weeks[t]]
            else:
                m = 1.0
            spend = c.daily_budget * m * rng.uniform(*SPEND_NOISE)

            cpm = CPM[c.channel] * rng.uniform(*CPM_NOISE)
            if c.channel == S3_CHANNEL and t >= S3_START:
                cpm *= S3_CPM_MULT
            impressions = spend / cpm * 1000

            ctr = CTR[c.channel] * 2 * sat / (sat + spend)
            k = 0.0
            if c.campaign_id == S1_CAMPAIGN and t >= S1_START:
                k = (t - S1_START) / max(1, (T - 1) - S1_START)
                ctr *= 1 - S1_CTR_DROP * k
            if c.campaign_id == S7_CAMPAIGN and t >= S7_START:
                ctr *= S7_CTR_MULT
            clicks = int(rng.poisson(impressions * ctr * rng.uniform(*CLICK_NOISE)))

            price_t = float(prices[c.sku_id][t])
            cvr = (
                CVR_AUD[c.audience] * CH_CVR[c.channel] * CVR_SCALE * (rating / RATING_REF)
                * weekday[t] * sale[t] * (price_t / list_price) ** ELASTICITY
            )
            orders = int(rng.binomial(clicks, min(cvr, MAX_CVR)))

            platform_conversions = round(orders * OVERLAP[c.channel] * rng.uniform(*OVERLAP_NOISE), 2)
            platform_revenue = round(platform_conversions * price_t, 2)

            noise = rng.normal(0, FREQ_SD)
            if c.campaign_id == S1_CAMPAIGN and t >= S1_START:
                frequency = S1_FREQ_FROM + (S1_FREQ_TO - S1_FREQ_FROM) * k + noise
            else:
                frequency = FREQ_BASE + noise

            num = c.campaign_id.split("-")[1]
            creative_id = S7_CREATIVE if (c.campaign_id == S7_CAMPAIGN and t >= S7_START) else f"CR-{num}a"

            rows.append({
                "date": date.strftime("%Y-%m-%d"),
                "channel": c.channel,
                "campaign_id": c.campaign_id,
                "sku_id": c.sku_id,
                "audience": c.audience,
                "creative_id": creative_id,
                "spend": round(spend, 2),
                "impressions": _r(impressions),
                "clicks": clicks,
                "frequency": round(max(frequency, 0.0), 2),
                "platform_conversions": max(platform_conversions, 0.0),
                "platform_revenue": max(platform_revenue, 0.0),
                "orders": orders,
                "price": price_t,
            })
    return pd.DataFrame(rows)


def build_orders(
    rng: np.random.Generator,
    dates: pd.DatetimeIndex,
    skus: pd.DataFrame,
    sim: pd.DataFrame,
    prices: dict[str, np.ndarray],
    weekday: np.ndarray,
    sale: np.ndarray,
) -> pd.DataFrame:
    """Per SKU per day: paid orders (sum of true campaign orders) + Poisson organic orders, units, revenue."""
    paid = sim.groupby(["sku_id", "date"])["orders"].sum()
    rows = []
    for s in skus.itertuples(index=False):
        for t, date in enumerate(dates):
            d = date.strftime("%Y-%m-%d")
            price_t = float(prices[s.sku_id][t])
            lam = s.organic_per_day * weekday[t] * sale[t] * (price_t / s.price) ** ELASTICITY
            organic = int(rng.poisson(lam))
            orders_paid = int(paid.get((s.sku_id, d), 0))
            units = orders_paid + organic
            rows.append({
                "date": d, "sku_id": s.sku_id, "orders_paid": orders_paid, "orders_organic": organic,
                "unit_price": round(price_t, 2), "units": units, "revenue": round(units * price_t, 2),
            })
    return pd.DataFrame(rows)


def build_inventory(dates: pd.DatetimeIndex, skus: pd.DataFrame, orders: pd.DataFrame) -> pd.DataFrame:
    """On-hand stock = target days of cover × trailing 7-day average units; inbound = 10 days of demand.

    SKU-B's cover collapses to ~5 days (S2, no inbound after t = 60); SKU-E is overstocked.
    """
    rows = []
    n = len(dates)
    for idx, s in enumerate(skus.itertuples(index=False)):
        units = orders[orders["sku_id"] == s.sku_id].sort_values("date")["units"].to_numpy(dtype=float)
        units_7d = pd.Series(units).rolling(7, min_periods=1).mean().to_numpy()
        for t, date in enumerate(dates):
            if s.sku_id == S2_SKU:
                if t < S2_DECLINE_START:
                    target = S2_COVER
                else:
                    frac = (t - S2_DECLINE_START) / max(1, (n - 1) - S2_DECLINE_START)
                    target = S2_COVER + (S2_END_COVER - S2_COVER) * frac
            elif s.sku_id == OVERSTOCK_SKU:
                target = OVERSTOCK_FROM + (OVERSTOCK_TO - OVERSTOCK_FROM) * t / max(1, n - 1)
            else:
                target = COVER_BASE + COVER_AMP * math.sin(2 * math.pi * t / COVER_PERIOD + idx * COVER_PHASE_STEP)
            inbound = 0 if (s.sku_id == S2_SKU and t >= S2_DECLINE_START) else _r(INBOUND_DAYS * units_7d[t])
            rows.append({
                "date": date.strftime("%Y-%m-%d"), "sku_id": s.sku_id,
                "on_hand": _r(target * units_7d[t]), "inbound": inbound,
            })
    return pd.DataFrame(rows)


def build_pricing(dates: pd.DatetimeIndex, skus: pd.DataFrame, prices: dict[str, np.ndarray]) -> pd.DataFrame:
    """Price, list price and a deterministic competitor price wave per SKU per day."""
    rows = []
    for s in skus.itertuples(index=False):
        for t, date in enumerate(dates):
            comp = s.price * (COMPETITOR_BASE + COMPETITOR_AMP * math.sin(t / COMPETITOR_PERIOD))
            rows.append({
                "date": date.strftime("%Y-%m-%d"), "sku_id": s.sku_id, "price": round(float(prices[s.sku_id][t]), 2),
                "list_price": round(float(s.price), 2), "competitor_price": round(comp, 2),
            })
    return pd.DataFrame(rows)


def build_ga(sim: pd.DataFrame, orders: pd.DataFrame) -> pd.DataFrame:
    """GA4 funnel per SKU per day derived from paid clicks, organic orders and units."""
    paid_clicks = sim.groupby(["sku_id", "date"])["clicks"].sum()
    rows = []
    for o in orders.itertuples(index=False):
        clicks = int(paid_clicks.get((o.sku_id, o.date), 0))
        sessions = _r(clicks * SESSIONS_PER_PAID_CLICK + o.orders_organic * SESSIONS_PER_ORGANIC_ORDER)
        purchases = int(o.units)
        checkout = _r(purchases / CHECKOUT_TO_PURCHASE)
        add_to_cart = _r(checkout / CART_TO_CHECKOUT)
        pdp_views = max(_r(sessions * PDP_PER_SESSION), add_to_cart)
        rows.append({
            "date": o.date, "sku_id": o.sku_id, "sessions": sessions, "pdp_views": pdp_views,
            "add_to_cart": add_to_cart, "checkout": checkout, "purchases": purchases,
        })
    return pd.DataFrame(rows)


def build_creatives(dates: pd.DatetimeIndex, campaigns: pd.DataFrame) -> pd.DataFrame:
    """One CR-NNa creative per campaign, plus the S7 UGC creative CR-10b."""
    first = dates[0].strftime("%Y-%m-%d")
    rows = [
        {"creative_id": f"CR-{c.campaign_id.split('-')[1]}a", "campaign_id": c.campaign_id, "format": c.format,
         "hook": "product_demo", "ugc": False, "launch_date": first}
        for c in campaigns.itertuples(index=False)
    ]
    rows.append({"creative_id": S7_CREATIVE, "campaign_id": S7_CAMPAIGN, "format": "video",
                 "hook": "ugc_testimonial", "ugc": True, "launch_date": dates[S7_START].strftime("%Y-%m-%d")})
    return pd.DataFrame(rows)


def build_events(dates: pd.DatetimeIndex) -> pd.DataFrame:
    """Business events log (EV-1 only if the sale falls inside the date range)."""
    rows = []
    year = pd.Timestamp(END_DATE).year
    sale_start = pd.Timestamp(year=year, month=SALE_DAYS[0][0], day=SALE_DAYS[0][1])
    if dates[0] <= sale_start <= dates[-1]:
        rows.append({"event_id": "EV-1", "date": sale_start.strftime("%Y-%m-%d"), "type": "sale", "entity": "all",
                     "description": "Independence Day sale (3 days)"})
    rows.append({"event_id": "EV-2", "date": dates[S6_START].strftime("%Y-%m-%d"), "type": "price_change",
                 "entity": S6_SKU, "description": "Casual X price raised ₹1,999 → ₹2,299"})
    rows.append({"event_id": "EV-3", "date": dates[S3_START].strftime("%Y-%m-%d"), "type": "competitor",
                 "entity": S3_CHANNEL, "description": "Competitor sale drives Google auction prices up"})
    rows.append({"event_id": "EV-4", "date": dates[S7_START].strftime("%Y-%m-%d"), "type": "creative_launch",
                 "entity": S7_CAMPAIGN, "description": "UGC testimonial creative CR-10b launched on TikTok"})
    return pd.DataFrame(rows, columns=["event_id", "date", "type", "entity", "description"])


def build_ground_truth() -> dict:
    """Answer key for the 8 planted scenarios."""
    return {
        "S1": {"type": "creative_fatigue", "campaign": S1_CAMPAIGN},
        "S2": {"type": "stockout_risk", "sku": S2_SKU},
        "S3": {"type": "cpc_spike", "channel": S3_CHANNEL},
        "S4": {"type": "underfunded", "campaigns": ["CMP-06", "CMP-07"]},
        "S5": {"type": "double_counting", "channels": {"meta": OVERLAP["meta"], "google": OVERLAP["google"]}},
        "S6": {"type": "price_change", "sku": S6_SKU, "event": "EV-2", "elasticity": ELASTICITY},
        "S7": {"type": "positive_spike", "campaign": S7_CAMPAIGN},
        "S8": {"type": "opportunity", "note": "unfunded combos scored before any spend"},
    }


AD_COLUMNS = ["date", "channel", "campaign_id", "sku_id", "audience", "creative_id", "spend", "impressions",
              "clicks", "frequency", "platform_conversions", "platform_revenue"]


def write_outputs(raw_dir: Path, frames: dict[str, pd.DataFrame], ground_truth: dict) -> int:
    """Write every CSV (index=False, fixed column order) and ground_truth.json. Returns file count."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    for name, df in frames.items():
        num = df.select_dtypes("number")
        assert (num >= 0).all().all(), f"{name} contains negative values"
        df.to_csv(raw_dir / name, index=False, lineterminator="\n")
    with open(raw_dir / "ground_truth.json", "w", encoding="utf-8", newline="\n") as f:
        json.dump(ground_truth, f, indent=2, sort_keys=False, ensure_ascii=False)
        f.write("\n")
    return len(frames) + 1


def main() -> None:
    """Generate all datasets and write them into RAW_DIR."""
    rng = np.random.default_rng(SEED)
    dates = build_dates()
    skus = build_skus()
    campaigns = build_campaigns(skus)
    prices = build_prices(dates, skus)
    weekday, sale = calendar_multipliers(dates)

    sim = simulate_campaigns(rng, dates, skus, campaigns, prices, weekday, sale)
    orders = build_orders(rng, dates, skus, sim, prices, weekday, sale)
    inventory = build_inventory(dates, skus, orders)
    pricing = build_pricing(dates, skus, prices)
    ga = build_ga(sim, orders)
    creatives = build_creatives(dates, campaigns)
    events = build_events(dates)

    frames = {
        "ad_performance.csv": sim[AD_COLUMNS],  # no true orders here: truth lives only in store files
        "store_orders_by_utm.csv": sim[["date", "campaign_id", "orders"]],
        "orders.csv": orders,
        "inventory.csv": inventory,
        "pricing.csv": pricing,
        "ga_events.csv": ga,
        "sku_master.csv": skus,
        "campaigns.csv": campaigns,
        "creatives.csv": creatives,
        "events.csv": events,
    }
    n_files = write_outputs(Path(RAW_DIR), frames, build_ground_truth())

    spend_per_day = sim["spend"].sum() / N_DAYS
    print(f"M1 OK · {N_DAYS} days to {END_DATE} · {len(campaigns)} campaigns · {len(skus)} SKUs · "
          f"spend {format_inr(spend_per_day)}/day · {n_files} files written")


if __name__ == "__main__":
    main()
