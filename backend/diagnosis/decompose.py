"""M4 root-cause diagnosis: the "thinking" step inside the Neural Brain's Diagnose lobe.

Run from the project root:  python -m backend.diagnosis.decompose

For every M3 anomaly this explains WHY it happened: it splits the ₹/day profit change into exact causes
(the waterfall), drills down to the responsible campaign or funnel step and writes a plain-English
narrative. Output is the M0 `RootCause` shape.

The metric tree (all values are DAILY AVERAGES over each window, ratios are Σnumerator ÷ Σdenominator):

  campaign / channel   Orders = Spend ÷ CPM × 1000 × CTR × CVR      drivers: Spend, CPM, CTR, CVR, Unit margin
                       GM = Orders × Unit margin;  Profit = GM − Spend
  SKU                  Units = Sessions × Site CVR                   drivers: Sessions, Site CVR, Unit margin
                       GM = Units × Unit margin

Because the drivers MULTIPLY, plain subtraction cannot split a change between them (the cross terms have
no owner), so the split uses LMDI (Log-Mean Divisia Index), which is exact: Σ contributions = ΔGM.
There is never an "other / unexplained" factor. Each anomaly is analysed over its own detail["window"],
so M4 examines exactly what M3 detected. Narratives are templates (no LLM): always correct, instant.
"""
from __future__ import annotations

import math
import time

import pandas as pd

from backend.core import metrics as m
from backend.core.config import CHANNEL_DISPLAY
from backend.core.db import read_table
from backend.core.schema import Anomaly, Factor, RootCause

# ---------------------------------------------------------------------------
# Fixed factor names: a contract with the UI (use these exact strings)
# ---------------------------------------------------------------------------
BUDGET, AUCTION, CREATIVE, CONVERSION, MARGIN = (
    "Budget change", "Auction cost (CPM/CPC)", "Click-through / creative", "Conversion rate", "Price / unit margin")
TRAFFIC, SITE_CVR = "Traffic (sessions)", "Site conversion rate"
FACTOR_NAMES = {
    "spend": BUDGET, "cpm": AUCTION, "ctr": CREATIVE, "cvr": CONVERSION, "unit_margin": MARGIN,
    "sessions": TRAFFIC, "site_cvr": SITE_CVR,
}
FACTOR_ORDER = {  # fixed display order per level
    "campaign": [BUDGET, AUCTION, CREATIVE, CONVERSION, MARGIN],
    "sku": [TRAFFIC, SITE_CVR, MARGIN],
}
CAMPAIGN_DRIVERS = ["spend", "cpm", "ctr", "cvr", "unit_margin"]
SKU_DRIVERS = ["sessions", "site_cvr", "unit_margin"]
SIGNS = {"cpm": -1.0}  # a higher auction cost lowers margin; every other driver is +1
FUNNEL_STAGES = ["sessions", "pdp_views", "add_to_cart", "checkout", "purchases"]

SUM_TOL = 0.01  # ₹: LMDI contributions must add up to ΔGM within this, else the fallback split is used
OFFSET_SHARE = 0.20  # an opposite factor above 20% of the main factor gets an "offset" sentence
FUNNEL_MATERIAL = 0.01  # a funnel step must fall by more than 1% to be called out in the CLI insight
MINUS = "−"


# ---------------------------------------------------------------------------
# Data access
# ---------------------------------------------------------------------------
class Tables:
    """The SQLite tables M4 reads, loaded once per run."""

    def __init__(self) -> None:
        self.fact = read_table("fact_daily")
        self.sku = read_table("sku_daily")
        self.campaigns = read_table("dim_campaign")
        self.creatives = read_table("dim_creative")
        self.events = read_table("events")


def _window_frame(df: pd.DataFrame, start: str, end: str) -> pd.DataFrame:
    """Rows whose date lies in [start, end] (ISO date strings sort correctly)."""
    return df[(df["date"] >= start) & (df["date"] <= end)]


def _days(start: str, end: str) -> int:
    """Calendar days in [start, end]."""
    return (pd.Timestamp(end) - pd.Timestamp(start)).days + 1


# ---------------------------------------------------------------------------
# Per-window driver values (daily averages, Σ-ratios)
# ---------------------------------------------------------------------------
def _campaign_parts(frame: pd.DataFrame, days: int) -> dict:
    """spend, cpm, ctr, cvr, unit_margin, gm, profit for a campaign (or Σ across a channel's campaigns)."""
    spend, impressions = float(frame["spend"].sum()), float(frame["impressions"].sum())
    clicks, orders, gm = float(frame["clicks"].sum()), float(frame["orders"].sum()), float(frame["gross_margin"].sum())
    unit_margin = gm / orders if orders > 0 else (float((frame["price"] - frame["cogs"]).mean()) if len(frame) else 0.0)
    parts = {
        "spend": spend / days,
        "cpm": m.safe_div(spend, impressions) * 1000.0 if impressions > 0 else 0.0,
        "ctr": m.safe_div(clicks, impressions) or 0.0,
        "cvr": m.safe_div(orders, clicks) or 0.0,
        "unit_margin": unit_margin,
        "gm": gm / days,
    }
    parts["profit"] = parts["gm"] - parts["spend"]
    return parts


def _sku_parts(frame: pd.DataFrame, days: int) -> dict:
    """sessions, site_cvr, unit_margin, gm for a SKU (unit margin weighted by units)."""
    margin = frame["unit_price"] - frame["cogs"]
    units, sessions = float(frame["units"].sum()), float(frame["sessions"].sum())
    gm = float((frame["units"] * margin).sum())
    return {
        "sessions": sessions / days,
        "site_cvr": units / sessions if sessions > 0 else 0.0,
        "unit_margin": gm / units if units > 0 else (float(margin.mean()) if len(frame) else 0.0),
        "gm": gm / days,
    }


# ---------------------------------------------------------------------------
# LMDI
# ---------------------------------------------------------------------------
def _equal_split(gm0: float, gm1: float, drivers: list[str]) -> dict:
    return {d: (gm1 - gm0) / len(drivers) for d in drivers}


def _lmdi(gm0: float, gm1: float, drivers0: dict, drivers1: dict, signs: dict) -> dict:
    """Log-Mean Divisia Index split of ΔGM = gm1 − gm0 over the drivers (exact: Σ = ΔGM).

    gm0, gm1 > 0 and different:  L = (gm1 − gm0) ÷ (ln gm1 − ln gm0);
                                 contribution[d] = L × sign[d] × ln(drivers1[d] ÷ drivers0[d]).
    gm0 == gm1:                  every contribution is 0.
    gm ≤ 0 in either window (the log is undefined): FALLBACK, ΔGM is split equally across the drivers.
    A driver ≤ 0 in either window contributes 0 and nothing is re-distributed; if the sum check then
    fails (|Σ − ΔGM| > ₹0.01) the equal-split fallback is used instead.
    """
    names = list(drivers0)
    if gm0 == gm1:
        return {d: 0.0 for d in names}
    if gm0 <= 0 or gm1 <= 0:
        return _equal_split(gm0, gm1, names)
    log_mean = (gm1 - gm0) / (math.log(gm1) - math.log(gm0))
    out = {}
    for d in names:
        v0, v1 = drivers0[d], drivers1[d]
        out[d] = log_mean * signs.get(d, 1.0) * math.log(v1 / v0) if v0 > 0 and v1 > 0 else 0.0
    if abs(sum(out.values()) - (gm1 - gm0)) > SUM_TOL:
        return _equal_split(gm0, gm1, names)
    return out


def _finish(impacts: dict[str, float], level: str, total_change: float) -> list[Factor]:
    """Round to 2 dp (residue onto the largest factor so the bars sum exactly), set pct, fix the order."""
    names = FACTOR_ORDER[level]
    rounded = {n: round(impacts[n], 2) for n in names}
    residue = round(round(total_change, 2) - sum(rounded.values()), 2)
    if residue:
        biggest = max(names, key=lambda n: abs(rounded[n]))
        rounded[biggest] = round(rounded[biggest] + residue, 2)
    total_abs = sum(abs(v) for v in rounded.values())
    return [Factor(n, rounded[n], round(abs(rounded[n]) / total_abs, 4) if total_abs else 0.0) for n in names]


def _decompose_campaign_frame(recent: pd.DataFrame, base: pd.DataFrame, days_recent: int | None = None,
                              days_base: int | None = None) -> tuple[list[Factor], float, dict, dict]:
    """Waterfall of Δprofit/day for a campaign or channel frame. Returns (factors, total_change, parts0, parts1).

    "Budget change" = contribution(Spend) − (spend1 − spend0): the volume gained minus the extra money spent,
    so Σ factors = (GM1 − spend1) − (GM0 − spend0) = Δprofit/day exactly.
    """
    p0 = _campaign_parts(base, days_base or max(base["date"].nunique(), 1))
    p1 = _campaign_parts(recent, days_recent or max(recent["date"].nunique(), 1))
    c = _lmdi(p0["gm"], p1["gm"], {d: p0[d] for d in CAMPAIGN_DRIVERS}, {d: p1[d] for d in CAMPAIGN_DRIVERS}, SIGNS)
    total = p1["profit"] - p0["profit"]
    impacts = {BUDGET: c["spend"] - (p1["spend"] - p0["spend"]), AUCTION: c["cpm"], CREATIVE: c["ctr"],
               CONVERSION: c["cvr"], MARGIN: c["unit_margin"]}
    return _finish(impacts, "campaign", total), round(total, 2), p0, p1


def _decompose_sku_frame(recent: pd.DataFrame, base: pd.DataFrame, days_recent: int | None = None,
                         days_base: int | None = None) -> tuple[list[Factor], float, dict, dict]:
    """Waterfall of ΔGM/day for a SKU frame (no ad-spend term). Returns (factors, total_change, parts0, parts1)."""
    p0 = _sku_parts(base, days_base or max(base["date"].nunique(), 1))
    p1 = _sku_parts(recent, days_recent or max(recent["date"].nunique(), 1))
    c = _lmdi(p0["gm"], p1["gm"], {d: p0[d] for d in SKU_DRIVERS}, {d: p1[d] for d in SKU_DRIVERS}, {})
    total = p1["gm"] - p0["gm"]
    impacts = {TRAFFIC: c["sessions"], SITE_CVR: c["site_cvr"], MARGIN: c["unit_margin"]}
    return _finish(impacts, "sku", total), round(total, 2), p0, p1


# ---------------------------------------------------------------------------
# Drill-downs
# ---------------------------------------------------------------------------
def _funnel(sku_id: str, sku_daily: pd.DataFrame, recent_win: tuple[str, str], base_win: tuple[str, str]) -> list[dict]:
    """Site funnel for a SKU: sessions → pdp_views → add_to_cart → checkout → purchases.

    Each step's rate = stage ÷ previous stage (Σ-ratios). The step with the biggest negative change is marked
    is_biggest_drop (no step is marked if nothing fell).
    """
    d = sku_daily[sku_daily["sku_id"] == sku_id]
    rec, base = _window_frame(d, *recent_win), _window_frame(d, *base_win)
    nr, nb = _days(*recent_win), _days(*base_win)
    steps = []
    for prev, stage in zip(FUNNEL_STAGES, FUNNEL_STAGES[1:]):
        r_rate, b_rate = m.safe_div(rec[stage].sum(), rec[prev].sum()), m.safe_div(base[stage].sum(), base[prev].sum())
        steps.append({
            "stage": stage, "from": prev,
            "baseline_rate": round(b_rate, 4) if b_rate is not None else None,
            "recent_rate": round(r_rate, 4) if r_rate is not None else None,
            "change_pct": round(m.change_pct(r_rate, b_rate), 4) if m.change_pct(r_rate, b_rate) is not None else None,
            "baseline_count_per_day": round(float(base[stage].sum()) / nb, 2),
            "recent_count_per_day": round(float(rec[stage].sum()) / nr, 2),
            "is_biggest_drop": False,
        })
    falling = [s for s in steps if s["change_pct"] is not None and s["change_pct"] < 0]
    if falling:
        min(falling, key=lambda s: s["change_pct"])["is_biggest_drop"] = True
    return steps


def _top_factor(factors: list[Factor], total_change: float) -> Factor | None:
    """Largest factor IN THE DIRECTION of the total change (never one that contradicts it)."""
    if total_change == 0:
        pool = factors
    else:
        pool = [f for f in factors if f.impact * total_change > 0]
    return max(pool, key=lambda f: abs(f.impact)) if pool and any(f.impact for f in pool) else None


def _channel_drilldown(channel: str, fact: pd.DataFrame, recent_win: tuple[str, str],
                       base_win: tuple[str, str]) -> list[dict]:
    """Per-campaign profit change on a channel, worst first, with each campaign's top factor."""
    ch = fact[fact["channel"] == channel]
    nr, nb = _days(*recent_win), _days(*base_win)
    rows = []
    for cid, g in ch.groupby("campaign_id"):
        rec, base = _window_frame(g, *recent_win), _window_frame(g, *base_win)
        factors, total, p0, p1 = _decompose_campaign_frame(rec, base, nr, nb)
        top = _top_factor(factors, total)
        rows.append({"campaign_id": cid, "campaign_name": g["campaign_name"].iloc[0],
                     "baseline_profit": round(p0["profit"], 2), "recent_profit": round(p1["profit"], 2),
                     "change": total, "top_factor": top.name if top else None})
    return sorted(rows, key=lambda r: (r["change"], r["campaign_id"]))


# ---------------------------------------------------------------------------
# Narrative
# ---------------------------------------------------------------------------
def _pct(x: float) -> str:
    return f"{round(abs(x) * 100):.0f}%"


def _inr(x: float) -> str:
    return m.format_inr(abs(x))


def _price(x: float) -> str:
    return f"₹{x:,.0f}"


def _channel_name(channel: str) -> str:
    return CHANNEL_DISPLAY.get(channel, channel.title())


def _signed_pct(x: float) -> str:
    return f"{'+' if x >= 0 else MINUS}{abs(x) * 100:.0f}%"


def causal_sentence(c: dict) -> str:
    """The synthetic-control sentence appended to a price-driven conversion_drop narrative."""
    r = c["result"]
    return (f"Causal check (synthetic control): units ≈ {_signed_pct(c['units_change_pct'])} vs what would have "
            f"happened anyway; net margin effect {m.format_inr(r.effect_per_day)}/day (95% CI "
            f"{m.format_inr(r.ci_low)} to {m.format_inr(r.ci_high)} over the {c['n_post']} days).")


def lead_sentence(rc: RootCause, kind: str) -> str:
    """The first narrative sentence (headline + largest driver), used as the brain event message."""
    text = rc.narrative
    if "Largest driver:" in text and "/day)." in text:
        return text[: text.index("/day).", text.index("Largest driver:")) + len("/day).")]
    if kind == "attribution_inflation":
        return text
    return text.split(". ")[0].rstrip(".") + "."


def _narrative(a: Anomaly, factors: list[Factor], total: float, label_of: dict[str, str], t: Tables,
               funnel: list[dict], causal: dict | None = None) -> str:
    """Template narrative: general → offset → kind-specific → knock-on. Always consistent with the numbers."""
    d, s = a.detail, []
    by_name = {f.name: f for f in factors}

    if a.kind == "attribution_inflation":
        s.append(f"{_channel_name(a.entity_id)} reports {_pct(d['inflation_pct'])} more conversions than the store "
                 f"recorded. Platform ROAS {d['roas_platform']:.2f} vs true {d['roas_true']:.2f} — optimising on "
                 f"platform numbers would over-fund this channel.")
    else:
        what = "gross margin" if a.entity_type == "sku" else "profit"
        top = _top_factor(factors, total)
        if total == 0 or top is None:
            s.append(f"{a.label}: daily {what} was essentially unchanged.")
        else:
            s.append(f"{a.label}: daily {what} {'rose' if total > 0 else 'fell'} by {_inr(total)}. Largest driver: "
                     f"{top.name} ({_pct(top.pct)} of the movement, {_inr(top.impact)}/day).")
            opposite = [f for f in factors if f.impact * total < 0 and abs(f.impact) > OFFSET_SHARE * abs(top.impact)]
            if opposite:
                off = max(opposite, key=lambda f: abs(f.impact))
                s.append(f"Partly offset by {off.name} ({_inr(off.impact)}/day).")

    if a.kind == "creative_fatigue":
        s.append(f"Frequency rose from {d['frequency_baseline']:.1f} to {d['frequency_recent']:.1f} and click-through "
                 f"fell {_pct(a.change_pct)} — the audience has seen this creative too often.")
    elif a.kind == "positive_spike" and d.get("new_creative"):
        win = d["window"]
        new = t.creatives[(t.creatives["campaign_id"] == a.entity_id)
                          & t.creatives["launch_date"].between(win["recent_start"], win["recent_end"])]
        cid = new["creative_id"].iloc[0] if len(new) else d["creative_ids_recent"][-1]
        if d.get("ctr_change", 0) > 0:
            s.append(f"A new creative ({cid}) launched in this window and lifted click-through by {_pct(d['ctr_change'])}.")
        else:
            s.append(f"A new creative ({cid}) launched in this window.")
    elif a.kind == "cpc_spike":
        worst = funnel[0]["campaign_name"] if funnel else None
        line = f"Clicks got {_pct(a.change_pct)} more expensive across {len(d['campaigns'])} {_channel_name(a.entity_id)} campaigns"
        s.append(line + (f"; hardest hit: {worst}." if worst else "."))
        win = d["window"]
        ev = t.events[(t.events["type"] == "competitor") & (t.events["entity"] == a.entity_id)
                      & t.events["date"].between(win["recent_start"], win["recent_end"])]
        if len(ev):
            s.append(f"Likely cause: {ev['description'].iloc[0]} ({ev['event_id'].iloc[0]}).")
    elif a.kind == "stockout_risk":
        stock = "no inbound shipment" if d.get("inbound", 0) == 0 else None
        s.append(f"Only {d['days_cover']:.1f} days of stock left{' with ' + stock if stock else ''}, while "
                 f"{_inr(d['spend_per_day'])}/day of ads still drive demand — {_inr(a.profit_impact)}/day of margin is at risk.")
    elif a.kind == "conversion_drop":
        moved = d.get("price_change", 0) != 0
        if moved:
            ev_txt = f" ({d['event_id']})" if d.get("event_id") else ""
            sent = (f"Site conversion fell {_pct(a.change_pct)} after the price moved from {_price(d['price_start'])} "
                    f"to {_price(d['price_end'])}{ev_txt}.")
            volume = by_name[TRAFFIC].impact + by_name[SITE_CVR].impact
            lost = -volume if volume < 0 else None
            gained = by_name[MARGIN].impact if by_name[MARGIN].impact > 0 else None
            if lost is not None or gained is not None:
                parts = []
                if lost is not None:
                    parts.append(f"volume lost {_inr(lost)}/day")
                if gained is not None:
                    parts.append(f"margin gained {_inr(gained)}/day")
                sent += " The price rise traded customers for margin: " + ", ".join(parts) + "."
            s.append(sent)
            if d.get("event_id"):
                s.append("See causal analysis for proof.")
                if causal and d["event_id"] in causal:
                    s.append(causal_sentence(causal[d["event_id"]]))
        else:
            s.append(f"Site conversion fell {_pct(a.change_pct)} with no price change.")

    related = d.get("related", [])
    if related:
        names = [label_of.get(k, k) for k in related]
        s.append(f"Linked to: {' and '.join(names)}.")
        if a.kind == "conversion_drop" and any(k.startswith("positive_spike:") for k in related):
            s.append("The viral traffic is colder and converts worse — scale carefully.")
    return " ".join(s)


# ---------------------------------------------------------------------------
# diagnose
# ---------------------------------------------------------------------------
def _windows(a: Anomaly) -> tuple[tuple[str, str], tuple[str, str]]:
    w = a.detail["window"]
    return (w["recent_start"], w["recent_end"]), (w["baseline_start"], w["baseline_end"])


def _diagnose(a: Anomaly, t: Tables, label_of: dict[str, str], causal: dict | None = None) -> RootCause:
    if a.kind == "attribution_inflation":  # a data issue: narrative only, no window to decompose
        return RootCause(a.id, a.entity_id, 0.0, [], [], _narrative(a, [], 0.0, label_of, t, []))
    recent_win, base_win = _windows(a)
    nr, nb = _days(*recent_win), _days(*base_win)
    if a.entity_type == "sku":
        d = t.sku[t.sku["sku_id"] == a.entity_id]
        factors, total, _, _ = _decompose_sku_frame(_window_frame(d, *recent_win), _window_frame(d, *base_win), nr, nb)
        funnel = _funnel(a.entity_id, t.sku, recent_win, base_win)
    elif a.entity_type == "channel":  # cpc_spike: Σ across the channel's campaigns
        d = t.fact[t.fact["channel"] == a.entity_id]
        factors, total, _, _ = _decompose_campaign_frame(_window_frame(d, *recent_win), _window_frame(d, *base_win), nr, nb)
        funnel = _channel_drilldown(a.entity_id, t.fact, recent_win, base_win)
    else:
        d = t.fact[t.fact["campaign_id"] == a.entity_id]
        factors, total, _, _ = _decompose_campaign_frame(_window_frame(d, *recent_win), _window_frame(d, *base_win), nr, nb)
        funnel = _funnel(d["sku_id"].iloc[0], t.sku, recent_win, base_win)
    return RootCause(a.id, a.entity_id, total, factors, funnel,
                     _narrative(a, factors, total, label_of, t, funnel, causal))


def _label_lookup(anomalies: list[Anomaly]) -> dict[str, str]:
    return {f"{a.kind}:{a.entity_id}": a.label for a in anomalies}


def causal_event_id(anomaly: Anomaly, causal: dict | None) -> str | None:
    """The event id of the causal analysis linked to an anomaly (a price-driven conversion_drop), else None."""
    eid = anomaly.detail.get("event_id") if anomaly.kind == "conversion_drop" else None
    return eid if eid and causal and eid in causal else None


def diagnose(anomaly: Anomaly, anomalies: list[Anomaly] | None = None, tables: Tables | None = None,
             causal: dict | None = None) -> RootCause:
    """Explain one anomaly. `anomalies` (the full list) lets knock-on narratives name their cause; `causal`
    ({event_id: event_effect_details}) appends the synthetic-control sentence to a price-driven conversion_drop."""
    return _diagnose(anomaly, tables or Tables(), _label_lookup(anomalies or [anomaly]), causal)


def diagnose_all(anomalies: list[Anomaly] | None = None, causal: dict | None = None) -> list[RootCause]:
    """Diagnose every anomaly (ranked order). With None, run M3 detect_all() first.

    `causal` ({event_id: details}); when omitted it is computed with M4b for every price-driven conversion_drop.
    """
    if anomalies is None:
        from backend.detection.detectors import detect_all  # local: keeps M4 importable without M3 data

        anomalies = detect_all()
    if causal is None:
        from backend.diagnosis.causal import compute_causal  # local: M4b depends on M3, not the other way round

        causal = compute_causal(anomalies)
    t, labels = Tables(), _label_lookup(anomalies)
    return [_diagnose(a, t, labels, causal) for a in anomalies]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _funnel_insight(rc: RootCause) -> str:
    if not rc.funnel:
        return "—"
    if "campaign_id" in rc.funnel[0]:
        w = rc.funnel[0]
        return f"worst campaign {w['campaign_name']} ({m.format_inr(w['change'])}/day, top factor {w['top_factor']})"
    drop = next((s for s in rc.funnel if s["is_biggest_drop"]), None)
    if not drop or drop["change_pct"] > -FUNNEL_MATERIAL:
        return "no material funnel drop"
    return f"biggest drop at {drop['stage']} ({drop['baseline_rate']:.1%} → {drop['recent_rate']:.1%}, {drop['change_pct']:+.0%})"


def print_report(anomalies: list[Anomaly], results: list[RootCause], elapsed: float) -> bool:
    """Print every diagnosis (factors, sum check, funnel insight, narrative). Returns True if all sums hold."""
    all_ok = True
    for a, rc in zip(anomalies, results):
        ok = rc.check_sum(tol=1.0)
        all_ok &= ok
        print(f"\n{rc.anomaly_id}  {a.label}   total {m.format_inr(rc.total_change)}/day")
        if rc.factors:
            for f in rc.factors:
                bar = "█" * round(f.pct * 20)
                print(f"    {f.name:<26}{m.format_inr(f.impact):>10}  {f.pct:>4.0%}  {bar}")
            print(f"    sum check: {'✔' if ok else '✘'} (Σ factors {sum(f.impact for f in rc.factors):.2f} vs total {rc.total_change:.2f})")
        print(f"    funnel: {_funnel_insight(rc)}")
        print(f"    {rc.narrative}")
    print(f"\nM4 OK · {len(results)} diagnoses · {'all waterfalls sum exactly' if all_ok else 'SUM CHECK FAILED'} · {elapsed:.1f}s")
    return all_ok


def main() -> None:
    from backend.detection.detectors import detect_all

    start = time.perf_counter()
    anomalies = detect_all()
    results = diagnose_all(anomalies)
    print_report(anomalies, results, time.perf_counter() - start)


if __name__ == "__main__":
    main()
