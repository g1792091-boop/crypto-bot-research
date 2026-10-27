"""tradingview/vwap-bot-signals.pine in Python, bar by bar as TradingView runs it (the same steps, the same order, Pine's
own seeds for ta.rma / ta.ema / ta.atr / ta.dmi), so tests/test_tradingview_vwap.py can put each part next to the bot's
own code: the VWAP fail and CMO sandwich signals (paperbot/strategy_view_defs), the 4h judges (paperbot/trendjudge.py),
the volatility gate (paperbot/entrygates.py), the time blocks (paperbot/combo.py, paperbot/events.py) and the ladder
(paperbot/ladder.py). TradingView itself cannot run here: this checks the method, the Pine file is its transcription.

Bars: numpy rows [open_ms, open, high, low, close, volume], oldest first, no gaps (Binance USDT-M klines)."""
from __future__ import annotations

import math
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import numpy as np

MS30, MS1H, MS4H, MSDAY, MIN = 1_800_000, 3_600_000, 14_400_000, 86_400_000, 60_000
NY, SEOUL = ZoneInfo("America/New_York"), ZoneInfo("Asia/Seoul")


# ---------------------------------------------------------------- Pine's built-ins
def pine_rma(x, n: int) -> np.ndarray:
    """ta.rma: na until n values, seeded with their SMA, then alpha 1/n (leading na skipped)."""
    x = np.asarray(x, float)
    out = np.full(len(x), np.nan)
    seen, acc, prev = 0, 0.0, math.nan
    for i, v in enumerate(x):
        if math.isnan(prev):
            if math.isnan(v):
                continue
            seen += 1
            acc += v
            if seen == n:
                prev = acc / n
                out[i] = prev
        else:
            prev = prev if math.isnan(v) else (prev * (n - 1) + v) / n
            out[i] = prev
    return out


def pine_ema(x, n: int) -> np.ndarray:
    """ta.ema with the SMA seed (alpha 2 / (n + 1))."""
    x = np.asarray(x, float)
    out = np.full(len(x), np.nan)
    a = 2.0 / (n + 1)
    seen, acc, prev = 0, 0.0, math.nan
    for i, v in enumerate(x):
        if math.isnan(prev):
            if math.isnan(v):
                continue
            seen += 1
            acc += v
            if seen == n:
                prev = acc / n
                out[i] = prev
        else:
            prev = prev if math.isnan(v) else a * v + (1 - a) * prev
            out[i] = prev
    return out


def pine_sma(x, n: int) -> np.ndarray:
    x = np.asarray(x, float)
    out = np.full(len(x), np.nan)
    for i in range(n - 1, len(x)):
        w = x[i - n + 1:i + 1]
        if not np.isnan(w).any():
            out[i] = w.mean()
    return out


def pine_tr(h, l, c, handle_na: bool) -> np.ndarray:
    pc = np.r_[np.nan, c[:-1]]
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    tr[0] = (h[0] - l[0]) if handle_na else np.nan
    return tr


def pine_atr(h, l, c, n: int = 14) -> np.ndarray:
    return pine_rma(pine_tr(h, l, c, True), n)


def roll(x, n: int, f) -> np.ndarray:
    x = np.asarray(x, float)
    out = np.full(len(x), np.nan)
    for i in range(n - 1, len(x)):
        out[i] = f(x[i - n + 1:i + 1])
    return out


def lag(x, k: int) -> np.ndarray:
    x = np.asarray(x, float)
    out = np.full(len(x), np.nan)
    if k < len(x):
        out[k:] = x[:len(x) - k]
    return out


def gtz(x, y) -> np.ndarray:
    with np.errstate(invalid="ignore"):
        return np.asarray(x, float) > np.asarray(y, float)


def ltz(x, y) -> np.ndarray:
    with np.errstate(invalid="ignore"):
        return np.asarray(x, float) < np.asarray(y, float)


# ---------------------------------------------------------------- the script's own functions
def quantile_window(vals: list, win: int, q: float) -> float:
    """f_quantile over f_push's window: the last ``win`` values (this bar's included), numpy-linear, na under half."""
    w = [v for v in vals[-win:] if not math.isnan(v)]
    if len(w) < max(win // 2, 1):
        return math.nan
    w.sort()
    pos = (len(w) - 1) * q
    lo = math.floor(pos)
    hi = min(lo + 1, len(w) - 1)
    return w[lo] + (w[hi] - w[lo]) * (pos - lo)


def f6(bars: np.ndarray) -> dict:
    """VWAP (UTC day) and the VWAP fail signal per 30m bar: {"vwap", "sig"} (+1 / -1 / 0)."""
    t, o, h, l, c, v = (bars[:, k] for k in range(6))
    n = len(c)
    vw = np.full(n, np.nan)
    sig = np.zeros(n, int)
    cpv = cv = 0.0
    lastS = lastL = -1
    lastSD = lastLD = -1
    killedS = usedS = killedL = usedL = False
    day = (t // MSDAY).astype(np.int64)
    for i in range(n):
        new = i == 0 or day[i] != day[i - 1]
        if new:
            cpv = cv = 0.0
        cpv += (h[i] + l[i] + c[i]) / 3 * v[i]
        cv += v[i]
        vw[i] = cpv / cv if cv > 0 else math.nan
        ok = (not new) and not math.isnan(vw[i - 1]) and not math.isnan(vw[i])
        brk_dn = ok and c[i - 1] >= vw[i - 1] and c[i] < vw[i]
        brk_up = ok and c[i - 1] <= vw[i - 1] and c[i] > vw[i]
        known = not math.isnan(vw[i])
        rt_s, back_s = known and h[i] >= vw[i], known and c[i] < vw[i] and c[i] < o[i]
        rt_l, back_l = known and l[i] <= vw[i], known and c[i] > vw[i] and c[i] > o[i]
        kill_s, kill_l = known and c[i] > vw[i], known and c[i] < vw[i]
        has_s = lastS >= 0 and i - lastS <= 10 and lastSD == day[i]
        has_l = lastL >= 0 and i - lastL <= 10 and lastLD == day[i]
        f_s = has_s and not killedS and not usedS and rt_s and back_s
        f_l = has_l and not killedL and not usedL and rt_l and back_l
        if brk_dn:
            lastS, lastSD, killedS, usedS = i, day[i], False, False
        else:
            killedS, usedS = killedS or kill_s, usedS or (rt_s and back_s)
        if brk_up:
            lastL, lastLD, killedL, usedL = i, day[i], False, False
        else:
            killedL, usedL = killedL or kill_l, usedL or (rt_l and back_l)
        sig[i] = 1 if f_l else (-1 if f_s else 0)
    return {"vwap": vw, "sig": sig}


def cmo(c, n: int = 14) -> np.ndarray:
    d = np.r_[np.nan, np.diff(c)]
    up = roll(np.where(gtz(d, 0), d, 0.0), n, np.sum)
    dn = roll(np.where(ltz(d, 0), -d, 0.0), n, np.sum)
    den = up + dn
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(den == 0, np.nan, 100.0 * (up - dn) / den)


def s3(bars: np.ndarray, win: int, q: float) -> dict:
    """f_s3 per 1h bar: {"sig", "atr", "atrp", "q"} (q on every bar: the script computes it on signal bars)."""
    o, h, l, c = (bars[:, k] for k in range(1, 5))
    a = pine_atr(h, l, c, 14)
    b = c - o
    b1, b2, b3 = lag(b, 2), lag(b, 1), b
    up_prior, dn_prior = gtz(lag(c, 3), lag(c, 7)), ltz(lag(c, 3), lag(c, 7))
    with np.errstate(invalid="ignore"):
        bodies = (np.abs(b1) >= 0.08 * a) & (np.abs(b2) >= 0.08 * a) & (np.abs(b3) >= 0.08 * a)
        h2, l2 = lag(h, 2), lag(l, 2)
        bear = up_prior & bodies & (b1 > 0) & (b2 < 0) & (b3 > 0) & (np.abs(h2 - h) <= 0.3 * a) \
            & (c <= np.maximum(h2, h) + 0.075 * a)
        bull = dn_prior & bodies & (b1 < 0) & (b2 > 0) & (b3 < 0) & (np.abs(l2 - l) <= 0.3 * a) \
            & (c >= np.minimum(l2, l) - 0.075 * a)
    cm = cmo(c, 14)
    cm1 = lag(cm, 1)
    with np.errstate(invalid="ignore"):
        cmu, cmd = (cm > 0) & (cm1 <= 0), (cm < 0) & (cm1 >= 0)

    def recent3(x):
        return x | np.r_[False, x[:-1]] | np.r_[False, False, x[:-2]]
    with np.errstate(invalid="ignore"):
        lo_ = recent3(bull) & recent3(cmu) & (cm > 0) & (bull | cmu)
        sh_ = recent3(bear) & recent3(cmd) & (cm < 0) & (bear | cmd)
    sig = np.where(lo_, 1, np.where(sh_, -1, 0))
    atrp = a / c
    buf, qs = [], np.full(len(c), np.nan)
    for i in range(len(c)):
        buf.append(atrp[i])
        qs[i] = quantile_window(buf, win, q)
    return {"sig": sig, "atr": a, "atrp": atrp, "q": qs}


def judges(bars: np.ndarray) -> dict:
    """f_judges per 4h bar: each judge (+1 / -1 / 0) and the up / down counts."""
    o, h, l, c, v = (bars[:, k] for k in range(1, 6))
    n = len(c)
    pc0 = np.r_[c[0], c[:-1]]                                   # nz(close[1], close)
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc0), np.abs(l - pc0)))
    at10 = pine_rma(tr, 10)
    hl = (h + l) / 2
    bl, bu = hl - 3.0 * at10, hl + 3.0 * at10
    lower = upper = math.nan
    d = 1
    v39 = np.zeros(n, int)
    for i in range(n):
        pL = bl[i] if math.isnan(lower) else lower
        pU = bu[i] if math.isnan(upper) else upper
        pc = c[i - 1] if i > 0 else math.nan
        nL = math.nan if math.isnan(bl[i]) else (max(bl[i], pL) if (not math.isnan(pc) and not math.isnan(pL) and pc > pL) else bl[i])
        nU = math.nan if math.isnan(bu[i]) else (min(bu[i], pU) if (not math.isnan(pc) and not math.isnan(pU) and pc < pU) else bu[i])
        if d == -1 and not math.isnan(pU) and c[i] > pU:
            d = 1
        elif d == 1 and not math.isnan(pL) and c[i] < pL:
            d = -1
        lower, upper = nL, nU
        v39[i] = d
    e20 = pine_ema(c, 20)
    up_m = np.r_[np.nan, np.diff(h)]
    dn_m = np.r_[np.nan, -np.diff(l)]
    with np.errstate(invalid="ignore"):
        pdm = np.where(np.isnan(up_m), np.nan, np.where((up_m > dn_m) & (up_m > 0), up_m, 0.0))
        mdm = np.where(np.isnan(dn_m), np.nan, np.where((dn_m > up_m) & (dn_m > 0), dn_m, 0.0))
    trur = pine_rma(pine_tr(h, l, c, False), 14)
    with np.errstate(invalid="ignore", divide="ignore"):
        dip = 100 * pine_rma(pdm, 14) / trur
        dim = 100 * pine_rma(mdm, 14) / trur
    s6 = np.where(gtz(c, e20) & gtz(dip, dim), 1, np.where(ltz(c, e20) & gtz(dim, dip), -1, 0))
    ch = np.r_[np.nan, np.diff(c)]
    obv = np.cumsum(np.where(np.isnan(ch), 0.0, np.sign(ch) * np.nan_to_num(v)))
    ma = pine_sma(obv, 30)
    jo = np.where(gtz(obv, ma), 1, np.where(ltz(obv, ma), -1, 0))
    hh = lambda k: roll(h, k, np.max)                            # noqa: E731
    ll = lambda k: roll(l, k, np.min)                            # noqa: E731
    sa = lag(((hh(9) + ll(9)) / 2 + (hh(26) + ll(26)) / 2) / 2, 26)
    sb = lag((hh(52) + ll(52)) / 2, 26)
    top, bot = np.fmax(sa, sb), np.fmin(sa, sb)
    ao = pine_sma(hl, 5) - pine_sma(hl, 34)
    n12 = np.where(gtz(c, top) & gtz(ao, 0), 1, np.where(ltz(c, bot) & ltz(ao, 0), -1, 0))
    m = np.vstack([v39, s6, jo, n12])
    return {"V39": v39, "S6": s6, "OBV": jo, "N12": n12, "up": (m > 0).sum(0), "down": (m < 0).sum(0)}


def judged_4h_open(close_ms: int) -> int:
    """The open of the 4h bar the script reads at a 30m bar closing at ``close_ms``: the one that closes with it (end4h),
    else the one before the 4h bar the 30m bar is in."""
    return close_ms - MS4H if close_ms % MS4H == 0 else (close_ms - MS30) // MS4H * MS4H - MS4H


def weekend(ts: int) -> bool:
    return datetime.fromtimestamp(ts / 1000, tz=SEOUL).weekday() >= 5


def us_open(ts: int, holidays) -> bool:
    ny = datetime.fromtimestamp(ts / 1000, tz=NY)
    since = ny.hour * 60 + ny.minute - 570
    return ny.weekday() < 5 and ny.strftime("%Y-%m-%d") not in holidays and -30 <= since < 30


def macro(ts: int, events: list) -> bool:
    return any(abs(e - ts) <= 30 * MIN for e in events)


def lock_for(best: float, first=0.08, gap=0.02, step=0.04):
    trig = first + gap
    return first + step * math.floor((best - trig) / step + 1e-9) if best >= trig - 1e-12 else None


def lock_price(side: int, entry: float, lev: float, lock: float, rt: float) -> float:
    return entry * (1.0 + side * (lock / lev + rt))


def to_utc(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
