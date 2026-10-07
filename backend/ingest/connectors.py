"""M2 connector layer: one interface for every data source.

Every connector returns normalised rows from `fetch()`, so swapping the CSV stand-ins for the
real APIs later changes nothing downstream.

| Connector source  | Stands in for                                        |
|-------------------|------------------------------------------------------|
| meta_ads          | Meta Marketing API (Insights)                        |
| google_ads        | Google Ads API (GAQL; cost_micros ÷ 1,000,000)       |
| amazon_ads        | Amazon Ads API (Sponsored Products reports)          |
| tiktok_ads        | TikTok Marketing API                                 |
| programmatic_ads  | DSP reporting API (e.g. DV360)                       |
| shopify_orders    | Shopify Admin API (Orders)                           |
| shopify_utm       | Shopify Admin API (Orders + UTM params)               |
| ga4               | GA4 Data API                                         |
| erp_inventory     | ERP / Shopify Inventory API                          |
| pricing           | Store catalogue + competitor price feed              |
| sku_master, campaigns, creatives, events | Internal catalogue / ad-account metadata |
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from backend.core import config
from backend.core.config import CHANNELS

# Columns normalised to a type on every fetch (only applied when present).
DATE_COLUMNS = ("date", "launch_date")
COUNT_COLUMNS = (
    "impressions", "clicks", "orders", "orders_paid", "orders_organic", "units", "on_hand", "inbound",
    "sessions", "pdp_views", "add_to_cart", "checkout", "purchases", "organic_per_day",
)
MONEY_COLUMNS = (
    "spend", "platform_revenue", "unit_price", "revenue", "price", "list_price", "competitor_price",
    "cogs", "daily_budget",
)
FLOAT_COLUMNS = ("frequency", "platform_conversions", "margin_pct", "rating", "sat_mult")
BOOL_COLUMNS = ("ugc",)
LOWERCASE_COLUMNS = ("channel", "audience", "format", "type")
TIMEZONE = "Asia/Kolkata"  # all dates are IST calendar days


def normalise(df: pd.DataFrame) -> pd.DataFrame:
    """Apply the M2 normalisation rules to any source frame.

    Dates → "YYYY-MM-DD" (IST calendar day), money → float ₹, counts → int, strings stripped,
    channel/audience/format/type lowercase. IDs (CMP-NN, SKU-X, CR-NNx, EV-N) are kept as-is.
    """
    df = df.copy()
    for col in df.columns:
        if df[col].dtype == object:
            df[col] = df[col].astype(str).str.strip()
    for col in DATE_COLUMNS:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col]).dt.strftime("%Y-%m-%d")
    for col in LOWERCASE_COLUMNS:
        if col in df.columns:
            df[col] = df[col].str.lower()
    for col in COUNT_COLUMNS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col]).fillna(0).round().astype("int64")
    for col in (*MONEY_COLUMNS, *FLOAT_COLUMNS):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col]).astype("float64")
    for col in BOOL_COLUMNS:
        if col in df.columns:
            df[col] = df[col].astype(str).str.lower().isin(("true", "1", "yes"))
    return df


class BaseConnector:
    """Common interface: `fetch()` returns normalised rows for one source.

    | source | real API |
    |---|---|
    | base | (abstract) |
    """

    source = "base"

    def fetch(self) -> pd.DataFrame:
        raise NotImplementedError


class CsvConnector(BaseConnector):
    """Reads a file M1 wrote into RAW_DIR; optionally filters to one ad channel.

    | source | real API this stands in for |
    |---|---|
    | meta_ads | Meta Marketing API (Insights) |
    | google_ads | Google Ads API (GAQL; cost_micros ÷ 1,000,000) |
    | amazon_ads | Amazon Ads API (Sponsored Products reports) |
    | tiktok_ads | TikTok Marketing API |
    | programmatic_ads | DSP reporting API (e.g. DV360) |
    | shopify_orders / shopify_utm | Shopify Admin API (Orders + UTM params) |
    | ga4 | GA4 Data API |
    | erp_inventory | ERP / Shopify Inventory API |
    | pricing | store catalogue + competitor price feed |
    """

    def __init__(self, source: str, filename: str, channel: str | None = None):
        if channel is not None and channel not in CHANNELS:
            raise ValueError(f"Unknown channel {channel!r}; expected one of {CHANNELS}")
        self.source = source
        self.filename = filename
        self.channel = channel

    @property
    def path(self) -> Path:
        # RAW_DIR is read at call time so tests can point it at a temp folder.
        return Path(config.RAW_DIR) / self.filename

    def fetch(self) -> pd.DataFrame:
        if not self.path.exists():
            raise FileNotFoundError(
                f"{self.source}: missing {self.path}. Run `python -m backend.generator.generate` first."
            )
        df = normalise(pd.read_csv(self.path))
        if self.channel is not None:
            df = df[df["channel"] == self.channel].reset_index(drop=True)
        return df

    def __repr__(self) -> str:
        return f"CsvConnector({self.source!r}, {self.filename!r}, channel={self.channel!r})"


AD_CONNECTORS = [CsvConnector(f"{ch}_ads", "ad_performance.csv", ch) for ch in CHANNELS]
STORE = CsvConnector("shopify_orders", "orders.csv")
UTM = CsvConnector("shopify_utm", "store_orders_by_utm.csv")
ERP = CsvConnector("erp_inventory", "inventory.csv")
PRICING = CsvConnector("pricing", "pricing.csv")
GA4 = CsvConnector("ga4", "ga_events.csv")
DIM_SKU = CsvConnector("sku_master", "sku_master.csv")
DIM_CAMPAIGN = CsvConnector("campaigns", "campaigns.csv")
DIM_CREATIVE = CsvConnector("creatives", "creatives.csv")
EVENTS = CsvConnector("events", "events.csv")

# Connector source → brain_manifest.json source id (the data-stream node it lights up).
SOURCE_MAP = {
    "meta_ads": "meta_ads",
    "google_ads": "google_ads",
    "amazon_ads": "amazon_ads",
    "tiktok_ads": "tiktok_ads",
    "programmatic_ads": "programmatic",
    "shopify_orders": "store",
    "shopify_utm": "store",
    "erp_inventory": "inventory",
    "ga4": "ga4",
    "pricing": "pricing",
}
