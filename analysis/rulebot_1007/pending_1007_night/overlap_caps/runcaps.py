"""Step 2 runner: cap-setting grid for the joint one-position traders (see capsim.py for the trader rules).

    python3 -I -B runcaps.py <sig23.npz> <out_dir> [procs]

Sets: T17 = wave 1 + wave 2 (17 traders), T10 = wave 1, T23 = + 6 reserves; scope CARD (main) or U (15m/30m/1h
for all + 4h where 20x sizes); thin = probability that a trader considers a signal (1.0 = rule proxy takes every
signal when flat; 0.5 = an AI that skips half the signals at random, decided before any cap check).
Cluster sets: PROP (proposed before this study), D60 / D50 (this study: average-linkage clusters of the
chance-corrected 1-hour entry co-occurrence at kappa >= 0.6 / >= 0.5, see clus.py).
Outputs: runs_book.csv, runs_trader.csv, crowding.csv (uncapped runs: entry R by how many other traders already hold
the same coin-side), daily_stop.csv (how often a -3R/day trader stop and a -12R/day book stop would fire).
"""
import itertools
import os
import sys

sys.path[:0] = ['/root/.local/lib/python3.11/site-packages', os.path.dirname(os.path.abspath(__file__))]
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from multiprocessing import Pool  # noqa: E402
import common5 as C  # noqa: E402
import capsim as S  # noqa: E402

T17 = C.WAVE1 + C.WAVE2
# swap variant (this study's recommendation): S2_ST_ROC -> N09_ALLIG_AROON, N02_ST_KST -> F9_IFVG
T17S = C.WAVE1 + ["F16_FIB500", "F7_RF_TRIPLE", "N09_ALLIG_AROON", "F9_IFVG", "N07_ICHI_CMO", "DOGE", "N13_3OUTSIDE"]
SETS = {"T17": T17, "T10": C.WAVE1, "T23": C.ALL, "T17S": T17S}
CLS = {
    "off": {},
    "PROP": C.CLUSTERS_PROPOSED,
    "D60": {"ST": ["N01_ST_EMA", "N23_HA_ST", "S2_ST_ROC"], "RF": ["DOGE", "F7_RF_TRIPLE"],
            "ICHV": ["N07_ICHI_CMO", "N22_VORTEX_PSAR"]},
    "D50": {"ST": ["N01_ST_EMA", "N23_HA_ST", "S2_ST_ROC", "N02_ST_KST"], "RF": ["DOGE", "F7_RF_TRIPLE"],
            "ICHV": ["N07_ICHI_CMO", "N22_VORTEX_PSAR"], "BB": ["F12_MSS", "S4_BB_BBP"],
            "VW": ["F6_VWAP_CROSS", "N09_ALLIG_AROON"]},
    # recommended: average linkage on kappa_1h cut 0.5, kept only if every pair has every-signal daily R corr >= 0.5
    "REC": {"ST": ["N01_ST_EMA", "N23_HA_ST", "S2_ST_ROC", "N02_ST_KST"], "RF": ["DOGE", "F7_RF_TRIPLE"]},
}
FULL = list(itertools.product((0, 2, 3, 4), ("off", "PROP", "D60", "D50"), (0, 6, 8, 10)))
SMALL = [(0, "off", 0), (3, "off", 0), (2, "off", 0), (4, "off", 0), (0, "PROP", 0), (0, "D60", 0), (0, "off", 8),
         (3, "PROP", 8), (3, "D60", 8), (2, "D60", 8), (4, "D60", 8), (3, "D60", 0), (3, "off", 8), (4, "D60", 10),
         (4, "off", 10), (0, "off", 10), (0, "off", 6)]
SMALL = SMALL + [(3, "REC", 8), (4, "REC", 10), (3, "REC", 10), (0, "REC", 0), (4, "REC", 0), (3, "REC", 0),
                 (2, "REC", 8)]
FULL = FULL + [(c, "REC", b) for c in (0, 2, 3, 4) for b in (0, 6, 8, 10)]
JOBS = [("T17", "CARD", 1.0, FULL), ("T10", "CARD", 1.0, SMALL), ("T23", "CARD", 1.0, SMALL),
        ("T17", "U", 1.0, SMALL), ("T17", "CARD", 0.5, SMALL), ("T17S", "CARD", 1.0, SMALL),
        ("T17S", "CARD", 0.5, SMALL)]
ND = int((pd.Timestamp("2026-09-30").value - S.T0) // S.DAYNS)


def cl_array(traders, name):
    a = np.full(len(traders), -1, np.int64)
    for ci, (_, mem) in enumerate(CLS[name].items()):
        for s in mem:
            if s in traders:
                a[traders.index(s)] = ci
    # a cluster with only one staffed member is no constraint
    for ci in set(a[a >= 0]):
        if (a == ci).sum() < 2:
            a[a == ci] = -1
    return a if (a >= 0).any() else None


def job(args):
    path, set_name, scope_name, thin, configs = args
    traders = SETS[set_name]
    scope = C.CARD if scope_name == "CARD" else C.U
    t, ts15 = S.prep(path, traders, scope)
    if thin < 1.0:
        rng = np.random.default_rng(20261008)
        t = t[rng.random(len(t)) < thin].reset_index(drop=True)
    nb = len(ts15)
    live = slice(int(np.searchsorted(ts15, S.T0)), nb)
    R = t.R.to_numpy(); G = t.g.to_numpy()
    tag = dict(set=set_name, scope=scope_name, thin=thin)
    book_rows, tr_rows, crowd_rows, stop_rows = [], [], [], []
    base = None
    for cs, cl, bk in configs:
        cla = cl_array(traders, cl)
        tk, bl, it = S.run(t, ts15, len(traders), cs_cap=cs, clusters=cla, book_cap=bk)
        df, book, daily = S.summarize(t, ts15, tk, bl, it, traders)
        # intended attempts per half = taken first choices + taken reroutes + blocked-flat attempts
        e_t = ts15[t.e.to_numpy()[tk[:, 0]]]
        e_bf = ts15[t.e.to_numpy()[bl[bl[:, 2] == 0, 0]]] if len(bl) else np.zeros(0)
        it_IS = int((e_t < S.SPLIT).sum() + (e_bf < S.SPLIT).sum())
        it_CF = int((e_t >= S.SPLIT).sum() + (e_bf >= S.SPLIT).sum())
        r = tk[:, 0]
        xd = np.clip(((ts15[t.x.to_numpy()[r]] - S.T0) // S.DAYNS).astype(int), 0, ND - 1)
        dailyG = np.bincount(xd, weights=G[r], minlength=ND)
        ex = S.exposure(t, tk, nb)
        L, Sh, csm = ex["long"][live], ex["short"][live], ex["csmax"][live]
        same = np.maximum(L, Sh)
        w = np.where(t.tf.to_numpy()[tk[:, 0]] >= 2, 1.5, 1.0)
        ee, xx, sd_ = t.e.to_numpy()[tk[:, 0]], t.x.to_numpy()[tk[:, 0]], t.side.to_numpy()[tk[:, 0]]
        wmax = 0.0
        for sgn in (1, -1):
            dd_ = np.zeros(nb + 1)
            m_ = sd_ == sgn
            np.add.at(dd_, ee[m_], w[m_]); np.add.at(dd_, xx[m_] + 1, -w[m_])
            wmax = max(wmax, float(np.cumsum(dd_)[:nb][live].max()))
        # per-trader daily R for the diversification ratio
        tid = t.tid.to_numpy()[r]
        per_tr = np.zeros((len(traders), ND))
        for k in range(len(traders)):
            m = tid == k
            per_tr[k] = np.bincount(xd[m], weights=R[r][m], minlength=ND)
        div = float(daily.std() / np.sqrt((per_tr.std(axis=1) ** 2).sum()))
        cfg = dict(cs_cap=cs, cluster=cl, book_cap=bk, clusters_active=0 if cla is None else len(set(cla[cla >= 0])))
        b = dict(**tag, **cfg, **book)
        b.update(blocked_share=book["blocked_first"] / book["intended"],
                 trades_per_day=book["trades"] / ND, book_mean_day=float(daily.mean()), book_sd_day=float(daily.std()),
                 book_sd_day_gross=float(dailyG.std()), worst_day_gross=float(dailyG.min()),
                 worst_day_demeaned=float((daily - daily.mean()).min()), diversification_ratio=div,
                 same_dir_max=int(same.max()), same_dir_p99=float(np.quantile(same, .99)),
                 same_dir_max_R_1p5=wmax, same_dir_p50=float(np.median(same)), share_time_same_dir_ge8=float((same >= 8).mean()),
                 share_time_same_dir_ge6=float((same >= 6).mean()),
                 cs_max=int(csm.max()), share_time_cs_ge3=float((csm >= 3).mean()),
                 share_time_cs_ge5=float((csm >= 5).mean()),
                 blocked_meanR=float(R[bl[:, 0]].mean()) if len(bl) else np.nan,
                 share_book_days_le_m12R=float((daily <= -12).mean()),
                 share_book_days_le_m20R=float((daily <= -20).mean()),
                 share_book_days_le_m30R=float((daily <= -30).mean()),
                 share_trader_days_le_m3R=float((per_tr <= -3).mean()),
                 share_trader_days_le_m4R=float((per_tr <= -4).mean()),
                 blocked_share_IS=float((ts15[t.e.to_numpy()[bl[:, 0]]] < S.SPLIT).sum() / max(1, it_IS))
                 if len(bl) else 0.0,
                 blocked_share_CF=float((ts15[t.e.to_numpy()[bl[:, 0]]] >= S.SPLIT).sum() / max(1, it_CF))
                 if len(bl) else 0.0,
                 taken_meanR=float(R[r].mean()))
        if base is None:
            assert cs == 0 and cl == "off" and bk == 0
            base = dict(daily=daily, dailyG=dailyG, df=df.set_index("trader"), book=book)
            # crowding analysis on the uncapped run
            crowd = np.minimum(tk[:, 2], 4)
            crowd_d = np.minimum(tk[:, 3], 12)
            wk = ((ts15[t.e.to_numpy()[r]] - S.T0) // (7 * S.DAYNS)).astype(int)
            for lab, cc in (("coin_side_open", crowd), ("same_dir_open", crowd_d)):
                for lv in np.unique(cc):
                    m = cc == lv
                    crowd_rows.append(dict(**tag, measure=lab, level=int(lv), n=int(m.sum()),
                                           meanR=float(R[r][m].mean()), meanG=float(G[r][m].mean())))
                # week-cluster bootstrap: high-crowd minus zero-crowd mean gross R
                hi = cc >= (3 if lab == "coin_side_open" else 8)
                lo = cc == 0 if lab == "coin_side_open" else cc <= 4
                nw = wk.max() + 1
                sh = np.bincount(wk[hi], weights=G[r][hi], minlength=nw); nh = np.bincount(wk[hi], minlength=nw)
                sl = np.bincount(wk[lo], weights=G[r][lo], minlength=nw); nl = np.bincount(wk[lo], minlength=nw)
                rng = np.random.default_rng(3)
                idx = rng.integers(0, nw, size=(2000, nw))
                dif = sh[idx].sum(1) / nh[idx].sum(1) - sl[idx].sum(1) / nl[idx].sum(1)
                crowd_rows.append(dict(**tag, measure=lab + "_diff_gross_hi_minus_lo", level=-1, n=int(hi.sum()),
                                       meanR=float(G[r][hi].mean() - G[r][lo].mean()),
                                       meanG=float(np.quantile(dif, .025)), ci_hi=float(np.quantile(dif, .975))))
            # daily stops (rule proxy, uncapped): -3R/day per trader, -12R/day book
            years = ND / 365.25
            E_ = t.e.to_numpy(); CS_ = t.coin.to_numpy().astype(np.int64) * 2 + (t.side.to_numpy() > 0)
            wants = {}
            for lab, key, tid_ in (("raw15", E_.astype(np.int64) * 12 + CS_, t.tid.to_numpy()),
                                   ("raw1h", (E_.astype(np.int64) // 4) * 12 + CS_, t.tid.to_numpy()),
                                   ("free15", E_[r].astype(np.int64) * 12 + CS_[r], t.tid.to_numpy()[r]),
                                   ("free1h", (E_[r].astype(np.int64) // 4) * 12 + CS_[r], t.tid.to_numpy()[r])):
                ser = pd.DataFrame({"k": key, "t": tid_}).drop_duplicates().groupby("k").t.size()
                for kk in (3, 5, 8):
                    wants[f"want_{lab}_ge{kk}_per_year"] = float((ser >= kk).sum()) / years
                wants[f"want_{lab}_max"] = int(ser.max())
            b5 = (csm >= 5).astype(np.int8)
            wants["hold_cs_ge5_share_time"] = float(b5.mean())
            wants["hold_cs_ge5_episodes_per_year"] = float((np.diff(np.r_[0, b5]) == 1).sum()) / years
            wants["hold_cs_max"] = int(csm.max())
            stop_rows.append(dict(**tag, **wants, trader_days=int(per_tr.size),
                                  share_trader_days_le_m3R=float((per_tr <= -3).mean()),
                                  share_book_days_le_m12R=float((daily <= -12).mean()),
                                  share_book_days_le_m12R_demeaned=float((daily - daily.mean() <= -12).mean()),
                                  book_mean_day=float(daily.mean())))
        else:
            dd = daily - base["daily"]
            lo, hi = S.week_ci(dd)
            ddg = dailyG - base["dailyG"]
            glo, ghi = S.week_ci(ddg)
            b.update(dG_book=float(ddg.sum()), dG_book_ci_lo=glo, dG_book_ci_hi=ghi)
            b.update(dR_book=float(dd.sum()), dR_book_ci_lo=lo, dR_book_ci_hi=hi,
                     dTrades=book["trades"] - base["book"]["trades"],
                     dR_per_trade_taken=book["meanR"] - base["book"]["meanR"])
        book_rows.append(b)
        bdf = base["df"]
        for _, row in df.iterrows():
            rr = dict(**tag, **cfg, **row.to_dict())
            bt = bdf.loc[row.trader]
            rr.update(trades_base=int(bt.trades), sumR_base=float(bt.sumR), meanR_base=float(bt.meanR),
                      d_trades_pct=(row.trades - bt.trades) / bt.trades, dR=row.sumR - bt.sumR)
            tr_rows.append(rr)
    return book_rows, tr_rows, crowd_rows, stop_rows


def main(path, out, procs=4):
    os.makedirs(out, exist_ok=True)
    jobs = [(path,) + j for j in JOBS]
    B, T, CR, ST = [], [], [], []
    with Pool(int(procs)) as p:
        for b, tr, cr, st in p.imap_unordered(job, jobs):
            B += b; T += tr; CR += cr; ST += st
            print(b[0]["set"], b[0]["scope"], b[0]["thin"], len(b), flush=True)
    pd.DataFrame(B).to_csv(os.path.join(out, "runs_book.csv"), index=False, float_format="%.5g")
    pd.DataFrame(T).to_csv(os.path.join(out, "runs_trader.csv"), index=False, float_format="%.5g")
    pd.DataFrame(CR).to_csv(os.path.join(out, "crowding.csv"), index=False, float_format="%.5g")
    pd.DataFrame(ST).to_csv(os.path.join(out, "daily_stop.csv"), index=False, float_format="%.5g")


if __name__ == "__main__":
    main(*sys.argv[1:4])
