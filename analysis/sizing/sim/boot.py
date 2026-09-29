"""Bootstrap 30-day and 1-year outcome distributions from the simulated daily equity series.

Moving-block bootstrap over (seed, day) with block length 10 days (circular inside a seed's IS span).
Same bootstrap indices for every edge x combo inside a TF (common random numbers).
Output: out/<tag>/<tf>_metrics.csv
"""
import argparse, json, os
import numpy as np
import pandas as pd

ap = argparse.ArgumentParser()
ap.add_argument("--tf", required=True)
ap.add_argument("--tag", default="base")
ap.add_argument("--paths", type=int, default=6000)
ap.add_argument("--block", type=int, default=10)
args = ap.parse_args()

d = os.path.join("out", args.tag)
meta = json.load(open(os.path.join(d, f"{args.tf}_meta.json")))
daily = np.load(os.path.join(d, f"{args.tf}_daily.npy"))
dmin = np.load(os.path.join(d, f"{args.tf}_dmin.npy"))
st = np.load(os.path.join(d, f"{args.tf}_stats.npz"))
ST = st["ST"]; names = list(st["names"]); ix = {k: i for i, k in enumerate(names)}
E, C, S, D = daily.shape
EDG, COMBOS = meta["edges"], meta["combos"]
LN10, LN50 = np.log(0.10), np.log(0.50)

rng = np.random.default_rng([7, int(meta["tfm"]), 2026])


def make_idx(T):
    nb = -(-T // args.block)
    s0 = rng.integers(0, S, size=(args.paths, nb))
    d0 = rng.integers(0, D, size=(args.paths, nb))
    j = np.arange(args.block)
    sidx = np.repeat(s0, args.block, axis=1)[:, :T]
    didx = ((d0[:, :, None] + j[None, None, :]) % D).reshape(args.paths, -1)[:, :T]
    return sidx, didx


IDX = {30: make_idx(30), 365: make_idx(365)}


def path_metrics(X, Mn):
    cum = np.cumsum(X, axis=1, dtype=np.float64)
    before = cum - X
    low = before + Mn                              # intraday low (trade-exit granularity)
    pmin = np.minimum(low.min(1), 0.0)
    rm_end = np.maximum(np.maximum.accumulate(cum, axis=1), 0.0)
    rm_prev = np.concatenate([np.zeros((X.shape[0], 1)), rm_end[:, :-1]], axis=1)
    mdd = np.maximum((rm_prev - low).max(1), (rm_end - cum).max(1))
    return cum[:, -1], pmin, mdd


rows = []
for e in range(E):
    for c in range(C):
        r = dict(tf=args.tf, edge_pct=EDG[e] * 100, combo=COMBOS[c])
        P, stop, tp = COMBOS[c].split("|")
        r.update(policy=P, stop=stop, tp=tp)
        # trade statistics (pooled over seeds)
        n = ST[ix["n"], e, c].sum()
        r["trades_per_30d"] = n / S / D * 30
        r["liq_share"] = ST[ix["n_liq"], e, c].sum() / n
        r["tp_share"] = ST[ix["n_tp"], e, c].sum() / n
        r["stop_share"] = ST[ix["n_stop"], e, c].sum() / n
        r["time_share"] = ST[ix["n_time"], e, c].sum() / n
        r["drift_H_pct"] = ST[ix["sum_drift"], e, c].sum() / n * 100          # planted drift realised on taken trades
        r["gross_pct"] = ST[ix["sum_g"], e, c].sum() / n * 100                 # side-adjusted exit price move (liq = -d_liq)
        r["net_notional_pct"] = ST[ix["sum_y"], e, c].sum() / n * 100          # after all costs, per unit notional
        r["eq_ret_pct"] = ST[ix["sum_r"], e, c].sum() / n * 100                 # mean equity return per trade
        r["win_rate"] = ST[ix["n_win"], e, c].sum() / n
        r["mean_N"] = ST[ix["sum_N"], e, c].sum() / n
        r["mean_M"] = ST[ix["sum_M"], e, c].sum() / n
        r["mean_L"] = ST[ix["sum_L"], e, c].sum() / n
        # IS span per seed (~35 months)
        fin = ST[ix["sum_log"], e, c]
        r["IS_median_mult"] = float(np.exp(np.median(fin)))
        r["IS_p_ruin"] = float(np.mean(ST[ix["min_log"], e, c] < LN10))
        r["IS_mdd_median"] = float(1 - np.exp(-np.median(ST[ix["mdd_log"], e, c])))
        for T, lab in ((30, "30d"), (365, "1y")):
            sidx, didx = IDX[T]
            X = daily[e, c][sidx, didx]
            Mn = dmin[e, c][sidx, didx]
            fin, pmin, mdd = path_metrics(X, Mn)
            r[f"{lab}_median_mult"] = float(np.exp(np.median(fin)))
            r[f"{lab}_p05_mult"] = float(np.exp(np.quantile(fin, 0.05)))
            r[f"{lab}_p95_mult"] = float(np.exp(np.quantile(fin, 0.95)))
            r[f"{lab}_p_loss"] = float(np.mean(fin < 0))
            r[f"{lab}_p_below50"] = float(np.mean(pmin < LN50))
            r[f"{lab}_p_ruin"] = float(np.mean(pmin < LN10))
            r[f"{lab}_mdd_median"] = float(1 - np.exp(-np.median(mdd)))
        rows.append(r)

df = pd.DataFrame(rows)
df.to_csv(os.path.join(d, f"{args.tf}_metrics.csv"), index=False)

# Kelly scan on the reference exit (1.5 ATR stop + time exit, net per unit notional)
Ngrid = np.r_[np.arange(0, 3, 0.05), np.arange(3, 40.01, 0.25)]
kr = []
for e in range(E):
    y = st[f"kelly_y_{e}"].astype(np.float64)
    ok = Ngrid < 1 / max(1e-9, -y.min())
    g = np.array([np.mean(np.log1p(N * y)) if o else -np.inf for N, o in zip(Ngrid, ok)])
    b = int(np.argmax(g))
    kr.append(dict(tf=args.tf, edge_pct=EDG[e] * 100, n=len(y), mean_y_pct=y.mean() * 100, sd_y_pct=y.std() * 100,
                   kelly_N=float(Ngrid[b]), g_per_trade_at_kelly=float(g[b]),
                   kelly2_N=float(max(0.0, y.mean() / (y.var() + y.mean() ** 2)))))
pd.DataFrame(kr).to_csv(os.path.join(d, f"{args.tf}_kelly.csv"), index=False)
print("wrote", args.tf, len(df), "rows")
