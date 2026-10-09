"""Stage 5: re-optimisation simulation (PREREG 'Re-optimisation simulation'), per strategy x timeframe, main exits.

Account: one position per coin (7 coins), signal-level net R, a signal on a coin with an open position is skipped
(free again for entries after the exit bar, as lens2 sim.py); same-moment ties in coin order.
Re-pick = the best plateau combo (same score and >= 200 trade minimum as the SEARCH selection) on the trades of all
grid combos CLOSED in the trailing window, exit times binned in 4-hour bins (only bins ended by the decision time).
  ROLL5_26w / ROLL5_4w : after every 5 closed account trades; WEEKLY_26w: every Monday 00:00 UTC.
  DEFAULT              : the default values under the same account rule.
The new combo applies to signals after the decision time; open positions continue. No eligible combo -> default.
Periods TEST and EXTRA (trailing history may reach back into the previous period's data: SEARCH for TEST).

    python3 -B research/st_custom/s5_reopt.py [procs]
"""
import heapq
import os
import sys
import time
from multiprocessing import Pool

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402
import numpy as np  # noqa: E402
import s2_signals as S2  # noqa: E402
import s3_select as S3  # noqa: E402

RE_DIR = os.path.join(C.WORK, "reopt")
os.makedirs(RE_DIR, exist_ok=True)
T0 = C.ts_ns("2020-01-01")
STEP = 15 * C.NS_MIN
BIN = 16                       # 4h = 16 x 15m
WEEK = 7 * 96
METHODS = {"ROLL5_26w": ("roll", 26), "ROLL5_4w": ("roll", 4), "WEEKLY_26w": ("weekly", 26), "DEFAULT": ("none", 0)}
RUN_PERIODS = ("TEST", "EXTRA")


def k_of(ts):
    return ((np.asarray(ts, np.int64) - T0) // STEP).astype(np.int64)


class Data:
    def __init__(self, strat, tf):
        self.strat, self.tf = strat, tf
        self.nc = C.NCOMBO[strat]
        self.codes = []          # (ci, per, lo, codes, offs)
        self.O, self.ts15, self.tst = {}, {}, {}
        for ci, coin in enumerate(C.COINS):
            z = np.load(os.path.join(C.OUTC_DIR, f"{coin}_{tf}.npz"))
            self.O[ci] = {k: z[k] for k in ("R_0", "R_1", "reason_0", "reason_1", "x_0", "x_1", "e")}
            self.ts15[ci] = C.load_bars(coin, "15m")["ts"]
            self.tst[ci] = C.load_bars(coin, tf)["ts"]
            for per in C.PERIOD_ORDER:
                p = S2.sig_path(coin, tf, per)
                lo = int(np.load(p)["lo"][0])
                codes, offs = C.load_signals(p, strat)
                self.codes.append((ci, per, lo, codes.astype(np.int32), offs))
        self.cache = {}
        kmax = int(k_of([C.ts_ns("2026-10-01")])[0])
        self.NB = kmax // BIN + 2
        self.build_bins()
        self.NBm = C.neighbour_matrix(strat)
        self.default = C.combo_index(strat, C.DEFAULT_IDX[strat])

    def _outcomes(self, ci, gi, sd):
        O = self.O[ci]
        si = sd < 0
        R = np.where(si, O["R_1"][gi], O["R_0"][gi]).astype(np.float64)
        done = np.where(si, O["reason_1"][gi], O["reason_0"][gi]) != 3
        x = np.where(si, O["x_1"][gi], O["x_0"][gi]).astype(np.int64)
        e = O["e"][gi].astype(np.int64)
        return R, done, x, e

    def build_bins(self):
        n = np.zeros(self.NB * self.nc, np.float64)
        s = np.zeros(self.NB * self.nc, np.float64)
        for ci, per, lo, codes, offs in self.codes:
            combo = np.repeat(np.arange(self.nc), np.diff(offs))
            gi = lo + codes // 2
            sd = np.where(codes % 2 == 1, 1, -1)
            R, done, x, _e = self._outcomes(ci, gi, sd)
            xk = k_of(self.ts15[ci][np.clip(x, 0, len(self.ts15[ci]) - 1)]) + 1     # end of the exit bar
            b = xk // BIN
            key = b[done] * self.nc + combo[done]
            n += np.bincount(key, minlength=len(n))
            s += np.bincount(key, weights=R[done], minlength=len(s))
        n = n.reshape(self.NB, self.nc)
        s = s.reshape(self.NB, self.nc)
        self.cn = np.vstack([np.zeros((1, self.nc)), np.cumsum(n, axis=0)])
        self.cs = np.vstack([np.zeros((1, self.nc)), np.cumsum(s, axis=0)])

    def repick(self, T, W_weeks):
        """Best plateau combo on trades closed in [T - W, T) (bins ended by T)."""
        b1 = T // BIN                       # bins < b1 have ended by T
        b0 = max(0, -(-(T - W_weeks * WEEK) // BIN))
        n = self.cn[b1] - self.cn[b0]
        s = self.cs[b1] - self.cs[b0]
        with np.errstate(invalid="ignore", divide="ignore"):
            m = s / n
        sc = S3.plateau(n, m, self.NBm, S3.MIN_POOLED)
        t = S3.top(sc, 1)
        return t[0] if t else self.default

    def events(self, c):
        """Signals of combo c over all coins and periods: sorted arrays (k_entry, coin, k_exit, R, k_signal, per)."""
        if c in self.cache:
            return self.cache[c]
        parts = []
        for ci, per, lo, codes, offs in self.codes:
            cc = codes[offs[c]:offs[c + 1]].astype(np.int64)
            gi = lo + cc // 2
            sd = np.where(cc % 2 == 1, 1, -1)
            R, done, x, e = self._outcomes(ci, gi, sd)
            ke = k_of(self.ts15[ci][e])
            kx = k_of(self.ts15[ci][np.clip(x, 0, len(self.ts15[ci]) - 1)])
            ks = k_of(self.tst[ci][gi])
            pi = C.PERIOD_ORDER.index(per)
            parts.append(np.stack([ke, np.full(len(ke), ci), kx, R, ks, np.full(len(ke), pi)], 1)[done])
        a = np.concatenate(parts)
        a = a[np.lexsort((a[:, 1], a[:, 0]))]
        ev = dict(ke=a[:, 0].astype(np.int64), coin=a[:, 1].astype(np.int64), kx=a[:, 2].astype(np.int64),
                  R=a[:, 3], ks=a[:, 4].astype(np.int64), per=a[:, 5].astype(np.int64))
        if len(self.cache) > 60:
            self.cache.pop(next(iter(self.cache)))
        self.cache[c] = ev
        return ev


def run(D, per, method):
    kind, W = METHODS[method]
    a, b = C.PERIODS[per]
    ka, kb = int(k_of([C.ts_ns(a)])[0]), int(k_of([C.ts_ns(b)])[0])
    pi = C.PERIOD_ORDER.index(per)
    active = D.default
    if kind != "none":
        active = D.repick(ka, W)
    ev = D.events(active)
    ptr = int(np.searchsorted(ev["ks"], ka))       # ks sorted with ke (signal bar precedes entry)
    busy = np.full(len(C.COINS), -1, np.int64)
    heap = []
    closes = 0
    trades = []                                    # (ke, coin, R, combo)
    picks = [(ka, active)]
    next_monday = ka + (WEEK - ((ka - int(k_of([C.WEEK0])[0])) % WEEK)) % WEEK
    if next_monday == ka:
        next_monday += WEEK

    def switch(T):
        nonlocal active, ev, ptr
        new = D.repick(T, W)
        picks.append((T, new))
        if new != active:
            active = new
            ev = D.events(active)
        ptr = int(np.searchsorted(ev["ke"], T))

    while True:
        nk = ev["ke"][ptr] if ptr < len(ev["ke"]) else None
        if nk is not None and ev["ks"][ptr] >= kb:
            nk = None
        if nk is not None and ev["per"][ptr] != pi:
            ptr += 1
            continue
        hc = heap[0][0] if heap else None
        if kind == "weekly" and next_monday < kb and (nk is None or next_monday <= nk) and \
                (hc is None or next_monday <= hc + 1):
            switch(next_monday)
            next_monday += WEEK
            continue
        if hc is not None and (nk is None or hc < nk):
            kx, _ci = heapq.heappop(heap)
            closes += 1
            if kind == "roll" and closes % 5 == 0:
                switch(kx + 1)
            continue
        if nk is None:
            break
        ci = int(ev["coin"][ptr])
        if busy[ci] < nk:
            busy[ci] = ev["kx"][ptr]
            heapq.heappush(heap, (int(ev["kx"][ptr]), ci))
            trades.append((nk, ci, float(ev["R"][ptr]), active))
        ptr += 1
    tr = np.array(trades) if trades else np.zeros((0, 4))
    return tr, np.array(picks)


def job(args):
    strat, tf = args
    path = os.path.join(RE_DIR, f"{strat}_{tf}.npz")
    if os.path.exists(path):
        return strat, tf, "cached", 0
    t0 = time.time()
    try:
        os.nice(5)
    except OSError:
        pass
    D = Data(strat, tf)
    out = {}
    for per in RUN_PERIODS:
        for method in METHODS:
            tr, pk = run(D, per, method)
            out[f"{per}|{method}|trades"] = tr
            out[f"{per}|{method}|picks"] = pk
            C.log(strat, tf, per, method, len(tr), round(float(tr[:, 2].mean()), 4) if len(tr) else None,
                  len(pk), len(set(pk[:, 1].tolist())))
    C.save_npz(path, **out)
    return strat, tf, "ok", round(time.time() - t0, 1)


if __name__ == "__main__":
    procs = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    jobs = [(s, tf) for s in C.STRATS for tf in C.TFS]
    with Pool(procs, maxtasksperchild=1) as p:
        for r in p.imap_unordered(job, jobs):
            C.log(*r)
