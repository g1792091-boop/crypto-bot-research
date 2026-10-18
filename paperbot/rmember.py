"""Research members of the combined bot (owners 2026-10-18): one setting of the 5-year search (2020-01..2026-09,
fixed rules: BTC 40x / others 30x, margin 40%, ladder 10% at 11% then +3%, one position), computed live exactly as
the search simulated it. A research member is a custom-number member (``numbers``) with these extra keys:

- ``invert`` (true): trade the other side of the strategy's signal.
- ``filter`` ([[tag, value], ...], all must hold) on tags at the signal bar's close T and the traded side:
  ``session`` (KST hour 09-17 0 asia, 17-22 1 europe, 06-09 3 dawn, else 2 us), ``weekend`` (KST Sat/Sun 1),
  ``btc`` (1: the last closed BTC 4h close is on the side's side of its EMA50; 0 for the first 50 bars),
  ``ctr4`` (1: the coin's last closed 4h close vs its EMA50 agrees with the side), ``mom24`` (1: the sign of the coin's
  1h-close return over the last 24 hours agrees), ``vol3`` (the coin's 1h ATR14 as % of price, its rank among the last
  500 hours: 0 low / 1 mid / 2 high third; 1 while unknown), ``fund`` (1: the last settled funding rate is paid by the
  side), ``side`` (1 long / -1 short).
- ``disp`` ([kind, k]) on the signal bar, from 1m bars (its tf minutes before T): "range" keeps high - low >= k ATR,
  "body" keeps an aligned body (open of the minute at T minus the bar's first open) >= k ATR, "small" range < k ATR.
- ``entry``: "now" (the open of the minute at T) or "break" (the open of the minute after the first minute, within
  the next tf minutes, that trades beyond the signal bar's high (long) / low (short); otherwise no trade).
- ``stop``: ["atr", k] (k x ATR14 of the signal bar, pulled in to fit inside liquidation, at least 1 ATR: the house
  atr_fit), ["pct", p] (p % of the fill), ["swing", n] (beyond the lowest low (long) / highest high (short) of the n x tf
  minutes before the entry minute, + 0.1 % of the price, at least 0.3 %); pct and swing are pulled in to 0.2 % of the
  fill inside liquidation.
- ``off`` ([[dim, value], ...]; any one that matches skips the trade): the buckets the search switched off, read at
  the entry minute E: ``sym`` (0 BTC 1 ETH 2 SOL 3 DOGE 4 LTC 5 BCH), ``side``, ``symside`` (sym*2 + long),
  ``hb`` (KST 4-hour block 0-5), ``hr`` (KST hour), ``dow`` (KST weekday, 0 Monday), the signal-time tags ``wk`` (weekend),
  ``btc``, ``ctr4``, ``mom24``, ``vol3``, ``fund``; ``reg`` (BTC 4h at E: 2 range when ADX14 < 20, else 0 up when the
  close is above EMA50, 1 down), ``regwk`` (reg*2 + wk), ``regside`` (reg*2 + long), ``reg5`` (4 range, 0 strong up
  ADX >= 30, 1 weak up, 2 strong down, 3 weak down), ``reg5side``, ``pos`` (the entry minute's open in the coin's 1m
  high-low range of the 10,080 minutes ending an hour before: 0 below, 1 bottom 20 %, 2 middle, 3 top 20 %, 4 above),
  ``posside``, ``oi24`` (open interest change over 24 hours: 0 < -5 %, 1 flat, 2 > +5 %, 3 unknown).

The definitions are the search's (scratchpad loop: autosearch.evaluate, prune.table, prune2.enrich, regime,
regime2, tags2, rd.tags, dispf); ``tests/test_rmember.py`` checks them on fixed arrays. ``RData`` keeps the market data
these rules read, from Binance (or arrays in the replay test)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np

MIN = 60_000
H1 = 3_600_000
H4 = 14_400_000
DAY = 86_400_000
KST_MS = 9 * H1
SYMS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT")
TF_MIN = {"15m": 15, "30m": 30, "1h": 60, "4h": 240}
FILTER_KEYS = ("session", "weekend", "btc", "ctr4", "mom24", "vol3", "fund", "side")
SIG_TAGS = ("session", "weekend", "btc", "ctr4", "mom24", "vol3", "fund")
OFF_DIMS = ("sym", "side", "symside", "hb", "hr", "dow", "wk", "btc", "ctr4", "mom24", "vol3", "fund", "reg", "regwk",
            "regside", "reg5", "reg5side", "pos", "posside", "oi24")
STOP_MODES = ("atr", "pct", "swing")
DISP_KINDS = ("range", "body", "small")
POS_WIN = 10_080                     # minutes in the 7-day range
POS_SHIFT = 60                       # ... ending an hour before the entry minute
POS_MINP = 5_000                     # rolling min_periods of the search
KO_DIM = {"sym": "코인", "side": "방향", "symside": "코인x방향", "hb": "4시간대", "hr": "시각", "dow": "요일",
          "wk": "주말", "btc": "BTC추세", "ctr4": "코인4h추세", "mom24": "24h모멘텀", "vol3": "변동성", "fund": "펀딩",
          "reg": "장세", "regwk": "장세x주말", "regside": "장세x방향", "reg5": "추세세기", "reg5side": "추세세기x방향",
          "pos": "7일위치", "posside": "7일위치x방향", "oi24": "미결제약정"}


class RSpecError(ValueError):
    """A research member's settings the combined bot refuses (message in Korean)."""


@dataclass(frozen=True)
class RSpec:
    stop: tuple                       # ("atr", k) | ("pct", p) | ("swing", n)
    entry: str = "now"
    invert: bool = False
    filter: tuple = ()                # ((tag, value), ...)
    disp: Optional[tuple] = None      # (kind, k)
    off: frozenset = frozenset()      # {(dim, value), ...}
    cell: Optional[str] = None        # the search's cell id, for the record


def parse_spec(sp: dict, where: str) -> Optional[RSpec]:
    """The research keys of a member spec -> RSpec, or None when the spec has none of them."""
    keys = ("stop", "entry", "invert", "filter", "disp", "off", "cell")
    if not any(k in sp for k in keys):
        return None
    st = sp.get("stop")
    if not (isinstance(st, (list, tuple)) and len(st) == 2 and st[0] in STOP_MODES
            and isinstance(st[1], (int, float)) and st[1] > 0):
        raise RSpecError(f'{where}: stop은 ["atr", k] / ["pct", p] / ["swing", n] 형식입니다')
    entry = sp.get("entry", "now")
    if entry not in ("now", "break"):
        raise RSpecError(f'{where}: entry는 "now" 또는 "break"입니다')
    inv = sp.get("invert", False)
    if not isinstance(inv, bool):
        raise RSpecError(f"{where}: invert는 true/false입니다")
    flt = []
    for f in sp.get("filter") or []:
        if not (isinstance(f, (list, tuple)) and len(f) == 2 and f[0] in FILTER_KEYS and isinstance(f[1], int)):
            raise RSpecError(f"{where}: filter 항목 {f!r} (있는 것: {', '.join(FILTER_KEYS)}; 값은 정수)")
        flt.append((str(f[0]), int(f[1])))
    disp = sp.get("disp")
    if disp is not None:
        if not (isinstance(disp, (list, tuple)) and len(disp) == 2 and disp[0] in DISP_KINDS
                and isinstance(disp[1], (int, float))):
            raise RSpecError(f'{where}: disp는 ["range"|"body"|"small", k] 형식입니다')
        disp = (str(disp[0]), float(disp[1]))
    off = set()
    for c in sp.get("off") or []:
        if not (isinstance(c, (list, tuple)) and len(c) == 2 and c[0] in OFF_DIMS and isinstance(c[1], int)):
            raise RSpecError(f"{where}: off 항목 {c!r} (있는 것: {', '.join(OFF_DIMS)}; 값은 정수)")
        off.add((str(c[0]), int(c[1])))
    return RSpec(stop=(str(st[0]), float(st[1])), entry=entry, invert=inv, filter=tuple(flt), disp=disp,
                 off=frozenset(off), cell=sp.get("cell"))


def describe(r: RSpec) -> str:
    stop = {"atr": f"{r.stop[1]:g} ATR", "pct": f"{r.stop[1]:g}%", "swing": f"스윙 {r.stop[1]:g}봉"}[r.stop[0]]
    out = f"손절 {stop}, 진입 {'즉시' if r.entry == 'now' else '돌파 확인'}" + (", 방향 반대로" if r.invert else "")
    if r.filter:
        out += ", 조건 " + " ".join(f"{k}={v}" for k, v in r.filter)
    if r.disp:
        out += f", 신호봉 {r.disp[0]} {r.disp[1]:g}ATR"
    if r.off:
        by: dict = {}
        for d, v in r.off:
            by[d] = by.get(d, 0) + 1
        out += ", 끄기 " + " ".join(f"{KO_DIM.get(d, d)}{n}" for d, n in sorted(by.items()))
    return out


# ====================================================================== pure definitions (arrays, oldest first)
def kst_hour(t: int) -> int:
    return int((int(t) + KST_MS) // H1 % 24)


def kst_dow(t: int) -> int:
    return int(((int(t) + KST_MS) // DAY + 3) % 7)


def session_of(t: int) -> int:
    hr = kst_hour(t)
    return 0 if 9 <= hr < 17 else 1 if 17 <= hr < 22 else 3 if 6 <= hr < 9 else 2


def ewm_mean(x: np.ndarray, alpha: float) -> np.ndarray:
    """pandas ewm(alpha=..., adjust=False).mean(): leading NaNs stay NaN, a NaN later keeps the last value."""
    out = np.full(len(x), np.nan)
    y = math.nan
    for i, v in enumerate(x):
        if math.isnan(v):
            out[i] = y
            continue
        y = v if math.isnan(y) else (1 - alpha) * y + alpha * v
        out[i] = y
    return out


def ema_sign(c: np.ndarray, span: int = 50, cold: int = 0) -> np.ndarray:
    e = ewm_mean(np.asarray(c, float), 2.0 / (span + 1))
    s = np.sign(np.asarray(c, float) - e)
    if cold:
        s[:cold] = 0
    return s.astype(np.int8)


def adx14(h: np.ndarray, l: np.ndarray, c: np.ndarray) -> np.ndarray:
    """regime.series / regime2._btc5: Wilder ADX14 (ewm alpha 1/14, adjust False) from the first bar."""
    h, l, c = (np.asarray(x, float) for x in (h, l, c))
    up = h - np.r_[h[0], h[:-1]]
    dn = np.r_[l[0], l[:-1]] - l
    pdm = np.where((up > dn) & (up > 0), up, 0.0)
    mdm = np.where((dn > up) & (dn > 0), dn, 0.0)
    pc = np.r_[c[0], c[:-1]]
    tr = np.maximum.reduce([h - l, np.abs(h - pc), np.abs(l - pc)])
    a = 1 / 14
    atr = ewm_mean(tr, a)
    with np.errstate(invalid="ignore", divide="ignore"):
        pdi = 100 * ewm_mean(pdm, a) / atr
        mdi = 100 * ewm_mean(mdm, a) / atr
        den = pdi + mdi
        dx = 100 * np.abs(pdi - mdi) / np.where(den == 0, np.nan, den)
    return ewm_mean(dx, a)


def regimes(h, l, c) -> tuple[np.ndarray, np.ndarray]:
    """(reg, reg5) of each bar (BTC 4h)."""
    c = np.asarray(c, float)
    ema = ewm_mean(c, 2.0 / 51)
    adx = adx14(h, l, c)
    upd = c > ema
    with np.errstate(invalid="ignore"):
        rng = adx < 20
        strong = adx >= 30
    reg = np.where(rng, 2, np.where(upd, 0, 1))
    reg5 = np.where(rng, 4, np.where(upd, np.where(strong, 0, 1), np.where(strong, 2, 3)))
    return reg.astype(np.int8), reg5.astype(np.int8)


def vol_rank(h, l, c, win: int = 500, minp: int = 200) -> np.ndarray:
    """tags2.coin_feats rank: 1h ATR14 % of close, pandas rolling(500, min_periods=200).rank(pct=True)."""
    h, l, c = (np.asarray(x, float) for x in (h, l, c))
    pc = np.r_[np.nan, c[:-1]]
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))   # NaN on the first bar, as pandas
    atrp = ewm_mean(tr, 1 / 14) / c
    out = np.full(len(c), np.nan)
    for i in range(len(c)):
        w = atrp[max(0, i - win + 1):i + 1]
        w = w[~np.isnan(w)]
        if len(w) < minp or math.isnan(atrp[i]):
            continue
        x = atrp[i]
        out[i] = ((w < x).sum() + ((w == x).sum() + 1) / 2) / len(w)
    return out


def last_idx(times: np.ndarray, t: int) -> int:
    return int(np.searchsorted(times, int(t), side="right")) - 1


def pos_bucket(c: float, hi: float, lo: float) -> int:
    if not (math.isfinite(hi) and math.isfinite(lo)):
        return 2
    if c > hi:
        return 4
    if c < lo:
        return 0
    if not hi > lo:
        return 2                  # the search: fraction NaN -> neither end -> middle
    fr = (c - lo) / (hi - lo)
    return 1 if fr < 0.2 else 3 if fr > 0.8 else 2


def oi_bucket(mt: np.ndarray, oi: np.ndarray, t: int) -> int:
    k1, k0 = last_idx(mt, t), last_idx(mt, t - DAY)
    if k1 < 0 or k0 < 0 or int(t) - int(mt[k1]) >= H1:
        return 3
    if not oi[k0] > 0:
        return 3
    ch = float(oi[k1]) / float(oi[k0]) - 1
    if not math.isfinite(ch):
        return 3
    return 0 if ch < -0.05 else 2 if ch > 0.05 else 1


def swing_frac(lows: np.ndarray, highs: np.ndarray, side: int, px: float) -> float:
    """autosearch swing stop: the extreme of the window before the entry minute, + 0.1 %, at least 0.3 %."""
    lv = float(np.min(lows)) if side > 0 else float(np.max(highs))
    return max((px - lv) / px + 0.001 if side > 0 else (lv - px) / px + 0.001, 0.003)


def pct_stop(side: int, raw: float, fill: float, frac: float, liq: float) -> Optional[float]:
    """ck3.trade_pct: stop = fill -/+ min(frac x fill, |fill - liq| - 0.2 % of fill); None when nothing fits."""
    widest = (abs(fill - liq) - 0.002 * fill) * (1 - 1e-6)
    dist = min(frac * fill, widest)
    if not dist > 0:
        return None
    return fill - side * dist


def disp_ok(disp: tuple, side: int, atr: float, highs: np.ndarray, lows: np.ndarray, first_open: float,
            open_at_t: float) -> bool:
    """dispf.mask on the signal bar's tf minutes (highs / lows) and the opens of its first minute and of the minute at T."""
    kind, k = disp
    if not atr > 0:
        return False
    rng = float(np.max(highs)) - float(np.min(lows))
    if kind == "range":
        return rng / atr >= k
    if kind == "small":
        return rng / atr < k
    body = open_at_t - first_open
    return int(np.sign(body)) == int(side) and abs(body) / atr >= k


# ====================================================================== live market data
class RData:
    """Market data of the research rules, per coin. ``klines(symbol, interval, start_ms, end_ms)``: closed bars
    [open_ms, o, h, l, c] with open in [start, end), oldest first; ``funding(symbol, start_ms)``: [(time_ms, rate)];
    ``oi(symbol, start_ms, end_ms)``: [(time_ms, open interest)] 5-minute snapshots. 1m bars come from the stepped
    minutes (``add_1m``), the missing ones from ``klines`` (a start, a gap)."""

    KEEP_1M = POS_WIN + POS_SHIFT + 2_000            # the 7-day range plus the longest swing window (20 x 1h)
    FETCH = {"1h": 1_500, "4h": 1_000}

    def __init__(self, symbols, klines: Callable, funding: Callable, oi: Callable):
        self.symbols = list(symbols)
        self.klines, self.funding_fetch, self.oi_fetch = klines, funding, oi
        self.m1 = {s: {} for s in self.symbols}             # ts -> (o, h, l)
        self._bars: dict = {}                               # (symbol, tf) -> dict of arrays
        self._fund: dict = {}
        self._oi: dict = {}
        self.errors: list[str] = []

    # ---- 1m bars
    def add_1m(self, symbol: str, ts: int, o: float, h: float, l: float) -> None:
        if symbol in self.m1:
            self.m1[symbol][int(ts)] = (float(o), float(h), float(l))

    def trim(self, now: int) -> None:
        lo = int(now) - self.KEEP_1M * MIN
        for s, d in self.m1.items():
            if d and min(d) < lo - 600 * MIN:
                for t in [t for t in d if t < lo]:
                    del d[t]

    def ensure_1m(self, symbol: str, start: int, end: int) -> None:
        """Every minute with open in [start, end) present (fetched from Binance when not)."""
        d = self.m1[symbol]
        need = [t for t in range(int(start), int(end), MIN) if t not in d]
        if not need:
            return
        t0 = need[0]
        while t0 < end:
            rows = self.klines(symbol, "1m", t0, int(end))
            if not rows:
                break
            for r in rows:
                self.add_1m(symbol, int(r[0]), float(r[1]), float(r[2]), float(r[3]))
            nxt = int(rows[-1][0]) + MIN
            if nxt <= t0:
                break
            t0 = nxt
            if len(rows) < 1000:
                break

    def window_1m(self, symbol: str, start: int, end: int) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """(ts, open, high, low) of the minutes present with open in [start, end)."""
        self.ensure_1m(symbol, start, end)
        d = self.m1[symbol]
        ts = np.array(sorted(t for t in d if start <= t < end), np.int64)
        if not len(ts):
            z = np.zeros(0)
            return ts, z, z, z
        a = np.array([d[t] for t in ts], float)
        return ts, a[:, 0], a[:, 1], a[:, 2]

    def open_at(self, symbol: str, t: int) -> Optional[float]:
        self.ensure_1m(symbol, t, t + MIN)
        v = self.m1[symbol].get(int(t))
        return None if v is None else v[0]

    # ---- 1h / 4h closed bars and what is computed on them
    def bars(self, symbol: str, tf: str, t: int) -> dict:
        """Closed bars of ``tf`` up to ``t`` (re-fetched when a newer closed bar should exist)."""
        ms = H1 if tf == "1h" else H4
        need = int(t) - int(t) % ms                  # the bar closing at or before t
        b = self._bars.get((symbol, tf))
        if b is None or int(b["close_t"][-1]) < need:
            rows = self.klines(symbol, tf, need - self.FETCH[tf] * ms, need)
            if not rows:
                raise RuntimeError(f"{symbol} {tf}: no bars")
            o = np.array([int(r[0]) for r in rows], np.int64)
            h = np.array([float(r[2]) for r in rows]); l = np.array([float(r[3]) for r in rows])
            c = np.array([float(r[4]) for r in rows])
            b = {"close_t": o + ms, "h": h, "l": l, "c": c}
            if tf == "4h":
                b["s50"] = ema_sign(c)
                b["s50cold"] = ema_sign(c, cold=50)
                if symbol == "BTCUSDT":
                    b["reg"], b["reg5"] = regimes(h, l, c)
            else:
                b["rank"] = vol_rank(h, l, c)
            self._bars[(symbol, tf)] = b
        return b

    def last_funding(self, symbol: str, t: int) -> Optional[float]:
        f = self._fund.get(symbol)
        # funding settles on the hour: read again in every new hour and at least every 5 minutes
        if f is None or int(t) // H1 != f["fetched"] // H1 or int(t) - f["fetched"] >= 5 * MIN:
            rows = self.funding_fetch(symbol, int(t) - 3 * DAY)
            ft = np.array([int(x[0]) - int(x[0]) % MIN for x in rows], np.int64)
            fr = np.array([float(x[1]) for x in rows])
            f = {"t": ft, "r": fr, "fetched": int(t)}
            self._fund[symbol] = f
        j = last_idx(f["t"], t)
        return None if j < 0 else float(f["r"][j])

    def oi_at(self, symbol: str, t: int) -> int:
        o = self._oi.get(symbol)
        if o is None or not 0 <= int(t) - o["fetched"] < 5 * MIN:
            rows = self.oi_fetch(symbol, int(t) - DAY - 2 * H1, int(t) + MIN)
            o = {"t": np.array([int(x[0]) for x in rows], np.int64), "v": np.array([float(x[1]) for x in rows]),
                 "fetched": int(t)}
            self._oi[symbol] = o
        return oi_bucket(o["t"], o["v"], t)

    # ---- the tags
    def signal_tags(self, symbol: str, side: int, t: int) -> dict:
        """The search's tags at the signal bar's close t for the traded side (rd.tags, tags2.tags)."""
        out = {"session": session_of(t), "weekend": int(kst_dow(t) >= 5), "side": int(side)}
        b4 = self.bars("BTCUSDT", "4h", t)
        j = last_idx(b4["close_t"], t)
        out["btc"] = int(j >= 0 and int(b4["s50cold"][j]) == side)
        c4 = self.bars(symbol, "4h", t)
        j4 = last_idx(c4["close_t"], t)
        out["ctr4"] = int(j4 >= 0 and int(c4["s50"][j4]) == side)
        c1 = self.bars(symbol, "1h", t)
        j1, j0 = last_idx(c1["close_t"], t), last_idx(c1["close_t"], t - 24 * H1)
        r = c1["c"][max(j1, 0)] / c1["c"][max(j0, 0)] - 1
        out["mom24"] = int(j0 >= 0 and int(np.sign(r)) == side)
        rk = c1["rank"][max(j1, 0)]
        out["vol3"] = 1 if math.isnan(rk) else (0 if rk < 1 / 3 else 1 if rk < 2 / 3 else 2)
        fr = self.last_funding(symbol, t)
        out["fund"] = int(fr is not None and side * fr > 0)
        return out

    def entry_dims(self, symbol: str, side: int, t: int, o_entry: float, sig: dict) -> dict:
        """Every ``off`` dimension at the entry minute t (``sig``: the signal-time tags)."""
        long = int(side > 0)
        si = SYMS.index(symbol)
        b4 = self.bars("BTCUSDT", "4h", t)
        j = last_idx(b4["close_t"], t)
        reg = int(b4["reg"][j]) if j >= 0 else 2
        reg5 = int(b4["reg5"][j]) if j >= 0 else 4
        lo_t = int(t) - (POS_SHIFT + POS_WIN - 1) * MIN
        ts, _o, h, l = self.window_1m(symbol, lo_t, int(t) - (POS_SHIFT - 1) * MIN)
        pos = pos_bucket(o_entry, float(h.max()), float(l.min())) if len(ts) >= POS_MINP else 2
        try:
            oi = self.oi_at(symbol, t)
        except Exception as exc:  # noqa: BLE001  unknown, as the search's rows without data
            self.errors.append(f"{symbol} open interest: {type(exc).__name__}: {exc}"[:200])
            oi = 3
        hr = kst_hour(t)
        d = {"sym": si, "side": int(side), "symside": si * 2 + long, "hb": hr // 4, "hr": hr, "dow": kst_dow(t),
             "wk": sig["weekend"], "btc": sig["btc"], "ctr4": sig["ctr4"], "mom24": sig["mom24"], "vol3": sig["vol3"],
             "fund": sig["fund"], "reg": reg, "regwk": reg * 2 + sig["weekend"], "regside": reg * 2 + long,
             "reg5": reg5, "reg5side": reg5 * 2 + long, "pos": pos, "posside": pos * 2 + long, "oi24": oi}
        return d


def filter_fails(r: RSpec, tags: dict) -> list:
    return [f"{k}={v}" for k, v in r.filter if int(tags[k]) != v]


def off_hits(r: RSpec, dims: dict) -> list:
    return sorted(f"{d}={v}" for d, v in r.off if int(dims[d]) == v)
