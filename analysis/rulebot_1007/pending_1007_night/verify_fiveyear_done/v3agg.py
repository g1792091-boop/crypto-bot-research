"""verify3 aggregation from the (row-parity-checked) per-signal pickles + live replay.
python3 -I -B v3agg.py <their_out> <out_real> <profiles_json> <outdir>
"""
import json
import os
import sys

sys.path.append('/root/.local/lib/python3.11/site-packages')
import numpy as np  # noqa
import pandas as pd  # noqa

TH, RD, PJ, OD = sys.argv[1:5]
NS = 86400 * 10 ** 9
WK = 7 * NS
S0, S1 = pd.Timestamp("2021-08-01").value, pd.Timestamp("2026-09-30").value
rng = np.random.default_rng(11)
NW = 4000


def ct(x, cl):
    """mean, cluster-robust t (clusters = cl)"""
    x = np.asarray(x, float)
    ok = np.isfinite(x)
    x, cl = x[ok], np.asarray(cl)[ok]
    n = len(x)
    if n < 3:
        return (x.mean() if n else np.nan), np.nan, n
    mu = x.mean()
    s = pd.Series(x - mu).groupby(cl).sum().to_numpy()
    g = len(s)
    se = np.sqrt((s ** 2).sum() * g / max(g - 1, 1)) / n
    return mu, mu / se if se > 0 else np.nan, n


def win_means(ts, v, L, starts):
    o = np.argsort(ts)
    ts, v = ts[o], v[o]
    cs = np.r_[0, np.cumsum(v)]
    a = np.searchsorted(ts, starts)
    b = np.searchsorted(ts, starts + L)
    cnt = b - a
    with np.errstate(invalid="ignore", divide="ignore"):
        return (cs[b] - cs[a]) / cnt, cnt


def bh(p):
    p = np.asarray(p, float)
    m = len(p)
    o = np.argsort(p)
    q = np.minimum.accumulate((p[o] * m / np.arange(1, m + 1))[::-1])[::-1]
    r = np.empty(m)
    r[o] = np.minimum(q, 1)
    return r


prof = json.load(open(PJ))["profiles"]
rep = pd.read_csv(os.path.join(RD, "replay_signals.csv"))
rep = rep[rep.run.isin(["current", "run-20261005T183457Z"])]
rep["ts"] = rep.bar_close.astype("int64") * 10 ** 6
rep["Rm"] = np.where(rep.status == "TRADED", rep.R, np.where(rep.status == "UNRESOLVED", rep.mark_R, np.nan))

summ, cells, par, wins, stops = [], [], [], [], []
for kind, pre, tfs in (("core", "fy36", ("5m", "15m", "30m", "1h", "4h")), ("ds", "fyds", ("15m", "30m", "1h", "4h"))):
    for tf in tfs:
        T = pd.read_pickle(os.path.join(TH, f"{pre}_{tf}.pkl.gz"))
        T = T[(T.ts >= S0) & (T.ts < S1)]
        days = (S1 - S0) / NS
        wk = T.ts.to_numpy() // WK
        z = (T.v4n_lev > 0) & T.v4n_done
        Z = T[z].sort_values("ts")
        wk_z = Z.ts.to_numpy() // WK
        R = Z.v4n_R.to_numpy(float)
        G = (Z.v4n_gross / Z.stop_frac).to_numpy(float)
        w = Z.win.to_numpy()
        m, t, n = ct(R, wk_z)
        gm, gt, _ = ct(G, wk_z)
        d = dict(kind=kind, tf=tf, n_all=len(T), n_sized=n, sized_share=z.mean(), netR=m, t_wk=t, grossR=gm, gross_t=gt,
                 costR=np.nanmean(G) - np.nanmean(R) if True else np.nan,
                 netR_is=R[w == 0].mean(), netR_cf=R[w == 1].mean(), gR_is=np.nanmean(G[w == 0]), gR_cf=np.nanmean(G[w == 1]),
                 liq_share=(Z.v4n_reason == 2).mean(), stop_med=Z.stop_frac.median())
        if kind == "core":
            zt = (T.tw_lev > 0) & T.tw_done
            d["twR"] = T.tw_R[zt].mean()
            for st, g in T.groupby("strategy", observed=True):
                p = prof.get(st, {}).get(tf)
                if p:
                    mm = (g.tw_lev > 0) & g.tw_done
                    par.append(dict(strategy=st, tf=tf, n=len(g), prof_n=p["signals"], mine=g.tw_roe[mm].astype(float).mean(),
                                    prof=p["mean_roe"]))
        # live stop sizes and the 5y position
        kk = "strategy" if kind == "core" else "ds200"
        lv = rep[(rep.kind == kk) & (rep.timeframe == tf) & (rep.status == "TRADED")]
        if len(lv):
            lo, hi, lmed = lv.stop_frac.quantile(0.1), lv.stop_frac.quantile(0.9), lv.stop_frac.median()
            inr = (Z.stop_frac >= lo) & (Z.stop_frac <= hi)
            d.update(live_stop_med=lmed, netR_liverange=R[inr.to_numpy()].mean(), gR_liverange=np.nanmean(G[inr.to_numpy()]),
                     n_liverange=int(inr.sum()), pct_stop_bars=(Z.stop_frac < lmed).mean())
            # window tests
            L = (2.2 if kind == "core" else 1.5034722) * NS
            starts = rng.uniform(S0, S1 - L, NW).astype(np.int64)
            tsz = Z.ts.to_numpy()
            wm, wc = win_means(tsz, R, L, starts)
            sfz = Z.stop_frac.to_numpy()
            ia, ib = np.searchsorted(tsz, starts[:1000]), np.searchsorted(tsz, starts[:1000] + L)
            wsm = np.array([np.median(sfz[a:b]) if b > a else np.nan for a, b in zip(ia, ib)])
            tsa = T.ts.to_numpy()
            _, wca = win_means(tsa, np.ones(len(tsa)), L, starts)
            lvm = lv.R.mean()
            lvmk = rep[(rep.kind == kk) & (rep.timeframe == tf)].Rm.mean()
            nsub = ((rep.kind == kk) & (rep.timeframe == tf)).sum()
            ok = np.isfinite(wm)
            # stop-matched windows: windows whose median stop within +-15% of live median
            sm = np.abs(wsm / lmed - 1) < 0.15
            wins.append(dict(kind=kind, tf=tf, live_n=len(lv), live_meanR=lvm, live_meanR_withmark=lvmk,
                             pct=(wm[ok] < lvm).mean(), pct_mark=(wm[ok] < lvmk).mean(), win_med=np.median(wm[ok]),
                             win_p5=np.percentile(wm[ok], 5), win_p95=np.percentile(wm[ok], 95),
                             live_stop_pct_in_windows=np.nanmean(wsm < lmed), n_stop_matched=int(sm.sum()),
                             pct_stopmatched=(wm[:1000][sm & ok[:1000]] < lvm).mean() if sm.sum() else np.nan,
                             med_stopmatched=np.nanmedian(wm[:1000][sm]) if sm.sum() else np.nan,
                             live_submitted=int(nsub), win_count_med=np.median(wca), count_pct=(wca < nsub).mean(),
                             freq_ratio=nsub / (len(T) / days * L / NS)))
        summ.append(d)
        # cells
        for st, g in T.groupby("strategy", observed=True):
            zz = (g.v4n_lev > 0) & g.v4n_done
            gg = g[zz]
            r = gg.v4n_R.to_numpy(float)
            gr = (gg.v4n_gross / gg.stop_frac).to_numpy(float)
            c = gg.ts.to_numpy() // WK
            m1, t1, n1 = ct(r, c)
            m2, t2, _ = ct(gr, c)
            ww = gg.win.to_numpy()
            cells.append(dict(kind=kind, strategy=st, tf=tf, n_all=len(g), per_day=len(g) / days, n=n1, per_day_sized=n1 / days,
                              netR=m1, t=t1, grossR=m2, gross_t=t2, net_is=r[ww == 0].mean() if (ww == 0).any() else np.nan,
                              net_cf=r[ww == 1].mean() if (ww == 1).any() else np.nan,
                              g_is=np.nanmean(gr[ww == 0]) if (ww == 0).any() else np.nan,
                              g_cf=np.nanmean(gr[ww == 1]) if (ww == 1).any() else np.nan))
        # 15m stop quintiles (core)
        if kind == "core" and tf == "15m":
            q = pd.qcut(Z.stop_frac, 5, labels=False)
            for k in range(5):
                mk = (q == k).to_numpy()
                stops.append(dict(q=k, stop_hi=Z.stop_frac[mk].max(), netR=R[mk].mean(), grossR=np.nanmean(G[mk]),
                                  costR=np.nanmean(G[mk]) - R[mk].mean()))
        del T, Z
        print(kind, tf, "done", flush=True)

pd.DataFrame(summ).to_csv(os.path.join(OD, "agg_tf.csv"), index=False)
C = pd.DataFrame(cells)
from math import erf, sqrt  # noqa
C["gross_p"] = [2 * (1 - 0.5 * (1 + erf(abs(x) / sqrt(2)))) if np.isfinite(x) else np.nan for x in C.gross_t]
C.to_csv(os.path.join(OD, "agg_cells.csv"), index=False)
pd.DataFrame(par).to_csv(os.path.join(OD, "agg_parity.csv"), index=False)
pd.DataFrame(wins).to_csv(os.path.join(OD, "agg_windows.csv"), index=False)
pd.DataFrame(stops).to_csv(os.path.join(OD, "agg_stopq15.csv"), index=False)
print("ok")
