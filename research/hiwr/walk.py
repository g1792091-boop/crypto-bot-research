"""Track 2 exit events (PREREG_HIWR.md section 7): one pass over the 1m bars per coin and timeframe finds, for every
candidate bar and both sides, the first event of every stop, every take-profit (taker and maker fill) and every
liquidation level; a pair's trades are then lookups (``pair_sums``, ``trade_list``). Read-only research code: public
prices in, numbers out, nothing trades.

One trade (section 7, long shown, a short is the mirror):
- entry: market order at the open P0 of minute e = kernel._entry_index (the first 1m bar after the signal-bar close);
  fill F = P0 x (1 + 0.0002); taker fee 0.05%;
- take-profit T = F x (1 + t), t the TP step's price move (2.1: net reading, ROE / L + 0.14% taker, + 0.09% maker;
  ``tp_move``). Taker TP: triggers when the 1m high reaches T, fills at T x (1 - 0.0002), or at a gapped open (open at
  or beyond T) x (1 - 0.0002); taker fee. Maker TP: fills only when the high trades through T (strictly) or a minute
  opens beyond T, always AT T (also on a gapped open); maker fee 0.02%, no slippage. ``pierce`` (read R7) asks for a
  move beyond T x (1 + pierce) instead (fill still at T);
- stop S = P0 - D, D = k x ATR14 of the signal bar (k in 1, 1.5, 2, 3) or p x P0 (p in 0.60 .. 1.50%); a stop-market
  on last price: fills at S x (1 - 0.0002) when the low touches S, or at a gapped open x (1 - 0.0002); taker fee;
- liquidation level Lq = F x (1 - d) with d from kernel._liq (isolated, one-way; the trade list uses the first
  bracket, ``first_tier_liqd``), checked on mark price;
- order inside a minute (7.5): the entry minute has no open checks; from the next minute on: mark open beyond Lq,
  open beyond S, open beyond T; then stop touched, mark through Lq, TP touched (taker) / traded through (maker). Event
  code = 8 x minute index + phase (0 .. 5), so the earliest code of a pair's stop, TP and liquidation is its exit;
- coin end (7.6): a coin whose tradable span ends inside the period closes a still-open position at its last bar's
  close as a stop-market order (phase 6). Period end: no event (code -1), "open at end" in the trade list;
- costs and the net result (7.7): r = side x (X / F - 1) - taker - fee_exit x X / F - funding / notional, funding =
  every funding event while open (minutes e+1 .. exit) on mark open x quantity. Liquidation: r = -1/L - taker (the
  whole isolated margin and the entry fee). As kernel._trade, a stop or coin-end fill whose loss is beyond the margin
  (side x (X / F - 1) < -1/L) counts as a liquidation. The liquidation level does not move with funding (funding is
  paid from the wallet, 7.6); kernel._trade moves it with the margin. Cost x2 (``cost=2`` tables): taker 0.10%,
  slippage 0.04% (so F and with it T and Lq move), maker 0.04%, funding unchanged, t unchanged (7.7).
- skips (7.3, 7.4): stop not wider than the TP (|F - S| / F <= t: "stop inside TP"); stop room at the tier with the
  house buffer: |F - S| + max(0.2% F, ATR14) <= |F - Lq| ("no stop room"); both judged at cost x1.
"""

from __future__ import annotations

import os
import sys

import numpy as np

try:
    from numba import njit
except ImportError:  # pragma: no cover  the server installs numba; the tests skip without it
    def njit(*a, **k):
        if a and callable(a[0]):
            return a[0]
        return lambda f: f

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from research.hiwr import data as D  # noqa: E402

K = D.fg_run().K                         # research/fullgrid/kernel.py, read-only: _entry_index, _liq, _bracket
_k_entry_index = K._entry_index
_k_liq = K._liq

# ------------------------------------------------------------------ the registered numbers
TAKER, SLIP, MAKER = 0.0005, 0.0002, 0.0002          # 7.7
RT_TAKER = 2 * TAKER + 2 * SLIP                      # 0.14%: round trip with a taker TP or a stop
RT_MAKER = TAKER + SLIP + MAKER                      # 0.09%: round trip with a maker TP
LEVS = (30, 40, 50)                                  # 6.5
ROE_STEPS = {30: (0.09, 0.105, 0.12), 40: (0.12, 0.135, 0.15), 50: (0.15, 0.165, 0.18)}   # 2.1, Q18
STOPS = (("atr", 1.0), ("atr", 1.5), ("atr", 2.0), ("atr", 3.0),
         ("pct", 0.006), ("pct", 0.0075), ("pct", 0.010), ("pct", 0.0125), ("pct", 0.015))  # 7.3, Q19 (family order)
STOP_ATR = np.array([v for f, v in STOPS if f == "atr"])
STOP_PCT = np.array([v for f, v in STOPS if f == "pct"])
FILLS = ("taker", "maker")
BUF_MIN, BUF_ATR = 0.002, 1.0                        # 7.4 house buffer max(0.2% F, 1 x ATR14)
DAY = 86_400_000
WEEK = 7 * DAY
MONDAY0 = 4 * DAY                                    # 1970-01-05 00:00 UTC was a Monday
# event phases inside a minute (7.5) and exit kinds
PH_OPEN_LIQ, PH_OPEN_STOP, PH_OPEN_TP, PH_STOP, PH_LIQ, PH_TP, PH_COIN_END = 0, 1, 2, 3, 4, 5, 6
X_STOP, X_TP, X_LIQ, X_COIN_END, X_OPEN = 0, 1, 2, 3, 4
# pair sums (``pair_sums``): one row of float64 per exit config
S_N, S_WIN, S_SUM, S_SQ, S_SUMR, S_LIQ, S_END, S_N2, S_SUM2, S_WIN2, S_ROOM, S_INSIDE, S_OPEN, S_NOENTRY, S_SUMW, \
    S_SUML = range(16)
NSUM = 16
SUM_NAMES = ("n", "wins", "sum_r", "sum_r2", "sum_rR", "liq", "coin_end", "n_x2", "sum_r_x2", "wins_x2", "skip_room",
             "skip_stop_inside_tp", "skip_open_at_end", "skip_no_entry", "sum_win_r", "sum_loss_r")


def stop_name(k: int) -> str:
    fam, v = STOPS[k]
    return f"{v:g}ATR" if fam == "atr" else f"{v * 100:g}%"


def tp_move(L: int, roe: float, fill: int, reading: str = "net") -> float:
    """Price move of the TP from the fill (2.1): net (the rule) ROE / L + round trip of that fill; gross (read R4)
    ROE / L. Rounded to 10 decimals so that equal moves of different tiers are one level."""
    if reading == "net":
        return round(roe / L + (RT_TAKER if fill == 0 else RT_MAKER), 10)
    if reading == "gross":
        return round(roe / L, 10)
    raise ValueError(reading)


def exit_configs(reading: str = "net", levs=LEVS) -> list[dict]:
    """The 162 exit configs of a combo (6.3) in grid order: tier 30 < 40 < 50, TP step, stop as listed, taker before
    maker (the 10.5 tie order)."""
    out = []
    for Li, L in enumerate(levs):
        for st, roe in enumerate(ROE_STEPS[L]):
            for k in range(len(STOPS)):
                for fill in (0, 1):
                    out.append({"Li": Li, "L": L, "step": st, "roe": roe, "k": k, "stop": stop_name(k), "fill": fill,
                                "fill_name": FILLS[fill], "t": tp_move(L, roe, fill, reading), "reading": reading})
    return out


def exit_label(c: dict) -> str:
    """'L<tier>|TP<price move %>|<stop>|<fill>' (the exit part of a pick id, section 11)."""
    tp = f"{c['t'] * 100:.4f}".rstrip("0").rstrip(".")
    return f"L{c['L']}|TP{tp}|{c['stop']}|{c['fill_name']}"


def tp_sets(cfgs) -> tuple:
    """(taker levels, maker levels, per config its index in its fill's levels) for the walk."""
    tt = sorted({c["t"] for c in cfgs if c["fill"] == 0})
    tm = sorted({c["t"] for c in cfgs if c["fill"] == 1})
    ti = np.array([(tt if c["fill"] == 0 else tm).index(c["t"]) for c in cfgs], np.int64)
    return np.array(tt, float), np.array(tm, float), ti


def cfg_arrays(cfgs, tp_t, tp_m) -> dict:
    tt, tm = list(tp_t), list(tp_m)
    return {"Li": np.array([c["Li"] for c in cfgs], np.int64), "L": np.array([c["L"] for c in cfgs], float),
            "k": np.array([c["k"] for c in cfgs], np.int64), "fill": np.array([c["fill"] for c in cfgs], np.int64),
            "ti": np.array([(tt if c["fill"] == 0 else tm).index(c["t"]) for c in cfgs], np.int64),
            "t": np.array([c["t"] for c in cfgs], float)}


# ------------------------------------------------------------------ candidates
def weekend(close_ms) -> np.ndarray:
    """Signal-bar close at or after Saturday 00:00 UTC and before Monday 00:00 UTC (2.4, 5)."""
    return ((np.asarray(close_ms, np.int64) - MONDAY0) % WEEK) >= 5 * DAY


def liq_price(side: int, F: float, N: float, L: float, mmr: float, cum: float) -> float:
    """Binance's isolated one-way liquidation price for notional N at tier L (kernel._liq: qty N / F, margin N / L)."""
    return float(_k_liq(side, N / F, F, N / L, mmr, cum))


def first_tier_liqd(br: np.ndarray, levs=LEVS) -> np.ndarray:
    """(2 sides, tiers) distance of the liquidation price from the fill for a notional in the first bracket (the trade
    list's planned notional, 7.4). With cum 0 it depends on neither the notional nor the fill. A tier the first bracket
    cannot hold gets 0 (every candidate then lacks stop room)."""
    mmr, cum = float(br[0, 2]), float(br[0, 3])
    if cum != 0.0:
        raise ValueError("first bracket with cum != 0")
    out = np.zeros((2, len(levs)))
    for Li, L in enumerate(levs):
        if br[0, 1] < L:
            continue
        for s, side in ((0, 1), (1, -1)):
            lp = liq_price(side, 1.0, 1.0, float(L), mmr, cum)
            out[s, Li] = side * (1.0 - lp)
    return out


@njit(cache=True)
def entry_indices(ts, close):
    """kernel._entry_index for every chart bar close (-1: no minute after it)."""
    out = np.empty(len(close), np.int64)
    for i in range(len(close)):
        out[i] = _k_entry_index(ts, close[i])
    return out


# ------------------------------------------------------------------ the walk
@njit(cache=True)
def _walk(o, h, l, c, mo, mh, ml, end, coin_end, ent, atr, slip, stop_atr, stop_pct, tp_t, tp_m, liqd, pierce,
          F, sd, sc, sx, tct, txt, tcm, txm, lc, ec, exr):
    """For every row i (entry minute ent[i], ATR atr[i]) and side s (0 long, 1 short): the fill F, the stop distances
    sd = |F - S| / F, and the first event code (8 x minute + phase) and gross return side x (X / F - 1) of every stop
    (sc, sx), every taker TP (tct, txt), every maker TP (tcm, txm), every liquidation level (lc) and the coin end (ec,
    exr). Minutes [ent, end). A row stops walking once every stop or every TP has fired: no later event can be the
    exit of any pair."""
    n = len(ent)
    na = len(stop_atr)
    ns = na + len(stop_pct)
    ntt = len(tp_t)
    ntm = len(tp_m)
    nl = liqd.shape[1]
    S = np.empty(ns)
    Tt = np.empty(ntt)
    Tm = np.empty(ntm)
    Tq = np.empty(ntm)
    Q = np.empty(nl)
    for i in range(n):
        e = ent[i]
        if e < 0 or e >= end:
            continue
        raw = o[e]
        for s in range(2):
            sg = 1.0 if s == 0 else -1.0
            f = raw * (1.0 + sg * slip)
            F[i, s] = f
            for k in range(ns):
                dist = stop_atr[k] * atr[i] if k < na else stop_pct[k - na] * raw
                S[k] = raw - sg * dist
                sd[i, s, k] = sg * (f - S[k]) / f
            for t in range(ntt):
                Tt[t] = f * (1.0 + sg * tp_t[t])
            for t in range(ntm):
                Tm[t] = f * (1.0 + sg * tp_m[t])
                Tq[t] = Tm[t] * (1.0 + sg * pierce)
            for q in range(nl):
                Q[q] = f * (1.0 - sg * liqd[s, q])
            left_s = ns
            left_t = ntt + ntm
            done = False
            for j in range(e, end):
                if j > e:
                    for q in range(nl):
                        if lc[i, s, q] < 0 and (mo[j] - Q[q]) * sg <= 0:
                            lc[i, s, q] = 8 * j + 0
                    for k in range(ns):
                        if sc[i, s, k] < 0 and (o[j] - S[k]) * sg <= 0:
                            sc[i, s, k] = 8 * j + 1
                            sx[i, s, k] = sg * (o[j] * (1.0 - sg * slip) / f - 1.0)
                            left_s -= 1
                    for t in range(ntt):
                        if tct[i, s, t] < 0 and (o[j] - Tt[t]) * sg >= 0:
                            tct[i, s, t] = 8 * j + 2
                            txt[i, s, t] = sg * (o[j] * (1.0 - sg * slip) / f - 1.0)
                            left_t -= 1
                    for t in range(ntm):
                        if tcm[i, s, t] < 0 and (o[j] - Tq[t]) * sg > 0:
                            tcm[i, s, t] = 8 * j + 2
                            txm[i, s, t] = sg * (Tm[t] / f - 1.0)          # a resting limit fills at T (7.2)
                            left_t -= 1
                for k in range(ns):
                    if sc[i, s, k] < 0 and ((l[j] <= S[k]) if sg > 0 else (h[j] >= S[k])):
                        sc[i, s, k] = 8 * j + 3
                        sx[i, s, k] = sg * (S[k] * (1.0 - sg * slip) / f - 1.0)
                        left_s -= 1
                for q in range(nl):
                    if lc[i, s, q] < 0 and ((ml[j] <= Q[q]) if sg > 0 else (mh[j] >= Q[q])):
                        lc[i, s, q] = 8 * j + 4
                for t in range(ntt):
                    if tct[i, s, t] < 0 and ((h[j] >= Tt[t]) if sg > 0 else (l[j] <= Tt[t])):
                        tct[i, s, t] = 8 * j + 5
                        txt[i, s, t] = sg * (Tt[t] * (1.0 - sg * slip) / f - 1.0)
                        left_t -= 1
                for t in range(ntm):
                    if tcm[i, s, t] < 0 and ((h[j] > Tq[t]) if sg > 0 else (l[j] < Tq[t])):
                        tcm[i, s, t] = 8 * j + 5
                        txm[i, s, t] = sg * (Tm[t] / f - 1.0)
                        left_t -= 1
                if left_s == 0 or left_t == 0:
                    done = True
                    break
            if not done and coin_end:
                ec[i, s] = 8 * (end - 1) + 6
                exr[i, s] = sg * (c[end - 1] * (1.0 - sg * slip) / f - 1.0)


class Tables:
    """The exit-event tables of one coin and timeframe over the candidate bars ``bars`` (chart bar indices), at cost
    x1 (``x1``) and cost x2 (``x2``). ``rows`` of a pair index ``bars``."""

    KEYS = ("F", "sd", "sc", "sx", "tct", "txt", "tcm", "txm", "lc", "ec", "exr")

    def __init__(self, arrays: dict, close_ms: np.ndarray, atr: np.ndarray, bars: np.ndarray, end_ms: int,
                 coin_end: bool, liqd: np.ndarray, tp_t: np.ndarray, tp_m: np.ndarray, pierce: float = 0.0,
                 costs=(1, 2)):
        ts = arrays["ts"]
        self.bars = np.asarray(bars, np.int64)
        self.close = np.asarray(close_ms, np.int64)[self.bars]
        self.atr = np.asarray(atr, float)[self.bars]
        self.end = int(np.searchsorted(ts, end_ms))
        self.coin_end = bool(coin_end)
        ent = entry_indices(ts, self.close)
        ent[(ent >= self.end) | ~(np.isfinite(self.atr) & (self.atr > 0))] = -1
        self.ent = ent
        self.ent_ms = np.where(ent >= 0, ts[np.maximum(ent, 0)], -1)
        self.p0 = np.where(ent >= 0, arrays["o"][np.maximum(ent, 0)], np.nan)      # entry reference price P0
        self.weekend = weekend(self.close)
        self.fc = np.cumsum(arrays["mo"] * arrays["fund"])       # funding per unit quantity, cumulative
        self.ts = ts
        self.liqd = np.ascontiguousarray(liqd, float)
        self.tp_t, self.tp_m = np.asarray(tp_t, float), np.asarray(tp_m, float)
        self.pierce = float(pierce)
        self.x = {}
        for cm in costs:
            self.x[cm] = self._walk(arrays, SLIP * cm)

    def _walk(self, a: dict, slip: float) -> dict:
        n, ns, ntt, ntm, nl = len(self.ent), len(STOPS), len(self.tp_t), len(self.tp_m), self.liqd.shape[1]
        T = {"F": np.full((n, 2), np.nan), "sd": np.full((n, 2, ns), np.nan),
             "sc": np.full((n, 2, ns), -1, np.int32), "sx": np.full((n, 2, ns), np.nan),
             "tct": np.full((n, 2, ntt), -1, np.int32), "txt": np.full((n, 2, ntt), np.nan),
             "tcm": np.full((n, 2, ntm), -1, np.int32), "txm": np.full((n, 2, ntm), np.nan),
             "lc": np.full((n, 2, nl), -1, np.int32), "ec": np.full((n, 2), -1, np.int32),
             "exr": np.full((n, 2), np.nan)}
        _walk(a["o"], a["h"], a["l"], a["c"], a["mo"], a["mh"], a["ml"], self.end, self.coin_end, self.ent, self.atr,
              slip, STOP_ATR, STOP_PCT, self.tp_t, self.tp_m, self.liqd, self.pierce, *(T[k] for k in self.KEYS))
        return T

    def args(self, cm: int) -> tuple:
        T = self.x[cm]
        return tuple(T[k] for k in self.KEYS)


def build_tables(arrays: dict, close_ms, atr, period: tuple, coin_end: bool, br: np.ndarray, cfgs=None,
                 warmup: int | None = None, **kw) -> Tables:
    """Tables over every chart bar whose close lies in ``period`` = (start ms, end ms) and that is not a warm-up bar
    (run.WARMUP_BARS), with the first-bracket liquidation levels of the tiers of ``cfgs``."""
    R = D.fg_run()
    warmup = R.WARMUP_BARS if warmup is None else warmup
    cfgs = exit_configs() if cfgs is None else cfgs
    close_ms = np.asarray(close_ms, np.int64)
    sel = (close_ms >= period[0]) & (close_ms < period[1])
    sel[:warmup] = False
    tp_t, tp_m, _ti = tp_sets(cfgs)
    if any(c["Li"] != LEVS.index(c["L"]) for c in cfgs):
        raise ValueError("configs must use the registered tier order")
    return Tables(arrays, close_ms, atr, np.flatnonzero(sel), period[1], coin_end, first_tier_liqd(br, LEVS), tp_t,
                  tp_m, **kw)


# ------------------------------------------------------------------ a trade from the tables
@njit(cache=True)
def _outcome(ent, fc, F, sc, sx, tct, txt, tcm, txm, lc, ec, exr, row, s, k, fill, ti, Li, L, tk, mk):
    """(status 0 closed / 1 liquidated / 2 open at the period end, exit kind, event code, r) of one trade."""
    inf = 2 ** 62
    cs = np.int64(sc[row, s, k])
    ct = np.int64(tct[row, s, ti]) if fill == 0 else np.int64(tcm[row, s, ti])
    cl = np.int64(lc[row, s, Li])
    ce = np.int64(ec[row, s])
    first = inf
    if 0 <= cs < first:
        first = cs
    if 0 <= ct < first:
        first = ct
    if 0 <= cl < first:
        first = cl
    if 0 <= ce < first:
        first = ce
    if first == inf:
        return 2, X_OPEN, np.int64(-1), 0.0
    if first == cl:
        return 1, X_LIQ, first, -1.0 / L - tk
    sg = 1.0 if s == 0 else -1.0
    if first == cs:
        g = sx[row, s, k]
        kind = X_STOP
    elif first == ct:
        g = txt[row, s, ti] if fill == 0 else txm[row, s, ti]
        kind = X_TP
    else:
        g = exr[row, s]
        kind = X_COIN_END
    if g < -1.0 / L:                                  # a fill beyond the margin is a liquidation (kernel._trade)
        return 1, X_LIQ, first, -1.0 / L - tk
    f = F[row, s]
    x = first // 8
    fund = -sg * (fc[x] - fc[ent[row]]) / f
    fee = mk if (kind == X_TP and fill == 1) else tk
    return 0, kind, first, g - tk - fee * (1.0 + sg * g) + fund


@njit(cache=True)
def _one_r(sd, s, slip, tk):
    """1R: the loss at the stop level, fees and slippage included (7.7), per notional."""
    sg = 1.0 if s == 0 else -1.0
    gs = sg * ((1.0 - sg * sd) * (1.0 - sg * slip) - 1.0)
    return -(gs - tk - tk * (1.0 + sg * gs))


@njit(cache=True)
def _pair_sums(rows, sides, ent, atr, liqd, fc, F, sd, sc, sx, tct, txt, tcm, txm, lc, ec, exr,
               F2, sd2, sc2, sx2, tct2, txt2, tcm2, txm2, lc2, ec2, exr2,
               c_Li, c_L, c_k, c_fill, c_ti, c_t, buf_min, buf_atr, slip, tk, mk, out):
    nc = len(c_Li)
    for q in range(len(rows)):                       # trades outer, configs inner: one row of the tables at a time
        row = rows[q]
        s = sides[q]
        if ent[row] < 0:
            for ci in range(nc):
                out[ci, 13] += 1
            continue
        f = F[row, s]
        b = buf_min
        a = buf_atr * atr[row] / f
        if a > b:
            b = a
        for ci in range(nc):
            Li, L, k, fill, ti, t = c_Li[ci], c_L[ci], c_k[ci], c_fill[ci], c_ti[ci], c_t[ci]
            sdk = sd[row, s, k]
            if sdk + b > liqd[s, Li]:
                out[ci, 10] += 1
                continue
            if sdk <= t:
                out[ci, 11] += 1
                continue
            st, kind, code, r = _outcome(ent, fc, F, sc, sx, tct, txt, tcm, txm, lc, ec, exr, row, s, k, fill, ti,
                                         Li, L, tk, mk)
            if st == 2:
                out[ci, 12] += 1
                continue
            out[ci, 0] += 1
            out[ci, 2] += r
            out[ci, 3] += r * r
            out[ci, 4] += r / _one_r(sdk, s, slip, tk)
            if r > 0:
                out[ci, 1] += 1
                out[ci, 14] += r
            else:
                out[ci, 15] += r
            if st == 1:
                out[ci, 5] += 1
            if kind == X_COIN_END:
                out[ci, 6] += 1
            st2, _k2, _c2, r2 = _outcome(ent, fc, F2, sc2, sx2, tct2, txt2, tcm2, txm2, lc2, ec2, exr2, row, s, k,
                                         fill, ti, Li, L, 2.0 * tk, 2.0 * mk)
            if st2 != 2:
                out[ci, 7] += 1
                out[ci, 8] += r2
                if r2 > 0:
                    out[ci, 9] += 1


def pair_sums(T: Tables, rows, sides, ca: dict, out: np.ndarray | None = None) -> np.ndarray:
    """Per exit config (``cfg_arrays``) the trade-list sums of the candidates (rows of ``T``, sides 0 long / 1 short),
    added into ``out`` (configs x NSUM) so that coins can be summed into one pair."""
    out = np.zeros((len(ca["Li"]), NSUM)) if out is None else out
    _pair_sums(np.asarray(rows, np.int64), np.asarray(sides, np.int64), T.ent, T.atr, T.liqd, T.fc, *T.args(1),
               *T.args(2), ca["Li"], ca["L"], ca["k"], ca["fill"], ca["ti"], ca["t"], BUF_MIN, BUF_ATR, SLIP, TAKER,
               MAKER, out)
    return out


@njit(cache=True)
def _trade_list(rows, sides, ent, atr, liqd, fc, F, sd, sc, sx, tct, txt, tcm, txm, lc, ec, exr,
                F2, sd2, sc2, sx2, tct2, txt2, tcm2, txm2, lc2, ec2, exr2,
                Li, L, k, fill, ti, t, buf_min, buf_atr, slip, tk, mk, skip, kind, code, r, r2, oneR):
    for q in range(len(rows)):
        row = rows[q]
        s = sides[q]
        if ent[row] < 0:
            skip[q] = 4
            continue
        sdk = sd[row, s, k]
        f = F[row, s]
        b = buf_min
        a = buf_atr * atr[row] / f
        if a > b:
            b = a
        if sdk + b > liqd[s, Li]:
            skip[q] = 1
            continue
        if sdk <= t:
            skip[q] = 2
            continue
        st, kd, cd, rr = _outcome(ent, fc, F, sc, sx, tct, txt, tcm, txm, lc, ec, exr, row, s, k, fill, ti, Li, L,
                                  tk, mk)
        kind[q] = kd
        code[q] = cd
        if st == 2:
            skip[q] = 3
            continue
        r[q] = rr
        oneR[q] = _one_r(sdk, s, slip, tk)
        st2, _k2, _c2, rr2 = _outcome(ent, fc, F2, sc2, sx2, tct2, txt2, tcm2, txm2, lc2, ec2, exr2, row, s, k,
                                      fill, ti, Li, L, 2.0 * tk, 2.0 * mk)
        if st2 != 2:
            r2[q] = rr2


SKIP_NAMES = {0: "taken", 1: "no stop room", 2: "stop inside TP", 3: "open at end", 4: "no entry or ATR"}


def trade_list(T: Tables, rows, sides, cfg: dict, tp_t=None, tp_m=None) -> dict:
    """Every candidate of one exit config alone (8.1): skip reason (SKIP_NAMES), exit kind, exit code, r, cost-x2 r
    (NaN where unresolved), 1R, entry and exit time (ms)."""
    tt = list(T.tp_t if tp_t is None else tp_t)
    tm = list(T.tp_m if tp_m is None else tp_m)
    ti = (tt if cfg["fill"] == 0 else tm).index(cfg["t"])
    rows = np.asarray(rows, np.int64)
    sides = np.asarray(sides, np.int64)
    n = len(rows)
    out = {"skip": np.zeros(n, np.int8), "kind": np.full(n, -1, np.int8), "code": np.full(n, -1, np.int64),
           "r": np.full(n, np.nan), "r2": np.full(n, np.nan), "oneR": np.full(n, np.nan)}
    _trade_list(rows, sides, T.ent, T.atr, T.liqd, T.fc, *T.args(1), *T.args(2), cfg["Li"], float(cfg["L"]),
                cfg["k"], cfg["fill"], ti, cfg["t"], BUF_MIN, BUF_ATR, SLIP, TAKER, MAKER, out["skip"], out["kind"],
                out["code"], out["r"], out["r2"], out["oneR"])
    out["rows"], out["sides"] = rows, sides
    out["entry_ms"] = T.ent_ms[rows]
    x = np.where(out["code"] >= 0, out["code"] // 8, 0)
    out["exit_ms"] = np.where(out["code"] >= 0, T.ts[x], -1)
    out["close_ms"] = T.close[rows]
    return out


# ------------------------------------------------------------------ one trade at any levels (the account)
@njit(cache=True)
def trade_one(o, h, l, c, mo, mh, ml, e, end, coin_end, sg, S, T, Q, slip, maker, pierce, f):
    """One trade from minute e with stop S, take-profit T (maker or taker), liquidation level Q, over minutes
    [e, end): (event code, gross return side x (X / F - 1)); code -1 when unresolved at ``end`` (no coin end). The
    same rules and order as ``_walk`` for a single set of levels."""
    Tq = T * (1.0 + sg * pierce)
    for j in range(e, end):
        if j > e:
            if (mo[j] - Q) * sg <= 0:
                return 8 * j + 0, 0.0
            if (o[j] - S) * sg <= 0:
                return 8 * j + 1, sg * (o[j] * (1.0 - sg * slip) / f - 1.0)
            if maker:
                if (o[j] - Tq) * sg > 0:
                    return 8 * j + 2, sg * (T / f - 1.0)
            elif (o[j] - T) * sg >= 0:
                return 8 * j + 2, sg * (o[j] * (1.0 - sg * slip) / f - 1.0)
        if (l[j] <= S) if sg > 0 else (h[j] >= S):
            return 8 * j + 3, sg * (S * (1.0 - sg * slip) / f - 1.0)
        if (ml[j] <= Q) if sg > 0 else (mh[j] >= Q):
            return 8 * j + 4, 0.0
        if maker:
            if (h[j] > Tq) if sg > 0 else (l[j] < Tq):
                return 8 * j + 5, sg * (T / f - 1.0)
        elif (h[j] >= T) if sg > 0 else (l[j] <= T):
            return 8 * j + 5, sg * (T * (1.0 - sg * slip) / f - 1.0)
    if coin_end and end > e:
        return 8 * (end - 1) + 6, sg * (c[end - 1] * (1.0 - sg * slip) / f - 1.0)
    return -1, 0.0


def stop_distance(k: int, atr: float, p0: float) -> float:
    fam, v = STOPS[k]
    return v * atr if fam == "atr" else v * p0
