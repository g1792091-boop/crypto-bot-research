"""All 36 cells from the analyst's (parity-checked) cells files: (a) time-to-confirm recomputed (own code, day and week
clusters, one-sample vs two-sample, one-position stream with its own design effect); (b) static levels in R2 (k/2
scaling) vs exact R2x (net pct / default 2 ATR stop pct) vs net pct.  usage: python3 -I vpow.py <scratchpad>"""
import sys, os, json
sys.path.append("/root/.local/lib/python3.11/site-packages")
import numpy as np
import pandas as pd

SCR = sys.argv[1]
CV = os.path.join(SCR, "lens2/custom_values")
HERE = os.path.dirname(os.path.abspath(__file__))
NSD, NSW = 86400 * 10**9, 7 * 86400 * 10**9
W0 = np.datetime64("2021-02-01", "ns").astype(np.int64)
OLO = W0 + 26 * NSW
NW = int((np.datetime64("2026-09-30", "ns").astype(np.int64) - W0) // NSW)
OHI = W0 + NW * NSW
SPLIT = np.datetime64("2024-07-01", "ns").astype(np.int64)
NWO = NW - 26
TFM = {"15m": 15, "30m": 30, "1h": 60}
STR = ["S2_ST_ROC", "N23_HA_ST", "N24_DMI", "N10_HA_PSAR", "S4_BB_BBP", "N06_MACD_ORB", "OBV_B", "F6_VWAP_CROSS",
       "F9_FVG", "N17_KC_RSI", "N16_BBRSI", "F5_BOX"]
Z = 2.487


def clus(v, g):
    """mean, sd, design effect of the ratio mean under clusters g."""
    n = len(v)
    m = v.mean()
    sd = v.std()
    e = np.bincount(g, v - m)
    var_cl = (e ** 2).sum() / n ** 2
    return m, sd, var_cl / (sd * sd / n)


pw, lv = [], []
for s in STR:
    for tf in ("15m", "30m", "1h"):
        cell = f"{s}_{tf}"
        z = np.load(os.path.join(CV, "work/cells", cell + ".npz"))
        ts, pm, fm, done = z["ts"], z["pmask"], z["fmask"], z["done"]
        rn, npct, sp = z["rnet"].astype(float), z["npct"].astype(float), z["stop_pct"].astype(float)
        ec = z["exit_close"]
        oo = (ts >= OLO) & (ts < OHI)
        r2 = rn * np.repeat([0.75, 1.0, 1.25], 3)[None, :]
        r2x = npct / sp[:, 1][:, None]
        d = oo & pm[:, 0] & done[:, 3]
        v = r2[d, 3]
        day = (ts[d] - OLO) // NSD
        wk = day // 7
        m, sd, deff_d = clus(v, day)
        _, _, deff_w = clus(v, wk)
        tpw = d.sum() / NWO
        row = dict(cell=cell, n=int(d.sum()), mean_R2=m, sd_R2=sd, deff_day=deff_d, deff_week=deff_w, tpw=tpw)
        for dl in (0.05, 0.10, 0.20):
            row[f"wk1s_day_{dl}"] = (Z * sd / dl) ** 2 * deff_d / tpw
        row["wk2s_day_0.1"] = 2 * row["wk1s_day_0.1"]
        row["wk1s_week_0.1"] = (Z * sd / 0.1) ** 2 * deff_w / tpw
        # one-position thinning (one position across the six coins), default stream
        tfn = TFM[tf] * 60 * 10**9
        ii = np.flatnonzero(d)
        free, tk = -1, []
        for i in ii:
            if ts[i] + tfn >= free:
                tk.append(i)
                free = ec[i, 3]
        tk = np.array(tk)
        v1 = r2[tk, 3]
        m1, sd1, deff1 = clus(v1, (ts[tk] - OLO) // NSD)
        _, _, deff1w = clus(v1, (ts[tk] - OLO) // NSW)
        tpw1 = len(tk) / NWO
        row.update(tpw_1pos=tpw1, mean_R2_1pos=m1, deff_day_1pos=deff1, deff_week_1pos=deff1w)
        row["wk1s_1pos_0.1"] = (Z * sd1 / 0.1) ** 2 * deff1 / tpw1
        row["wk1s_1pos_week_0.1"] = (Z * sd1 / 0.1) ** 2 * deff1w / tpw1
        row["ratio_1pos_vs_all_weeks"] = row["wk1s_1pos_0.1"] / row["wk1s_day_0.1"]
        pw.append(row)
        # static levels by half (combo = P0, filter, stop, exit); default j=3
        for h, (lo, hi) in enumerate(((OLO, SPLIT), (SPLIT, OHI))):
            sel = (ts >= lo) & (ts < hi) & pm[:, 0]
            base = sel & done[:, 3]
            bm = {k: arr[base, 3].mean() for k, arr in (("R2", r2), ("R2x", r2x), ("NP", npct * 100))}
            levels = {"stop1.5": (None, 0), "stop2.5": (None, 6), "F_htf": (0, 3), "F_adx": (1, 3), "F_box": (2, 3),
                      "F_session": (3, 3), "exit_rladder": (None, 4), "exit_tp": (None, 5)}
            for nm, (f, j) in levels.items():
                mk = sel & done[:, j]
                if f is not None:
                    mk &= fm[:, f]
                for k, arr in (("R2", r2), ("R2x", r2x), ("NP", npct * 100)):
                    lv.append(dict(cell=cell, half="AB"[h], level=nm, metric=k, n=int(mk.sum()),
                                   delta=arr[mk, j].mean() - bm[k]))
    print(cell, flush=True)

P = pd.DataFrame(pw)
P.drop(columns=[c for c in P.columns if c.endswith("_1pos") and P[c].isna().all()]).to_csv(os.path.join(HERE, "vpow_cells.csv"), index=False)
L = pd.DataFrame(lv)
L.to_csv(os.path.join(HERE, "vlevels_cells.csv"), index=False)
th = pd.read_csv(os.path.join(CV, "out_R2/cell_desc.csv"))
mm = P.merge(th[["cell", "weeks_needed_0.1", "deff", "trades_per_week", "sd_R"]], on="cell")
summ = dict(
    weeks_0p10_all_signal_median_mine=float(P["wk1s_day_0.1"].median()),
    weeks_0p10_range_mine=[float(P["wk1s_day_0.1"].min()), float(P["wk1s_day_0.1"].max())],
    weeks_0p10_median_analyst=float(th["weeks_needed_0.1"].median()),
    max_rel_diff_weeks_vs_analyst=float((mm["wk1s_day_0.1"] / mm["weeks_needed_0.1"] - 1).abs().max()),
    weeks_0p05_median=float(P["wk1s_day_0.05"].median()), weeks_0p20_median=float(P["wk1s_day_0.2"].median()),
    weeks_0p10_two_sample_median=float(P["wk2s_day_0.1"].median()),
    weeks_0p10_week_cluster_median=float(P["wk1s_week_0.1"].median()),
    deff_day_range=[float(P.deff_day.min()), float(P.deff_day.max())],
    deff_week_range=[float(P.deff_week.min()), float(P.deff_week.max())],
    one_pos_weeks_0p10_median=float(P["wk1s_1pos_0.1"].median()),
    one_pos_weeks_0p10_range=[float(P["wk1s_1pos_0.1"].min()), float(P["wk1s_1pos_0.1"].max())],
    one_pos_ratio_range=[float(P.ratio_1pos_vs_all_weeks.min()), float(P.ratio_1pos_vs_all_weeks.max())],
    one_pos_ratio_median=float(P.ratio_1pos_vs_all_weeks.median()),
    one_pos_deff_day_range=[float(P.deff_day_1pos.min()), float(P.deff_day_1pos.max())],
    tpw_ratio_range=[float((P.tpw / P.tpw_1pos).min()), float((P.tpw / P.tpw_1pos).max())],
    cells_weeks_0p10_le_12=int((P["wk1s_day_0.1"] <= 12).sum()), cells_weeks_0p20_le_12=int((P["wk1s_day_0.2"] <= 12).sum()),
    cells_1pos_weeks_0p20_le_12=int(((P["wk1s_1pos_0.1"] / 4) <= 12).sum()),
)
g = L.groupby(["level", "metric", "half"]).delta.agg(["mean", lambda x: int((x > 0).sum())]).round(5)
g.columns = ["mean_delta", "cells_pos"]
summ["levels"] = {f"{a}|{b}|{c}": list(map(float, r)) for (a, b, c), r in g.iterrows()}
json.dump(summ, open(os.path.join(HERE, "vpow_summary.json"), "w"), indent=1)
print(json.dumps({k: v for k, v in summ.items() if k != "levels"}, indent=0))
print(g.unstack("half").to_string())
