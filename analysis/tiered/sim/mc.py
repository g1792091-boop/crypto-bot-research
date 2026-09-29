"""Monte-Carlo (stationary block bootstrap of simulated days) from $1,000 for every case -> out/metrics.csv.

Paths: 5,000 per TF, 365 days each.  Each path strings together blocks of consecutive simulated days
(geometric block length, mean 20 days) drawn from random (seed, start-day) positions of the 2021-08..2024-06
IS simulation.  Same bootstrap indices for every case inside a TF (paired comparison).
Equity-fraction sizing -> equity = 1000 * exp(cumulative log factor).  'ever' minima use the intraday
(trade-by-trade) minimum of realised equity; open-trade mark-to-market dips are not included.
Fees in $ = sum over days of (day's costs as a fraction of equity) * equity at the start of that day
(ignores compounding inside a day).
"""
import json, os, sys
import numpy as np
import pandas as pd

# (tf, file tag, exit resolution): base = exits resolved on 5m sub-bars; 'tf' = on the chart-TF bars (sensitivity)
DS = [("5m", "5m", "5m"), ("15m", "15m_fine", "5m"), ("1h", "1h_fine", "5m"), ("4h", "4h_fine", "5m"),
      ("15m", "15m", "tf"), ("1h", "1h", "tf"), ("4h", "4h", "tf")]
DS = [d for d in DS if os.path.exists(f"out/{d[1]}.npz")]
NP, T, BLK = 5000, 365, 20
HOR = {"1m": 30, "3m": 91, "12m": 365}
rows = []
cal_rows = []
for tf, tag, res in DS:
    Z = np.load(f"out/{tag}.npz")
    meta = json.load(open(f"out/{tag}_meta.json"))
    LR, DMIN, FEE, ST, CAL = Z["LR"], Z["DMIN"], Z["FEE"], Z["ST"], Z["CAL"]
    S, ND = meta["S"], meta["ND"]
    stn = meta["stn"]
    months = ND / 30.4375
    rng = np.random.default_rng([meta["tfm"], 99])
    new = rng.random((NP, T)) < 1.0 / BLK
    new[:, 0] = True
    rs = rng.integers(0, S, (NP, T)); rd = rng.integers(0, ND, (NP, T))
    sidx = np.empty((NP, T), np.int64); didx = np.empty((NP, T), np.int64)
    for t in range(T):
        if t == 0:
            sidx[:, 0], didx[:, 0] = rs[:, 0], rd[:, 0]
        else:
            sidx[:, t] = np.where(new[:, t], rs[:, t], sidx[:, t - 1])
            didx[:, t] = np.where(new[:, t], rd[:, t], (didx[:, t - 1] + 1) % ND)
    flat = sidx * ND + didx
    Eab = np.array(list(meta["Eabs"].values()))
    for si, (nm, D, conc) in enumerate(meta["scen"]):
        c = CAL[si].mean(0)
        cal_rows.append(dict(tf=tf, res=res, scen=nm, D=D, conc=conc, drift_all=c[0], drift_top=c[1], drift_rest=c[2],
                             q_mean=c[3], q_top=c[4], q_rest=c[5], drift_all_sd_seed=CAL[si, :, 0].std()))
    for cj, (si, pol, st, tp, o) in enumerate(meta["cases"]):
        nm, D, conc = meta["scen"][si]
        lr = LR[cj].reshape(-1)[flat].astype(np.float64)
        dm = DMIN[cj].reshape(-1)[flat].astype(np.float64)
        fe = FEE[cj].reshape(-1)[flat].astype(np.float64)
        cum = np.cumsum(lr, 1)
        before = cum - lr
        runlow = np.minimum.accumulate(np.minimum(before + dm, 0.0), 1)
        cumfee = np.cumsum(fe * np.exp(before), 1)
        r = dict(tf=tf, res=res, scen=nm, D=D, conc=conc, pol=pol, stop=st, tp=tp, order=o)
        for h, H in HOR.items():
            eq = 1000.0 * np.exp(cum[:, H - 1])
            lo = 1000.0 * np.exp(runlow[:, H - 1])
            r[f"{h}_med"] = np.median(eq); r[f"{h}_p10"] = np.percentile(eq, 10); r[f"{h}_p90"] = np.percentile(eq, 90)
            r[f"{h}_mean"] = eq.mean()
            r[f"{h}_P500"] = np.mean(eq < 500); r[f"{h}_P100"] = np.mean(eq < 100)
            r[f"{h}_P500ever"] = np.mean(lo < 500); r[f"{h}_P100ever"] = np.mean(lo < 100)
            r[f"{h}_Pgain"] = np.mean(eq > 1000)
            r[f"{h}_fees_med"] = np.median(1000.0 * cumfee[:, H - 1])
        st_ = ST[cj]                         # (S, nst)
        tot = st_.sum(0)
        g = dict(zip(stn, tot))
        n = g["n"]
        r.update(trades_pm=n / S / months, liq_pm=g["n_liq"] / S / months, liq_share=g["n_liq"] / n,
                 tp_share=g["n_tp"] / n, stop_share=g["n_stop"] / n, time_share=g["n_time"] / n,
                 gross_pt=g["sum_g"] / n, drift_pt=g["sum_drift"] / n, fee_eq_pt=g["sum_fee"] / n,
                 mean_N=g["sum_N"] / n, hold_bars=g["sum_hold"] / n, win=g["n_win"] / n,
                 mean_logret_pt=g["sum_lr"] / n,
                 share_t2=g["n_t2"] / n, liq_rate_t0=g["liq_t0"] / max(g["n_t0"], 1), liq_rate_t1=g["liq_t1"] / max(g["n_t1"], 1),
                 liq_rate_t2=g["liq_t2"] / max(g["n_t2"], 1),
                 drift_t2=g["drift_t2"] / max(g["n_t2"], 1), drift_rest=(g["drift_t0"] + g["drift_t1"]) / max(g["n_t0"] + g["n_t1"], 1),
                 gross_t2=g["g_t2"] / max(g["n_t2"], 1), gross_rest=(g["g_t0"] + g["g_t1"]) / max(g["n_t0"] + g["n_t1"], 1),
                 chain3y_mdd_med=np.median(1 - np.exp(-st_[:, stn.index("mdd")])))
        rows.append(r)
    print(tf, res, "cases", len(meta["cases"]), flush=True)
M = pd.DataFrame(rows)
M.to_csv("out/metrics.csv", index=False)
pd.DataFrame(cal_rows).to_csv("out/calibration.csv", index=False)
print("wrote out/metrics.csv", M.shape)
