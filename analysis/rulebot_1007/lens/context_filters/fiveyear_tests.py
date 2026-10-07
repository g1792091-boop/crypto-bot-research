#!/usr/bin/env python3
"""5-year check of the live context candidates (contrasts fixed from the live results BEFORE this was run).

C1 session europe | C2 adx >= 30 | C3 htf box middle | C4 ema_s with | C5 di_s with | C6 box far edge |
C7 range far edge | C8 stop wide (cost control) | C9 consensus many | C10 the live learned filter (chart features
computable from bars) applied to 5 years | C11 a filter learned on 5-year IS (2021-08..2024-06) tested on CF
(2024-07..2026-09): the upper bound of what these features can do with plenty of data.
Clusters: KST day (CR1). Within-side = strata year x side; per-year estimates for stability.

    python3 -I fiveyear_tests.py <lens_dir> <live_out_dir> <out5y_dir>
"""
from __future__ import annotations

import os
import site
import sys

sys.dont_write_bytecode = True
sys.path.append(site.getusersitepackages())
sys.path.insert(0, sys.argv[1])

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from scipy import stats  # noqa: E402

import features as F  # noqa: E402
import learned_filter as L  # noqa: E402
from stats_util import cr_contrast  # noqa: E402

LENS, LIVE_OUT, O5 = sys.argv[1:4]
HOUR = 3_600_000
CONTR = [("C1", "session", "europe"), ("C2", "adx_b", "ge30"), ("C3", "htfpos_s", "middle"), ("C4", "ema_s", "with"),
         ("C5", "di_s", "with"), ("C6", "boxpos_s", "far_edge"), ("C7", "rangepos_s", "far_edge"),
         ("C8", "stop_t", "wide"), ("C9", "consensus", "many")]
FEATS5 = ["er_t", "adx_b", "di_s", "ema_s", "age_b", "boxpos_s", "htfpos_s", "rangepos_s", "stop_t", "consensus",
          "conflict"]


def to_live_cols(X):
    Y = pd.DataFrame({
        "timeframe": X["tf"], "side": X["side"].astype(int), "R": X["R"], "bar_close": X["close_t"],
        "regime": np.nan, "htf_regime": np.nan, "er": X["er"], "box_pos": X["box_pos"], "htf_box_pos": X["htf_pos"],
        "ema20_dist_atr": X["ema_dist"], "trend_age": X["age"], "range_pct": X["range_pos"], "adx": X["adx"],
        "di_plus": X["dip"], "di_minus": X["dim"], "sr_room": np.nan, "sr_floor": np.nan,
        "sr_level_before_lock": np.nan, "sr_support_before_stop": np.nan, "sr_breakout": np.nan,
        "stop_pct": X["stop_pct"], "kst_hour": X["kst_hour"].astype(int), "symbol": X["coin"] + "T", "q_tier": None,
        "kind": "strategy", "n_same": X["n_same"], "n_opp": X["n_opp"], "strategy": X["strategy"],
    })
    Y = F.add_buckets(Y)
    dt = pd.to_datetime(Y["bar_close"] + 9 * HOUR, unit="ms")
    Y["year"] = dt.dt.year
    Y["day"] = (Y["bar_close"] + 9 * HOUR) // (24 * HOUR)
    Y["period"] = np.where(Y["bar_close"] < pd.Timestamp("2024-07-01").value // 10 ** 6, "IS", "CF")
    return Y


def strata_contrast(Y, col, bucket, by):
    runs = []
    for _, g in Y[Y[col].notna()].groupby(by):
        runs.append({"y": g["R"].to_numpy(float), "inb": (g[col] == bucket).to_numpy(),
                     "bc": g["bar_close"].to_numpy(np.int64)})
    d, se, df = cr_contrast(runs, hours=24.0, min_each=30)
    return d, se


def main():
    X = pd.read_csv(os.path.join(O5, "fiveyear_signals.csv.gz"))
    X = X[X["R"].notna()]
    Y = to_live_cols(X)
    rows = []
    for tf in ("15m", "30m"):
        y = Y[Y["timeframe"] == tf]
        for cid, f, b in CONTR:
            col = F.bucket_col(f)
            d1, s1 = strata_contrast(y, col, b, ["year"])
            d2, s2 = strata_contrast(y, col, b, ["year", "side"])
            r = {"tf": tf, "id": cid, "feature": f, "bucket": b, "n": int(y[col].notna().sum()),
                 "n_in": int((y[col] == b).sum()), "share_in": float((y[col] == b).mean()),
                 "d_year_strata": d1, "se": s1, "z": d1 / s1, "d_within_side": d2, "se_ws": s2, "z_ws": d2 / s2}
            per = []
            for yr, g in y.groupby("year"):
                dd, ss = strata_contrast(g, col, b, ["side"])
                r[f"d_{yr}"] = dd
                per.append(dd)
            per = np.array(per)
            r["years_same_sign_as_pooled"] = int(np.sum(np.sign(per) == np.sign(d2)))
            r["years"] = len(per)
            rows.append(r)
    T = pd.DataFrame(rows)
    T["p_two_ws"] = 2 * stats.norm.sf(np.abs(T["z_ws"]))
    T.to_csv(os.path.join(O5, "fiveyear_contrasts.csv"), index=False)
    pd.set_option("display.width", 250)
    print(T.round(3).to_string())

    # C10: live learned filter (all live runs, core 36, 15m + 30m) -> 5 years
    live = pd.read_csv(os.path.join(LIVE_OUT, "signals_bucketed.csv.gz"), low_memory=False)
    live = live[(live["kind"] == "strategy") & live["timeframe"].isin(["15m", "30m"])]
    out = []
    Xtr_df = L.design(live, FEATS5)
    cols = Xtr_df.columns
    lam = L.choose_lambda(Xtr_df.to_numpy(float), live["R"].to_numpy(float), live["bar_close"].to_numpy())
    m = L.ridge_fit(Xtr_df.to_numpy(float), live["R"].to_numpy(float), lam)
    Yd = Y.copy()
    Yd["kind"] = "strategy"
    pred = L.ridge_pred(m, L.design(Yd, FEATS5, cols).to_numpy(float))
    Yd["pred_live"] = pred
    for (tf, yr), g in Yd.groupby(["timeframe", "year"]):
        thr = g["pred_live"].quantile(2 / 3)
        keep = g["pred_live"] >= thr
        out.append({"model": "C10 live filter -> 5y", "tf": tf, "year": yr, "n": len(g), "mean_R_all": g["R"].mean(),
                    "mean_R_top3rd": g.loc[keep, "R"].mean(), "uplift": g.loc[keep, "R"].mean() - g["R"].mean(),
                    "spearman": stats.spearmanr(g["pred_live"], g["R"]).correlation})
    # C11: 5-year IS -> CF (same features), lambda by blocked CV inside IS
    for tf in ("15m", "30m"):
        g = Yd[Yd["timeframe"] == tf]
        tr, te = g[g["period"] == "IS"], g[g["period"] == "CF"]
        Xtr = L.design(tr, FEATS5)
        c2 = Xtr.columns
        lam2 = L.choose_lambda(Xtr.to_numpy(float), tr["R"].to_numpy(float), tr["bar_close"].to_numpy())
        m2 = L.ridge_fit(Xtr.to_numpy(float), tr["R"].to_numpy(float), lam2)
        p2 = L.ridge_pred(m2, L.design(te, FEATS5, c2).to_numpy(float))
        te = te.assign(pred=p2)
        for yr, h in te.groupby("year"):
            thr = h["pred"].quantile(2 / 3)
            keep = h["pred"] >= thr
            out.append({"model": "C11 5y IS -> CF", "tf": tf, "year": yr, "n": len(h), "mean_R_all": h["R"].mean(),
                        "mean_R_top3rd": h.loc[keep, "R"].mean(), "uplift": h.loc[keep, "R"].mean() - h["R"].mean(),
                        "spearman": stats.spearmanr(h["pred"], h["R"]).correlation, "lambda": lam2})
        # day-cluster CI of the CF uplift (both CF years pooled)
        thr_all = te.groupby("year")["pred"].transform(lambda s: s.quantile(2 / 3))
        k = (te["pred"] >= thr_all).to_numpy()
        yv = te["R"].to_numpy(float)
        day = te["day"].to_numpy()
        u, inv = np.unique(day, return_inverse=True)
        G = len(u)
        sk = np.bincount(inv, weights=yv * k, minlength=G)
        nk = np.bincount(inv, weights=k.astype(float), minlength=G)
        sa = np.bincount(inv, weights=yv, minlength=G)
        na = np.bincount(inv, minlength=G).astype(float)
        rng = np.random.default_rng(5)
        bs = []
        for _ in range(1000):
            i = rng.integers(0, G, G)
            bs.append(sk[i].sum() / nk[i].sum() - sa[i].sum() / na[i].sum())
        out.append({"model": "C11 5y IS -> CF pooled", "tf": tf, "year": "CF", "n": len(te), "mean_R_all": yv.mean(),
                    "mean_R_top3rd": yv[k].mean(), "uplift": yv[k].mean() - yv.mean(),
                    "ci95": f"{np.percentile(bs, 2.5):.3f} {np.percentile(bs, 97.5):.3f}", "lambda": lam2})
        coef = pd.Series(m2[0], index=c2)
        coef.to_csv(os.path.join(O5, f"fiveyear_IS_coefs_{tf}.csv"))
    U = pd.DataFrame(out)
    U.to_csv(os.path.join(O5, "fiveyear_filters.csv"), index=False)
    print(U.round(3).to_string())
    pd.Series(m[0], index=cols).to_csv(os.path.join(O5, "live_filter_coefs_reduced.csv"))


if __name__ == "__main__":
    main()
