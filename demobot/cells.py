"""Trade outcomes of every possible entry ("cells"): for each coin, timeframe, bar and side, the result of entering at
the next 15m open under every exit (house exit at the sizer's leverage for the ranking, the 12 fixed take-profit /
stop pairs, and the house exit at 20/30/40/50x with liquidation for the accounts).

Outcomes do not depend on the strategy settings (only on bar, side, the signal bar's ATR14 and the timeframe), so a
signal of any setting is a lookup into this book (the study's precompute idea).
"""
from __future__ import annotations

import numpy as np

from . import exits as X
from . import grid as G
from . import store as ST

M15 = 15 * 60 * 1000


def compute(coin: str, tf: str, b15: dict, sig_ts: np.ndarray, sides: np.ndarray, atr: np.ndarray,
            forming=None) -> dict:
    """Outcomes of cells (signal bar open time sig_ts, side, ATR of the signal bar) on the 15m bars b15.
    Returns dict: e_ts, raw, done (bool), F (n, NF) float32, T (n, NT) int64 (exit bar open time ms, -1 open).
    A cell whose entry bar has not closed yet is a placeholder (entry price = the forming bar's open when known)."""
    n = len(sig_ts)
    F = np.full((n, ST.NF), np.nan, np.float32)
    T = np.full((n, ST.NT), -1, np.int64)
    F[:, ST.F_MAIN_REASON] = 3
    F[:, ST.F_L_REASON:ST.F_L_REASON + 4] = 3
    done = np.zeros(n, bool)
    step = G.TF_MIN[tf] * 60 * 1000
    e_ts = np.asarray(sig_ts, np.int64) + step
    raw = np.full(n, np.nan)
    ts15 = b15["ts"]
    e = np.searchsorted(ts15, e_ts)
    have = (e < len(ts15))
    have[have] &= ts15[e[have]] == e_ts[have]
    raw[have] = b15["o"][e[have]]
    if forming is not None:
        fm = (~have) & (e_ts == int(forming[0]))
        raw[fm] = float(forming[1])
    ok = have & np.isfinite(atr) & (atr > 0)
    # an entry bar missing inside the data (gap) or no ATR: never tradable, closed as empty
    last = ts15[-1] if len(ts15) else -1
    done[~ok & (e_ts <= last)] = True
    idx = np.flatnonzero(ok)
    if not len(idx):
        return dict(e_ts=e_ts, raw=raw, done=done, F=F, T=T)
    ee = e[idx].astype(np.int64)
    sd = np.asarray(sides, np.int64)[idx]
    a = np.asarray(atr, float)[idx]
    rw = raw[idx]
    lev, liq, _feas = X.lev_liq(coin, sd, a / rw)
    r = X.run_scan(b15, ee, sd, lev, liq, X.K_STOP * a)
    F[idx, ST.F_MAIN_R] = r["R"]
    F[idx, ST.F_MAIN_G] = r["gross"]
    F[idx, ST.F_MAIN_REASON] = r["reason"]
    F[idx, ST.F_MAIN_EXIT] = r["exit_raw"]
    d_main = r["done"]
    T[idx, ST.T_MAIN] = np.where(d_main, ts15[np.clip(r["x"], 0, len(ts15) - 1)], -1)
    tr, tg, tx = X.tpsl_outcomes(b15, ee, sd, a, lev, liq)
    F[idx, ST.F_TP_R:ST.F_TP_R + 12] = tr.T
    F[idx, ST.F_TP_G:ST.F_TP_G + 12] = tg.T
    T[idx, ST.T_TP:ST.T_TP + 12] = np.where(tx.T >= 0, ts15[np.clip(tx.T, 0, len(ts15) - 1)], -1)
    d_tp = np.all(tx >= 0, axis=0)
    d_all = d_main & d_tp
    for li, L in enumerate(G.LEVS):
        lf = np.where(sd > 0, X.first_tier_liq_frac(coin, 1, L), X.first_tier_liq_frac(coin, -1, L))
        rl = X.run_scan(b15, ee, sd, np.full(len(ee), float(L)), lf, X.K_STOP * a, liq_touch=True)
        F[idx, ST.F_L_R + li] = rl["R"]
        F[idx, ST.F_L_REASON + li] = rl["reason"]
        F[idx, ST.F_L_EXIT + li] = rl["exit_raw"]
        T[idx, ST.T_L + li] = np.where(rl["done"], ts15[np.clip(rl["x"], 0, len(ts15) - 1)], -1)
        d_all &= rl["done"]
    done[idx] = d_all
    return dict(e_ts=e_ts, raw=raw, done=done, F=F, T=T)


def n_finished(F: np.ndarray, T: np.ndarray) -> np.ndarray:
    """Number of exits that have finished per cell (main, 12 TP/stop pairs, 4 leverages): a cell is written to the
    database whenever this changes, so a separate reader (the rank process) sees every finished exit."""
    main = (F[:, ST.F_MAIN_REASON] != 3) & (T[:, ST.T_MAIN] >= 0)
    tp = (T[:, ST.T_TP:ST.T_TP + 12] >= 0).sum(axis=1)
    lv = (T[:, ST.T_L:ST.T_L + 4] >= 0).sum(axis=1)
    return main.astype(int) + tp + lv


class Book:
    """In-memory cells of one (coin, tf): two rows per bar (0 = long, 1 = short), bars from the history start."""

    def __init__(self, coin: str, tf: str):
        self.coin, self.tf = coin, tf
        self.ts = np.zeros(0, np.int64)
        self.atr = np.zeros(0)
        self.raw = np.zeros((0, 2))
        self.done = np.zeros((0, 2), bool)
        self.F = np.zeros((0, 2, ST.NF), np.float32)
        self.T = np.zeros((0, 2, ST.NT), np.int64)
        self.stored = np.zeros(0, bool)          # bar row already in the database

    def __len__(self):
        return len(self.ts)

    def index(self, ts: np.ndarray) -> np.ndarray:
        """Row (bar) index of signal bar times; -1 when absent."""
        k = np.searchsorted(self.ts, ts)
        kc = np.minimum(k, max(len(self.ts) - 1, 0))
        ok = (k < len(self.ts)) & (len(self.ts) > 0)
        ok[ok] &= self.ts[kc[ok]] == np.asarray(ts)[ok]
        return np.where(ok, k, -1)

    def load(self, conn) -> None:
        z = ST.load_cells(conn, self.coin, self.tf)
        if not len(z["ts"]):
            return
        bars = np.unique(z["ts"])
        nb = len(bars)
        self.ts = bars
        self.atr = np.full(nb, np.nan)
        self.raw = np.full((nb, 2), np.nan)
        self.done = np.zeros((nb, 2), bool)
        self.F = np.full((nb, 2, ST.NF), np.nan, np.float32)
        self.T = np.full((nb, 2, ST.NT), -1, np.int64)
        k = np.searchsorted(bars, z["ts"])
        s = np.where(z["side"] > 0, 0, 1)
        self.atr[k] = z["atr"]
        self.raw[k, s] = z["raw"]
        self.done[k, s] = z["done"]
        self.F[k, s] = z["F"]
        self.T[k, s] = z["T"]
        self.stored = np.ones(nb, bool)

    def add_bars(self, ts: np.ndarray, atr: np.ndarray) -> np.ndarray:
        """Append new signal bars (sorted, newer than the last); returns their row indices."""
        ts = np.asarray(ts, np.int64)
        if len(self.ts):
            keep = ts > self.ts[-1]
            ts, atr = ts[keep], np.asarray(atr)[keep]
        m = len(ts)
        if not m:
            return np.zeros(0, np.int64)
        k0 = len(self.ts)
        self.ts = np.concatenate([self.ts, ts])
        self.atr = np.concatenate([self.atr, np.asarray(atr, float)])
        self.raw = np.concatenate([self.raw, np.full((m, 2), np.nan)])
        self.done = np.concatenate([self.done, np.zeros((m, 2), bool)])
        F = np.full((m, 2, ST.NF), np.nan, np.float32)
        F[:, :, ST.F_MAIN_REASON] = 3
        F[:, :, ST.F_L_REASON:ST.F_L_REASON + 4] = 3
        self.F = np.concatenate([self.F, F])
        self.T = np.concatenate([self.T, np.full((m, 2, ST.NT), -1, np.int64)])
        self.stored = np.concatenate([self.stored, np.zeros(m, bool)])
        return np.arange(k0, k0 + m)

    def update(self, rows: np.ndarray, b15: dict, forming=None, only_changed: bool = False) -> list:
        """(Re)compute the cells of bar rows (both sides); returns DB rows for store.put_cells. only_changed: only
        cells that finished now or were never stored (open cells are recomputed from the bars after a restart)."""
        rows = np.asarray(rows, np.int64)
        if not len(rows):
            return []
        kk = np.repeat(rows, 2)
        fresh = ~self.stored[kk] if len(self.stored) else np.ones(len(kk), bool)
        sides = np.tile(np.array([1, -1], np.int64), len(rows))
        res = compute(self.coin, self.tf, b15, self.ts[kk], sides, self.atr[kk], forming=forming)
        si = np.tile(np.array([0, 1]), len(rows))
        prev_fin = n_finished(self.F[kk, si], self.T[kk, si])
        self.raw[kk, si] = res["raw"]
        self.done[kk, si] = res["done"]
        self.F[kk, si] = res["F"]
        self.T[kk, si] = res["T"]
        self.stored[rows] = True
        new_fin = n_finished(res["F"], res["T"])
        out = []
        for j in range(len(kk)):
            if only_changed and not fresh[j] and new_fin[j] == prev_fin[j]:
                continue
            out.append((self.coin, self.tf, int(self.ts[kk[j]]), int(sides[j]), int(res["e_ts"][j]),
                        int(res["done"][j]), float(self.atr[kk[j]]), float(res["raw"][j]),
                        res["F"][j], res["T"][j]))
        return out

    def open_rows(self) -> np.ndarray:
        """Bar rows with at least one unfinished side."""
        return np.flatnonzero(~self.done.all(axis=1))
