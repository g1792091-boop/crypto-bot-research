"""Step 2: one-position AI traders (rule proxy, setup B) run TOGETHER over 2021-08..2026-09 with cross-trader
exposure caps.

    python3 -I -B capsim.py <sig23.npz> <out_dir> [procs]

Trader = one strategy on its entry-timeframe scope (CARD by default), six coins, one position at a time.
Each signal is the verified every-signal outcome (lens2/multi_tf precompute: house exit = 2 ATR stop + ROE ladder,
taker 0.05% + 0.02% slippage per side, funding; stop/ladder on 15m bars). Entry = 15m bar e (open after the signal
bar's close); the position occupies 15m bars e..x and the trader is free again for entries at e' > x.
Setup B: among a free trader's signals at the same e: longer tf first, then widest stop first, then coin order.
No switching; signals while holding are ignored. Sizing 1% risk per stop, so P&L in R = % of that trader's equity.

Caps (checked at entry against all traders' open positions):
  cs   : at most N open positions on the same coin and side across all traders
  cl   : at most 1 open position per same-bet cluster per coin-side
  book : at most M open positions in the same direction across all coins
A trader whose first choice is blocked takes its next allowed signal at the same e if it has one; otherwise it
stays flat (free for later signals). Same-moment order across traders (pre-registered tie-break): longer tf, then
widest stop first, then a daily rotation of trader ids.
"""
import heapq
import json
import os
import sys

sys.path[:0] = ['/root/.local/lib/python3.11/site-packages', os.path.dirname(os.path.abspath(__file__))]
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from multiprocessing import Pool  # noqa: E402
import common5 as C  # noqa: E402

DAYNS = 86400 * 10**9
T0 = pd.Timestamp("2021-08-01").value
SPLIT = pd.Timestamp("2024-07-01").value
_G = {}


def prep(path, traders, scope):
    d = C.load(path)
    names = list(d["names"])
    m = C.scope_mask(d, {s: scope[s] for s in traders})
    tid_of = np.full(len(names), -1, np.int16)
    for k, s in enumerate(traders):
        tid_of[names.index(s)] = k
    t = pd.DataFrame({"tid": tid_of[d["s"][m]], "e": d["e"][m], "x": d["x"][m], "tf": d["tf"][m],
                      "coin": d["coin"][m], "side": d["side"][m], "R": d["R"][m].astype(float),
                      "g": d["gross"][m].astype(float), "sf": d["sf"][m].astype(float)})
    t = t.assign(ntf=-t.tf, nsf=-t.sf).sort_values(["e", "tid", "ntf", "nsf", "coin"], kind="mergesort")
    t = t.drop(columns=["ntf", "nsf"]).reset_index(drop=True)
    ts15 = d["ts15"]
    return t, ts15


def run(t, ts15, ntr, cs_cap=0, clusters=None, book_cap=0, rot=True):
    """clusters: array tid -> cluster id (-1 none) or None. Caps 0 = off."""
    E = t.e.to_numpy(); X = t.x.to_numpy(); TID = t.tid.to_numpy(); TF = t.tf.to_numpy()
    CO = t.coin.to_numpy(); SD = t.side.to_numpy(); SF = t.sf.to_numpy()
    CS = (CO.astype(np.int64) * 2 + (SD > 0)).astype(np.int64)
    n = len(E)
    bnd = np.flatnonzero(np.diff(E)) + 1
    starts = np.r_[0, bnd]
    ends = np.r_[bnd, n]
    busy = np.full(ntr, -1, np.int64)
    cs_cnt = np.zeros(12, np.int64)
    ncl = int(clusters.max()) + 1 if clusters is not None and (clusters >= 0).any() else 0
    cl_cnt = np.zeros((max(ncl, 1), 12), np.int64)
    dir_cnt = np.zeros(2, np.int64)
    heap = []
    taken = []      # row idx, rank, crowd_cs, crowd_dir
    blocked = []    # first-choice row idx, reason bits, rerouted(0/1)
    intended = np.zeros(ntr, np.int64)
    day0 = ts15[E] // DAYNS
    for g0, g1 in zip(starts, ends):
        e = E[g0]
        while heap and heap[0][0] < e:
            _, cs, cl, dr = heapq.heappop(heap)
            cs_cnt[cs] -= 1
            dir_cnt[dr] -= 1
            if cl >= 0:
                cl_cnt[cl, cs] -= 1
        # segments per trader (rows sorted by tid then priority)
        segs = []
        i = g0
        while i < g1:
            k = TID[i]
            j = i + 1
            while j < g1 and TID[j] == k:
                j += 1
            if busy[k] < e:
                segs.append((-TF[i], -SF[i], ((k + day0[i]) % ntr) if rot else k, k, i, j))
            i = j
        if not segs:
            continue
        segs.sort()
        for _, _, _, k, i, j in segs:
            intended[k] += 1
            cl = clusters[k] if clusters is not None else -1
            took = False
            first_reason = 0
            for r in range(i, j):
                cs = CS[r]
                dr = 1 if SD[r] > 0 else 0
                reason = 0
                if cs_cap and cs_cnt[cs] >= cs_cap:
                    reason |= 1
                if cl >= 0 and cl_cnt[cl, cs] >= 1:
                    reason |= 2
                if book_cap and dir_cnt[dr] >= book_cap:
                    reason |= 4
                if r == i:
                    first_reason = reason
                if reason == 0:
                    taken.append((r, r - i, cs_cnt[cs], dir_cnt[dr]))
                    cs_cnt[cs] += 1
                    dir_cnt[dr] += 1
                    if cl >= 0:
                        cl_cnt[cl, cs] += 1
                    heapq.heappush(heap, (X[r], cs, cl, dr))
                    busy[k] = X[r]
                    took = True
                    break
            if first_reason:
                blocked.append((i, first_reason, 1 if took else 0))
    tk = np.array(taken, dtype=np.int64).reshape(-1, 4)
    bl = np.array(blocked, dtype=np.int64).reshape(-1, 3)
    return tk, bl, intended


def exposure(t, tk, nbars):
    """Open-position counts per 15m bar: same direction (long, short) and max per coin-side."""
    r = tk[:, 0]
    e = t.e.to_numpy()[r]; x = t.x.to_numpy()[r]; sd = t.side.to_numpy()[r]; co = t.coin.to_numpy()[r]
    out = {}
    dl = np.zeros(nbars + 1, np.int32)
    ds = np.zeros(nbars + 1, np.int32)
    np.add.at(dl, e[sd > 0], 1); np.add.at(dl, x[sd > 0] + 1, -1)
    np.add.at(ds, e[sd < 0], 1); np.add.at(ds, x[sd < 0] + 1, -1)
    L = np.cumsum(dl)[:nbars]; S = np.cumsum(ds)[:nbars]
    out["long"], out["short"] = L, S
    csmax = np.zeros(nbars, np.int32)
    for c in range(6):
        for s in (1, -1):
            m = (co == c) & (sd == s)
            dd = np.zeros(nbars + 1, np.int32)
            np.add.at(dd, e[m], 1); np.add.at(dd, x[m] + 1, -1)
            csmax = np.maximum(csmax, np.cumsum(dd)[:nbars])
    out["csmax"] = csmax
    return out


def summarize(t, ts15, tk, bl, intended, traders, base=None):
    """Per-trader and book stats. base = (tk, ...) of the uncapped run for paired differences."""
    R = t.R.to_numpy(); G = t.g.to_numpy(); TID = t.tid.to_numpy(); E = t.e.to_numpy(); X = t.x.to_numpy()
    r = tk[:, 0]
    rows = []
    for k, s in enumerate(traders):
        m = TID[r] == k
        mb = TID[bl[:, 0]] == k if len(bl) else np.zeros(0, bool)
        rows.append(dict(trader=s, wave=C.WAVE[s], intended=int(intended[k]), trades=int(m.sum()),
                         sumR=float(R[r[m]].sum()), meanR=float(R[r[m]].mean()) if m.any() else np.nan,
                         meanG=float(G[r[m]].mean()) if m.any() else np.nan,
                         blocked_first=int(mb.sum()),
                         blocked_flat=int((mb & (bl[:, 2] == 0)).sum()) if len(bl) else 0,
                         rerouted=int((tk[m, 1] > 0).sum()),
                         blocked_R=float(R[bl[mb, 0]].mean()) if mb.any() else np.nan,
                         blocked_G=float(G[bl[mb, 0]].mean()) if mb.any() else np.nan,
                         by_cs=int(((bl[mb, 1] & 1) > 0).sum()) if mb.any() else 0,
                         by_cl=int(((bl[mb, 1] & 2) > 0).sum()) if mb.any() else 0,
                         by_book=int(((bl[mb, 1] & 4) > 0).sum()) if mb.any() else 0))
    df = pd.DataFrame(rows)
    df["blocked_share"] = df.blocked_first / df.intended
    # book R by exit day / week
    xd = ((ts15[X[r]] - T0) // DAYNS).astype(int)
    ND = int((pd.Timestamp("2026-09-30").value - T0) // DAYNS)
    xd = np.clip(xd, 0, ND - 1)
    daily = np.bincount(xd, weights=R[r], minlength=ND)
    cum = np.cumsum(daily)
    dd = float(np.max(np.maximum.accumulate(np.r_[0, cum]) - np.r_[0, cum]))
    roll30 = np.convolve(daily, np.ones(30), "valid")
    book = dict(trades=int(len(r)), sumR=float(R[r].sum()), meanR=float(R[r].mean()), sumG=float(G[r].sum()),
                meanG=float(G[r].mean()), blocked_meanG=float(G[bl[:, 0]].mean()) if len(bl) else np.nan,
                worst_day=float(daily.min()),
                worst_30d=float(roll30.min()), maxDD_R=dd, intended=int(intended.sum()),
                blocked_first=int(len(bl)), blocked_flat=int((bl[:, 2] == 0).sum()) if len(bl) else 0)
    return df, book, daily


def week_ci(diff_daily, B=2000, seed=7):
    """95% CI of the total of a daily series by week-block bootstrap."""
    nw = len(diff_daily) // 7
    w = diff_daily[:nw * 7].reshape(nw, 7).sum(1)
    rng = np.random.default_rng(seed)
    bs = w[rng.integers(0, nw, size=(B, nw))].sum(1)
    return float(np.quantile(bs, 0.025)), float(np.quantile(bs, 0.975))
