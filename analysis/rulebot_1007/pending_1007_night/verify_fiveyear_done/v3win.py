"""verify3 window test with correct live lengths (core v3b+v4 contiguous 2.202 d; DS v4 only 1.503 d), mean-stop matching.
python3 -I -B v3win.py <their_out> <out_real> <outcsv>"""
import os, sys
sys.path.append('/root/.local/lib/python3.11/site-packages')
import numpy as np, pandas as pd
TH, RD, OUT = sys.argv[1:4]
NS = 86400 * 10 ** 9
S0, S1 = pd.Timestamp("2021-08-01").value, pd.Timestamp("2026-09-30").value
rng = np.random.default_rng(99)
rep = pd.read_csv(os.path.join(RD, "replay_signals.csv"))
rep = rep[rep.run.isin(["current", "run-20261005T183457Z"]) & (rep.status == "TRADED")]
rows = []
for kind, pre, kk, Ld in (("core", "fy36", "strategy", 0.6986111 + 1.5034722), ("ds", "fyds", "ds200", 1.5034722), ("ds_2.2d", "fyds", "ds200", 2.202)):
    for tf in ("15m", "30m", "1h", "4h"):
        T = pd.read_pickle(os.path.join(TH, f"{pre}_{tf}.pkl.gz"))
        T = T[(T.ts >= S0) & (T.ts < S1) & (T.v4n_lev > 0) & T.v4n_done].sort_values("ts")
        ts, R, sf = T.ts.to_numpy(), T.v4n_R.to_numpy(float), T.stop_frac.to_numpy(float)
        cR, cS = np.r_[0, np.cumsum(R)], np.r_[0, np.cumsum(sf)]
        L = int(Ld * NS)
        st = rng.uniform(S0, S1 - L, 4000).astype(np.int64)
        a, b = np.searchsorted(ts, st), np.searchsorted(ts, st + L)
        n = b - a
        ok = n > 0
        mR = (cR[b] - cR[a])[ok] / n[ok]
        mS = (cS[b] - cS[a])[ok] / n[ok]
        lv = rep[(rep.kind == kk) & (rep.timeframe == tf)]
        lm, ls = lv.R.mean(), lv.stop_frac.mean()
        mt = np.abs(mS / ls - 1) <= 0.15
        pm = (mR[mt] < lm).mean() if mt.any() else np.nan
        rows.append(dict(kind=kind, tf=tf, L_days=Ld, live_n=len(lv), live_R=lm, pct=(mR < lm).mean(), p5=np.percentile(mR, 5),
                         p50=np.median(mR), p95=np.percentile(mR, 95), stop_pct_mean=(mS < ls).mean(), n_matched=int(mt.sum()),
                         matched_p50=np.median(mR[mt]) if mt.any() else np.nan, matched_pct=pm,
                         matched_p_two=2 * min(pm, 1 - pm) if mt.any() else np.nan))
        del T
D = pd.DataFrame(rows); D.to_csv(OUT, index=False)
pd.set_option("display.width", 250); print(D.round(3).to_string())
