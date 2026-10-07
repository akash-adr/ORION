"""M6 mock ad-platform API. Same call shapes as the real APIs, so swapping in real clients changes only this class.

Every method returns a dict and NEVER touches the network. Timestamps are "YYYY-MM-DDTHH:MM:SS" (IST); a clock can
be injected so tests are deterministic.

  update_budget          Meta Marketing API (adset daily_budget) · Google Ads API (CampaignBudgetService mutate,
                         amount_micros = ₹ × 1,000,000) · Amazon Ads (campaign budget) · TikTok (adgroup budget) · DSP
  create_test_campaign   the same platforms' campaign-create endpoints
  set_conversion_source  Meta Conversions API (CAPI) · Google Ads enhanced conversions · TikTok Events API
  pause_test_campaign    campaign status update (PAUSED), used to roll back a launch test
  rotate_creative        creative / ad-group creative rotation (queued for the platform's review)
"""
from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Callable
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
TS_FORMAT = "%Y-%m-%dT%H:%M:%S"


class MockAdsAPI:
    """Pretends to be every ad platform. `clock` is a zero-argument callable returning a datetime."""

    def __init__(self, clock: Callable[[], datetime] | None = None):
        self._clock = clock or (lambda: datetime.now(IST))

    def _ts(self) -> str:
        return self._clock().strftime(TS_FORMAT)

    def update_budget(self, campaign_id: str, channel: str, daily_budget: float) -> dict:
        """Set a campaign's daily budget (₹/day)."""
        return {"platform": channel, "endpoint": f"/{channel}/campaigns/{campaign_id}/budget", "method": "POST",
                "daily_budget": round(daily_budget, 2), "status": "OK", "ts": self._ts()}

    def create_test_campaign(self, sku_id: str, channel: str, audience: str, daily_budget: float) -> dict:
        """Create a small test campaign; the id is deterministic so a replay finds the same campaign."""
        cid = "TST-" + hashlib.md5(f"{sku_id}|{channel}|{audience}".encode()).hexdigest()[:6]
        return {"platform": channel, "endpoint": f"/{channel}/campaigns", "method": "POST", "campaign_id": cid,
                "daily_budget": round(daily_budget, 2), "status": "OK", "ts": self._ts()}

    def set_conversion_source(self, channel: str, source: str) -> dict:
        """Choose where the platform learns about conversions: "server_side" (store-verified) or "platform"."""
        return {"platform": channel, "endpoint": f"/{channel}/conversions/settings", "method": "POST",
                "conversion_source": source, "status": "OK", "ts": self._ts()}

    def pause_test_campaign(self, test_campaign_id: str, channel: str) -> dict:
        """Pause a launched test campaign (the rollback of a launch)."""
        return {"platform": channel, "endpoint": f"/{channel}/campaigns/{test_campaign_id}/pause", "method": "POST",
                "campaign_id": test_campaign_id, "status": "PAUSED", "ts": self._ts()}

    def rotate_creative(self, campaign_id: str, channel: str, suggested: str) -> dict:
        """Queue a creative rotation for a campaign."""
        return {"platform": channel, "endpoint": f"/{channel}/campaigns/{campaign_id}/creatives", "method": "POST",
                "campaign_id": campaign_id, "suggested": suggested, "status": "QUEUED", "ts": self._ts()}
