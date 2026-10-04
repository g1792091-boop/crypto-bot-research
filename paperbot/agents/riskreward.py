"""Risk-reward (손익비) numbers of the paper v3 accounts (owners' request 2026-10-04). Code only, read-only on paper3.db
and daily3.db; the staff read these numbers and interpret them, nothing here trades or changes an account.

Why the numbers look the way they do: the paper v3 rules (docs/paper-v3-rules*.md, fixed for the 30-day run) put
the stop at 2 ATR with 20-50x leverage and lock profit on a ladder (first lock +10% ROE once the best ROE reaches
+12%, then 5% steps). A loss is often -10..-50% ROE (a liquidation -100%), a win often around the first locks. So
the payoff ratio is low by design and the win rate has to be high to break even. This module measures exactly that.

- ``stats``          one cell (a list of closed trades): trades, wins / losses, win rate, the average win and loss in
                     ROE (on margin) and in account-equity terms (ROE x the tier's margin share, as
                     docs/observation-shadows.md section 4, with the restarted run's margin = leverage %: 50x 50%,
                     40x 40%, 30x 30%, 20x / 10x 20%), the payoff ratio
                     (average win / |average loss|), the breakeven win rate |L| / (W + |L|), the actual win rate's gap
                     to it (percentage points), the expectancy per trade, the exit-reason mix (LOCK / SL / LIQ / other),
                     the winners' give-back (best ROE during the trade, from ``mfe_price``, vs the realised ROE), the
                     losers that first reached the first lock's trigger (+12%) or +5% and their best ROE (median,
                     80th / 90th percentile), the winners' adverse excursion (``mae_price``: as % of the entry and as a
                     fraction of the initial stop distance |entry - stop_initial|, median / 80th / 90th percentile, and
                     the share that stayed within 25 / 50 / 75% of it: would a tighter stop have kept them?), and the
                     distribution of win and loss ROE in buckets. ``small``: under ``SMALL_N`` trades.
- ``table``          per strategy (all four timeframes) and per strategy x timeframe over [since, until).
- ``shadow_summary`` the nightly exit shadows (daily3.db ``shadows``: base, lock15, lock20, lock30, timestop, lev10,
                     lev20; paperbot/obsshadows.py; and from docs/observation-shadows-3.md lev30, lev40, lev50 and
                     the stop widths stopw1.5, stopw2.5, stopw3 at the real trade's leverage) per strategy over the
                     same window: each variant's mean P&L on equity against the base shadow of the same trades, and
                     how often it did better / worse; ``leverage_turns``: the strategies whose base loses while
                     lev10 .. lev50 makes money on equity (and the reverse, ``turns_negative``, when there is any);
                     ``stop_turns``: the same for the stop widths; and from docs/observation-shadows-4.md the fixed
                     take-profits tp1R, tp1.5R, tp2R, tp3R (2 ATR stop, no ladder) and ladder_cap2R (the ladder plus
                     an exit at 2R), with ``tp_turns`` (base loses while the take-profit makes money, and the reverse).
                     The 5-year comparison (research/exitstyle) found no take-profit that beat the ladder. Also
                     lev20m20 .. lev50m50 (fixed leverage, margin = leverage %) with ``margin_turns``.
                     Descriptive only ("설명용, 판정 아님").
- ``tier_table``     the live closed strategy trades grouped by the leverage actually used (50 / 40 / 30 / 20x):
                     trades, win rate, mean ROE, mean P&L on equity, payoff, breakeven win rate. Confounded: the
                     tier is chosen from the stop distance (2 ATR / price), so a tier is also a kind of spot; the
                     shadows above (same trades, only the leverage changed) are the clean comparison.
- ``rr_packet``      the Thursday 손익비·청산 회의 packet (team:review, trigger rr_review).
- ``strategy_brief`` / ``brief_many``  compact numbers for a strategy specialist's packet and the 14:00 ranking.
"""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
from typing import Any, Iterable, Optional

from ..config import V3_TRADE_TFS

DAY_MS = 86_400_000
TFS = V3_TRADE_TFS                   # the run's timeframes (5m removed 2026-10-04, docs/paper-v3-rules-change-1.md)
SMALL_N = 10                     # cells under this many trades are marked small (chance can explain them)
EXITS = ("LOCK", "SL", "LIQ")    # the rest count as 'other' (TP, HALT, END, ...)
# share of equity put up as margin at each leverage: the paper v3 rule's tiers (config.v3_settings, the first tier listing
# a leverage wins) over the 2026-10-04 table (= obsshadows.MARGIN_FRAC: margin = leverage %; 10x is the lev10 shadow)
MARGIN_FRAC_TABLE = {50: 0.50, 40: 0.40, 30: 0.30, 20: 0.20, 10: 0.20}


def _rule_margin_fracs() -> dict:
    from ..config import v3_settings
    out, seen = dict(MARGIN_FRAC_TABLE), set()
    for t in v3_settings().tiers:
        for lev in t.leverages:
            if lev not in seen:
                seen.add(lev)
                out[int(lev)] = t.margin_frac
    return out


MARGIN_FRAC = _rule_margin_fracs()
UP_5 = 0.05                      # a loser that was up this much (net ROE) at its best ("수익 났다가 손절", cards.TAGS)
# ROE buckets (fractions): wins lo <= roe < hi, losses lo < roe <= hi
WIN_BUCKETS = (("0~5%", 0.0, 0.05), ("5~10%", 0.05, 0.10), ("10~15%", 0.10, 0.15), ("15~20%", 0.15, 0.20),
               ("20~30%", 0.20, 0.30), ("30~50%", 0.30, 0.50), ("50%+", 0.50, None))
LOSS_BUCKETS = (("0~-5%", -0.05, 0.0), ("-5~-10%", -0.10, -0.05), ("-10~-20%", -0.20, -0.10),
                ("-20~-30%", -0.30, -0.20), ("-30~-50%", -0.50, -0.30), ("-50~-80%", -0.80, -0.50),
                ("-80% 이하", None, -0.80))
SHADOW_VARIANTS = ("lock15", "lock20", "lock30", "timestop", "lev10", "lev20")      # compared with "base"
# docs/observation-shadows-3.md (paperbot/obsshadows.py VARIANTS3): fixed 30 / 40 / 50x at the tier's margin share,
# and the initial stop at 1.5 / 2.5 / 3 ATR at the real trade's leverage
SHADOW_VARIANTS3 = ("lev30", "lev40", "lev50", "stopw1.5", "stopw2.5", "stopw3")
# docs/observation-shadows-4.md (paperbot/obsshadows.py VARIANTS4): fixed take-profit at k x R (R = the initial
# 2 ATR stop distance) without the ladder, and the ladder capped at 2R; the real trade's leverage
SHADOW_VARIANTS4 = ("tp1R", "tp1.5R", "tp2R", "tp3R", "ladder_cap2R")
# and fixed 20 / 30 / 40 / 50x with margin = leverage % (the comparison against the entry-strength leverage rule)
SHADOW_MARGIN4 = ("lev20m20", "lev30m30", "lev40m40", "lev50m50")
ALL_SHADOWS = SHADOW_VARIANTS + SHADOW_VARIANTS3 + SHADOW_VARIANTS4 + SHADOW_MARGIN4
SHADOW_KO = {"lock15": "첫 잠금 15%", "lock20": "첫 잠금 20%", "lock30": "첫 잠금 30%",
             "timestop": "잠금 없이 N봉 지나면 시장가 청산", "lev10": "10배 고정·증거금 20%", "lev20": "20배 고정·증거금 20%"}
SHADOW_KO3 = {"lev30": "30배 고정·증거금 30%", "lev40": "40배 고정·증거금 40%", "lev50": "50배 고정·증거금 40%",
              "stopw1.5": "처음 손절 1.5 ATR(레버리지는 실제 거래와 같게)", "stopw2.5": "처음 손절 2.5 ATR(〃)",
              "stopw3": "처음 손절 3 ATR(〃)"}
SHADOW_KO4 = {"tp1R": "고정 익절 1R(R = 처음 손절 거리 2 ATR), 계단 잠금 없음", "tp1.5R": "고정 익절 1.5R(〃)",
              "tp2R": "고정 익절 2R(〃)", "tp3R": "고정 익절 3R(〃)", "ladder_cap2R": "계단 잠금 그대로 + 2R에서 익절"}
SHADOW_KO_M4 = {"lev20m20": "20배 고정·증거금 20%", "lev30m30": "30배 고정·증거금 30%", "lev40m40": "40배 고정·증거금 40%",
                "lev50m50": "50배 고정·증거금 50%"}
TP_SHADOWS = SHADOW_VARIANTS4
# research/exitstyle/out/SUMMARY_KO.md (pre-registered research/exitstyle/PREREG_EXITSTYLE.md), 15m/30m/1h/4h
TP_FIVE_YEAR = ("5년 비교(research/exitstyle): 어느 고정 익절도 계단 잠금을 이기지 못함(미리 정한 세 조건을 모두 만족한 방식 "
                "없음). 거래당 자금 대비 평균: 계단 잠금 −1.415%, 1R −1.422%, 1.5R −1.418%, 2R −1.389%, 3R −1.378%, "
                "잠금+2R −1.403%; 보정 뒤 유의하게 나은 칸은 128칸 중 많아야 9칸. 그래서 계단 잠금 유지")
SHADOW_LABEL = "설명용, 판정 아님"
LEVERAGE_SHADOWS = ("lev10", "lev20", "lev30", "lev40", "lev50")
STOP_SHADOWS = ("stopw1.5", "stopw2.5", "stopw3")
TIER_LEVERAGES = (50, 40, 30, 20)
# the 5-year lab tests an improvement idea goes to (agents/labtests.py: lock_start, stop_atr); read here, never run
LAB_TESTS = {"lock_start": {"first_lock": (0.15, 0.20, 0.30)}, "stop_atr": {"k": (1.5, 2.5, 3.0)}}


def _f(x: Any) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


def _r(x: Optional[float], n: int = 4) -> Optional[float]:
    return None if x is None else round(float(x), n)


def _mean(xs: Iterable[Optional[float]]) -> Optional[float]:
    v = [x for x in xs if x is not None]
    return sum(v) / len(v) if v else None


def ladder() -> dict:
    """The paper v3 exit rules in numbers (config.v3_settings, read only)."""
    from ..config import v3_settings
    s = v3_settings()
    return {"first_lock": s.ladder_first_lock, "step": s.ladder_step, "trigger_gap": s.ladder_trigger_gap,
            "first_trigger": round(s.ladder_first_lock + s.ladder_trigger_gap, 4), "stop_atr": 2.0,
            "leverage": f"{s.min_leverage}~{s.max_leverage}배", "round_trip": round(s.round_trip_cost, 6)}


def pnl_equity(roe: Optional[float], leverage: Any) -> Optional[float]:
    """ROE x the tier's margin share (obsshadows.pnl_equity); None for a leverage outside the tiers."""
    lev = _f(leverage)
    if roe is None or lev is None:
        return None
    f = MARGIN_FRAC.get(int(round(lev)))
    return None if f is None else roe * f


def norm_trade(d: dict, round_trip: float) -> Optional[dict]:
    """One closed trade (trades.data) as the numbers used here; None when it has no P&L."""
    pnl, roe = _f(d.get("pnl")), _f(d.get("roe"))
    if pnl is None or roe is None:
        return None
    side, entry, best, lev = _f(d.get("side")), _f(d.get("entry_price")), _f(d.get("mfe_price")), _f(d.get("leverage"))
    mfe = None
    if side and entry and best and lev:
        from ..ladder import net_roe              # read-only use of the engine's ROE definition (cards.best_roe)
        mfe = net_roe(int(side), entry, best, lev, round_trip)
    # adverse excursion: how far price went against the trade (mae_price) as a fraction of the entry price, and as
    # a fraction of the initial stop distance |entry - stop_initial| (1.0 = it touched the first stop's level)
    mae, mae_stop = None, None
    worst, stop0 = _f(d.get("mae_price")), _f(d.get("stop_initial"))
    if side and entry and worst:
        mae = max(0.0, -int(side) * (worst / entry - 1.0))
        if stop0 and abs(entry - stop0) > 0:
            mae_stop = mae / (abs(entry - stop0) / entry)
    reason = str(d.get("exit_reason") or "")
    return {"win": pnl > 0, "roe": roe, "eq": pnl_equity(roe, lev), "exit": reason if reason in EXITS else "other",
            "mfe_roe": mfe, "mae": mae, "mae_stop": mae_stop, "exit_time": int(_f(d.get("exit_time")) or 0),
            "lev": None if lev is None else int(round(lev))}


def _side(rows: list[dict], key: str) -> dict:
    """Average win / loss, payoff, breakeven win rate, gap and expectancy on one basis (``key``: roe or eq)."""
    known = [r for r in rows if r[key] is not None]
    w = [r[key] for r in known if r["win"]]
    lo = [r[key] for r in known if not r["win"]]
    aw, al = _mean(w), _mean(lo)
    wr = len(w) / len(known) if known else None
    payoff = aw / abs(al) if aw is not None and al else None
    be = abs(al) / (aw + abs(al)) if aw is not None and al is not None and (aw + abs(al)) > 0 else None
    return {"trades": len(known), "avg_win": _r(aw), "avg_loss": _r(al), "payoff": _r(payoff, 3),
            "breakeven_win_rate": _r(be), "gap_pp": None if be is None or wr is None else round((wr - be) * 100, 1),
            "expectancy": _r(_mean(r[key] for r in known))}


def pctl(vals: list[float], q: float) -> Optional[float]:
    """The ``q`` quantile (0..1) with linear interpolation (numpy's default); None for no values."""
    v = sorted(vals)
    if not v:
        return None
    k = (len(v) - 1) * q
    lo = int(k)
    hi = min(lo + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (k - lo)


STOP_SHARES = (0.25, 0.50, 0.75)


def winners_mae(wins: list[dict]) -> dict:
    """The winners' adverse excursion (owners' request 2026-10-04): median / 80th / 90th percentile as a fraction
    of the entry price (``pct``) and of the initial stop distance (``of_stop``), and the share of winners whose
    excursion stayed within 25 / 50 / 75% of the stop distance: if most winners never came near the stop, a tighter
    stop would have kept them (a 5-year test: stop_atr 1.5)."""
    pc = [r["mae"] for r in wins if r.get("mae") is not None]
    st = [r["mae_stop"] for r in wins if r.get("mae_stop") is not None]
    out = {"winners": len(pc), "median_pct": _r(pctl(pc, 0.5), 5), "p80_pct": _r(pctl(pc, 0.8), 5),
           "p90_pct": _r(pctl(pc, 0.9), 5), "with_stop": len(st), "median_of_stop": _r(pctl(st, 0.5), 3),
           "p80_of_stop": _r(pctl(st, 0.8), 3), "p90_of_stop": _r(pctl(st, 0.9), 3),
           "within_of_stop": {f"{int(x * 100)}%": (_r(sum(1 for v in st if v <= x + 1e-12) / len(st), 3) if st else None)
                              for x in STOP_SHARES}}
    if len(pc) < SMALL_N:
        out["small"] = True
    return out


def losers_mfe(losses: list[dict]) -> dict:
    """The losers' best net ROE before they closed: median / 80th / 90th percentile."""
    v = [r["mfe_roe"] for r in losses if r.get("mfe_roe") is not None]
    out = {"losers": len(v), "median_best_roe": _r(pctl(v, 0.5)), "p80_best_roe": _r(pctl(v, 0.8)),
           "p90_best_roe": _r(pctl(v, 0.9))}
    if len(v) < SMALL_N:
        out["small"] = True
    return out


def _buckets(vals: list[float], spec: tuple, win: bool) -> dict:
    out = {}
    for label, lo, hi in spec:
        if win:
            out[label] = sum(1 for v in vals if v >= lo and (hi is None or v < hi))
        else:
            out[label] = sum(1 for v in vals if (lo is None or v > lo) and v <= hi)
    return out


def stats(rows: list[dict], first_trigger: float = 0.12, min_n: int = SMALL_N) -> dict:
    """Everything about one cell of normalised trades (``norm_trade``). ROE and equity numbers are fractions
    (0.10 = +10%); ``gap_pp`` is in percentage points (actual win rate - breakeven win rate). With averages from
    the same trades, gap > 0 exactly when the expectancy is > 0."""
    n = len(rows)
    if not n:
        return {"trades": 0, "small": True}
    wins = [r for r in rows if r["win"]]
    losses = [r for r in rows if not r["win"]]
    ex = {k: sum(1 for r in rows if r["exit"] == k) for k in (*EXITS, "other")}
    gw = [r for r in wins if r["mfe_roe"] is not None]
    sum_mfe = sum(r["mfe_roe"] for r in gw)
    lm = [r for r in losses if r["mfe_roe"] is not None]
    reached = sum(1 for r in lm if r["mfe_roe"] >= first_trigger - 1e-12)
    up5 = sum(1 for r in lm if r["mfe_roe"] >= UP_5 - 1e-12)
    out = {"trades": n, "wins": len(wins), "losses": len(losses), "win_rate": _r(len(wins) / n),
           "roe": _side(rows, "roe"), "equity": _side(rows, "eq"),
           "exits": ex, "exit_share": {k: _r(v / n, 3) for k, v in ex.items()},
           "giveback": {"winners": len(gw), "mean_best_roe": _r(_mean(r["mfe_roe"] for r in gw)),
                        "mean_roe": _r(_mean(r["roe"] for r in gw)),
                        "mean_giveback_roe": _r(_mean(r["mfe_roe"] - r["roe"] for r in gw)),
                        "kept_share": _r(sum(r["roe"] for r in gw) / sum_mfe, 3) if sum_mfe > 0 else None},
           "losers_reached_first_lock": {"n": reached, "share": _r(reached / len(lm), 3) if lm else None,
                                         "trigger_roe": first_trigger},
           "losers_were_up_5pct": {"n": up5, "share": _r(up5 / len(lm), 3) if lm else None},
           "winners_mae": winners_mae(wins), "losers_mfe": losers_mfe(losses),
           "buckets": {"wins": _buckets([r["roe"] for r in wins], WIN_BUCKETS, True),
                       "losses": _buckets([r["roe"] for r in losses], LOSS_BUCKETS, False)}}
    if n < min_n:
        out["small"] = True
    return out


def compact(s: dict) -> dict:
    """The few numbers a packet carries for a cell: equity-terms payoff, breakeven win rate and gap (= the
    dashboard's 손익비, which uses the $ P&L), the average win / loss ROE for intuition, the exit mix."""
    if not s.get("trades"):
        return {"trades": 0, "small": True}
    e = s["equity"]
    out = {"trades": s["trades"], "win_rate": s["win_rate"], "payoff": e["payoff"],
           "breakeven_win_rate": e["breakeven_win_rate"], "gap_pp": e["gap_pp"], "expectancy_eq": e["expectancy"],
           "avg_win_roe": s["roe"]["avg_win"], "avg_loss_roe": s["roe"]["avg_loss"], "exit_share": s["exit_share"]}
    if s.get("small"):
        out["small"] = True
    return out


def tiny(s: dict) -> dict:
    """A strategy x timeframe cell in a meeting packet (the smallest form)."""
    if not s.get("trades"):
        return {"trades": 0, "small": True}
    e = s["equity"]
    out = {"trades": s["trades"], "win_rate": _r(s["win_rate"], 3), "payoff": _r(e["payoff"], 2),
           "breakeven_win_rate": _r(e["breakeven_win_rate"], 3), "gap_pp": e["gap_pp"],
           "lock_share": s["exit_share"]["LOCK"], "win_mae_p80_of_stop": s["winners_mae"]["p80_of_stop"],
           "win_mae_within_50pct_stop": s["winners_mae"]["within_of_stop"]["50%"]}
    if s["exits"]["LIQ"]:
        out["liq"] = s["exits"]["LIQ"]
    if s.get("small"):
        out["small"] = True
    return out


def shadow_brief(cells: dict) -> dict:
    """A strategy's shadows in a meeting packet: per variant only trades, the difference to the base and the
    better / worse shares."""
    out = {"base": cells.get("base")}
    for v in SHADOW_VARIANTS:
        c = cells.get(v) or {}
        keys = ("trades", "vs_base_eq", "better_share", "worse_share", "small")
        if v in LEVERAGE_SHADOWS:          # lower leverage: its own expectancy on equity next to the base's
            keys = ("trades", "mean_eq", "base_mean_eq", "vs_base_eq", "better_share", "worse_share", "liq",
                    "base_liq", "not_entered", "small")
        out[v] = {k: c[k] for k in keys if k in c}
    return out


def _turns(cells_by_strategy: dict, variants: tuple, always_reverse: bool) -> dict:
    """Per variant: ``turns_positive`` = strategies whose base shadow lost on average (P&L on equity <= 0) while the
    variant on the same trades made money (> 0); ``still_negative`` = the variant <= 0 too; ``turns_negative`` = the
    reverse (base > 0, variant <= 0; listed only when there is any unless ``always_reverse``)."""
    out = {}
    for v in variants:
        pos, neg, rev = [], [], []
        for st, cells in sorted(cells_by_strategy.items()):
            c = cells.get(v) or {}
            if not c.get("trades") or c.get("base_mean_eq") is None or c.get("mean_eq") is None:
                continue
            item = {"strategy": st, "trades": c["trades"], "mean_eq": c["mean_eq"], "base_mean_eq": c["base_mean_eq"],
                    **({"small": True} if c.get("small") else {})}
            if c["base_mean_eq"] <= 0 < c["mean_eq"]:
                pos.append(item)
            elif c["mean_eq"] <= 0:
                neg.append(st)
                if c["base_mean_eq"] > 0:
                    rev.append(item)
        out[v] = {"turns_positive": pos, "still_negative": neg}
        if rev or always_reverse:
            out[v]["turns_negative"] = rev
    return out


def leverage_turns(cells_by_strategy: dict) -> dict:
    """Per fixed-leverage shadow (lev10, lev20, and from docs/observation-shadows-3.md lev30, lev40, lev50): the
    strategies whose base shadow lost on average (P&L on equity <= 0) while that shadow of the same trades made money
    (> 0), the ones that stayed negative, and (``turns_negative``, only when there is any) the reverse: base > 0 but
    the shadow <= 0. Code's count; descriptive only (small samples marked)."""
    return _turns(cells_by_strategy, LEVERAGE_SHADOWS, False)


def stop_turns(cells_by_strategy: dict) -> dict:
    """Per stop-width shadow (stopw1.5, stopw2.5, stopw3: k x ATR at the real trade's leverage,
    docs/observation-shadows-3.md): ``turns_positive`` = strategies whose base (2 ATR) lost on average while that
    stop width made money on the same trades, ``turns_negative`` = base made money but that stop width lost,
    ``still_negative`` = that stop width <= 0. Code's count; descriptive only (small samples marked)."""
    return _turns(cells_by_strategy, STOP_SHADOWS, True)


def shadow_brief3(cells: dict) -> dict:
    """A strategy's docs/observation-shadows-3.md shadows in a meeting packet, as short rows (columns in
    ``SHADOW3_COLUMNS``; P&L on equity to 4 decimals, shares to 2); variants without a trade are left out."""
    out = {}
    for v in SHADOW_VARIANTS3:
        c = cells.get(v) or {}
        if not c.get("trades") and not c.get("not_entered"):
            continue
        out[v] = [c.get("trades", 0), _r(c.get("mean_eq")), _r(c.get("base_mean_eq")), _r(c.get("vs_base_eq")),
                  _r(c.get("better_share"), 2), _r(c.get("worse_share"), 2), c.get("liq", 0), c.get("base_liq", 0),
                  c.get("not_entered", 0)]
    return out


def tp_turns(cells_by_strategy: dict) -> dict:
    """Per take-profit shadow (tp1R, tp1.5R, tp2R, tp3R, ladder_cap2R; docs/observation-shadows-4.md):
    ``turns_positive`` = strategies whose base (the ladder) lost on average while that take-profit made money on the
    same trades, ``turns_negative`` = the reverse (base > 0, take-profit <= 0), ``still_negative_n`` = how many
    stayed <= 0 (a count, not the names, to keep the packet small). A variant with nothing in any of the three is
    left out (no strategy compared yet, or none turned and none stayed negative). Code's count; descriptive only."""
    out = {}
    for v, c in _turns(cells_by_strategy, TP_SHADOWS, True).items():
        if c["turns_positive"] or c["turns_negative"] or c["still_negative"]:
            out[v] = {"turns_positive": c["turns_positive"], "turns_negative": c["turns_negative"],
                      "still_negative_n": len(c["still_negative"])}
    return out


def margin_turns(cells_by_strategy: dict) -> dict:
    """``tp_turns`` for the margin = leverage % shadows (lev20m20 .. lev50m50, docs/observation-shadows-4.md)."""
    out = {}
    for v, c in _turns(cells_by_strategy, SHADOW_MARGIN4, True).items():
        if c["turns_positive"] or c["turns_negative"] or c["still_negative"]:
            out[v] = {"turns_positive": c["turns_positive"], "turns_negative": c["turns_negative"],
                      "still_negative_n": len(c["still_negative"])}
    return out


def shadow_brief_m4(cells: dict) -> dict:
    """A strategy's margin = leverage % shadows as short rows in ``SHADOW3_COLUMNS`` order (as shadow_brief3)."""
    out = {}
    for v in SHADOW_MARGIN4:
        c = cells.get(v) or {}
        if not c.get("trades") and not c.get("not_entered"):
            continue
        out[v] = [c.get("trades", 0), _r(c.get("mean_eq")), _r(c.get("base_mean_eq")), _r(c.get("vs_base_eq")),
                  _r(c.get("better_share"), 2), _r(c.get("worse_share"), 2), c.get("liq", 0), c.get("base_liq", 0),
                  c.get("not_entered", 0)]
    return out


def shadow_brief4(cells: dict) -> dict:
    """A strategy's docs/observation-shadows-4.md shadows in a meeting packet, as short rows (columns in
    ``SHADOW4_COLUMNS``); variants without a compared trade are left out (not entered / open: all_strategies)."""
    out = {}
    for v in SHADOW_VARIANTS4:
        c = cells.get(v) or {}
        if not c.get("trades"):
            continue
        out[v] = [c.get("trades", 0), _r(c.get("mean_eq")), _r(c.get("base_mean_eq")), _r(c.get("vs_base_eq")),
                  _r(c.get("better_share"), 2), _r(c.get("worse_share"), 2), c.get("tp", 0), c.get("liq", 0),
                  c.get("base_liq", 0)]
    return out


SHADOW4_COLUMNS = ["trades(비교한 거래, 10건 미만은 작음)", "mean_eq(그림자 자금 대비 평균)", "base_mean_eq(같은 거래 base)",
                   "vs_base_eq(차이)", "better_share(base보다 나음)", "worse_share(base보다 나쁨)", "tp(익절로 끝남)",
                   "liq(그림자 강제청산)", "base_liq"]


SHADOW3_COLUMNS = ["trades(비교한 거래, 10건 미만은 작음)", "mean_eq(그림자 자금 대비 평균)", "base_mean_eq(같은 거래 base)", "vs_base_eq(차이)",
                   "better_share(base보다 나음)", "worse_share(base보다 나쁨)", "liq(그림자 강제청산)", "base_liq",
                   "not_entered(진입 안 함)"]


# ---------------------------------------------------------------- reading paper3.db
def round_trip_of(paper_ro: Optional[sqlite3.Connection]) -> float:
    """The run's round-trip cost (state 'run' taker fee when recorded, else the v3 default)."""
    from ..config import v3_settings
    fee = None
    try:
        r = paper_ro.execute("SELECT data FROM state WHERE k = 'run'").fetchone() if paper_ro is not None else None
        fee = json.loads(r[0]).get("taker_fee") if r else None
    except (sqlite3.Error, TypeError, ValueError, AttributeError):
        fee = None
    return v3_settings(**({"taker_fee": fee} if fee else {})).round_trip_cost


def closed(paper_ro: sqlite3.Connection, since_ms: int, until_ms: int, kinds: tuple = ("strategy",),
           strategies: Optional[Iterable[str]] = None, round_trip: Optional[float] = None) -> list[tuple]:
    """(strategy, timeframe, normalised trade) of the trades closed in [since, until) on accounts of ``kinds``
    (and ``strategies`` when given). Read-only."""
    rt = round_trip_of(paper_ro) if round_trip is None else round_trip
    ks = list(kinds)
    sql = ("SELECT a.strategy, a.timeframe, t.data FROM trades t JOIN accounts a ON a.account_id = t.account_id "
           f"WHERE a.kind IN ({','.join('?' * len(ks))}) AND t.exit_time >= ? AND t.exit_time < ?")
    args: list = [*ks, int(since_ms), int(until_ms)]
    ss = list(strategies or [])
    if ss:
        sql += f" AND a.strategy IN ({','.join('?' * len(ss))})"
        args += ss
    out = []
    for strat, tf, data in paper_ro.execute(sql + " ORDER BY t.exit_time, t.id", args):
        try:
            d = json.loads(data)
        except (TypeError, ValueError):
            continue
        t = norm_trade(d, rt) if isinstance(d, dict) else None
        if t is not None:
            out.append((strat, tf, t))
    return out


def table(rows: list[tuple], first_trigger: float = 0.12, min_n: int = SMALL_N) -> dict:
    """{"all": stats, "strategies": {strategy: {"all": stats, "by_tf": {tf: stats}}}} of ``closed`` rows."""
    per: dict = {}
    for s, tf, t in rows:
        e = per.setdefault(s, {})
        e.setdefault(tf, []).append(t)
    out = {"all": stats([t for *_x, t in rows], first_trigger, min_n), "strategies": {}}
    for s, tfs in per.items():
        allt = [t for v in tfs.values() for t in v]
        out["strategies"][s] = {"all": stats(allt, first_trigger, min_n),
                                "by_tf": {tf: stats(tfs[tf], first_trigger, min_n)
                                          for tf in sorted(tfs, key=lambda x: TFS.index(x) if x in TFS else 9)}}
    return out


TIER_NOTE = ("레버리지 단계별 실거래(설명용, 판정 아님). 주의: 단계는 진입 품질과 손절 거리로 정해짐 — 진입 품질 'best'(강도 "
             "점수 ≥ 4) 신호는 50%×50배, 나머지 신호는 30%×30배부터 시도하고, 손절 손실 ≤ 자금 15%·청산가 여유에 막힐 때만 "
             "40 → 30 → 20배로 내려감(나머지 신호는 50·40배 없음, docs/paper-v3-rules-change-1.md). 그래서 50·40배 거래는 "
             "품질 점수가 높고 손절이 가까운(조용한) 자리, 20배 거래는 손절이 먼(변동성 큰) 자리이고 시간봉도 섞여 있음(긴 봉일수록 "
             "낮은 단계). "
             "단계끼리의 차이는 레버리지 때문인지 자리 때문인지 가를 수 없는 교란된 비교. 깨끗한 비교는 같은 거래를 레버리지만 "
             "바꿔 다시 돌린 그림자(lev10·lev20·lev30·lev40·lev50, docs/observation-shadows-3.md)")


def tier_cell(rows: list[dict]) -> dict:
    """One leverage tier's live trades: trades, win rate, mean ROE, mean P&L on equity, payoff and breakeven win rate
    (inside one tier the margin share is fixed, so ROE and equity give the same payoff)."""
    n = len(rows)
    if not n:
        return {"trades": 0, "small": True}
    e = _side(rows, "eq")
    out = {"trades": n, "win_rate": _r(sum(1 for r in rows if r["win"]) / n), "mean_roe": _r(_mean(r["roe"] for r in rows)),
           "mean_eq": _r(_mean(r["eq"] for r in rows), 5), "payoff": e["payoff"],
           "breakeven_win_rate": e["breakeven_win_rate"], "gap_pp": e["gap_pp"],
           "liq": sum(1 for r in rows if r["exit"] == "LIQ")}
    if n < SMALL_N:
        out["small"] = True
    return out


TIER_COLUMNS = ["trades", "win_rate", "mean_roe", "mean_eq(자금 대비)", "payoff(손익비)", "breakeven_win_rate(본전 승률)",
                "gap_pp", "liq", "small(1 = 10건 미만)"]
TIER_TF_COLUMNS = ["trades", "win_rate", "mean_roe", "mean_eq"]


def tier_row(c: dict) -> list:
    """``tier_cell`` as a short row (``TIER_COLUMNS``)."""
    return [c.get("trades", 0), c.get("win_rate"), c.get("mean_roe"), c.get("mean_eq"), c.get("payoff"),
            c.get("breakeven_win_rate"), c.get("gap_pp"), c.get("liq", 0), int(bool(c.get("small")))]


def tier_packet(got: dict) -> dict:
    """The meeting packet's ``tiers``: per window the tiers in short rows, per timeframe since the start, the note."""
    out: dict = {"columns": TIER_COLUMNS, "by_tf_columns": TIER_TF_COLUMNS, "confounded": True, "note": TIER_NOTE}
    for w, rows in got.items():
        t = tier_table(rows)
        out[w] = {"by_leverage": {lev: tier_row(c) for lev, c in t["by_leverage"].items()},
                  **({"other_leverage": t["other_leverage"]} if t["other_leverage"] else {})}
        if w == "since_start":
            out[w]["by_tf"] = t["by_tf"]
    return out


def tier_table(rows: list[tuple]) -> dict:
    """The ``closed`` rows grouped by the leverage actually used (50 / 40 / 30 / 20x): ``by_leverage`` per tier
    (``tier_cell``), ``by_tf`` the same per timeframe in short rows [trades, win_rate, mean_roe, mean_eq], trades at
    another leverage counted in ``other_leverage``, and the confound note (``TIER_NOTE``)."""
    per: dict = {lev: [] for lev in TIER_LEVERAGES}
    by_tf: dict = {}
    other = 0
    for _s, tf, t in rows:
        lev = t.get("lev")
        if lev not in per:
            other += 1
            continue
        per[lev].append(t)
        by_tf.setdefault(tf, {}).setdefault(lev, []).append(t)
    tfs = sorted(by_tf, key=lambda x: TFS.index(x) if x in TFS else 9)
    return {"by_leverage": {str(lev): tier_cell(v) for lev, v in per.items()},
            "by_tf": {tf: {str(lev): [len(v), _r(sum(1 for r in v if r["win"]) / len(v), 3),
                                      _r(_mean(r["roe"] for r in v)), _r(_mean(r["eq"] for r in v), 5)]
                           for lev, v in sorted(by_tf[tf].items(), key=lambda kv: -kv[0])} for tf in tfs},
            "by_tf_columns": ["trades", "win_rate", "mean_roe", "mean_eq"],
            "other_leverage": other, "confounded": True, "note": TIER_NOTE}


def windows(now_ms: int, days: int = 7) -> dict:
    """The two windows: the last ``days`` days and since the start (every closed trade)."""
    return {"7d": (now_ms - days * DAY_MS, now_ms), "since_start": (0, now_ms)}


# ---------------------------------------------------------------- the nightly exit shadows (daily3.db)
def _utc_day(ms: int) -> str:
    return dt.datetime.fromtimestamp(max(0, ms) / 1000, dt.timezone.utc).strftime("%Y-%m-%d")


def _strategy_of(paper_ro: Optional[sqlite3.Connection]) -> Optional[dict]:
    """account -> strategy of the strategy accounts (paper3.db), None when it cannot be read."""
    if paper_ro is None:
        return None
    try:
        return {a: s for a, s in paper_ro.execute("SELECT account_id, strategy FROM accounts WHERE kind = 'strategy'")}
    except sqlite3.Error:
        return None


def _variant_cell(pairs: list[tuple], extra: dict) -> dict:
    """pairs: (variant pnl_equity, base pnl_equity, variant reason, base reason) of the same trades."""
    n = len(pairs)
    if not n:
        return {"trades": 0, **extra}
    m, b = _mean(p[0] for p in pairs), _mean(p[1] for p in pairs)
    out = {"trades": n, "mean_eq": _r(m, 5), "base_mean_eq": _r(b, 5), "vs_base_eq": _r(m - b, 5),
           "better_share": _r(sum(1 for p in pairs if p[0] > p[1] + 1e-12) / n, 3),
           "worse_share": _r(sum(1 for p in pairs if p[0] < p[1] - 1e-12) / n, 3),
           "liq": sum(1 for p in pairs if p[2] == "LIQ"), "base_liq": sum(1 for p in pairs if p[3] == "LIQ"), **extra}
    if n < SMALL_N:
        out["small"] = True
    return out


def _shadow_cells(rows: list[tuple]) -> dict:
    """rows: (kind, trade key, roe, exit_reason, resolved, data dict) of one group -> per variant vs base."""
    base = {}
    for kind, key, roe, reason, resolved, d in rows:
        if kind == "base" and resolved and roe is not None and _f(d.get("pnl_equity")) is not None:
            base[key] = (_f(d.get("pnl_equity")), reason, _f(d.get("actual_pnl_equity")))
    out = {"base": {"trades": len(base), "mean_eq": _r(_mean(v[0] for v in base.values()), 5),
                    "actual_mean_eq": _r(_mean(v[2] for v in base.values()), 5)}}
    for v in ALL_SHADOWS:
        pairs, not_entered, open_, beyond, tps = [], 0, 0, 0, 0
        for kind, key, roe, reason, resolved, d in rows:
            if kind != v:
                continue
            if not resolved:
                open_ += 1
            elif roe is None:
                not_entered += 1
            elif key in base and _f(d.get("pnl_equity")) is not None:
                pairs.append((_f(d.get("pnl_equity")), base[key][0], reason, base[key][1]))
                beyond += 1 if d.get("stop_beyond_liq") else 0
                tps += 1 if reason == "TP" else 0
        extra = {k: x for k, x in (("not_entered", not_entered), ("open", open_), ("stop_beyond_liq", beyond),
                                   ("tp", tps)) if x}
        out[v] = _variant_cell(pairs, extra)
    return out


def shadow_summary(daily_ro: Optional[sqlite3.Connection], paper_ro: Optional[sqlite3.Connection], since_ms: int,
                   until_ms: int, strategies: Optional[Iterable[str]] = None) -> dict:
    """The nightly exit shadows of the strategy accounts' trades that closed in the window (by the nightly job's
    UTC day), per strategy and for all strategies: for each variant, over the trades both it and the base shadow
    resolved, its mean P&L on equity, the base's, the difference and the better / worse shares against the base.
    'Not entered' (sizing refused, lev10 / lev20) and unresolved rows are counted apart. Descriptive only."""
    if daily_ro is None:
        return {"error": "daily3.db 없음", "label": SHADOW_LABEL}
    kinds = ("base", *ALL_SHADOWS)
    try:
        got = daily_ro.execute(
            f"SELECT key, kind, account_id, roe, exit_reason, resolved, data FROM shadows WHERE day >= ? AND day <= ? "
            f"AND kind IN ({','.join('?' * len(kinds))})", (_utc_day(since_ms), _utc_day(until_ms - 1), *kinds)).fetchall()
    except sqlite3.Error as exc:
        return {"error": f"daily3.db shadows를 읽지 못함: {type(exc).__name__}", "label": SHADOW_LABEL}
    owner = _strategy_of(paper_ro)
    want = set(strategies or [])
    per: dict = {}
    for key, kind, aid, roe, reason, resolved, data in got:
        s = owner.get(aid) if owner is not None else str(aid).split("@")[0]
        if s is None or (want and s not in want):
            continue                          # coin flips, new-strategy accounts
        try:
            d = json.loads(data or "{}")
        except (TypeError, ValueError):
            d = {}
        per.setdefault(s, []).append((kind, str(key).split("|", 1)[-1], _f(roe), reason, int(resolved or 0),
                                      d if isinstance(d, dict) else {}))
    out = {"label": SHADOW_LABEL, "days": [_utc_day(since_ms), _utc_day(until_ms - 1)],
           "all": _shadow_cells([r for v in per.values() for r in v]),
           "strategies": {s: _shadow_cells(v) for s, v in sorted(per.items())}}
    return out


# ---------------------------------------------------------------- packets
HOW_TO_READ = (
    "ROE·자금 대비 숫자는 비율(0.10 = +10%). win_rate = 이긴 거래(손익 > 0) 비율. equity = ROE × 증거금 비율(50·40배 "
    "40%, 30배 30%, 20배 20%, docs/observation-shadows.md 4절): 레버리지가 섞이면 ROE끼리는 비교가 안 되므로 자금 대비로 "
    "봄(대시보드 손익비와 같은 기준). payoff = 평균 이익 ÷ |평균 손실|. breakeven_win_rate(본전 승률) = |평균 손실| ÷ "
    "(평균 이익 + |평균 손실|): 이 승률보다 높아야 남음. gap_pp = 실제 승률 − 본전 승률(%p, 플러스면 남는 쪽). "
    "expectancy = 거래당 평균. exits: LOCK(익절 잠금)·SL(손절)·LIQ(강제청산)·other. giveback: 이긴 거래의 거래 중 최고 "
    "ROE(mfe_price로 코드 계산) vs 실제 ROE, kept_share = 실제 합 ÷ 최고 합. losers_reached_first_lock: 진 거래 중 첫 잠금 "
    "발동선(+12%)까지 갔던 것, losers_mfe = 진 거래의 거래 중 최고 ROE(중앙값·80%). winners_mae = 이긴 거래가 진입 뒤 "
    "반대로 밀린 폭: pct = 진입가 대비, of_stop = 처음 손절 거리 대비(1.0 = 손절선까지), within_of_stop = 손절 거리의 "
    "25·50·75% 안에서 버틴 이긴 거래 비율(높으면 더 가까운 손절, 5년 시험 stop_atr 1.5로도 대부분 남았을 수 있음). "
    "small = 10건 미만(우연일 수 있음).")
RULES_NOTE = ("지금 규칙(30일 동안 고정, 바꿀 수 없음): 처음 손절 2 ATR, 레버리지 20~50배, 계단식 익절(최고 ROE +12%에서 "
              "+10% 잠금, 그 뒤 5%씩). 그래서 손실은 흔히 −10~−50% ROE, 이익은 첫 잠금 근처에 몰리는 것이 설계상 "
              "자연스러움. 개선 생각은 5년 시험(lock_start 첫 잠금 15·20·30%, stop_atr 손절 1.5·2.5·3 ATR)으로만 확인")


def _brief(s: dict) -> dict:
    """A strategy's total in a meeting packet: compact plus give-back and losers that reached the first lock."""
    if not s.get("trades"):
        return {"trades": 0, "small": True}
    out = compact(s)
    out.pop("exit_share", None)               # the counts below say the same
    out["exits"] = s["exits"]
    out["giveback"] = {k: s["giveback"][k] for k in ("winners", "mean_best_roe", "mean_roe", "kept_share")}
    out["losers_reached_first_lock"] = s["losers_reached_first_lock"]["n"]
    out["avg_win_eq"], out["avg_loss_eq"] = s["equity"]["avg_win"], s["equity"]["avg_loss"]
    w = s["winners_mae"]
    out["winners_mae"] = {k: w[k] for k in ("winners", "median_pct", "median_of_stop", "p80_of_stop", "p90_of_stop",
                                            "within_of_stop", "small") if k in w}
    out["losers_mfe"] = {k: s["losers_mfe"][k] for k in ("losers", "median_best_roe", "p80_best_roe")}
    return out


def _drop_empty4(cells: Optional[dict]) -> Optional[dict]:
    """The packet's all-strategies cells without the docs/observation-shadows-4.md variants that have nothing yet
    ({"trades": 0}); the earlier variants keep their empty cells as before."""
    if not isinstance(cells, dict):
        return cells
    return {k: c for k, c in cells.items() if not (k in SHADOW_VARIANTS4 + SHADOW_MARGIN4 and c == {"trades": 0})}


def rr_packet(paper_ro: Optional[sqlite3.Connection], daily_ro: Optional[sqlite3.Connection], now_ms: int,
              days: int = 7, round_trip: Optional[float] = None, names_ko: Optional[dict] = None) -> dict:
    """The Thursday 손익비·청산 회의 packet: all strategies and the coin flips in full (both windows), each strategy's
    total (both windows) and its timeframes (since the start; the last 7 days only where not small), and the exit
    shadows (both windows for all strategies, since the start per strategy)."""
    if paper_ro is None:
        return {"error": "paper3.db 없음"}
    lad = ladder()
    ft = lad["first_trigger"]
    rt = round_trip_of(paper_ro) if round_trip is None else round_trip
    if names_ko is None:
        from .roster3 import STRATEGY_KO
        names_ko = dict(STRATEGY_KO)
    win = windows(now_ms, days)
    try:
        got = {w: closed(paper_ro, a, b, round_trip=rt) for w, (a, b) in win.items()}
        tabs = {w: table(rows, ft) for w, rows in got.items()}
        flips = {w: stats([t for *_x, t in closed(paper_ro, a, b, kinds=("random",), round_trip=rt)], ft)
                 for w, (a, b) in win.items()}
    except sqlite3.Error as exc:
        return {"error": f"paper3.db를 읽지 못함: {type(exc).__name__}"}
    strategies = []
    for s, e in tabs["since_start"]["strategies"].items():
        w7 = tabs["7d"]["strategies"].get(s) or {"all": {"trades": 0}, "by_tf": {}}
        strategies.append({"strategy": s, "name_ko": names_ko.get(s, s), "since_start": _brief(e["all"]),
                           "7d": compact(w7["all"]), "by_tf": {tf: tiny(c) for tf, c in e["by_tf"].items()},
                           # the last 7 days per timeframe: only the cells with enough trades, in short
                           "by_tf_7d": {tf: {"trades": c["trades"], "gap_pp": c["equity"]["gap_pp"]}
                                        for tf, c in w7["by_tf"].items() if not c.get("small")}})
    strategies.sort(key=lambda r: -(r["since_start"].get("trades") or 0))
    sh = {w: shadow_summary(daily_ro, paper_ro, a, b) for w, (a, b) in win.items()}
    shadows = {"label": SHADOW_LABEL, "variants_ko": SHADOW_KO,
               "all_strategies": {w: (_drop_empty4(v.get("all")) if "error" not in v else {"error": v["error"]})
                                  for w, v in sh.items()},
               "by_strategy_since_start": {k: shadow_brief(v) for k, v in
                                           (sh["since_start"].get("strategies") or {}).items()},
               "note": ("밤 점검이 그날 끝난 거래를 규칙 하나만 바꿔 혼자 다시 돌린 기록(docs/observation-shadows.md). "
                        "vs_base_eq = 그 그림자 평균 − 같은 거래들의 base 그림자 평균(자금 대비). better/worse_share도 "
                        "base와 비교. lev10·lev20은 자금 대비 평균(mean_eq = 거래당 기대값)을 base와 나란히 둠. lower_leverage = "
                        "base는 마이너스인데 낮은 레버리지 그림자는 플러스인 매매법(turns_positive, 코드 집계). lev10은 지금 "
                        "규칙 범위(20~50배) 밖이라 쓰려면 두 분 결정과 규칙 v4가 필요. 같은 기간 거래끼리 닮아 있고 기간이 "
                        "짧아 우연일 수 있음: 설명용, 판정 아님")}
    shadows["lower_leverage"] = {w: leverage_turns(v.get("strategies") or {}) for w, v in sh.items()
                                 if "error" not in v}
    # docs/observation-shadows-3.md: fixed 30 / 40 / 50x and the stop widths at the real trade's leverage
    shadows["new_variants"] = {
        "doc": "docs/observation-shadows-3.md", "variants_ko": SHADOW_KO3, "columns": SHADOW3_COLUMNS,
        "by_strategy_since_start": {k: b for k, b in ((k, shadow_brief3(v)) for k, v in
                                                      (sh["since_start"].get("strategies") or {}).items()) if b},
        "stop_turns": {w: stop_turns(v.get("strategies") or {}) for w, v in sh.items() if "error" not in v},
        "note": ("같은 거래를 레버리지만(lev30·40·50, 크기 조건 그대로) 또는 처음 손절폭만(stopw: 실제와 같은 레버리지, "
                 "15% 상한·청산가 여유 없이, 청산은 적용) 바꾼 기록. 전체 숫자는 all_strategies, lev30~50의 플러스 전환은 "
                 "lower_leverage, stop_turns = base(2 ATR) 마이너스→그 손절폭 플러스(turns_positive)와 반대(turns_negative). "
                 "30일 체크포인트(2026-11-01) 전 결론 없음")}
    # docs/observation-shadows-4.md: fixed take-profits (no ladder) and the ladder capped at 2R
    shadows["tp_variants"] = {
        "doc": "docs/observation-shadows-4.md", "variants_ko": SHADOW_KO4, "columns": SHADOW4_COLUMNS,
        "by_strategy_since_start": {k: b for k, b in ((k, shadow_brief4(v)) for k, v in
                                                      (sh["since_start"].get("strategies") or {}).items()) if b},
        "tp_turns": {w: tp_turns(v.get("strategies") or {}) for w, v in sh.items() if "error" not in v},
        "five_year": TP_FIVE_YEAR,
        "note": ("같은 거래를 계단 잠금 대신 고정 익절(R = 처음 손절 거리 2 ATR, 손절 2 ATR 그대로, 실제와 같은 레버리지)로, "
                 "또는 잠금 + 2R 상한으로 나간 기록. 익절도 테이커 수수료·슬리피지, 같은 봉에서 손절과 둘 다 닿으면 손절. "
                 "tp_turns = base(계단 잠금) 마이너스→익절 플러스(turns_positive)와 반대(turns_negative), 빈 칸은 생략. "
                 "30일 체크포인트 전 결론 없음")}
    # docs/observation-shadows-4.md: fixed leverage with margin = leverage % (vs the entry-strength leverage rule)
    shadows["margin_variants"] = {
        "doc": "docs/observation-shadows-4.md", "variants_ko": SHADOW_KO_M4, "columns": "new_variants.columns와 같음",
        "by_strategy_since_start": {k: b for k, b in ((k, shadow_brief_m4(v)) for k, v in
                                                      (sh["since_start"].get("strategies") or {}).items()) if b},
        "margin_turns": {w: margin_turns(v.get("strategies") or {}) for w, v in sh.items() if "error" not in v},
        "note": "레버리지 고정·증거금 = 레버리지 %·크기 조건 그대로(안 되면 not_entered). 계좌별 자금 곡선은 대시보드"}
    if "error" in sh["since_start"]:
        shadows["error"] = sh["since_start"]["error"]
    return {"window": {w: {"from": a, "to": b} for w, (a, b) in win.items()}, "rules": {**lad, "note": RULES_NOTE},
            "lab_tests": LAB_TESTS, "trades": {w: t["all"].get("trades", 0) for w, t in tabs.items()},
            "all_strategies": {w: t["all"] for w, t in tabs.items()}, "coin_flips": flips,
            "strategies": strategies, "shadows": shadows,
            "tiers": tier_packet(got),
            "small_n": SMALL_N, "how_to_read": HOW_TO_READ,
            "note": "모두 코드 계산(수수료·펀딩 포함한 끝난 거래). 동전 봇(무작위 진입, 같은 규칙)이 규칙 자체의 손익비 기준"}


def strategy_brief(paper_ro: Optional[sqlite3.Connection], strategy: str, now_ms: int, days: int = 7,
                   round_trip: Optional[float] = None) -> dict:
    """A strategy specialist's risk-reward numbers (its own four accounts only): totals of the last 7 days and
    since the start, and each timeframe since the start."""
    if paper_ro is None:
        return {"error": "paper3.db 없음"}
    ft = ladder()["first_trigger"]
    rt = round_trip_of(paper_ro) if round_trip is None else round_trip
    try:
        rows = closed(paper_ro, 0, now_ms, strategies=[strategy], round_trip=rt)
    except sqlite3.Error as exc:
        return {"error": f"paper3.db를 읽지 못함: {type(exc).__name__}"}
    since7 = now_ms - days * DAY_MS
    t = table(rows, ft)["strategies"].get(strategy) or {"all": {"trades": 0}, "by_tf": {}}
    w7 = stats([x for *_s, x in rows if x["exit_time"] >= since7], ft)
    return {"since_start": _brief(t["all"]), "7d": compact(w7),
            "by_tf": {tf: tiny(c) for tf, c in t["by_tf"].items()}, "note": BRIEF_NOTE}


BRIEF_NOTE = ("손익비 숫자(코드 계산): payoff = 평균 이익 ÷ |평균 손실|(자금 대비), breakeven_win_rate = 본전 승률, "
              "gap_pp = 실제 승률 − 본전 승률(%p), exit_share = 청산 이유 비율(LOCK 익절 잠금, SL 손절, LIQ 강제청산). "
              "규칙은 30일 동안 고정: 개선 생각은 5년 시험(lock_start 15·20·30%, stop_atr 1.5·2.5·3 ATR)으로만. small = 10건 미만")


def brief_many(paper_ro: Optional[sqlite3.Connection], strategies: Iterable[str], now_ms: int,
               round_trip: Optional[float] = None) -> dict:
    """{strategy: compact since the start} for the ranking review's picked strategies, plus the coin flips."""
    if paper_ro is None:
        return {"error": "paper3.db 없음"}
    ft = ladder()["first_trigger"]
    rt = round_trip_of(paper_ro) if round_trip is None else round_trip
    ss = list(strategies)
    try:
        rows = closed(paper_ro, 0, now_ms, strategies=ss, round_trip=rt) if ss else []
        flips = [t for *_x, t in closed(paper_ro, 0, now_ms, kinds=("random",), round_trip=rt)]
    except sqlite3.Error as exc:
        return {"error": f"paper3.db를 읽지 못함: {type(exc).__name__}"}
    tab = table(rows, ft)["strategies"]
    return {"strategies": {s: compact((tab.get(s) or {}).get("all") or {"trades": 0}) for s in ss},
            "coin_flips": compact(stats(flips, ft)), "note": BRIEF_NOTE}
