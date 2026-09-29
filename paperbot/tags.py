"""Cause tags for closed trades (tagger v1).

Every trade gets tags, winners included, so a tag's effect can be judged
against its base rate. Tags are hypotheses, not verdicts.

Classes by net R (R = entry-to-initial-stop distance x qty):
    loss       net R <= -0.1
    breakeven  -0.1 < net R <= +0.1
    win        net R > +0.1

Entry-time tags (``pre``; knowable at entry, usable for filters):
    H0  counter-trend: higher-timeframe trend against the trade
    B1  box middle: inside a box, position 0.35-0.65
    B2  box edge chase: long near the top (>=0.8) / short near the bottom (<=0.2)
    B3  trend/breakout strategy entered in a box or chop regime
    R1  mean-reversion strategy against a trend
    E1  late trend entry: >= 2.5 ATR beyond EMA20 in the trade direction
    B7  higher-timeframe box wall: long at >=0.85 / short at <=0.15 of the HTF box
Outcome tags (``post``; descriptive only, never used as filters):
    LIQ liquidated
    G1  gave back: MFE >= 1R, ended as a loss
    T1  stop too tight: stopped out, then price reached the target within K bars
    W1  took profit early: after the exit price ran >= 1R further before -1R
    W2  late take-profit: won, but MFE >= 1.5R and gave back >= 50% of it
    W5  fees ate the edge: gross positive, net R <= +0.1
    W3  clean win (no other win tag)
    N0  normal loss (no other loss tag)
All thresholds are initial values.
"""

from __future__ import annotations

from typing import Optional, Sequence

from .models import Bar, TradeRecord

TREND_STYLES = {"trend", "breakout"}
MR_STYLES = {"mean_reversion"}

# Loss primary-cause priority, first match wins.
LOSS_ORDER = ["LIQ", "G1", "T1", "B3", "R1", "H0", "B7", "B2", "B1", "E1"]
WIN_ORDER = ["W5", "W1", "W2"]


def r_unit(t: TradeRecord) -> Optional[float]:
    d = abs(t.entry_price - t.stop_price) * t.qty
    return d if d > 0 else None


def excursions_r(t: TradeRecord) -> tuple[Optional[float], Optional[float]]:
    d = abs(t.entry_price - t.stop_price)
    if d <= 0:
        return None, None
    mfe = t.side * (t.mfe_price - t.entry_price) / d
    mae = t.side * (t.mae_price - t.entry_price) / d
    return mfe, mae


def pre_tags(t: TradeRecord) -> list[str]:
    c = t.context or {}
    side = t.side
    out = []
    htf = c.get("htf_regime")
    if (htf == "trend_up" and side < 0) or (htf == "trend_down" and side > 0):
        out.append("H0")
    reg = c.get("regime")
    pos = c.get("box_pos")
    if reg == "box" and pos is not None:
        if 0.35 <= pos <= 0.65:
            out.append("B1")
        if (side > 0 and pos >= 0.8) or (side < 0 and pos <= 0.2):
            out.append("B2")
    if t.strategy_style in TREND_STYLES and reg in ("box", "chop"):
        out.append("B3")
    if t.strategy_style in MR_STYLES and (
            (reg == "trend_up" and side < 0) or (reg == "trend_down" and side > 0)):
        out.append("R1")
    dist = c.get("ema20_dist_atr")
    if dist is not None and side * dist >= 2.5:
        out.append("E1")
    hpos = c.get("htf_box_pos")
    if htf == "box" and hpos is not None and (
            (side > 0 and hpos >= 0.85) or (side < 0 and hpos <= 0.15)):
        out.append("B7")
    return out


def _first_hit(post: Sequence[Bar], side: int, up: float, down: float) -> Optional[str]:
    """Which level the price reaches first after the exit: 'up' (favourable
    to the trade side) or 'down'. Ambiguous bars count as 'down'."""
    for b in post:
        fav = (b.high >= up) if side > 0 else (b.low <= up)
        adv = (b.low <= down) if side > 0 else (b.high >= down)
        if adv:
            return "down"
        if fav:
            return "up"
    return None


def tag_trade(t: TradeRecord, post: Sequence[Bar] = (), k_bars: int = 20) -> dict:
    """``post``: 1m bars after the exit (optional; enables T1/W1)."""
    unit = r_unit(t)
    net_r = t.pnl / unit if unit else None
    mfe, mae = excursions_r(t)
    cls = "breakeven"
    if net_r is not None:
        cls = "loss" if net_r <= -0.1 else ("win" if net_r > 0.1 else "breakeven")
    pre = pre_tags(t)
    post_tags: list[str] = []
    d = abs(t.entry_price - t.stop_price)
    after = list(post[:k_bars])

    if t.exit_reason == "LIQ":
        post_tags.append("LIQ")
    if cls == "loss" and mfe is not None and mfe >= 1.0:
        post_tags.append("G1")
    if cls == "loss" and t.exit_reason == "SL" and after:
        reached = any((b.high >= t.tp_price) if t.side > 0 else (b.low <= t.tp_price)
                      for b in after)
        if reached:
            post_tags.append("T1")
    gross = t.pnl + t.fees + t.funding
    if gross > 0 and net_r is not None and net_r <= 0.1:
        post_tags.append("W5")
    if cls == "win":
        if t.exit_reason == "TP" and after and d > 0:
            up = t.exit_price + t.side * d
            down = t.exit_price - t.side * d
            if _first_hit(after, t.side, up, down) == "up":
                post_tags.append("W1")
        if mfe is not None and mfe >= 1.5 and net_r is not None and net_r <= 0.5 * mfe:
            post_tags.append("W2")
        if not any(x in post_tags for x in ("W1", "W2", "W5")):
            post_tags.append("W3")
    all_tags = pre + post_tags

    if cls == "loss":
        order = LOSS_ORDER
        if mfe is not None and mfe >= 1.0:  # entry was right; look at the exit first
            order = ["LIQ", "G1", "T1"] + [x for x in LOSS_ORDER if x not in ("LIQ", "G1", "T1")]
        causes = [x for x in order if x in all_tags]
        if not causes:
            post_tags.append("N0")
            causes = ["N0"]
    elif cls == "win":
        causes = [x for x in WIN_ORDER if x in all_tags] or ["W3"]
    else:
        causes = [x for x in ("W5",) if x in all_tags] or ["BE"]
    return {"class": cls, "net_r": net_r, "mfe_r": mfe, "mae_r": mae,
            "pre": pre, "post": post_tags, "primary": causes[0],
            "secondary": causes[1:3], "post_window": len(after)}


def tag_table(tagged: list[dict]) -> list[dict]:
    """Per entry-time tag: counts, mean net R with/without the tag, and lift
    (share of losses carrying the tag / share of wins carrying it). Uses
    entry-time tags only, so the numbers can support filter hypotheses."""
    rows = []
    wins = [x for x in tagged if x["class"] == "win"]
    losses = [x for x in tagged if x["class"] == "loss"]
    codes = sorted({c for x in tagged for c in x["pre"]})
    for code in codes:
        with_t = [x["net_r"] for x in tagged if code in x["pre"] and x["net_r"] is not None]
        without = [x["net_r"] for x in tagged if code not in x["pre"] and x["net_r"] is not None]
        p_loss = sum(code in x["pre"] for x in losses) / len(losses) if losses else None
        p_win = sum(code in x["pre"] for x in wins) / len(wins) if wins else None
        rows.append({
            "tag": code, "n": len(with_t),
            "mean_r_with": sum(with_t) / len(with_t) if with_t else None,
            "mean_r_without": sum(without) / len(without) if without else None,
            "lift": (p_loss / p_win) if p_loss is not None and p_win else None,
            "status": "ok" if len(with_t) >= 30 else "insufficient (n<30)",
        })
    return rows
