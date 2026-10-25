"""Hunt 10/25 step 2: every single-member bot = entry cell (strategy@tf) x side mode (both / short only / long only) x
trend filter (none, or the higher bar's trend state must agree) x exit (330), one wallet one position across the
6 coins, fixed sizing. Scores the 19 days, the two halves and four quarters. Output: out/single.npz + out/groups.csv."""
import os, sys, time
import numpy as np, pandas as pd
from numba import njit, prange

HERE = os.path.dirname(os.path.abspath(__file__)); OUTD = os.path.join(HERE, "out")
MIN = 60_000
A = 1791212400000            # 2026-10-05 15:00 UTC = 10-06 00:00 KST
Z = 1792851120000            # 2026-10-24 14:12 UTC (data end)
Q = np.linspace(A, Z, 5).astype(np.int64)        # quarter edges; the middle one is the half split
MIN_SIG = 6

S = pd.read_pickle(os.path.join(OUTD, "sig.pkl.gz"))
F = np.load(os.path.join(OUTD, "fwd.npz"))
W = F["W"]; K = F["K"]
TFO = {"15m": 0, "30m": 1, "1h": 2, "4h": 3}
order = np.lexsort((-S.tf.map(TFO).to_numpy(), S.t.to_numpy()))      # time, then the longer timeframe first
S = S.iloc[order].reset_index(drop=True); W = W[order]; K = K[order]
side = S.side.to_numpy()


sys.path.insert(0, HERE)
import hb_common as HC  # noqa: E402
FILT = HC.filters(S)
FNAMES = list(FILT)

cell = (S.name + "@" + S.tf).to_numpy()
cells = sorted(set(cell))
groups = []; idx_list = []
cid = {c: np.flatnonzero(cell == c) for c in cells}
for c in cells:
    ii = cid[c]
    for mode in ("B", "S", "L"):
        jj = ii if mode == "B" else ii[side[ii] < 0] if mode == "S" else ii[side[ii] > 0]
        for f in FNAMES:
            kk = jj[FILT[f][jj]]
            if len(kk) >= MIN_SIG:
                groups.append((c, mode, f)); idx_list.append(kk)
ptr = np.zeros(len(groups) + 1, np.int64); ptr[1:] = np.cumsum([len(x) for x in idx_list])
IDX = np.concatenate(idx_list).astype(np.int64)
print("groups", len(groups), "rows", len(IDX), flush=True)
t = S.t.to_numpy(np.int64)


@njit(parallel=True, cache=True)
def score(ptr, IDX, t, W, K, Q):
    G = len(ptr) - 1; X = W.shape[1]
    R = np.zeros((G, X, 13), np.float32)    # eq, dd, n, wins, eqH1, eqH2, nH1, nH2, eqQ1..Q4, worst
    for g in prange(G):
        for x in range(X):
            free = -1; eq = 1.0; peak = 1.0; dd = 0.0; n = 0; wn = 0
            e1 = 1.0; e2 = 1.0; n1 = 0; n2 = 0; q = np.ones(4); worst = 0.0
            for p in range(ptr[g], ptr[g + 1]):
                i = IDX[p]
                if t[i] < free:
                    continue
                w = W[i, x]; eq *= 1 + w; n += 1
                if w > 0:
                    wn += 1
                if w < worst:
                    worst = w
                if eq > peak:
                    peak = eq
                if eq / peak - 1 < dd:
                    dd = eq / peak - 1
                if t[i] < Q[2]:
                    e1 *= 1 + w; n1 += 1
                else:
                    e2 *= 1 + w; n2 += 1
                for k in range(4):
                    if t[i] >= Q[k] and t[i] < Q[k + 1]:
                        q[k] *= 1 + w
                free = t[i] + K[i, x] * 60000
            R[g, x, 0] = eq; R[g, x, 1] = dd; R[g, x, 2] = n; R[g, x, 3] = wn; R[g, x, 4] = e1; R[g, x, 5] = e2
            R[g, x, 6] = n1; R[g, x, 7] = n2
            for k in range(4):
                R[g, x, 8 + k] = q[k]
            R[g, x, 12] = worst
    return R


t0 = time.time()
R = score(ptr, IDX, t, W, K, Q)
print("scored", R.shape, round(time.time() - t0), "s", flush=True)
np.save(os.path.join(OUTD, "single_R.npy"), R)
pd.DataFrame(groups, columns=["cell", "mode", "filter"]).to_csv(os.path.join(OUTD, "groups.csv"), index=False)
np.savez(os.path.join(OUTD, "groups_idx.npz"), ptr=ptr, IDX=IDX, order=order)
