"""Independent 1d check with exits resolved on 5m sub-bars, zero planted edge (random side).
Per-trade outcomes for P3 (20%x20, TP 10% ROE, no stop) and P4 (40%x50), then an i.i.d. trade bootstrap
(Poisson number of trades per period at the sim's taken rate) for 30d / 1y metrics."""
import numpy as np
import pandas as pd
from common import *

rng = np.random.default_rng(777)
D1 = load("1d"); D5 = load("5m")
H5 = 4 * 288
rows = {k: [] for k in ("o", "h", "l", "c")}
for c in COINS:
    d1 = D1[c]; d5 = D5[c]
    ok = np.where(admissible(d1, "1d"))[0]
    ts5 = d5.ts.values.astype("datetime64[m]").astype(np.int64)
    ts1 = d1.ts.values.astype("datetime64[m]").astype(np.int64)
    s1 = np.searchsorted(ts5, ts1[ok + 1])
    good = (s1 + H5 - 1 < len(ts5))
    s1c = np.minimum(s1, len(ts5) - H5)
    good &= (ts5[s1c] == ts1[ok + 1]) & (ts5[s1c + H5 - 1] - ts5[s1c] == (H5 - 1) * 5)
    s1 = s1[good]
    j = s1[:, None] + np.arange(H5)[None, :]
    for k, col in (("o", "open"), ("h", "high"), ("l", "low"), ("c", "close")):
        rows[k].append(d5[col].values[j])
o, h, l, cl = (np.vstack(rows[k]) for k in ("o", "h", "l", "c"))
n = len(o)
print("1d candidates with full 5m sub-paths:", n)
out = []
for name, M, L in (("P3 20%x20", .2, 20), ("P4 40%x50", .4, 50)):
    rs = []
    for sg in (1, -1):
        dl = np.full(n, 1 / L - MMR); sd = np.full(n, np.inf); td = np.full(n, 0.1 / L)
        jx, code, g = exits(o, h, l, cl, np.full(n, sg), dl, sd, td, "colour")
        r = equity_ret(code, g, jx, M, L, 5)
        rs.append((r, code))
    r = np.concatenate([rs[0][0], rs[1][0]]); code = np.concatenate([rs[0][1], rs[1][1]])
    lr = np.log1p(r)
    # i.i.d. trade bootstrap at the sim's taken rate (6.1 trades / 30 days)
    rate30 = 6.1
    NP = 20000
    res = {}
    for T, lab in ((30, "30d"), (365, "1y")):
        k = rng.poisson(rate30 * T / 30, NP)
        K = k.max()
        X = lr[rng.integers(0, len(lr), (NP, K))]
        X[np.arange(K)[None, :] >= k[:, None]] = 0.0
        cum = X.cumsum(1)
        mn = np.minimum(cum.min(1), 0)
        peak = np.maximum(np.maximum.accumulate(cum, 1), 0)
        mdd = (peak - cum).max(1)
        res[lab] = (np.exp(np.median(cum[:, -1])), np.mean(cum[:, -1] < 0), np.mean(mn < np.log(.5)), np.mean(mn < np.log(.1)), 1 - np.exp(-np.median(mdd)))
    out.append(dict(policy=name, n=len(r), win=np.mean(r > 0), p_tp=np.mean(code == 1), p_liq=np.mean(code == 3), mean_eq_ret_pct=100 * r.mean(),
                    med30=res["30d"][0], p_loss30=res["30d"][1], mdd30_med=res["30d"][4], med1y=res["1y"][0], p_below50_1y=res["1y"][2], p_ruin_1y=res["1y"][3]))
pd.set_option("display.width", 250)
print(pd.DataFrame(out).to_string(index=False, float_format=lambda v: f"{v:.4f}"))
