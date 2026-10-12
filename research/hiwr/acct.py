"""Track 2 trade lists and the account (PREREG_HIWR.md section 8). Read-only research code.

- Trade list (8.1): ``stats_from_sums`` / ``trade_stats`` (n, win rate, mean r, mean in R, cost-x2 mean) and
  ``b_pass`` (10.2: n >= 150, win rate >= 70.0%, mean > 0, cost-x2 mean > 0).
- Account (8.2): $1,000 compounding, isolated margin, one position at a time over all coins. Candidates in time order
  of the fill minute, ties by coin order (section 4), long before short; a fill minute not after the open position's
  exit minute is dropped ("busy"). Notional N = f x wallet, cut to the tier's notional cap (the largest notionalCap
  among the brackets whose initialLeverage >= L; counted), skipped below the coin's minimum notional; the bracket
  holding N gives the liquidation price (kernel._bracket, kernel._liq) and the stop-room check is redone there.
  Coin end closes at the coin's last bar; a position open at the period end is marked at the last 1m close (flagged).
  Bust: the wallet after a close below 10% of the start; the account stops.
- Drawdown (8.3): on every 1m bar of an open position the equity is marked at the bar's adverse last-price extreme
  (against the peak of the closes before that minute) and at its close, both less a market exit (slippage + taker
  fee) and less the funding paid so far. Exit minute: its adverse extreme counts for a TP filled inside the minute, a
  coin-end close and the period-end mark; a stop or liquidation counts at its fill; an exit on the open has no mark.
  Peak = max(start, every close mark, every wallet after a close). The realized-only DD (wallets after closes) is
  beside it.
- Size (8.4): on the 0.01 grid, f_path = the largest f such that EVERY grid size from 0.01 to f meets (i) SEL path max
  DD <= cap and (ii) worst account trade <= 15% of the equity before it, with (iii) f <= L^2 / 100; i.e. 0.01 below the
  first failing size, found by an upward scan (``first_fail_scan``). f* = the same with (i') the 95th percentile of
  the week-block bootstrap max DD <= cap added, scanned on [0.01, f_path]. Why a scan: the stop room judged at the
  bracket of N, the notional-cap cut and the minimum notional make the taken trades depend on f, so the drawdown is not
  monotone in f and a bisection can land on a feasible island above a failing size. Exact speed-up of the f* scan: on
  consecutive grid sizes whose accounts take the same trades with the same per-notional results, exits and phases, and
  cut none (N / wallet = f), every path's mark-to-market DD is nondecreasing in f (``bootstrap_scan``), so inside such a
  run the first failing size is found by bisection; elsewhere every size is evaluated.
  The bootstrap regroups the account's trades (taken at the SEL path at that f) by the UTC week (Monday) of their fill
  minute, draws the period's weeks (empty ones included) with replacement and runs their trades in draw order, each
  with its own SEL-path notional fraction N / wallet and its own result and minute marks (caps, stop room and the
  minimum notional are not redone in a resample; decomposed per trade so that a path is a sum over trades;
  ``boot_dd_slow`` is the plain loop).
- Monthly return (8.5): equity at each UTC month end (an open position marked at its last close before the month
  boundary) over the equity at its start.
Choices written into PREREG_HIWR 8.3 / 8.4: a resampled trade keeps its SEL-path N / wallet and result; the f95 draws
use sha256("hiwr|f95|<period>|<pick id>|f95"); a period-end mark is less a market exit, as every other mark; the exit
minute's adverse extreme also counts for a coin-end close and the period-end mark; bust is the wallet after a close
below 10% of the start; a liquidation loses the isolated margin and the entry fee, and the funding paid while it was
open stays paid (funding is paid from the wallet, 7.6).
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import sys

import numpy as np

try:
    from numba import njit
except ImportError:  # pragma: no cover
    def njit(*a, **k):
        if a and callable(a[0]):
            return a[0]
        return lambda f: f

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from research.hiwr import data as D  # noqa: E402
from research.hiwr import walk as W  # noqa: E402

K = W.K
_k_liq = K._liq
_k_bracket = K._bracket
_trade_one = W.trade_one
EXCHANGE30 = os.path.join(ROOT, "research", "hunt", "exchange30.json")
PROXY_OF_STOPPED = "SANDUSDT"            # section 4, Q3: the table SANDUSDT and COMPUSDT share

CAP = {"15m": 0.15, "30m": 0.20, "1h": 0.30, "4h": 0.30}     # 2.2
START = 1000.0                                               # Q14
BUST = 0.10                                                  # 8.3: equity below 10% of the start
MAX_LOSS = 0.15                                              # 8.4 (ii)
MIN_N, MIN_WIN = 150, 0.70                                   # 10.2
N_BOOT = 10_000                                              # 8.4
Q_BOOT = 0.95
# candidate status in the account
A_TAKEN, A_BUSY, A_NO_ROOM, A_MIN_NOTIONAL, A_AFTER_BUST, A_STOP_INSIDE, A_NO_TIER, A_WINDOW = 1, 2, 3, 4, 5, 6, 7, 8
A_NAMES = {A_TAKEN: "taken", A_BUSY: "busy", A_NO_ROOM: "no stop room at N", A_MIN_NOTIONAL: "minimum notional",
           A_AFTER_BUST: "after bust", A_STOP_INSIDE: "stop inside TP", A_NO_TIER: "no bracket at L",
           A_WINDOW: "window too short (bug)"}


# ------------------------------------------------------------------ trade-list statistics (8.1, 10.2)
def stats_from_sums(row: np.ndarray) -> dict:
    """One pair's sums (walk.pair_sums row) -> n, win rate, mean r (fraction of notional), cost-x2 mean, mean in R."""
    n = row[W.S_N]
    n2 = row[W.S_N2]
    return {"n": int(n), "win": row[W.S_WIN] / n if n else float("nan"), "mean": row[W.S_SUM] / n if n else float("nan"),
            "mean_x2": row[W.S_SUM2] / n2 if n2 else float("nan"), "mean_R": row[W.S_SUMR] / n if n else float("nan"),
            "sd": math.sqrt(max(0.0, row[W.S_SQ] / n - (row[W.S_SUM] / n) ** 2)) if n else float("nan"),
            "liq": int(row[W.S_LIQ]), "coin_end": int(row[W.S_END]), "skip_room": int(row[W.S_ROOM]),
            "skip_stop_inside_tp": int(row[W.S_INSIDE]), "skip_open_at_end": int(row[W.S_OPEN])}


def trade_stats(r, r2=None, oneR=None) -> dict:
    """The same from per-trade r (NaN = not a trade), cost-x2 r and 1R."""
    r = np.asarray(r, float)
    ok = np.isfinite(r)
    x = r[ok]
    out = {"n": int(ok.sum()), "win": float((x > 0).mean()) if len(x) else float("nan"),
           "mean": float(x.mean()) if len(x) else float("nan")}
    if r2 is not None:
        y = np.asarray(r2, float)[ok]
        y = y[np.isfinite(y)]
        out["mean_x2"] = float(y.mean()) if len(y) else float("nan")
    if oneR is not None:
        out["mean_R"] = float((x / np.asarray(oneR, float)[ok]).mean()) if len(x) else float("nan")
    return out


def b_pass(st: dict) -> bool:
    return bool(st["n"] >= MIN_N and st["win"] >= MIN_WIN and st["mean"] > 0 and st["mean_x2"] > 0)


# ------------------------------------------------------------------ brackets (section 4)
def exchange30(path: str = EXCHANGE30, symbols=D.SYMBOLS) -> dict:
    """{symbol: {"br": bracket rows (notional_cap, max_leverage, mmr, cum), "qty_step", "min_notional", "proxy"}}.
    The 8 coins without a table use SANDUSDT's table and specs (Q3), labelled ``proxy``."""
    from paperbot.margin import Brackets
    with open(path) as fh:
        doc = json.load(fh)
    by = {p["symbol"]: p for p in doc["brackets"]}
    out = {}
    for s in symbols:
        src = s if s in by else PROXY_OF_STOPPED
        spec = doc["specs"][src]
        out[s] = {"br": K.bracket_arrays(Brackets.from_binance(by[src])), "qty_step": float(spec["qty_step"]),
                  "min_notional": float(spec["min_notional"]), "proxy": s not in by}
    return out


def notional_cap(br: np.ndarray, L: float) -> float:
    """At tier L the notional can reach the largest notionalCap among the brackets with initialLeverage >= L."""
    caps = [float(r[0]) for r in br if r[1] >= L]
    return max(caps) if caps else 0.0


def coin_params(coins: list[dict], L: float) -> tuple:
    """Padded bracket rows (coins x rows x 4), row counts, notional caps at L and minimum notionals, for ``_account``."""
    nr = max(len(c["br"]) for c in coins)
    br = np.zeros((len(coins), nr, 4))
    br_n = np.zeros(len(coins), np.int64)
    for i, c in enumerate(coins):
        br[i, :len(c["br"])] = c["br"]
        br_n[i] = len(c["br"])
    caps = np.array([notional_cap(c["br"], L) for c in coins])
    mins = np.array([c["min_notional"] for c in coins])
    return br, br_n, caps, mins


# ------------------------------------------------------------------ the minute store and candidates
class Store:
    """Concatenated 1m segments the account walks: one per coin (``from_coins``), or one per candidate window.
    kind per segment: 0 the segment ends at the period end (open positions are marked there), 1 at the coin's end
    (close at its last bar), 2 a window that must hold the trade's exit."""

    KEYS = ("ts", "o", "h", "l", "c", "mo", "mh", "ml")

    def __init__(self, segs: list[dict], kinds):
        self.off = np.r_[0, np.cumsum([len(s["ts"]) for s in segs])].astype(np.int64)
        for k in self.KEYS:
            setattr(self, k, np.concatenate([np.asarray(s[k]) for s in segs]) if segs else np.zeros(0))
        self.ts = self.ts.astype(np.int64)
        self.fc = np.concatenate([np.cumsum(np.asarray(s["mo"]) * np.asarray(s["fund"])) for s in segs])
        self.kind = np.asarray(kinds, np.int64)

    @classmethod
    def from_coins(cls, coin_arrays: list[dict], ended: list[bool]) -> "Store":
        return cls(coin_arrays, [1 if e else 0 for e in ended])

    def args(self) -> tuple:
        return (self.ts, self.o, self.h, self.l, self.c, self.mo, self.mh, self.ml, self.fc, self.off, self.kind)


def candidates(coin, seg, e_local, side, stop_D, atr, fill_ms) -> dict:
    """The account's candidates in its order: fill minute, then coin order, long before short. ``side`` +1 / -1."""
    coin = np.asarray(coin, np.int64)
    side = np.asarray(side, np.int64)
    o = np.lexsort(((side < 0).astype(np.int64), coin, np.asarray(fill_ms, np.int64)))
    return {"coin": coin[o], "seg": np.asarray(seg, np.int64)[o], "e": np.asarray(e_local, np.int64)[o],
            "side": side[o], "D": np.asarray(stop_D, float)[o], "atr": np.asarray(atr, float)[o],
            "fill_ms": np.asarray(fill_ms, np.int64)[o], "order": o}


def candidates_from_tables(tables: list, tl: list, cfg: dict) -> dict:
    """Candidates of one pair from per-coin tables (coin c = tables[c], segment c of a ``Store.from_coins``) and its
    per-coin trade lists (``walk.trade_list``): every candidate with an entry whose stop is wider than the TP. The stop
    room is judged again in the account, at the bracket of N; a trade open at the period end is kept (marked there)."""
    cs, es, sides, Ds, atrs, fills = [], [], [], [], [], []
    fam, v = W.STOPS[cfg["k"]]
    for c, (T, x) in enumerate(zip(tables, tl)):
        keep = (x["skip"] != 4) & (x["skip"] != 2)
        rows, sd = x["rows"][keep], x["sides"][keep]
        cs.append(np.full(len(rows), c, np.int64))
        es.append(T.ent[rows])
        sides.append(np.where(sd == 0, 1, -1))
        Ds.append(v * (T.atr[rows] if fam == "atr" else T.p0[rows]))
        atrs.append(T.atr[rows])
        fills.append(T.ent_ms[rows])
    cat = lambda z: np.concatenate(z) if z else np.zeros(0)  # noqa: E731
    cs = cat(cs)
    return candidates(cs, cs, cat(es), cat(sides), cat(Ds), cat(atrs), cat(fills))


# ------------------------------------------------------------------ the account (8.2, 8.3)
@njit(cache=True)
def _account(ts, o, h, l, c, mo, mh, ml, fc, seg_off, seg_kind,
             q_seg, q_e, q_coin, q_side, q_D, q_atr,
             t, maker, pierce, L, f, w0, bust_w, tk, mk, slip, buf_min, buf_atr,
             br, br_n, caps, mins, bounds,
             st, cut, N_out, W_out, r_out, kind_out, ph_out, x_out, feff, u_out, d1_out, d2_out, meq):
    n = len(q_seg)
    wal = w0
    P = w0
    Pr = w0
    dd = 0.0
    ddr = 0.0
    worst = 0.0
    busy = np.int64(-1)
    bust = False
    open_end = False
    bad = 0
    nb = len(bounds)
    bi = 0
    for q in range(n):
        sgi = q_seg[q]
        s1 = seg_off[sgi + 1]
        e = seg_off[sgi] + q_e[q]
        tf = ts[e]
        while bi < nb and bounds[bi] <= tf:
            meq[bi] = wal
            bi += 1
        if bust:
            st[q] = 5
            continue
        if tf <= busy:
            st[q] = 2
            continue
        sg = 1.0 if q_side[q] > 0 else -1.0
        raw = o[e]
        F = raw * (1.0 + sg * slip)
        S = raw - sg * q_D[q]
        T = F * (1.0 + sg * t)
        if sg * (F - S) / F <= t:
            st[q] = 6
            continue
        cc = q_coin[q]
        if caps[cc] <= 0:
            st[q] = 7
            continue
        N = f * wal
        if N > caps[cc]:
            N = caps[cc]
            cut[q] = True
        if N < mins[cc]:
            st[q] = 4
            continue
        brc = br[cc, :br_n[cc]]
        kb = _k_bracket(brc, N)
        Q = _k_liq(sg, N / F, F, N / L, brc[kb, 2], brc[kb, 3])
        b = buf_min * F
        if buf_atr * q_atr[q] > b:
            b = buf_atr * q_atr[q]
        if abs(F - S) + b > abs(F - Q):
            st[q] = 3
            continue
        code, g = _trade_one(o, h, l, c, mo, mh, ml, e, s1, seg_kind[sgi] == 1, sg, S, T, Q, slip, maker, pierce, F)
        if code < 0:
            if seg_kind[sgi] == 2:
                st[q] = 8
                bad += 1
                continue
            x = s1 - 1
            ph = 7
            g = sg * (c[x] * (1.0 - sg * slip) / F - 1.0)
        else:
            x = code // 8
            ph = code % 8
        if ph == 0 or ph == 4 or g < -1.0 / L:
            r = -1.0 / L - tk - sg * (fc[x] - fc[e]) / F      # the margin, the entry fee and the funding paid
            kind = 2
        else:
            fee = mk if (maker and (ph == 2 or ph == 5)) else tk
            r = g - tk - fee * (1.0 + sg * g) - sg * (fc[x] - fc[e]) / F
            if ph == 1 or ph == 3:
                kind = 0
            elif ph == 2 or ph == 5:
                kind = 1
            elif ph == 6:
                kind = 3
            else:
                kind = 4
        # marks (8.3)
        fe = N / wal
        M = 1.0
        u = 1.0
        d1 = np.inf
        d2 = np.inf
        for j in range(e, x + 1):
            last = j == x
            adv = (not last) or ph == 5 or ph == 6 or ph == 7
            cls = (not last) or ph == 7
            if not adv and not cls:
                break
            fj = -sg * (fc[j] - fc[e]) / F
            if adv:
                X = l[j] if sg > 0 else h[j]
                ga = sg * (X * (1.0 - sg * slip) / F - 1.0)
                ma = ga - tk - tk * (1.0 + sg * ga) + fj
                Ea = wal + N * ma
                if 1.0 - Ea / P > dd:
                    dd = 1.0 - Ea / P
                va = 1.0 + fe * ma
                if va < d1:
                    d1 = va
                if va / M < d2:
                    d2 = va / M
            if cls:
                gc = sg * (c[j] * (1.0 - sg * slip) / F - 1.0)
                mc = gc - tk - tk * (1.0 + sg * gc) + fj
                Ec = wal + N * mc
                if Ec > P:
                    P = Ec
                vc = 1.0 + fe * mc
                if vc > M:
                    M = vc
                if vc > u:
                    u = vc
                if not last:
                    while bi < nb and bounds[bi] <= ts[j + 1]:
                        meq[bi] = Ec
                        bi += 1
        wn = wal + N * r
        if 1.0 - wn / P > dd:
            dd = 1.0 - wn / P
        if wn > P:
            P = wn
        if wn > Pr:
            Pr = wn
        if 1.0 - wn / Pr > ddr:
            ddr = 1.0 - wn / Pr
        if -fe * r > worst:
            worst = -fe * r
        st[q] = 1
        N_out[q] = N
        W_out[q] = wal
        r_out[q] = r
        kind_out[q] = kind
        ph_out[q] = ph
        x_out[q] = ts[x]
        feff[q] = fe
        u_out[q] = u
        d1_out[q] = d1
        d2_out[q] = d2
        wal = wn
        busy = ts[x]
        if ph == 7:
            busy = np.int64(2 ** 62)
            open_end = True
        if wal < bust_w:
            bust = True
    while bi < nb:
        meq[bi] = wal
        bi += 1
    return wal, dd, ddr, worst, bust, open_end, bad


def account(store: Store, cand: dict, coins: list[dict], cfg: dict, f: float, period: tuple, w0: float = START,
            pierce: float = 0.0, cost: int = 1) -> dict:
    """The one-at-a-time account of one pair at size f (notional = f x wallet) over ``period`` = (start, end) ms.
    ``coins[c]`` = exchange30 entry of the coin index used in ``cand['coin']``."""
    L = float(cfg["L"])
    if len(store.ts) and (store.ts[store.off[1:] - 1] >= period[1]).any():
        raise ValueError("a segment reaches past the period end: cut the minutes at the period end first")
    if len(cand["fill_ms"]) and (cand["fill_ms"].min() < period[0] or cand["fill_ms"].max() >= period[1]):
        raise ValueError("a candidate fills outside the period")
    br, br_n, caps, mins = coin_params(coins, L)
    n = len(cand["seg"])
    st = np.zeros(n, np.int8)
    cut = np.zeros(n, np.bool_)
    out = {k: np.zeros(n) for k in ("N", "W", "r", "feff", "u", "d1", "d2")}
    kind = np.full(n, -1, np.int8)
    ph = np.full(n, -1, np.int8)
    xms = np.full(n, -1, np.int64)
    bounds = month_bounds(period)
    meq = np.zeros(len(bounds))
    wal, dd, ddr, worst, bust, open_end, bad = _account(
        *store.args(), cand["seg"], cand["e"], cand["coin"], cand["side"], cand["D"], cand["atr"],
        float(cfg["t"]), bool(cfg["fill"] == 1), float(pierce), L, float(f), float(w0), BUST * w0,
        W.TAKER * cost, W.MAKER * cost, W.SLIP * cost, W.BUF_MIN, W.BUF_ATR, br, br_n, caps, mins, bounds,
        st, cut, out["N"], out["W"], out["r"], kind, ph, xms, out["feff"], out["u"], out["d1"], out["d2"], meq)
    taken = np.flatnonzero(st == A_TAKEN)
    res = {"f": float(f), "final": float(wal), "dd": float(dd), "dd_real": float(ddr), "worst_loss": float(worst),
           "bust": bool(bust), "open_at_end": bool(open_end), "window_errors": int(bad), "status": st, "cut": cut,
           "taken": taken, "n": int(len(taken)), "month_eq": meq, "bounds": bounds, "w0": float(w0),
           "kind": kind[taken], "phase": ph[taken], "exit_ms": xms[taken], "fill_ms": cand["fill_ms"][taken],
           "counts": {A_NAMES[k]: int((st == k).sum()) for k in A_NAMES}, "n_cut": int(cut[taken].sum())}
    for k, v in out.items():
        res[k] = v[taken]
    if bad:
        raise RuntimeError(f"{bad} account trades did not resolve inside their minute window")
    return res


# ------------------------------------------------------------------ monthly return (8.5)
def month_bounds(period: tuple) -> np.ndarray:
    """UTC month starts after the period start, through the period end (each = the end of a month)."""
    import pandas as pd
    a = pd.Timestamp(period[0], unit="ms", tz="UTC")
    b = pd.Timestamp(period[1], unit="ms", tz="UTC")
    m = pd.date_range(a.normalize().replace(day=1) + pd.offsets.MonthBegin(1), b, freq="MS")
    out = [int(x.value // 1_000_000) for x in m]
    if not out or out[-1] != period[1]:
        out.append(int(period[1]))
    return np.array(out, np.int64)


def monthly(res: dict) -> dict:
    eq = np.asarray(res["month_eq"], float)
    M = eq / np.r_[res["w0"], eq[:-1]]
    ln = np.log(M)
    return {"months": int(len(M)), "mean_ln": float(ln.mean()), "geo_pct": float(math.expm1(ln.mean()) * 100),
            "median_M": float(np.median(M)), "worst_M": float(M.min()), "final_x": float(eq[-1] / res["w0"])}


# ------------------------------------------------------------------ the week-block bootstrap (8.4)
def week_ids(fill_ms, period: tuple) -> tuple:
    """(week index of each trade from the period's first UTC week, number of weeks in the period, empty included)."""
    w0 = (period[0] - W.MONDAY0) // W.WEEK
    w1 = (period[1] - 1 - W.MONDAY0) // W.WEEK
    return (np.asarray(fill_ms, np.int64) - W.MONDAY0) // W.WEEK - w0, int(w1 - w0 + 1)


def rng_for(kind: str, period: str, pick_id: str, s) -> np.random.Generator:
    """Section 11: numpy PCG64 seeded with the first 8 bytes (little-endian) of sha256("hiwr|kind|period|id|s")."""
    seed = int.from_bytes(hashlib.sha256(f"hiwr|{kind}|{period}|{pick_id}|{s}".encode()).digest()[:8], "little")
    return np.random.Generator(np.random.PCG64(seed))


def boot_draws(period: tuple, pick_id: str, period_name: str = "SEL", n_boot: int = N_BOOT) -> np.ndarray:
    """The f95 draws (8.4): n_boot x weeks week indices, the same for every f. Seeded as section 11 with "f95" in
    place of s (and of the control letter, which 8.4 leaves open)."""
    _w, nw = week_ids(np.zeros(0, np.int64), period)
    return rng_for("f95", period_name, pick_id, "f95").integers(0, nw, (n_boot, nw)).astype(np.int64)


@njit(cache=True)
def _path_dd(order, w, u, d1, d2, bust):
    """Max mark-to-market DD of the trades ``order`` run in that order from wallet 1 (8.3 decomposed per trade: w = the
    wallet multiple of the trade, u = its highest close mark, d1 = its lowest adverse mark, d2 = its lowest adverse
    mark over the highest close mark before that minute, all relative to the wallet at its entry)."""
    wal = 1.0
    P = 1.0
    dd = 0.0
    for i in range(len(order)):
        q = order[i]
        x = 1.0 - wal * d1[q] / P
        if x > dd:
            dd = x
        if 1.0 - d2[q] > dd:
            dd = 1.0 - d2[q]
        if wal * u[q] > P:
            P = wal * u[q]
        wal *= w[q]
        if wal > P:
            P = wal
        if 1.0 - wal / P > dd:
            dd = 1.0 - wal / P
        if wal < bust:
            return 1.0
    return dd


@njit(cache=True)
def _boot_dd(w, u, d1, d2, wk_start, wk_len, draws, bust):
    B, nw = draws.shape
    out = np.empty(B)
    buf = np.empty(len(w) * nw + 1, np.int64)
    for b in range(B):
        m = 0
        for i in range(nw):
            s = wk_start[draws[b, i]]
            for q in range(wk_len[draws[b, i]]):
                buf[m] = s + q
                m += 1
        out[b] = _path_dd(buf[:m], w, u, d1, d2, bust)
    return out


def boot_dd(res: dict, period: tuple, draws: np.ndarray) -> np.ndarray:
    """Max DD of every resampled path of the account's trades (``account`` result at one f)."""
    wk, nw = week_ids(res["fill_ms"], period)
    if draws.shape[1] != nw:
        raise ValueError("draws do not match the period's weeks")
    wk_start = np.searchsorted(wk, np.arange(nw)).astype(np.int64)
    wk_len = (np.searchsorted(wk, np.arange(nw), side="right") - wk_start).astype(np.int64)
    w = 1.0 + res["feff"] * res["r"]
    return _boot_dd(w, res["u"], res["d1"], res["d2"], wk_start, wk_len, draws, BUST)


def path_dd(res: dict, order=None) -> float:
    """The decomposed max DD of the account's own trades in ``order`` (default: as taken; equals res['dd'])."""
    order = np.arange(res["n"], dtype=np.int64) if order is None else np.asarray(order, np.int64)
    return float(_path_dd(order, 1.0 + res["feff"] * res["r"], res["u"], res["d1"], res["d2"], BUST))


# ------------------------------------------------------------------ f_path and f* (8.4)
def first_fail_scan(ok, top: int) -> int:
    """The largest k in [0, top] such that ok(j) holds for EVERY j in 1 .. k (grid sizes in hundredths): an upward
    scan that stops at the first failure (0 when ok(1) fails, ``top`` when nothing fails)."""
    for k in range(1, int(top) + 1):
        if not ok(k):
            return k - 1
    return int(top)


def structure(res: dict):
    """The account's structure at one size: which candidates it took and their per-notional results, exit phases and
    exit minutes. None when a taken trade was cut (its N / wallet is not f) or the account busted. Two sizes with the
    same structure differ only by f: every path's mark-to-market DD is then nondecreasing in f (8.3 marks are
    wallet x (1 + f x m) with the same m; a peak-to-trough ratio is a product of steps (1 + f a) / (1 + f b) and
    f d/df ln(ratio) <= ln(ratio) < 0 for a drawdown, since y / (1 + y) <= ln(1 + y))."""
    if res["bust"] or bool(np.asarray(res["cut"])[res["taken"]].any()):
        return None
    h = hashlib.sha256()
    for k in ("taken", "r", "phase", "exit_ms", "kind"):
        h.update(np.ascontiguousarray(res[k]).tobytes())
    return h.digest()


def bootstrap_scan(boot_ok, sig: dict, top: int) -> int:
    """The largest k in [0, top] such that boot_ok(j) for every j in 1 .. k, given ``sig`` (k -> ``structure`` of the
    account at k / 100). Inside a run of consecutive k with one structure (not None) boot_ok can only turn from true to
    false (``structure``), so the run's last k is checked first and, when it fails, the first failure inside the run is
    found by bisection; a k without a structure is checked alone. Equal to ``first_fail_scan(boot_ok, top)``."""
    k = 1
    while k <= top:
        end = k
        if sig.get(k) is not None:
            while end + 1 <= top and sig.get(end + 1) == sig[k]:
                end += 1
        if boot_ok(end):
            k = end + 1
            continue
        lo, hi = k - 1, end                 # boot_ok holds at lo (k - 1 passed, or lo = 0), fails at hi
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if boot_ok(mid):
                lo = mid
            else:
                hi = mid
        return hi - 1
    return int(top)


def sizes(run_at, cap: float, L: float, period: tuple, draws: np.ndarray, q: float = Q_BOOT,
          max_loss: float = MAX_LOSS, exact_boot: bool = False) -> dict:
    """f_path and f* of one pair (8.4) on the 0.01 grid: ``run_at(f)`` returns the SEL ``account`` at size f.
    f_path = 0.01 below the first grid size that breaks (i) or (ii) (or L^2 / 100, iii); f* = 0.01 below the first grid
    size up to f_path whose bootstrap 95th percentile is above the cap (i'). ``exact_boot``: evaluate the bootstrap at
    every grid size (the plain scan; tests compare it with the run-and-bisect speed-up)."""
    top = int(round(L * L))                                # (iii) margin at most L% of the wallet: f <= L^2 / 100
    sig: dict = {}
    n_acc = [0]
    last: dict = {}

    def acc(k):
        if k not in last:
            last.clear()                                   # one result kept: the scans move forward
            n_acc[0] += 1
            last[k] = run_at(k / 100.0)
        return last[k]

    def ok_path(k):
        a = acc(k)
        sig[k] = structure(a)
        return a["dd"] <= cap and a["worst_loss"] <= max_loss

    kp = first_fail_scan(ok_path, top)
    bq: dict = {}

    def boot(k):
        if k not in bq:
            d = boot_dd(acc(k), period, draws)
            bq[k] = (float(np.quantile(d, q)), float((d > cap).mean()))
        return bq[k]

    def boot_ok(k):
        return boot(k)[0] <= cap

    ks = first_fail_scan(boot_ok, kp) if exact_boot else bootstrap_scan(boot_ok, sig, kp)
    out = {"cap": cap, "L": L, "f_ceiling": top / 100.0,
           "scan": {"account_runs": n_acc[0], "bootstraps": len(bq), "grid_sizes_path": min(kp + 1, top)}}
    for name, k in (("f_path", kp), ("f_star", ks)):
        f = k / 100.0
        a = acc(k) if k > 0 else None
        q95, share = boot(k) if k > 0 else (0.0, 0.0)
        out[name] = {"f": f, "margin_pct": f / L * 100.0, "notional_x": f, "dd": a["dd"] if a else 0.0,
                     "dd_real": a["dd_real"] if a else 0.0, "boot_q95": q95, "boot_share_over_cap": share,
                     "trades": a["n"] if a else 0, "worst_loss": a["worst_loss"] if a else 0.0,
                     "monthly": monthly(a) if a else None}
    return out


# ------------------------------------------------------------------ slow references (tests)
def boot_dd_slow(res: dict, period: tuple, draws: np.ndarray, marks: list) -> np.ndarray:
    """The bootstrap as a plain loop over every mark of every trade of every path (``marks[i]`` = list of
    ("adv" | "close", mark per notional) of trade i in time order). For the tests."""
    wk, nw = week_ids(res["fill_ms"], period)
    out = np.empty(len(draws))
    for b in range(len(draws)):
        wal = P = 1.0
        dd = 0.0
        busted = False
        for wkx in draws[b]:
            for i in np.flatnonzero(wk == wkx):
                fe = res["feff"][i]
                for typ, m in marks[i]:
                    e = wal * (1.0 + fe * m)
                    if typ == "adv":
                        dd = max(dd, 1.0 - e / P)
                    else:
                        P = max(P, e)
                wal *= 1.0 + fe * res["r"][i]
                P = max(P, wal)
                dd = max(dd, 1.0 - wal / P)
                if wal < BUST:
                    busted = True
                    break
            if busted:
                break
        out[b] = 1.0 if busted else dd
    return out
