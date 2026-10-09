"""The live ranking ("순위표") of every setting: per strategy x timeframe, for the 13 exits, 8 scopes (all coins,
each coin) and 3 windows (since the live start, the last 26 weeks incl. the history fill, the last 4 weeks).
Signal-level, as the 5-year study (every signal is a trade; costs included). Writes rank_<STRAT>_<tf>.npz
(CONTRACT section 4).
"""
from __future__ import annotations

import time

import numpy as np

from . import grid as G
from . import store as ST

WEEK_MS = 7 * 86400 * 1000
M15 = 15 * 60 * 1000
K_STATS = ("n", "wins", "mean_R", "mean_G", "mdd_R", "whip", "avg_win_R", "avg_loss_R", "plateau", "open", "nsig")
MIN_N = {"live": (30, 15), "26w": (200, 100), "4w": (50, 25)}
WHIP_BARS = 3
LUCK_B = 400


def windows(live0: int, now: int) -> list:
    return [("live", live0, now), ("26w", now - 26 * WEEK_MS, now), ("4w", now - 4 * WEEK_MS, now)]


def _seg_mdd(seg_start: np.ndarray, r: np.ndarray) -> np.ndarray:
    """Max drawdown of the cumulative sum of r inside each segment (segments start at seg_start indices)."""
    if not len(r):
        return np.zeros(len(seg_start))
    cs = np.cumsum(r)
    base = np.r_[0.0, cs][seg_start]
    lens = np.diff(np.r_[seg_start, len(r)])
    rel = cs - np.repeat(base, lens)
    segno = np.repeat(np.arange(len(seg_start)), lens).astype(float)
    K = (np.abs(rel).max() + 10.0) * 4
    adj = rel + segno * K
    runmax = np.maximum(np.maximum.accumulate(adj), segno * K)
    return np.maximum.reduceat(runmax - adj, seg_start)


def _gather(eng, strat: str, tf: str, lo_ms: int):
    """All signals since lo_ms of every coin: coin int8, t15 int32 (15m index from lo_ms), combo int16,
    side index (0 long / 1 short) int8, book row k int32. Coin-major, time order inside a coin."""
    parts = []
    for ci, coin in enumerate(G.COINS):
        ts, cb, sd = eng.sigs[(coin, tf, strat)].arrays()
        a = int(np.searchsorted(ts, lo_ms))
        ts, cb, sd = ts[a:], cb[a:], sd[a:]
        k = eng.books[(coin, tf)].index(ts)
        ok = k >= 0
        parts.append((np.full(int(ok.sum()), ci, np.int8), ((ts[ok] - lo_ms) // M15).astype(np.int32),
                      cb[ok].astype(np.int16), np.where(sd[ok] > 0, 0, 1).astype(np.int8), k[ok].astype(np.int32)))
    return tuple(np.concatenate([p[i] for p in parts]) for i in range(5))


def _outcome(eng, tf: str, coin_a, k_a, si_a, e: int):
    """Net R and gross R (float32, NaN while open) of every signal under exit e."""
    R = np.full(len(k_a), np.nan, np.float32)
    Gv = np.full(len(k_a), np.nan, np.float32)
    bounds = np.searchsorted(coin_a, np.arange(len(G.COINS) + 1))
    for ci, coin in enumerate(G.COINS):
        a, b = bounds[ci], bounds[ci + 1]
        if a == b:
            continue
        F = eng.books[(coin, tf)].F
        kk, ss = k_a[a:b], si_a[a:b]
        if e == 0:
            rs = F[kk, ss, ST.F_MAIN_REASON]
            R[a:b] = np.where(rs != 3, F[kk, ss, ST.F_MAIN_R], np.nan)
            Gv[a:b] = np.where(rs != 3, F[kk, ss, ST.F_MAIN_G], np.nan)
        elif e == G.HALFBE:
            R[a:b] = F[kk, ss, ST.F_HB_R]
            Gv[a:b] = F[kk, ss, ST.F_HB_G]
        else:
            R[a:b] = F[kk, ss, ST.F_TP_R + e - 1]
            Gv[a:b] = F[kk, ss, ST.F_TP_G + e - 1]
    return R, Gv


def _mdd_by_key(order: np.ndarray, key: np.ndarray, r: np.ndarray, minl: int, chunk: int = 600_000) -> np.ndarray:
    """Largest fall of the cumulative sum of r per key, rows taken in `order` (grouped by key, time inside)."""
    out = np.zeros(minl)
    n = len(order)
    i = 0
    while i < n:
        j = min(n, i + chunk)
        if j < n:                         # end the chunk at a key boundary
            kj = key[order[j - 1]]
            while j < n and key[order[j]] == kj:
                j += 1
        oo = order[i:j]
        ks = key[oo]
        starts = np.flatnonzero(np.r_[True, ks[1:] != ks[:-1]])
        md = _seg_mdd(starts, r[oo].astype(np.float64))
        out[ks[starts]] = np.maximum(out[ks[starts]], md)
        i = j
    return out


def compute(eng, strat: str, tf: str, now_ms: int, seed: int = 0) -> dict:
    """Ranking arrays of one strategy x timeframe (memory-lean: one exit at a time, small dtypes)."""
    t0 = time.time()
    nc = G.NCOMBO[strat]
    live0 = eng.live_start or now_ms
    wins_ = windows(live0, now_ms)
    W, E, S, K = len(wins_), G.NEXIT, len(G.SCOPES), len(K_STATS)
    stats = np.full((W, E, S, nc, K), np.nan, np.float32)
    luck = np.full((W, E, S), np.nan, np.float32)
    step15 = G.TF_MIN[tf] // 15
    lo_all = min(w[1] for w in wins_)
    lo_all -= lo_all % M15
    coin_a, t15, cb, si, k_a = _gather(eng, strat, tf, lo_all)
    n_all = len(t15)
    key_all = cb.astype(np.int32)
    key_coin = (coin_a.astype(np.int32) + 1) * nc + key_all
    # whip (noise): the same setting on the same coin signals the other side within WHIP_BARS bars
    o = np.lexsort((t15, cb, coin_a))
    whip = np.zeros(n_all, bool)
    if n_all > 1:
        a, b = o[:-1], o[1:]
        whip[a] = ((coin_a[b] == coin_a[a]) & (cb[b] == cb[a]) & (t15[b] - t15[a] <= WHIP_BARS * step15)
                   & (si[b] != si[a]))
    ord_coin = o.astype(np.int32)
    del o
    ord_all = np.lexsort((coin_a, t15, cb)).astype(np.int32)
    # window membership (signal bar time); live: entries at/after the live start
    t_ms_lo = [max(0, (w[1] - lo_all) // M15) for w in wins_]
    inw = []
    for wi, (wname, w0, w1) in enumerate(wins_):
        if wname == "live":
            inw.append(t15 + step15 >= (live0 - lo_all) // M15)
        else:
            inw.append(t15 >= t_ms_lo[wi])
    rng = np.random.default_rng(seed)
    nsig_w, nwh_w = [], []
    for wi in range(W):
        m = inw[wi]
        nsig_w.append((np.bincount(key_all[m], minlength=nc), np.bincount(key_coin[m], minlength=nc * S)))
        mw = m & whip
        nwh_w.append((np.bincount(key_all[mw], minlength=nc), np.bincount(key_coin[mw], minlength=nc * S)))
    for e in range(E):
        R, Gv = _outcome(eng, tf, coin_a, k_a, si, e)
        done = np.isfinite(R)
        Rz = np.where(done, R, np.float32(0))
        Gz = np.where(done, Gv, np.float32(0))
        del R, Gv
        for wi, (wname, _w0, _w1) in enumerate(wins_):
            d = done & inw[wi]
            pos = d & (Rz > 0)
            neg = d & ~pos
            op = inw[wi] & ~done
            for kind, key, minl in (("all", key_all, nc), ("coin", key_coin, nc * S)):
                n = np.bincount(key[d], minlength=minl).astype(float)
                wn = np.bincount(key[pos], minlength=minl).astype(float)
                sR = np.bincount(key[d], weights=Rz[d], minlength=minl)
                sG = np.bincount(key[d], weights=Gz[d], minlength=minl)
                sP = np.bincount(key[pos], weights=Rz[pos], minlength=minl)
                sN = np.bincount(key[neg], weights=-Rz[neg], minlength=minl)
                nop = np.bincount(key[op], minlength=minl).astype(float)
                nsig = nsig_w[wi][0 if kind == "all" else 1].astype(float)
                nwh = nwh_w[wi][0 if kind == "all" else 1].astype(float)
                mdd = _mdd_by_key(ord_all if kind == "all" else ord_coin, key, np.where(d, Rz, np.float32(0)), minl)
                with np.errstate(invalid="ignore", divide="ignore"):
                    block = np.stack([n, wn, sR / n, sG / n, mdd, nwh / nsig, sP / wn, sN / (n - wn),
                                      np.full(minl, np.nan), nop, nsig], axis=1)
                if kind == "all":
                    stats[wi, e, 0] = block
                else:
                    stats[wi, e, 1:] = block.reshape(S, nc, K)[1:]
            for sc in range(S):
                mn = MIN_N[wname][0 if sc == 0 else 1]
                nn = stats[wi, e, sc, :, 0].astype(float)
                mean = stats[wi, e, sc, :, 2].astype(float)
                stats[wi, e, sc, :, 8] = G.plateau(nn, mean, strat, mn)
                # luck: best of as many random players as eligible settings, same trade counts (normal approx.)
                pool = Rz[d & (coin_a == sc - 1)] if sc > 0 else Rz[d]
                elig = nn >= mn
                if len(pool) >= 30 and elig.any():
                    mu, sdv = float(pool.mean()), float(pool.std())
                    se = sdv / np.sqrt(nn[elig])
                    z = rng.standard_normal((LUCK_B, int(elig.sum())))
                    luck[wi, e, sc] = np.percentile((mu + z * se[None, :]).max(axis=1), 95)
        del Rz, Gz, done
    min_n = np.array([MIN_N[w[0]] for w in wins_], np.int32)
    bounds = np.array([[w[1], w[2]] for w in wins_], np.int64)
    return dict(stats=stats, luck95=luck, min_n=min_n, bounds_ms=bounds, generated_ms=np.int64(now_ms),
                seconds=round(time.time() - t0, 1))


def write_all(eng, snap_dir: str, now_ms: int, log=print) -> dict:
    meta = {"generated_ms": now_ms, "windows": list(G.WINDOWS), "exits": list(G.EXITS), "scopes": list(G.SCOPES),
            "stats": list(K_STATS), "files": {}}
    for strat in G.STRATS:
        for tf in G.TFS:
            r = compute(eng, strat, tf, now_ms)
            name = f"rank_{G.SHORT[strat]}_{tf}.npz"
            ST.write_npz(f"{snap_dir}/{name}", stats=r["stats"], luck95=r["luck95"], min_n=r["min_n"],
                         bounds_ms=r["bounds_ms"], generated_ms=r["generated_ms"])
            meta["files"][f"{G.SHORT[strat]}_{tf}"] = {"file": name, "seconds": r["seconds"],
                                                     "settings": G.NCOMBO[strat]}
            log("rank", strat, tf, f"{r['seconds']}s")
    ST.write_json(f"{snap_dir}/rank_meta.json", meta)
    return meta


def leaders(snap_dir: str, window: str = "26w", exit_i: int = 0) -> list:
    """Top setting (by plateau score) per strategy x timeframe for the home page and the daily message."""
    out = []
    wi = G.WINDOWS.index(window)
    for strat in G.STRATS:
        for tf in G.TFS:
            try:
                z = np.load(f"{snap_dir}/rank_{G.SHORT[strat]}_{tf}.npz")
            except OSError:
                continue
            st = z["stats"][wi, exit_i, 0]
            sc = st[:, 8].astype(float)
            t = G.top(sc, 1)
            if not t:
                continue
            c = t[0]
            n = float(st[c, 0])
            lk = float(z["luck95"][wi, exit_i, 0])
            mean = float(st[c, 2])
            out.append(dict(strategy=strat, short=G.SHORT[strat], tf=tf, window=window, exit=G.EXITS[exit_i],
                            label=G.combo_label(strat, c), combo=c, n=int(n), mean_R=mean,
                            win_rate=(float(st[c, 1]) / n if n else None), plateau=float(sc[c]),
                            luck95=lk, beats_luck=bool(np.isfinite(lk) and mean > lk)))
    return out


class _View:
    """The slice of the engine state rank.compute reads (one timeframe's cells, one strategy's signals), loaded
    from the database: the ranking runs as its own short process (demobot-rank.timer), not in the live loop."""

    def __init__(self, conn, tf: str, books: dict):
        from .engine import SigBuf
        self._SigBuf = SigBuf
        self.conn = conn
        self.tf = tf
        self.books = books
        self.live_start = ST.get_meta(conn, "live_start_ms")
        self.history_start = ST.get_meta(conn, "history_start_ms")
        self.sigs = {}

    def load_strat(self, strat: str, since_ms: int) -> None:
        self.sigs = {}
        for coin in G.COINS:
            b = self._SigBuf()
            b.add(*ST.load_sigs(self.conn, coin, self.tf, strat, since_ms=since_ms))
            self.sigs[(coin, self.tf, strat)] = b


def run_standalone(conn, snap_dir: str, now_ms: int, log=print) -> dict:
    """python -m demobot rank: every strategy x timeframe from the database, one timeframe's cells in memory at a
    time. Writes the rank files and rank_meta.json; records last_rank_ms."""
    from .cells import Book
    if ST.get_meta(conn, "history_start_ms") is None:
        raise RuntimeError("no history yet: run warm first")
    meta = {"generated_ms": now_ms, "windows": list(G.WINDOWS), "exits": list(G.EXITS), "scopes": list(G.SCOPES),
            "stats": list(K_STATS), "files": {}}
    for tf in G.TFS:
        books = {}
        for coin in G.COINS:
            bk = Book(coin, tf)
            bk.load(conn)
            books[(coin, tf)] = bk
        view = _View(conn, tf, books)
        live0 = view.live_start or now_ms
        lo = min(w[1] for w in windows(live0, now_ms))
        for strat in G.STRATS:
            view.load_strat(strat, lo - lo % M15)
            r = compute(view, strat, tf, now_ms)
            name = f"rank_{G.SHORT[strat]}_{tf}.npz"
            ST.write_npz(f"{snap_dir}/{name}", stats=r["stats"], luck95=r["luck95"], min_n=r["min_n"],
                         bounds_ms=r["bounds_ms"], generated_ms=r["generated_ms"])
            meta["files"][f"{G.SHORT[strat]}_{tf}"] = {"file": name, "seconds": r["seconds"],
                                                     "settings": G.NCOMBO[strat]}
            log("rank", strat, tf, f"{r['seconds']}s")
            view.sigs = {}
        del books, view
    ST.write_json(f"{snap_dir}/rank_meta.json", meta)
    ST.set_meta(conn, "last_rank_ms", int(now_ms))
    return meta
