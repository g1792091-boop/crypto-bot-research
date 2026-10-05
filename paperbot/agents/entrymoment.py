"""The moment of entry: how the closed strategy trades turned out, split by what the market looked like when they
entered (owners' request 2026-10-04). Code only, descriptive, read-only on paper3.db (trades, live_bars, outcomes),
daily3.db (shadows), liq.db, flow.db and market.db. Nothing here changes an account or a rule; the strategy signal
code is never read or run.

Every bucket carries ``n`` (closed trades), ``wr`` (win rate: pnl > 0), ``roe`` (mean net ROE, 0.01 = 1%) and
``eq`` (mean P&L on the account's equity before the trade: pnl / (equity_after - pnl)); a bucket under ``min_n``
(``SMALL_N`` = riskreward.SMALL_N) trades carries ``small: true``. Many buckets are examined at once
(``multiple_comparisons``): by chance alone about 1 in 20 of them looks "different" at the 5% level, so a bucket
difference is a hypothesis to test later, never a finding.

Dimensions (``DIMS``), each with an ``unknown`` bucket when its data is missing:

- ``strength``    the strategy's own entry-strength features recorded with the signal (entry_marks, trade
                  ``context.strength``), scored on the existing scale of obsshadows.quality_score: the mean period-1
                  quintile (1..5) of the features against the entry study's frozen edges (quality_edges.json).
                  ``weak`` = score <= 2, ``mid`` = 2 < score < 4, ``strong`` = score >= 4 (the tiers base / good /
                  best of docs/observation-shadows-2.md); ``unknown`` = nothing recorded or no edges.
- ``volatility``  ATR14 / close of the signal bar (the trade's timeframe, built from the 1m ``live_bars`` the
                  accounts stepped on; only complete bars) against the same coin and timeframe's ATR14 / close of the
                  bars of the 30 days before (at least ``VOL_MIN_HISTORY`` bars): percentile < 1/3 ``low``, < 2/3
                  ``mid``, else ``high``.
- candle shape of the signal bar (o, h, l, c; range = h - l; body = |c - o|), side-relative ("with" = in the
  trade's direction: up for a long, down for a short):
  ``body``          body / ATR14: ``<0.3``, ``0.3-1``, ``1+``.
  ``wick_against``  the wick on the side the trade does not want (upper for a long, lower for a short) / range:
                    ``<0.2``, ``0.2-0.4``, ``0.4+``.  ``wick_with``: the other wick, same buckets.
  ``close_loc``     where the close sits in the range, measured in the trade's direction ((c - l) / range for a
                    long, (h - c) / range for a short): ``weak`` < 1/3, ``mid`` < 2/3, ``strong``.
  ``streak``        consecutive complete bars of the same colour ending at the signal bar (green c > o, red c < o; a
                    doji ends a run): ``with_1``, ``with_2``, ``with_3+`` when that colour is the trade's direction,
                    ``against_1``, ``against_2+`` when not, ``doji`` when the signal bar itself is a doji.
  ``pattern``       first match of: engulfing = the signal bar's colour is opposite to the previous bar's and its
                    body covers the previous body (min(o, c) <= previous min, max(o, c) >= previous max, larger body);
                    pin bar = hammer (lower wick >= 0.6 range and upper wick <= 0.15 range) or shooting star (the
                    mirror); doji = body <= 0.1 range. ``engulf_with`` / ``engulf_against`` (bullish engulfing is
                    "with" for a long), ``pin_with`` / ``pin_against`` (a hammer is "with" for a long), ``doji``,
                    ``none``.
- ``liq``         liquidation burst before the entry (liq.db, the public forced-order stream; it sends at most one
                  order per coin per second, so bursts are undercounted): a coin's 1-minute liquidation notional
                  (filled qty x average price) is a burst at or above the ``LIQ_BURST_PCT`` percentile of that coin's
                  non-zero minutes in the loaded window (the analysis window plus 30 days before; at least
                  ``LIQ_MIN_MINUTES`` such minutes). ``burst_with`` / ``burst_against`` = a burst minute ended within
                  ``LIQ_AFTER_MIN`` minutes before the entry and its dominant side pushed price with / against the
                  trade (shorts liquidated push up: "with" for a long), ``none`` = no burst, ``unknown`` = no record
                  covering that time.
- 추세 초입·중간·막판 (owners' request 2026-10-06 00:45 KST), from the trade's chart context of the signal bar
  (``context``: paperbot/context.py; the reel's 5m context may lack a field: ``unknown``), side-relative:
  ``trend_stage``  x = ema20_dist_atr x side: ``역방향`` x < 0, ``초입`` 0 <= x < 1, ``중간`` 1 <= x < 2, ``막판`` x >= 2.
  ``range_pos``    range_pct (1 - range_pct for a short): ``아래쪽`` < 0.33, ``가운데``, ``위쪽`` >= 0.67.
  ``trend_align``  regime and htf_regime against the side: ``반대`` when either trends the other way, else ``같은 방향``
                   when either trends this way, else ``횡보·불분명``; ``unknown`` when neither was recorded.
- ``hold``        holding time: ``<30m``, ``30m-2h``, ``2h-8h``, ``8h+``.
- ``funding``     funding rate at the entry: the last settlement at most 9 hours before (market.db ``funding``), else
                  an estimate from the latest completed 5-minute premium index (flow.db ``premium5m``, at most 15
                  minutes old): premium + clamp(0.01% - premium, -0.05%, +0.05%) (Binance's formula with the current
                  premium in place of its 8-hour mean). ``neg`` < 0, ``base`` 0 to 0.01%, ``high`` > 0.01% (positive:
                  longs pay shorts). ``coverage.funding_source`` counts which source each trade used.
- ``weekday``     entry day in Korea time (agents/compare.py ``_kst``).

``skipped_signals``: the signals the strategy accounts did not take (paper3.db ``outcomes``: SKIPPED = a position
already open or a higher-ranked signal entered; REJECTED = guard, sizing, halt) by reason, and for the skipped ones
the nightly check's hypothetical outcome (daily3.db ``shadows`` kind ``skipped``: the same signal alone on a fresh
account, net ROE). REJECTED signals have no hypothetical outcome recorded: counts only.

``packet`` (Wednesday coin and regime meeting, ``coins.entry_moment``) stays under ``MAX_BYTES`` compact JSON;
``strategy_brief`` (a strategy specialist's packet) under ``BRIEF_MAX_BYTES``; ``dash_view`` for the dashboard.
"""

from __future__ import annotations

import bisect
import json
import math
import os
import re
import sqlite3
from typing import Optional

import numpy as np

MIN = 60_000
HOUR_MS = 3_600_000
DAY_MS = 86_400_000
TF_MS = {"5m": 5 * MIN, "15m": 15 * MIN, "30m": 30 * MIN, "1h": HOUR_MS, "4h": 4 * HOUR_MS}

SMALL_N = 10                    # = riskreward.SMALL_N (a test keeps them equal)
MAX_BYTES = 8_000               # the meeting packet's compact JSON
BRIEF_MAX_BYTES = 2_000         # a specialist's brief
NOTABLE = 10                    # strategy buckets furthest from the strategy's own mean ROE

ATR_N = 14
VOL_LOOKBACK_MS = 30 * DAY_MS
VOL_MIN_HISTORY = 50            # bars of the 30 days before the signal bar needed for a percentile
BODY_EDGES = (0.3, 1.0)         # body / ATR14
WICK_EDGES = (0.2, 0.4)         # wick / range
PIN_WICK, PIN_OTHER = 0.6, 0.15
DOJI_BODY = 0.1
STREAK_LOOK = 12
LIQ_BURST_PCT = 0.95
LIQ_AFTER_MIN = 15
LIQ_MIN_MINUTES = 30
FUNDING_BASE = 0.0001
FUNDING_CLAMP = 0.0005
FUNDING_MAX_AGE_MS = 9 * HOUR_MS
PREMIUM_MAX_AGE_MS = 15 * MIN
HOLD_EDGES_MIN = (30, 120, 480)
WEEKDAY_KO = ("월", "화", "수", "목", "금", "토", "일")
# 추세 초입·중간·막판 (owners' request 2026-10-06 00:45 KST; roster3 entry_timing). Edges fixed before any result was
# looked at, read from the trade's chart context of the signal bar (paperbot/context.py, read only):
STAGE_EDGES = (0.0, 1.0, 2.0)   # side-relative EMA20 distance in ATR14 (ema20_dist_atr x side): <0 역방향, <1 초입,
                                # <2 중간, else 막판 (= the loss card's '많이 오른/내린 뒤 추격' at 2 ATR)
RANGE_EDGES = (0.33, 0.67)      # side-relative place in the regime window's range (range_pct; 1 - range_pct for a
                                # short): <0.33 아래쪽, <0.67 가운데, else 위쪽 (위쪽 = far along in the trade's way)
TREND_OF_SIDE = {1: "trend_up", -1: "trend_down"}   # context.regime labels; box / chop / unknown = no trend

BUCKETS = {
    "strength": ("weak", "mid", "strong", "unknown"),
    "volatility": ("low", "mid", "high", "unknown"),
    "trend_stage": ("역방향", "초입", "중간", "막판", "unknown"),
    "range_pos": ("아래쪽", "가운데", "위쪽", "unknown"),
    "trend_align": ("같은 방향", "반대", "횡보·불분명", "unknown"),
    "body": ("<0.3", "0.3-1", "1+", "unknown"),
    "wick_against": ("<0.2", "0.2-0.4", "0.4+", "unknown"),
    "wick_with": ("<0.2", "0.2-0.4", "0.4+", "unknown"),
    "close_loc": ("weak", "mid", "strong", "unknown"),
    "streak": ("with_1", "with_2", "with_3+", "against_1", "against_2+", "doji", "unknown"),
    "pattern": ("engulf_with", "engulf_against", "pin_with", "pin_against", "doji", "none", "unknown"),
    "liq": ("burst_with", "burst_against", "none", "unknown"),
    "hold": ("<30m", "30m-2h", "2h-8h", "8h+"),
    "funding": ("neg", "base", "high", "unknown"),
    "weekday": WEEKDAY_KO,
}
DIMS = tuple(BUCKETS)
# the order dimensions leave a brief that is too big (the least specific first)
BRIEF_DROP = ("weekday", "wick_with", "streak", "hold", "funding", "body", "wick_against", "close_loc", "pattern",
              "liq", "range_pos", "trend_align", "volatility", "trend_stage")
STAGE_DIMS = ("trend_stage", "range_pos", "trend_align")

HOW_TO_READ = ("진입 순간의 모습별 끝난 거래 성적(코드 계산). 칸: n 거래 수, wr 승률, roe 평균 ROE(0.01=1%), eq 자금 대비 평균 "
               "손익. small = 거래 적어 우연일 수 있음. 정의는 회의 안내(진입 순간 칸)에 있음. with/against = 거래 방향과 같은/"
               "반대 쪽. trend_stage 추세 단계(EMA20에서 거래 방향으로 ATR 몇 배: 0 미만 역방향, 0~1 초입, 1~2 중간, 2 이상 "
               "막판), range_pos 최근 범위 안 위치(거래 방향 기준 0.33 미만 아래쪽, 0.67 이상 위쪽), trend_align 이 봉·상위 "
               "봉 장세가 거래와 같은 방향/반대(하나라도 반대면 반대)/횡보·불분명. unknown = 그 자료가 없음")
NOTE = ("설명용 집계일 뿐 규칙이 아님. 칸을 아주 많이 보므로(multiple_comparisons) 20칸 중 1칸쯤은 우연만으로 달라 보임: "
        "칸 차이는 가설로만, 나중 거래로 확인할 예측을 붙여 남김")


# ---------------------------------------------------------------- small helpers
def _f(x, default: float = 0.0) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return default
    return v if math.isfinite(v) else default


def _cut(x: float, edges: tuple, labels: tuple) -> str:
    for e, lab in zip(edges, labels):
        if x < e:
            return lab
    return labels[len(edges)]


def _ro(path: Optional[str]) -> Optional[sqlite3.Connection]:
    """A read-only connection to a side database (liq.db, flow.db, market.db) or None."""
    if not path or not os.path.exists(path):
        return None
    try:
        c = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
        c.execute("PRAGMA query_only = 1")
        return c
    except sqlite3.Error:
        return None


def compact_bytes(obj) -> int:
    return len(json.dumps(obj, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8"))


# ---------------------------------------------------------------- bars (live_bars -> timeframe bars)
def load_live_bars(paper_ro: sqlite3.Connection, symbols, lo: int, hi: int) -> dict:
    """{symbol: (t, o, h, l, c) numpy arrays} of paper3.db ``live_bars`` in [lo, hi), oldest first."""
    out: dict = {}
    for sym in sorted(set(symbols)):
        try:
            rows = paper_ro.execute("SELECT ts, open, high, low, close FROM live_bars WHERE symbol = ? AND ts >= ? "
                                    "AND ts < ? ORDER BY ts", (sym, int(lo), int(hi))).fetchall()
        except sqlite3.Error:
            return {}
        if rows:
            a = np.array(rows, dtype=float)
            out[sym] = (a[:, 0].astype(np.int64), a[:, 1], a[:, 2], a[:, 3], a[:, 4])
    return out


def resample(t: np.ndarray, o, h, l, c, tf_ms: int) -> dict:
    """Complete timeframe bars from 1m bars (every minute present), with Wilder ATR14 and ATR14 / close.
    Keys: key (bar open // tf_ms), o, h, l, c, atr, share (NaN until 14 true ranges)."""
    if len(t) == 0:
        return {"key": np.array([], np.int64)}
    g = t // tf_ms
    keys, start, counts = np.unique(g, return_index=True, return_counts=True)
    full = counts == tf_ms // MIN
    ends = start + counts - 1
    bo = o[start]
    bh = np.maximum.reduceat(h, start)
    bl = np.minimum.reduceat(l, start)
    bc = c[ends]
    keys, bo, bh, bl, bc = keys[full], bo[full], bh[full], bl[full], bc[full]
    n = len(keys)
    atr = np.full(n, np.nan)
    trs: list = []
    a = None
    for i in range(n):
        tr = bh[i] - bl[i]
        if i and keys[i - 1] == keys[i] - 1:
            tr = max(tr, abs(bh[i] - bc[i - 1]), abs(bl[i] - bc[i - 1]))
        if a is None:
            trs.append(tr)
            if len(trs) == ATR_N:
                a = sum(trs) / ATR_N
        else:
            a = (a * (ATR_N - 1) + tr) / ATR_N
        if a is not None:
            atr[i] = a
    with np.errstate(divide="ignore", invalid="ignore"):
        share = np.where(bc > 0, atr / bc, np.nan)
    return {"key": keys, "o": bo, "h": bh, "l": bl, "c": bc, "atr": atr, "share": share}


def _colour(o: float, c: float, h: float, l: float) -> int:
    rng = h - l
    if rng <= 0 or abs(c - o) <= DOJI_BODY * rng:
        return 0
    return 1 if c > o else -1


def candle(b: dict, i: int, side: int) -> dict:
    """Bucket of each candle dimension for the signal bar ``i`` of timeframe bars ``b`` (``resample``)."""
    o, h, l, c = (float(b[k][i]) for k in ("o", "h", "l", "c"))
    atr = float(b["atr"][i])
    rng = h - l
    out = {"body": "unknown", "wick_against": "unknown", "wick_with": "unknown", "close_loc": "unknown"}
    body = abs(c - o)
    if math.isfinite(atr) and atr > 0:
        out["body"] = _cut(body / atr, BODY_EDGES, BUCKETS["body"])
    up, dn = h - max(o, c), min(o, c) - l
    col = _colour(o, c, h, l)
    if rng > 0:
        against, withw = (up, dn) if side > 0 else (dn, up)
        out["wick_against"] = _cut(against / rng, WICK_EDGES, BUCKETS["wick_against"])
        out["wick_with"] = _cut(withw / rng, WICK_EDGES, BUCKETS["wick_with"])
        loc = (c - l) / rng if side > 0 else (h - c) / rng
        out["close_loc"] = _cut(loc, (1 / 3, 2 / 3), BUCKETS["close_loc"])
    # streak of same-colour complete bars ending at i
    if col == 0:
        out["streak"] = "doji"
    else:
        run, j = 1, i
        while run < STREAK_LOOK and j > 0 and b["key"][j - 1] == b["key"][j] - 1 and \
                _colour(*(float(b[k][j - 1]) for k in ("o", "c", "h", "l"))) == col:
            run += 1
            j -= 1
        if col == side:
            out["streak"] = "with_1" if run == 1 else "with_2" if run == 2 else "with_3+"
        else:
            out["streak"] = "against_1" if run == 1 else "against_2+"
    # pattern: engulfing > pin bar > doji > none
    pat = "none"
    if i > 0 and b["key"][i - 1] == b["key"][i] - 1:
        po, pc = float(b["o"][i - 1]), float(b["c"][i - 1])
        pcol = _colour(po, pc, float(b["h"][i - 1]), float(b["l"][i - 1]))
        if col and pcol == -col and min(o, c) <= min(po, pc) and max(o, c) >= max(po, pc) and body > abs(pc - po):
            pat = "engulf_with" if col == side else "engulf_against"
    if pat == "none" and rng > 0:
        if dn >= PIN_WICK * rng and up <= PIN_OTHER * rng:          # hammer: pushes up
            pat = "pin_with" if side > 0 else "pin_against"
        elif up >= PIN_WICK * rng and dn <= PIN_OTHER * rng:        # shooting star: pushes down
            pat = "pin_with" if side < 0 else "pin_against"
    if pat == "none" and col == 0:
        pat = "doji"
    out["pattern"] = pat
    return out


def volatility(b: dict, i: int, close_ms: int, tf_ms: int) -> str:
    v = float(b["share"][i])
    if not math.isfinite(v):
        return "unknown"
    k0 = (close_ms - VOL_LOOKBACK_MS) // tf_ms
    j0 = int(np.searchsorted(b["key"], k0, side="left"))
    hist = b["share"][j0:i]
    hist = hist[np.isfinite(hist)]
    if len(hist) < VOL_MIN_HISTORY:
        return "unknown"
    p = float((hist < v).mean())
    return "low" if p < 1 / 3 else "mid" if p < 2 / 3 else "high"


# ---------------------------------------------------------------- liquidations (liq.db)
def load_liq(liq_path: Optional[str], symbols, lo: int, hi: int) -> Optional[dict]:
    """{symbol: {"start": first record, "minutes": [minute ms], "side": [+1 shorts liquidated (push up) / -1],
    "burst": [bool], "threshold": usd, "nonzero": count}} or None when liq.db is missing / unreadable."""
    c = _ro(liq_path)
    if c is None:
        return None
    out: dict = {}
    try:
        for sym in sorted(set(symbols)):
            first = c.execute("SELECT MIN(trade_ts) FROM liq WHERE symbol = ?", (sym,)).fetchone()[0]
            per: dict = {}
            for m, side, usd in c.execute(
                    "SELECT trade_ts / 60000, side, SUM(COALESCE(filled_qty, qty) * COALESCE(avg_price, price)) "
                    "FROM liq WHERE symbol = ? AND trade_ts >= ? AND trade_ts < ? GROUP BY trade_ts / 60000, side",
                    (sym, int(lo), int(hi))):
                e = per.setdefault(int(m), [0.0, 0.0])        # [longs liquidated (SELL), shorts liquidated (BUY)]
                e[0 if side == "SELL" else 1] += _f(usd)
            mins = sorted(per)
            tot = [per[m][0] + per[m][1] for m in mins]
            nz = sorted(x for x in tot if x > 0)
            thr = nz[min(len(nz) - 1, int(LIQ_BURST_PCT * (len(nz) - 1) + 0.5))] if nz else None
            out[sym] = {"start": None if first is None else int(first), "minutes": [m * MIN for m in mins],
                        "side": [1 if per[m][1] > per[m][0] else -1 for m in mins],
                        "burst": [thr is not None and x >= thr and x > 0 for x in tot],
                        "threshold": thr, "nonzero": len(nz)}
    except sqlite3.Error:
        return None
    finally:
        c.close()
    return out


def liq_bucket(liq: Optional[dict], sym: str, entry: int, side: int) -> str:
    e = (liq or {}).get(sym)
    if not e or e["start"] is None or e["nonzero"] < LIQ_MIN_MINUTES or e["start"] > entry - LIQ_AFTER_MIN * MIN:
        return "unknown"
    mins = e["minutes"]
    j0 = bisect.bisect_left(mins, entry - LIQ_AFTER_MIN * MIN)
    j1 = bisect.bisect_right(mins, entry - MIN)                 # the minute ended at or before the entry
    push = [e["side"][j] for j in range(j0, j1) if e["burst"][j]]
    if not push:
        return "none"
    s = sum(push)
    if s == 0:
        s = push[-1]                                           # a tie: the latest burst's side
    return "burst_with" if (s > 0) == (side > 0) else "burst_against"


# ---------------------------------------------------------------- funding (market.db, flow.db)
def load_funding(market_path: Optional[str], flow_path: Optional[str], symbols, lo: int, hi: int) -> dict:
    """{"settled": {sym: ([time], [rate])}, "premium": {sym: ([close time], [premium close])}}."""
    out: dict = {"settled": {}, "premium": {}}
    syms = sorted(set(symbols))
    c = _ro(market_path)
    if c is not None:
        try:
            for sym in syms:
                rows = c.execute("SELECT funding_time, rate FROM funding WHERE symbol = ? AND funding_time >= ? AND "
                                 "funding_time < ? ORDER BY funding_time", (sym, int(lo), int(hi))).fetchall()
                if rows:
                    out["settled"][sym] = ([int(r[0]) for r in rows], [_f(r[1]) for r in rows])
        except sqlite3.Error:
            pass
        finally:
            c.close()
    c = _ro(flow_path)
    if c is not None:
        try:
            for sym in syms:
                rows = c.execute("SELECT ts, close FROM premium5m WHERE symbol = ? AND ts >= ? AND ts < ? AND close IS "
                                 "NOT NULL ORDER BY ts", (sym, int(lo), int(hi))).fetchall()
                if rows:
                    out["premium"][sym] = ([int(r[0]) + 5 * MIN for r in rows], [_f(r[1]) for r in rows])
        except sqlite3.Error:
            pass
        finally:
            c.close()
    return out


def funding_at(fund: dict, sym: str, entry: int) -> tuple[Optional[float], str]:
    """(rate, source) at ``entry``: the last settlement within 9 h, else the premium estimate, else (None, '')."""
    s = fund["settled"].get(sym)
    if s:
        j = bisect.bisect_right(s[0], entry) - 1
        if j >= 0 and entry - s[0][j] <= FUNDING_MAX_AGE_MS:
            return s[1][j], "settled"
    p = fund["premium"].get(sym)
    if p:
        j = bisect.bisect_right(p[0], entry) - 1
        if j >= 0 and entry - p[0][j] <= PREMIUM_MAX_AGE_MS:
            prem = p[1][j]
            return prem + min(max(FUNDING_BASE - prem, -FUNDING_CLAMP), FUNDING_CLAMP), "premium_est"
    return None, ""


def funding_bucket(rate: Optional[float]) -> str:
    if rate is None:
        return "unknown"
    if rate < -1e-9:
        return "neg"
    return "base" if rate <= FUNDING_BASE + 1e-9 else "high"


# ---------------------------------------------------------------- strength, hold, weekday
def strength_bucket(d: dict, strategy: str, tf: str) -> str:
    ctx = d.get("context") if isinstance(d.get("context"), dict) else {}
    st = ctx.get("strength")
    if not isinstance(st, dict):
        return "unknown"
    try:
        from ..obsshadows import quality_score
        q = quality_score(st, strategy, tf)
    except Exception:  # noqa: BLE001  (a description only: missing edges or an odd record is 'unknown')
        return "unknown"
    return {"base": "weak", "good": "mid", "best": "strong"}.get(q.get("tier"), "unknown")


def hold_bucket(minutes: float) -> str:
    return _cut(minutes, HOLD_EDGES_MIN, BUCKETS["hold"])


def weekday_bucket(entry_ms: int) -> str:
    from .compare import _kst
    return WEEKDAY_KO[_kst(int(entry_ms))[1]]


# ---------------------------------------------------------------- trend stage, range position, trend alignment
def _ctx_of(d: dict) -> dict:
    c = d.get("context") if isinstance(d, dict) else None
    return c if isinstance(c, dict) else {}


def _num(x) -> Optional[float]:
    if isinstance(x, bool) or x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def trend_stage_bucket(ctx: dict, side: int) -> str:
    """역방향 / 초입 / 중간 / 막판 from the side-relative EMA20 distance in ATR14 (``STAGE_EDGES``)."""
    x = _num((ctx or {}).get("ema20_dist_atr"))
    if x is None:
        return "unknown"
    return _cut(x * (1 if side > 0 else -1), STAGE_EDGES, BUCKETS["trend_stage"])


def range_pos_bucket(ctx: dict, side: int) -> str:
    """아래쪽 / 가운데 / 위쪽 of the side-relative range_pct (``RANGE_EDGES``)."""
    x = _num((ctx or {}).get("range_pct"))
    if x is None:
        return "unknown"
    # rounded: 1 - 0.67 is 0.32999999999999996 in floats, and a short at range_pct 0.67 sits on the 0.33 edge
    return _cut(round(x if side > 0 else 1.0 - x, 12), RANGE_EDGES, BUCKETS["range_pos"])


def trend_align_bucket(ctx: dict, side: int) -> str:
    """The signal bar's regime and the higher timeframe's (``htf_regime``) against the trade: 반대 when either is a trend
    the other way (the loss cards' '추세 반대 진입' / '상위 봉 추세 반대'), else 같은 방향 when either is a trend this way,
    else 횡보·불분명 (box, chop, 'unknown' label); ``unknown`` when neither label was recorded."""
    regs = [v for v in ((ctx or {}).get("regime"), (ctx or {}).get("htf_regime")) if isinstance(v, str) and v]
    if not regs:
        return "unknown"
    s = 1 if side > 0 else -1
    if TREND_OF_SIDE[-s] in regs:
        return "반대"
    if TREND_OF_SIDE[s] in regs:
        return "같은 방향"
    return "횡보·불분명"


def stage_buckets(d: dict, side: int) -> dict:
    ctx = _ctx_of(d)
    return {"trend_stage": trend_stage_bucket(ctx, side), "range_pos": range_pos_bucket(ctx, side),
            "trend_align": trend_align_bucket(ctx, side)}


# ---------------------------------------------------------------- per-trade features
def features(paper_ro: sqlite3.Connection, now_ms: int, since_ms: int = 0, strategy: Optional[str] = None,
             liq_path: Optional[str] = None, flow_path: Optional[str] = None,
             market_path: Optional[str] = None, kinds: tuple = ("strategy",),
             timeframes: Optional[tuple] = None) -> dict:
    """{"window", "rows": [{kind, strategy, timeframe, symbol, side, pnl, roe, eq, b: {dim: bucket}}], "coverage"} of
    the accounts' trades closed in [since_ms, now_ms) (one strategy when ``strategy`` is given). ``kinds`` = the
    account kinds (default the 36: 'strategy'; DeepSeek 'ds200', the reel 'reel', coin flips 'random');
    ``timeframes`` None = the core timeframes (digest.TFS); the reel and its coin flips pass ('5m',)."""
    from .digest import _closed
    raw = [x for x in _closed(paper_ro, since_ms, now_ms, kinds=tuple(kinds), tfs=timeframes)
           if strategy is None or x[2] == strategy]
    rows: list = []
    cov = {"trades": len(raw), "candle": 0, "volatility": 0, "strength": 0, "liq": 0, "trend_stage": 0,
           "funding_source": {"settled": 0, "premium_est": 0, "none": 0}}
    if not raw:
        return {"window": {"from": since_ms, "to": now_ms}, "rows": rows, "coverage": cov}
    syms = {str(d.get("symbol")) for *_x, d in raw}
    first = min(int(_f(d.get("signal_ts"), _f(d.get("entry_time")))) for *_x, d in raw)
    last = max(int(_f(d.get("entry_time"))) for *_x, d in raw)
    lo, hi = first - VOL_LOOKBACK_MS - 4 * HOUR_MS * (ATR_N + 2), last + MIN
    bars = load_live_bars(paper_ro, syms, lo, hi)
    tfb: dict = {}
    liq = load_liq(liq_path, syms, first - VOL_LOOKBACK_MS, hi)
    fund = load_funding(market_path, flow_path, syms, first - DAY_MS, hi)
    for _aid, kind, strat, tf, d in raw:
        sym = str(d.get("symbol"))
        side = 1 if _f(d.get("side")) > 0 else -1
        entry, exit_ = int(_f(d.get("entry_time"))), int(_f(d.get("exit_time")))
        pnl, eq_after = _f(d.get("pnl")), _f(d.get("equity_after"))
        before = eq_after - pnl
        b = {dim: "unknown" for dim in DIMS}
        tf = tf or d.get("timeframe")
        tf_ms = TF_MS.get(tf)
        if tf_ms and sym in bars:
            if (sym, tf) not in tfb:
                tfb[(sym, tf)] = resample(*bars[sym], tf_ms)
            bb = tfb[(sym, tf)]
            close_ms = int(_f(d.get("signal_ts"), entry - 1)) + 1
            key = close_ms // tf_ms - 1
            i = int(np.searchsorted(bb["key"], key))
            if i < len(bb["key"]) and bb["key"][i] == key:
                b.update(candle(bb, i, side))
                cov["candle"] += 1
                b["volatility"] = volatility(bb, i, close_ms, tf_ms)
                cov["volatility"] += b["volatility"] != "unknown"
        b["strength"] = strength_bucket(d, strat, tf)
        cov["strength"] += b["strength"] != "unknown"
        b["liq"] = liq_bucket(liq, sym, entry, side)
        cov["liq"] += b["liq"] != "unknown"
        rate, src = funding_at(fund, sym, entry)
        b["funding"] = funding_bucket(rate)
        cov["funding_source"][src or "none"] += 1
        b["hold"] = hold_bucket((exit_ - entry) / MIN)
        b["weekday"] = weekday_bucket(entry)
        b.update(stage_buckets(d, side))
        cov["trend_stage"] += b["trend_stage"] != "unknown"
        rows.append({"kind": kind, "strategy": strat, "timeframe": tf, "symbol": sym, "side": side, "pnl": pnl,
                     "roe": _f(d.get("roe")), "eq": pnl / before if before > 0 else None, "b": b})
    if liq is None:
        cov["liq_note"] = "liq.db 없음"
    if not bars:
        cov["bars_note"] = "live_bars 기록 없음"
    return {"window": {"from": since_ms, "to": now_ms}, "rows": rows, "coverage": cov}


# ---------------------------------------------------------------- cells and tables
def cell(rs: list, min_n: int = SMALL_N) -> dict:
    n = len(rs)
    if not n:
        return {"n": 0}
    eqs = [r["eq"] for r in rs if r.get("eq") is not None]
    c = {"n": n, "wr": round(sum(1 for r in rs if r["pnl"] > 0) / n, 3), "roe": round(sum(r["roe"] for r in rs) / n, 4),
         "eq": round(sum(eqs) / len(eqs), 5) if eqs else None}
    if n < min_n:
        c["small"] = True
    return c


def table(rows: list, min_n: int = SMALL_N, dims=DIMS, eq: bool = True) -> dict:
    """{dim: {bucket: cell}} with only the buckets that have trades, in ``BUCKETS`` order."""
    out: dict = {}
    for dim in dims:
        groups: dict = {}
        for r in rows:
            groups.setdefault(r["b"].get(dim, "unknown"), []).append(r)
        t = {}
        for k in BUCKETS[dim]:
            if groups.get(k):
                c = cell(groups[k], min_n)
                if not eq:
                    c.pop("eq", None)
                t[k] = c
        out[dim] = t
    return out


def _examined(tab: dict) -> tuple[int, int]:
    """(buckets with trades, of them not small) of a ``table``, 'unknown' left out (no comparison is made on it)."""
    n = big = 0
    for t in tab.values():
        for k, c in t.items():
            if k == "unknown":
                continue
            n += 1
            big += not c.get("small")
    return n, big


def _multiple(examined: int, big: int) -> dict:
    return {"buckets_examined": examined, "buckets_not_small": big,
            "chance_hits_at_5pct": round(0.05 * big, 1),
            "note": f"칸 {examined}개를 봄(작지 않은 칸 {big}개): 우연만으로도 약 {round(0.05 * big, 1)}개는 5% 수준에서 "
                    "달라 보임. 가장 달라 보이는 칸은 그중 최댓값이라 실제보다 크게 보이기 쉬움"}


# ---------------------------------------------------------------- shadows of the signals not taken
def skipped_signals(paper_ro: Optional[sqlite3.Connection], daily_ro: Optional[sqlite3.Connection], since_ms: int,
                    until_ms: int, strategy: Optional[str] = None, entered_rows: Optional[list] = None,
                    kinds: tuple = ("strategy",), timeframes: Optional[tuple] = None) -> dict:
    """Counts of the strategy accounts' signals not taken by status and reason (paper3.db ``outcomes``) and the
    hypothetical outcome of the skipped ones (daily3.db ``shadows`` kind 'skipped'). ``kinds`` / ``timeframes`` as
    ``features`` (``timeframes`` None = any timeframe of those kinds, as before)."""
    out: dict = {}
    accts: dict = {}
    if paper_ro is not None:
        try:
            accts = {a: s for a, s, k, tf in paper_ro.execute("SELECT account_id, strategy, kind, timeframe FROM accounts")
                     if k in kinds and (strategy is None or s == strategy)
                     and (timeframes is None or tf in timeframes)}
            by: dict = {}
            for aid, status, reason, n in paper_ro.execute(
                    "SELECT account_id, status, reason, COUNT(*) FROM outcomes WHERE status != 'ENTERED' AND "
                    "step_ts >= ? AND step_ts < ? GROUP BY account_id, status, reason", (since_ms, until_ms)):
                if aid in accts:
                    k = f"{status}:{re.sub(r'[-+]?[0-9][0-9.]*', '#', str(reason))[:40]}"
                    by[k] = by.get(k, 0) + int(n)
            out["not_taken"] = dict(sorted(by.items(), key=lambda kv: -kv[1])[:8])
        except sqlite3.Error:
            out["not_taken"] = {"note": "outcomes 표를 읽지 못함"}
    rows = None
    if daily_ro is not None:
        try:
            rows = daily_ro.execute("SELECT key, account_id, roe, resolved FROM shadows WHERE kind = 'skipped'").fetchall()
        except sqlite3.Error:
            rows = None
    if rows is None:
        out["skipped_outcome"] = {"note": "가상 결과 기록 없음(daily3.db shadows 없음): 건너뛴 신호의 결과는 말할 수 없음"}
    else:
        got = []
        for key, aid, roe, resolved in rows:
            try:
                bc = int(str(key).rsplit("|", 1)[1])
            except (IndexError, ValueError):
                continue
            if aid in accts and since_ms <= bc < until_ms:
                got.append((roe, resolved))
        done = [_f(r) for r, ok in got if ok and r is not None]
        sk = {"signals": len(got), "resolved": len(done)}
        if done:
            sk.update(wr=round(sum(1 for r in done if r > 0) / len(done), 3), roe=round(sum(done) / len(done), 4))
            if len(done) < SMALL_N:
                sk["small"] = True
        if entered_rows:
            sk["entered_roe"] = round(sum(r["roe"] for r in entered_rows) / len(entered_rows), 4)
        out["skipped_outcome"] = sk
    out["note"] = ("SKIPPED(포지션 보유 중·다른 신호 우선)만 밤 점검이 같은 신호를 새 계좌에 혼자 돌린 가상 ROE가 있음. "
                   "REJECTED(가드·크기·정지)는 가상 결과 기록이 없어 수만 셈")
    return out


# ---------------------------------------------------------------- the meeting packet, the brief, the dashboard
def _notable(rows: list, min_n: int, names_ko: Optional[dict], k: int = NOTABLE) -> tuple[list, int, int]:
    """Per strategy and dimension, the buckets (not small, not unknown) furthest from the strategy's own mean ROE,
    ranked by |difference| x sqrt(n). Returns (top ``k``, buckets examined, of them not small)."""
    per: dict = {}
    for r in rows:
        per.setdefault(r["strategy"], []).append(r)
    cand, ex, big = [], 0, 0
    for s, rs in per.items():
        mean = sum(r["roe"] for r in rs) / len(rs)
        tab = table(rs, min_n, eq=False)
        e, b = _examined(tab)
        ex, big = ex + e, big + b
        for dim, t in tab.items():
            for bk, c in t.items():
                if bk == "unknown" or c.get("small") or c["n"] >= len(rs):
                    continue
                diff = c["roe"] - mean
                cand.append((abs(diff) * math.sqrt(c["n"]), {
                    "strategy": s, **({"name_ko": names_ko[s]} if names_ko and s in names_ko else {}),
                    "dim": dim, "bucket": bk, "n": c["n"], "wr": c["wr"], "roe": c["roe"],
                    "strategy_roe": round(mean, 4), "strategy_n": len(rs)}))
    cand.sort(key=lambda x: -x[0])
    return [c for _s, c in cand[:k]], ex, big


def packet_from(feat: dict, skipped: Optional[dict] = None, min_n: int = SMALL_N, names_ko: Optional[dict] = None,
                max_bytes: int = MAX_BYTES, money: bool = True) -> dict:
    """``money`` False (DeepSeek, coin flips: CONTRACT section 1, D11): no ``eq`` column anywhere."""
    rows = feat["rows"]
    out: dict = {"window": feat["window"], "trades": len(rows), "min_n": min_n, "coverage": feat["coverage"]}
    if not rows:
        out["note"] = "이 기간에 끝난 매매법 거래 없음"
        return out
    tab = table(rows, min_n, eq=money)
    e_all, b_all = _examined(tab)
    notable, e_s, b_s = _notable(rows, min_n, names_ko)
    out["all"] = tab
    out["notable"] = notable
    if skipped is not None:
        out["skipped_signals"] = skipped
    out["multiple_comparisons"] = _multiple(e_all + e_s, b_all + b_s)
    out["how_to_read"] = HOW_TO_READ
    out["note"] = NOTE
    # bounded: the per-strategy list shrinks first, then the equity column of the whole table
    while compact_bytes(out) > max_bytes and out["notable"]:
        out["notable"].pop()
    if compact_bytes(out) > max_bytes:
        for t in out["all"].values():
            for c in t.values():
                c.pop("eq", None)
    if compact_bytes(out) > max_bytes:
        out["all"].pop("weekday", None)
        out["trimmed"] = True
    for dim in BRIEF_DROP:                      # still too big (more dimensions since 2026-10-06): the least specific
        if compact_bytes(out) <= max_bytes:
            break
        out["all"].pop(dim, None)
    return out


def packet(paper_ro: Optional[sqlite3.Connection], now_ms: int, since_ms: int = 0,
           daily_ro: Optional[sqlite3.Connection] = None, liq_path: Optional[str] = None,
           flow_path: Optional[str] = None, market_path: Optional[str] = None, min_n: int = SMALL_N,
           names_ko: Optional[dict] = None, feat: Optional[dict] = None, kinds: tuple = ("strategy",),
           timeframes: Optional[tuple] = None) -> dict:
    """The Wednesday coin and regime meeting's ``entry_moment`` (all strategy trades closed since ``since_ms``);
    ``kinds`` / ``timeframes`` as ``features`` (DeepSeek and coin flips: no ``eq``)."""
    if paper_ro is None:
        return {"error": "paper3.db 없음"}
    try:
        feat = feat or features(paper_ro, now_ms, since_ms, liq_path=liq_path, flow_path=flow_path,
                                market_path=market_path, kinds=kinds, timeframes=timeframes)
        sk = skipped_signals(paper_ro, daily_ro, since_ms, now_ms, entered_rows=feat["rows"], kinds=kinds,
                             timeframes=timeframes)
    except sqlite3.Error as exc:
        return {"error": f"paper3.db를 읽지 못함: {type(exc).__name__}"}
    return packet_from(feat, sk, min_n, names_ko, money=has_money(kinds))


def strategy_brief_from(feat: dict, strategy: str, min_n: int = SMALL_N, max_bytes: int = BRIEF_MAX_BYTES) -> dict:
    rows = [r for r in feat["rows"] if r["strategy"] == strategy]
    out: dict = {"trades": len(rows), "min_n": min_n}
    if not rows:
        out["note"] = "끝난 거래 없음"
        return out
    tab = table(rows, min_n, eq=False)
    for t in tab.values():
        t.pop("unknown", None)
    e, b = _examined(tab)
    out["roe"] = round(sum(r["roe"] for r in rows) / len(rows), 4)
    out["buckets"] = tab
    out["multiple_comparisons"] = {"buckets_examined": e, "buckets_not_small": b}
    out["note"] = "진입 순간 모습별 성적(코드, 설명용). small은 우연일 수 있고, 칸이 많아 차이는 가설로만"
    left = []
    for dim in BRIEF_DROP:
        if compact_bytes(out) <= max_bytes:
            break
        tab.pop(dim, None)
        left.append(dim)
    if left:
        out["left_out"] = left
    return out


def strategy_brief(paper_ro: Optional[sqlite3.Connection], strategy: str, now_ms: int, since_ms: int = 0,
                   liq_path: Optional[str] = None, flow_path: Optional[str] = None,
                   market_path: Optional[str] = None, feat: Optional[dict] = None) -> dict:
    """One strategy's buckets for its specialist (compact, under ``BRIEF_MAX_BYTES``)."""
    if paper_ro is None:
        return {"error": "paper3.db 없음"}
    try:
        feat = feat or features(paper_ro, now_ms, since_ms, strategy=strategy, liq_path=liq_path,
                                flow_path=flow_path, market_path=market_path)
    except sqlite3.Error as exc:
        return {"error": f"paper3.db를 읽지 못함: {type(exc).__name__}"}
    return strategy_brief_from(feat, strategy)


def dash_view(paper_ro: Optional[sqlite3.Connection], now_ms: int, since_ms: int = 0,
              daily_ro: Optional[sqlite3.Connection] = None, liq_path: Optional[str] = None,
              flow_path: Optional[str] = None, market_path: Optional[str] = None,
              names_ko: Optional[dict] = None, kinds: tuple = ("strategy",),
              timeframes: Optional[tuple] = None) -> dict:
    """For the dashboard: the whole table, the notable strategy buckets, coverage, the not-taken signals and the
    multiple-comparison count (the same numbers as the meeting packet, bounded the same way). ``kinds`` /
    ``timeframes`` as ``features``; ``group_dash_view`` picks them per v4 group."""
    pk = packet(paper_ro, now_ms, since_ms, daily_ro=daily_ro, liq_path=liq_path, flow_path=flow_path,
                market_path=market_path, names_ko=names_ko, kinds=kinds, timeframes=timeframes)
    if "error" in pk:
        return pk
    return {"generated_ms": now_ms, "dims": list(DIMS), "bucket_order": {k: list(v) for k, v in BUCKETS.items()},
            **{k: pk.get(k) for k in ("window", "trades", "min_n", "coverage", "all", "notable", "skipped_signals",
                                      "multiple_comparisons", "how_to_read", "note") if k in pk}}


# ---------------------------------------------------------------- v4 groups (owners' request 2026-10-06 00:45 KST)
# The entry analyses cover DeepSeek and the reel too, not only the 36. Each group is read on its own timeframes
# (the 36 and DeepSeek: the core 15m-4h; the reel: 5m) and the reel is set next to ITS three 5m coin flips (same 5m
# bars, long only, the reel's exits) the way the 36 are set next to theirs elsewhere (coin meeting all_strategies /
# coin_flips, risk view all / coin_flips): the same buckets side by side. DeepSeek and the coin flips are counted only
# (CONTRACT section 1, D11): no eq, no money; n, win rate and ROE only.
GROUPS = ("core", "ds200", "reel")
GROUP_LABEL_KO = {"core": "기존 36 매매법", "ds200": "딥시크", "reel": "릴스 5분 단타"}
REEL_TFS = ("5m",)                       # config.REEL_TF (a test keeps them equal)
NO_MONEY_KINDS = ("ds200", "random")
GROUP_BRIEF_MAX_BYTES = 6_000            # a v4 group room's entry-moment section
FLIPS_NOTE = ("coin_flips = 같은 칸의 5분봉 동전 던지기 3개(같은 5분봉, 롱만, 릴스와 같은 청산, 비교용): 동전도 같은 칸에서 "
              "지면 릴스 진입 탓이 아니라 그 시장 모습 탓일 수 있음. 동전은 개수·승률·ROE만")


def has_money(kinds) -> bool:
    """False for DeepSeek and the coin flips (counted only)."""
    return not any(k in NO_MONEY_KINDS for k in kinds)


def group_scope(group: str) -> tuple:
    """(kinds, timeframes) of a v4 group: the 36 and DeepSeek on the core timeframes (None), the reel on 5m."""
    if group == "ds200":
        return ("ds200",), None
    if group == "reel":
        return ("reel",), REEL_TFS
    return ("strategy",), None


def _no_eq(x):
    if isinstance(x, dict):
        return {k: _no_eq(v) for k, v in x.items() if k != "eq"}
    if isinstance(x, list):
        return [_no_eq(v) for v in x]
    return x


def _bare(c: dict) -> dict:
    """A cell without money: n, wr, roe (and small)."""
    return {k: c[k] for k in ("n", "wr", "roe", "small") if k in c}


def flips_side_by_side(flip_rows: list, min_n: int = SMALL_N, dims=DIMS) -> dict:
    """The coin flips' cells in the same buckets (n, wr, roe only: counted only) and their total."""
    return {"flip_trades": len(flip_rows), "flip_all": _bare(cell(flip_rows, min_n)) if flip_rows else {"n": 0},
            "coin_flips": table(flip_rows, min_n, dims, eq=False)}


def group_dash_view(paper_ro: Optional[sqlite3.Connection], now_ms: int, group: str = "core", since_ms: int = 0,
                    daily_ro: Optional[sqlite3.Connection] = None, liq_path: Optional[str] = None,
                    flow_path: Optional[str] = None, market_path: Optional[str] = None,
                    names_ko: Optional[dict] = None) -> dict:
    """``dash_view`` for one v4 group (``GROUPS``): 'core' is exactly ``dash_view`` (plus ``group``); 'ds200' has no
    money (``no_money``: no eq anywhere); 'reel' carries its three 5m coin flips' cells side by side (``coin_flips``)."""
    g = group if group in GROUPS else "core"
    kinds, tfs = group_scope(g)
    if g != "core" and names_ko is None and paper_ro is not None:
        try:
            from ..groups import label_ko
            names_ko = {s: label_ko(s) or s for (s,) in paper_ro.execute(
                f"SELECT DISTINCT strategy FROM accounts WHERE kind IN ({','.join('?' * len(kinds))})", kinds)}
        except (ImportError, sqlite3.Error):
            names_ko = None
    v = dash_view(paper_ro, now_ms, since_ms, daily_ro=daily_ro, liq_path=liq_path, flow_path=flow_path,
                  market_path=market_path, names_ko=names_ko, kinds=kinds, timeframes=tfs)
    if "error" in v:
        return {**v, "group": g}
    v["group"], v["group_label"] = g, GROUP_LABEL_KO[g]
    if g == "reel":
        try:
            ff = features(paper_ro, now_ms, since_ms, liq_path=liq_path, flow_path=flow_path, market_path=market_path,
                          kinds=("random",), timeframes=REEL_TFS)
            v.update(flips_side_by_side(ff["rows"], v.get("min_n", SMALL_N)))
            v["coin_flips_note"] = FLIPS_NOTE
        except sqlite3.Error as exc:
            v["coin_flips"] = {"error": type(exc).__name__}
    if not has_money(kinds):
        v = _no_eq(v)
        v["no_money"] = True
    return v


def group_brief(rows: list, families: Optional[dict] = None, flip_rows: Optional[list] = None,
                min_n: int = SMALL_N, max_bytes: int = GROUP_BRIEF_MAX_BYTES) -> dict:
    """A v4 group room's entry-moment section (money-free: n, wr, roe only, CONTRACT section 1). ``rows`` = the room's
    accounts' ``features`` rows. ``families`` {strategy: family} (DeepSeek): per family the total and the three
    stage dimensions (trend_stage, range_pos, trend_align). ``flip_rows`` (the reel): the 5m coin flips' cells in the
    same buckets side by side. Dimensions are left out in ``BRIEF_DROP`` order until it fits ``max_bytes``."""
    out: dict = {"trades": len(rows), "min_n": min_n}
    if not rows:
        out["note"] = "이 방 계좌의 끝난 거래 없음"
        if flip_rows is not None:
            out["flip_trades"] = len(flip_rows)
        return out
    out["all"] = _bare(cell(rows, min_n))
    tab = table(rows, min_n, eq=False)
    for t in tab.values():
        t.pop("unknown", None)
    out["buckets"] = tab
    if families:
        per: dict = {}
        for r in rows:
            per.setdefault(families.get(r["strategy"]) or "?", []).append(r)
        fam = {}
        for f, rs in sorted(per.items()):
            ft = table(rs, min_n, dims=STAGE_DIMS, eq=False)
            for t in ft.values():
                t.pop("unknown", None)
            fam[f] = {**_bare(cell(rs, min_n)), **{d: t for d, t in ft.items() if t}}
        out["families"] = fam
    ftab = None
    if flip_rows is not None:
        side = flips_side_by_side(flip_rows, min_n)
        ftab = side["coin_flips"]
        for t in ftab.values():
            t.pop("unknown", None)
        out.update(flip_trades=side["flip_trades"], flip_all=side["flip_all"], coin_flips=ftab,
                   coin_flips_note=FLIPS_NOTE)
    e, b = _examined(tab)
    out["multiple_comparisons"] = {"buckets_examined": e, "buckets_not_small": b,
                                   "chance_hits_at_5pct": round(0.05 * b, 1)}
    out["how_to_read"] = HOW_TO_READ.replace("eq 자금 대비 평균 손익. ", "")
    out["note"] = NOTE
    left = []
    for dim in BRIEF_DROP:
        if compact_bytes(out) <= max_bytes:
            break
        tab.pop(dim, None)
        if ftab is not None:
            ftab.pop(dim, None)
        left.append(dim)
    if compact_bytes(out) > max_bytes and "families" in out:
        out["families"] = {f: _bare(c) for f, c in out["families"].items()}
        left.append("families.stage")
    if left:
        out["left_out"] = left
    return out
