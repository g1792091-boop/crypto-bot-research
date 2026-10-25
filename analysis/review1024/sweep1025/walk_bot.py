"""walk_all with the live engine's entry-bar rule: the ladder ignores the entry minute's range."""
import numpy as np
from numba import njit, prange


@njit(parallel=True, cache=False)
def walk_bot(o, h, l, c, start, stop_end, side, lev, atrf, ex_sk, ex_sv, ex_tk, ex_tv, ex_lg, ex_ll, ex_ls,
             cost, margin, maxk):
    n = len(start); m = len(ex_sk)
    W = np.zeros((n, m), np.float32); K = np.zeros((n, m), np.int32); Y = np.zeros((n, m), np.int8)
    for i in prange(n):
        e0 = start[i]; e1 = min(stop_end[i], e0 + maxk); sd = side[i]; L = lev[i]; p0 = o[e0]
        dliq = 1.0 / L - 0.005
        for x in range(m):
            d = ex_sv[x] * atrf[i] if ex_sk[x] == 0 else ex_sv[x] / L - cost
            if d <= 0.0005:
                d = 0.0005
            liq = d >= dliq
            if liq:
                d = dliq
            u = 1e9
            if ex_tk[x] == 1:
                u = ex_tv[x] / L + cost
            elif ex_tk[x] == 2:
                u = ex_tv[x] * atrf[i]
            g1 = ex_lg[x] / L + cost if ex_lg[x] > 0 else 1e9
            l1 = ex_ll[x] / L + cost; stp = ex_ls[x] / L
            lock = -1e9; best = 0.0; mv = 0.0; why = 3; kk = e1 - e0
            for j in range(e0, e1):
                if sd > 0:
                    oj = o[j] / p0 - 1; lj = l[j] / p0 - 1; hj = h[j] / p0 - 1
                else:
                    oj = 1 - o[j] / p0; lj = 1 - h[j] / p0; hj = 1 - l[j] / p0
                floor = max(-d, lock)
                if oj <= floor:
                    mv = oj; why = 0 if lock < -d + 1e-12 or lock == -1e9 else 1; kk = j - e0; break
                if lj <= floor:
                    mv = floor; why = 0 if lock == -1e9 else 1; kk = j - e0; break
                if hj >= u:
                    mv = max(u, oj); why = 2; kk = j - e0; break
                if hj > best and j > e0:
                    best = hj
                    if best >= g1:
                        nl = l1 + np.floor((best - g1) / stp + 1e-9) * stp
                        if nl > lock:
                            lock = nl
                if j == e1 - 1:
                    mv = c[j] / p0 - 1 if sd > 0 else 1 - c[j] / p0
                    why = 4 if e1 < stop_end[i] else 3; kk = j - e0
            if why == 0 and liq and mv <= -d + 1e-12:
                w = -margin
            else:
                w = margin * L * (mv - cost)
                if w < -margin:
                    w = -margin
            W[i, x] = w; K[i, x] = kk + 1; Y[i, x] = why
    return W, K, Y


