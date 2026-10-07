"""Own 5-year one-position AI-trader call simulation (core 36), built on the multi_tf every-signal outcome tables
(house exits checked on 15m bars, sizing feasibility) + the Binance 15m bars (move events).
python3 -I v_5y.py <outc_dir> <sig15_dir> <out_dir> [procs]
Writes per-strategy daily count arrays (npz, compact int16) and a per-strategy summary csv."""
import sys, os
sys.path.insert(0, "/root/.local/lib/python3.11/site-packages")
import numpy as np
from multiprocessing import Pool
OUTC, SIG, OUT = sys.argv[1:4]; PROCS = int(sys.argv[4]) if len(sys.argv) > 4 else 3
COINS = ["BTCUSD", "ETHUSD", "SOLUSD", "DOGEUSD", "LTCUSD", "BCHUSD"]
TFS = ["15m", "30m", "1h", "4h"]; TFM = {"15m": 15, "30m": 30, "1h": 60, "4h": 240}
M = 60 * 10**9
D0 = np.datetime64("2021-08-01").astype("datetime64[ns]").astype(np.int64)
D1 = np.datetime64("2026-09-30").astype("datetime64[ns]").astype(np.int64)
KST = 9 * 3600 * 10**9; DAY = 86400 * 10**9
NDAY = int((D1 + KST) // DAY - (D0 + KST) // DAY) + 1
def kday(t): return ((t + KST) // DAY - (D0 + KST) // DAY).astype(np.int64)
CNT = ["entry", "trades", "switch", "p1_sw", "p1_ign", "p2_sw", "p2_ign", "mv05", "mv10", "otf_sw", "otf_ign", "held_min"]
def load(strat):
    bars, sig = {}, []
    for ci, c in enumerate(COINS):
        z = np.load(os.path.join(SIG, f"sig_15m_{c}.npz"))
        bars[ci] = (z["ts"], z["h"], z["l"], z["c"])
        ts = z["ts"]
        for ti, tf in enumerate(TFS):
            o = np.load(os.path.join(OUTC, f"out_{tf}_{c}.npz"))
            k = "m__C:" + strat
            if k not in o.files: continue
            p = o[k]
            e, x = o["e"][p], o["x"][p]
            ok = (x >= e) & (x < len(ts))
            p, e, x = p[ok], e[ok], x[ok]
            t0 = ts[e]; t1 = ts[x] + 15 * M          # exit within bar x -> free at the next 15m bar
            sig.append(np.column_stack([t0, t1, np.full(len(p), ci), np.full(len(p), ti), o["feasible"][p].astype(np.int64),
                                        (2 * o["atr_frac"][p] <= 0.032).astype(np.int64), e, x,
                                        (o["risk"][p] * 1e8).astype(np.int64), (o["fill"][p] * 1e8).astype(np.int64)]))
    S = np.concatenate(sig); S = S[np.lexsort((S[:, 2], S[:, 3], S[:, 0]))]
    return bars, S
def moves(bars, ci, e, x, fill, risk, k):
    ts, h, l, c = bars[ci]; thr = k * risk; ref = fill; n = 0
    hh, ll, cc = h[e:x + 1], l[e:x + 1], c[e:x + 1]
    for i in range(len(hh)):
        m = max(hh[i] - ref, ref - ll[i])
        if m >= thr:
            n += int(m // thr); ref = cc[i]
    return n
def bounds(t0, t1, step):
    s = step * M; k0 = t0 // s + 1; k1 = (t1 - 1) // s
    return np.arange(k0, k1 + 1) * s
def job(args):
    strat, setup, feas_only, pe = args
    rr = np.random.default_rng(5)
    bars, S = load(strat)
    inset = np.ones(len(S), bool)
    if setup == "A": inset = S[:, 3] <= 1
    elif setup == "C": inset = (S[:, 3] <= 2) | (S[:, 5] == 1)
    off = inset & ((S[:, 4] == 1) if feas_only else True)
    O = S[off]; mom = np.unique(O[:, 0])
    first = {}
    for i in range(len(O) - 1, -1, -1): first[O[i, 0]] = i     # lowest tf first (sorted by t, tf, coin)
    cnt = np.zeros((len(CNT), NDAY), np.float32)
    def add(name, t, n=1):
        d = kday(np.asarray(t)); d = d[(d >= 0) & (d < NDAY)]
        np.add.at(cnt[CNT.index(name)], d, n)
    j = 0; free_at = -1
    byc = {(ci): S[S[:, 2] == ci] for ci in range(6)}
    while j < len(mom):
        m = mom[j]
        if m < free_at: j += 1; continue
        s = O[first[m]]; t0, t1 = s[0], s[1]; ci, ti = int(s[2]), int(s[3])
        add("entry", [m])
        if rr.random() > pe: j += 1; continue
        add("trades", [m]); free_at = t1
        hm = np.arange(t0, t1, 15 * M); add("held_min", hm, 15)
        sw = mom[(mom > t0) & (mom < t1)]; add("switch", sw)
        sws = set(sw.tolist())
        for name, step in (("p1", TFM[TFS[ti]]), ("p2", 30)):
            b = bounds(t0, t1, step); add(name + "_ign", b)
            add(name + "_sw", np.array([v for v in b.tolist() if v not in sws], np.int64))
        fill, risk = s[9] / 1e8, s[8] / 1e8
        n05 = moves(bars, ci, int(s[6]), int(s[7]), fill, risk, 0.5); n10 = moves(bars, ci, int(s[6]), int(s[7]), fill, risk, 1.0)
        add("mv05", [t0], n05); add("mv10", [t0], n10)
        C = byc[ci]; q = C[(C[:, 0] > t0) & (C[:, 0] < t1) & (C[:, 3] != ti)]
        add("otf_ign", np.unique(q[:, 0]))
        qq = q[~np.isin(q[:, 0], sw)] ; add("otf_sw", np.unique(qq[:, 0]))
        j = np.searchsorted(mom, t1)
    return strat, setup, feas_only, cnt

if __name__ == "__main__":
    import pandas as pd
    S8 = ["N24_DMI", "S6_EMA_DMI_ADX", "N05_PSAR_POC", "OBV_S", "N12_ICHI_AO", "N08_ICHI_WR", "V45_AMB", "N16_BBRSI"]
    jobs = [(s, "B", True, pe) for s in S8 for pe in (1.0, 0.5)]
    with Pool(3) as P:
        out = P.map(job, jobs)
    rows = []
    for (s, su, fo, c), (_, _, _, pe) in zip(out, jobs):
        a = c.sum(1) / NDAY; g = dict(zip(CNT, a))
        E = g["entry"] + g["switch"]; H = g["p2_sw"] + g["mv05"] + g["otf_sw"]
        rows.append(dict(s=s, pe=pe, entry=g["entry"], trades=g["trades"], E=E, H=H, calls=E + H, usd_day=E * 0.01288 + H * 0.00673, occ=g["held_min"] / 1440))
    df = pd.DataFrame(rows); print(df.round(2).to_string(index=False))
    p = df.pivot(index="s", columns="pe", values="usd_day"); print("cost ratio pe0.5/pe1 median %.3f" % (p[0.5] / p[1.0]).median())
