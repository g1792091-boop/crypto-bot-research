"""Hunt 10/25: the same members (cell x side mode x filter x exit) over 2020-03 .. 2026-10-24 on the research 1m grid,
same sizing and costs. trades(member) -> DataFrame t, w, k (minutes held), side, coin; merge(list) -> one position."""
import os, sys
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import hb_common as HC                                   # noqa: E402
import hb_build as HB                                    # noqa: E402
from hb_common import RD, COINS                          # noqa: E402
from common import grid, ms                              # noqa: E402

EXITS = HB.EXITS
_M = {}


def minutes():
    if not _M:
        O, H, L, C, off = [], [], [], [], [0]
        for coin in COINS:
            g = grid(coin)
            O.append(g["o"]); H.append(g["h"]); L.append(g["l"]); C.append(g["c"]); off.append(off[-1] + g["n"])
        _M.update(o=np.concatenate(O), h=np.concatenate(H), l=np.concatenate(L), c=np.concatenate(C), off=np.array(off))
    return _M


_SIG = {}


def sigs(name, tf):
    key = (name, tf)
    if key not in _SIG:
        S = RD.signals(names=[name], tfs=[tf], period=(ms("2020-03-01"), ms("2026-10-24 14:12")))
        S = HC.add_atr(S); S = HC.add_trend(S)
        _SIG[key] = S
    return _SIG[key]


def trades(name, tf, mode, filt, exit_id):
    S = sigs(name, tf)
    m = HC.filters(S)[filt].copy()
    if mode == "S":
        m &= S.side.to_numpy() < 0
    elif mode == "L":
        m &= S.side.to_numpy() > 0
    S = S[m & np.isfinite(S.atr.to_numpy()) & (S.atr.to_numpy() > 0)].reset_index(drop=True)
    M = minutes()
    ci = S.coin.to_numpy(int)
    start = M["off"][ci] + S.e.to_numpy(np.int64); send = M["off"][ci + 1]
    p0 = M["o"][start]; ok = np.isfinite(p0)
    S = S[ok].reset_index(drop=True); start = start[ok]; send = send[ok]; ci = ci[ok]
    x = EXITS[exit_id]
    (sk, sv), (tk, tv), lad = x
    lg, ll, ls = HB.LADS[lad]
    W, K, Y = HB.walk_all(M["o"], M["h"], M["l"], M["c"], start, send, S.side.to_numpy(np.int8), HB.LEVC[ci],
                          S.atr.to_numpy() / M["o"][start], np.array([0 if sk == "atr" else 1], np.int8),
                          np.array([sv]), np.array([{"none": 0, "roe": 1, "atr": 2}[tk]], np.int8), np.array([tv]),
                          np.array([lg]), np.array([ll]), np.array([max(ls, 1e-9)]), HB.COST, HB.MARGIN, HB.MAXK)
    tfo = {"15m": 0, "30m": 1, "1h": 2, "4h": 3}[tf]
    return pd.DataFrame({"t": S.t.to_numpy(np.int64), "w": W[:, 0].astype(float), "k": K[:, 0], "why": Y[:, 0],
                         "side": S.side.to_numpy(), "coin": ci, "tfo": tfo, "member": f"{name}@{tf}/{mode}/{filt}/{exit_id}"})


def merge(T_list):
    T = pd.concat(T_list, ignore_index=True)
    T = T.sort_values(["t", "tfo"], ascending=[True, False]).reset_index(drop=True)
    t = T.t.to_numpy(); k = T.k.to_numpy(); keep = np.zeros(len(T), bool); free = -1
    for i in range(len(T)):
        if t[i] >= free:
            keep[i] = True; free = t[i] + k[i] * 60000
    return T[keep].reset_index(drop=True)


def by_period(T, freq="Y"):
    d = pd.to_datetime(T.t + 9 * 3600 * 1000, unit="ms")
    g = T.assign(p=d.dt.to_period(freq).astype(str)).groupby("p")
    return g.apply(lambda x: pd.Series({"x": float(np.prod(1 + x.w)), "n": len(x), "win": float((x.w > 0).mean())}),
                   include_groups=False)
