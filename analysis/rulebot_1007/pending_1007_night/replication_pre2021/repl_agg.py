"""Per-cell aggregation of the pre-2021 house-exit rerun and comparison with the verified 5y table.

    python3 -I -B repl_agg.py <out_dir> <agg_cells_5y.csv> <prespec.json> <orderflow_dir> <lens_out_dir>

Writes <out_dir>/pre_cells.csv (every cell), primary.csv (pre-specified 23 cells with replication verdicts),
bh22.csv (all 22 BH-significant 5y cells), global.json (rank agreement over all cells).
Gross R = v4n_gross / stop_frac (liquidations NaN, as verify3/v3agg.py); net R = v4n_R; sized & done rows only.
t = mean / cluster-robust SE with clusters = ts // 7 days (v3agg.ct).
"""
import json
import os
import sys
from math import erf, sqrt

sys.path.append('/root/.local/lib/python3.11/site-packages')
import numpy as np  # noqa
import pandas as pd  # noqa

OD, AC, PS, OF, LENS = sys.argv[1:6]
WK = 7 * 86400 * 10 ** 9
NS = 86400 * 10 ** 9
TFM = {"5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240}
SYM = {"BTCUSD": "btc", "ETHUSD": "eth", "SOLUSD": "sol", "DOGEUSD": "doge", "LTCUSD": "ltc", "BCHUSD": "bch"}
SPLIT = pd.Timestamp("2021-01-01").value
F8 = 0.0001
Phi = lambda x: 0.5 * (1 + erf(x / sqrt(2)))  # noqa


def ct(x, cl):
    x = np.asarray(x, float)
    ok = np.isfinite(x)
    x, cl = x[ok], np.asarray(cl)[ok]
    n = len(x)
    if n < 3:
        return (x.mean() if n else np.nan), np.nan, n, np.nan
    mu = x.mean()
    s = pd.Series(x - mu).groupby(cl).sum().to_numpy()
    g = len(s)
    se = np.sqrt((s ** 2).sum() * g / max(g - 1, 1)) / n
    return mu, (mu / se if se > 0 else np.nan), n, se


def bh(p):
    p = np.asarray(p, float)
    m = len(p)
    o = np.argsort(p)
    q = np.minimum.accumulate((p[o] * m / np.arange(1, m + 1))[::-1])[::-1]
    r = np.empty(m)
    r[o] = np.minimum(q, 1)
    return r


# real funding (data/orderflow), cumulative per coin
FUND = {}
for c, s in SYM.items():
    f = pd.read_csv(os.path.join(OF, f"{s}_funding.csv.gz"))
    t = (f.calc_time.to_numpy(np.int64) // 1000) * 10 ** 9   # ms -> ns, rounded to the second
    o = np.argsort(t)
    FUND[c] = (t[o], np.r_[0, np.cumsum(f.last_funding_rate.to_numpy(float)[o])])


def real_fund_R(g, tf):
    """R with the constant 0.01%/8h replaced by the coin's actual funding (side*rate summed over funding times in
    (entry, exit]); lock-ladder path effects of funding ignored (they are tiny)."""
    out = np.full(len(g), np.nan)
    bar = TFM[tf] * 60 * 10 ** 9
    for c, idx in g.groupby("coin", observed=True).indices.items():
        tt, cs = FUND[str(c)]
        x = g.iloc[idx]
        t0 = x.ts.to_numpy(np.int64) + bar
        t1 = t0 + x.v4n_held.to_numpy(float).astype(np.int64) * bar
        s = cs[np.searchsorted(tt, t1, "right")] - cs[np.searchsorted(tt, t0, "right")]
        const = F8 * TFM[tf] / 480.0 * x.v4n_held.to_numpy(float)
        out[idx] = x.v4n_R.to_numpy(float) + (const - x.side.to_numpy(float) * s) / x.stop_frac.to_numpy(float)
    return out


rows = []
meta = []
for kind, tfs in (("core", ("5m", "15m", "30m", "1h", "4h")), ("ds", ("15m", "30m", "1h", "4h"))):
    M = pd.read_csv(os.path.join(OD, f"pre_{kind}_meta.csv"))
    for tf in tfs:
        T = pd.read_pickle(os.path.join(OD, f"pre_{kind}_{tf}.pkl.gz"))
        days = M[M.tf == tf].days.max()          # longest coin series (BTC/ETH/BCH): calendar days of the window
        cdays = M[M.tf == tf].days.sum()         # coin-days
        meta.append(dict(kind=kind, tf=tf, days=days, coin_days=cdays, rows=len(T)))
        hasfl = "fl_R" in T.columns
        for st, g in T.groupby("strategy", observed=True):
            z = (g.v4n_lev > 0) & g.v4n_done
            gg = g[z].copy()
            if not len(gg):
                rows.append(dict(kind=kind, strategy=st, tf=tf, n_all=len(g), n=0))
                continue
            cl = gg.ts.to_numpy() // WK
            G = (gg.v4n_gross / gg.stop_frac).to_numpy(float)
            Rn = gg.v4n_R.to_numpy(float)
            gm, gt, _, gse = ct(G, cl)
            nm, nt, n, _ = ct(Rn, cl)
            rf = real_fund_R(gg, tf)
            fm, ftt, _, _ = ct(rf, cl)
            lg = gg.side.to_numpy() > 0
            h1 = gg.ts.to_numpy() < SPLIT
            d = dict(kind=kind, strategy=st, tf=tf, n_all=len(g), per_day=len(g) / days, n=n, sized_share=z.mean(),
                     per_day_sized=n / days, grossR=gm, gross_t=gt, gross_se=gse, netR=nm, net_t=nt, costR=np.nanmean(G) - Rn.mean(),
                     netR_realfund=fm, net_t_realfund=ftt, long_share=lg.mean(),
                     g_long=np.nanmean(G[lg]) if lg.any() else np.nan, g_short=np.nanmean(G[~lg]) if (~lg).any() else np.nan,
                     g_2020=np.nanmean(G[h1]) if h1.any() else np.nan, g_2021=np.nanmean(G[~h1]) if (~h1).any() else np.nan,
                     n_2020=int(h1.sum()), n_2021=int((~h1).sum()), stop_med=float(gg.stop_frac.median()),
                     liq_share=float((gg.v4n_reason == 2).mean()))
            if hasfl:
                zf = z & (g.fl_lev > 0) & g.fl_done
                ff = g[zf]
                Gf = (ff.fl_gross / ff.stop_frac).to_numpy(float)
                Ga = (ff.v4n_gross / ff.stop_frac).to_numpy(float)
                dm, dt, dn, _ = ct((Ga - Gf) / 2, ff.ts.to_numpy() // WK)
                d.update(g_flip=np.nanmean(Gf), dir_content=dm, dir_t=dt, n_pair=dn)
            rows.append(d)
        del T
        print(kind, tf, "done", flush=True)

P = pd.DataFrame(rows)
# 5y side split from the verified lens pickles (same sized & done rows as agg_cells)
S0, S1 = pd.Timestamp("2021-08-01").value, pd.Timestamp("2026-09-30").value
side_rows = []
for kind, pre, tfs in (("core", "fy36", ("5m", "15m", "30m", "1h", "4h")), ("ds", "fyds", ("15m", "30m", "1h", "4h"))):
    for tf in tfs:
        T = pd.read_pickle(os.path.join(LENS, f"{pre}_{tf}.pkl.gz"))[["strategy", "ts", "side", "stop_frac", "v4n_lev", "v4n_done", "v4n_gross"]]
        T = T[(T.ts >= S0) & (T.ts < S1) & (T.v4n_lev > 0) & T.v4n_done]
        T["G"] = (T.v4n_gross / T.stop_frac).astype(float)
        T["lg"] = T.side > 0
        a = T.groupby(["strategy", "lg"], observed=True).G.mean().unstack()
        b = T.groupby("strategy", observed=True).lg.mean()
        for st in b.index:
            side_rows.append(dict(kind=kind, strategy=st, tf=tf, y5_long_share=b[st],
                                  y5_g_long=a.loc[st].get(True, np.nan), y5_g_short=a.loc[st].get(False, np.nan)))
        del T
P = P.merge(pd.DataFrame(side_rows), on=["kind", "strategy", "tf"], how="left")
F = pd.read_csv(AC)[["kind", "strategy", "tf", "n", "per_day_sized", "netR", "t", "grossR", "gross_t", "g_is", "g_cf"]]
F.columns = ["kind", "strategy", "tf"] + ["y5_" + c for c in F.columns[3:]]
X = P.merge(F, on=["kind", "strategy", "tf"], how="outer")
X["sign_agree"] = np.sign(X.grossR) == np.sign(X.y5_grossR)
X["exp_t"] = X.y5_grossR / X.gross_se                   # t expected in pre2021 if the true effect = the 5y estimate
X["pow15"] = [Phi(abs(e) - 1.5) if np.isfinite(e) else np.nan for e in X.exp_t]
X.to_csv(os.path.join(OD, "pre_cells.csv"), index=False)
pd.DataFrame(meta).to_csv(os.path.join(OD, "pre_meta.csv"), index=False)


def verdict(r):
    if not np.isfinite(r.gross_t):
        return "no data"
    if r.sign_agree and abs(r.gross_t) >= 1.5:
        return "replicates (BH)" if r.q_one <= 0.05 else "replicates (nominal only)"
    if (not r.sign_agree) and abs(r.gross_t) >= 1.5:
        return "contradicted"
    return "inconclusive (same sign)" if r.sign_agree else "inconclusive (sign flipped)"


def family(cells, name):
    key = pd.DataFrame([dict(strategy=c.split("@")[0], tf=c.split("@")[1]) for c in cells])
    Y = key.merge(X, on=["strategy", "tf"], how="left")
    s5 = np.sign(Y.y5_grossR)
    Y["p_one"] = [1 - Phi(s * t) if np.isfinite(t) else 1.0 for s, t in zip(s5, Y.gross_t)]
    Y["q_one"] = bh(Y.p_one.to_numpy())
    Y["p_two"] = [2 * (1 - Phi(abs(t))) if np.isfinite(t) else 1.0 for t in Y.gross_t]
    Y["q_two"] = bh(Y.p_two.to_numpy())
    Y["verdict"] = [verdict(r) for r in Y.itertuples()]
    Y.to_csv(os.path.join(OD, name), index=False)
    return Y


ps = json.load(open(PS))
prim = family(ps["primary_cells_expected_positive"] + ps["primary_cells_expected_negative"], "primary.csv")
# all 22 BH-significant 5y cells (week-clustered, n>=200, two-sided BH over the 5y cells)
F5 = pd.read_csv(AC)
F5 = F5[F5.n >= 200].copy()
F5["p"] = [2 * (1 - Phi(abs(t))) if np.isfinite(t) else 1.0 for t in F5.gross_t]
F5["q"] = bh(F5.p.to_numpy())
b22 = F5[F5.q < 0.05]
bhc = family([f"{s}@{t}" for s, t in zip(b22.strategy, b22.tf)], "bh22.csv")

# global rank agreement
gl = {}
for lab, sub in (("all", X), ("core", X[X.kind == "core"]), ("ds", X[X.kind == "ds"]),
                 ("ai_tfs_15m_30m_1h", X[X.tf.isin(["15m", "30m", "1h"])])):
    s = sub[(sub.n >= 200) & (sub.y5_n >= 200) & sub.gross_t.notna() & sub.y5_gross_t.notna()]
    a, b = s.y5_gross_t.rank(), s.gross_t.rank()
    rho = float(np.corrcoef(a, b)[0, 1])
    rng = np.random.default_rng(3)
    perm = np.array([np.corrcoef(a, rng.permutation(b.to_numpy()))[0, 1] for _ in range(5000)])
    strong = s[abs(s.y5_gross_t) >= 2]
    gl[lab] = dict(cells=len(s), spearman_t=rho, perm_p_two=float((np.abs(perm) >= abs(rho)).mean()),
                   pearson_gross=float(np.corrcoef(s.y5_grossR, s.grossR)[0, 1]),
                   sign_agree_all=float(s.sign_agree.mean()),
                   strong5y_cells=len(strong), strong5y_sign_agree=float(strong.sign_agree.mean()) if len(strong) else None,
                   pre_pos_t2=int((s.gross_t >= 2).sum()), pre_neg_t2=int((s.gross_t <= -2).sum()))
json.dump(gl, open(os.path.join(OD, "global.json"), "w"), indent=1)
print(json.dumps(gl, indent=1))
pd.set_option("display.width", 250)
print(prim[["strategy", "tf", "n", "per_day_sized", "grossR", "gross_t", "netR", "net_t", "y5_grossR", "y5_gross_t", "exp_t",
            "sign_agree", "q_one", "verdict"]].round(4).to_string())
