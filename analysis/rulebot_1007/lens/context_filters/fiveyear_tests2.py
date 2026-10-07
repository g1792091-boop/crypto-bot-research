#!/usr/bin/env python3
"""5-year follow-up: (a) the C1-C9 contrasts within strategy x year x side (composition-free);
(b) the C11 filter (5y IS -> CF, pooled model) per strategy x tf in CF: mean R all, top third, uplift, day-cluster SE;
(c) the same contrasts in ROE (money per margin) for the cost-channel contrast C8.

    python3 -I fiveyear_tests2.py <lens_dir> <live_out_dir> <out5y_dir>
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

import features as F  # noqa: E402
import fiveyear_tests as FT  # noqa: E402
import learned_filter as L  # noqa: E402
from stats_util import cr_contrast  # noqa: E402

LENS, LIVE_OUT, O5 = sys.argv[1:4]


def main():
    X = pd.read_csv(os.path.join(O5, "fiveyear_signals.csv.gz"))
    X = X[X["R"].notna()]
    Y = FT.to_live_cols(X)
    Y["roe"] = X["roe"].to_numpy()
    rows = []
    for tf in ("15m", "30m"):
        y = Y[Y["timeframe"] == tf]
        for cid, f, b in FT.CONTR:
            col = F.bucket_col(f)
            for oc in ("R", "roe"):
                runs = []
                for _, g in y[y[col].notna()].groupby(["strategy", "year", "side"]):
                    runs.append({"y": g[oc].to_numpy(float), "inb": (g[col] == b).to_numpy(),
                                 "bc": g["bar_close"].to_numpy(np.int64)})
                d, se, df = cr_contrast(runs, hours=24.0, min_each=10)
                rows.append({"tf": tf, "id": cid, "feature": f, "bucket": b, "outcome": oc,
                             "d_within_strategy_year_side": d, "se": se, "z": d / se if se else np.nan})
    W = pd.DataFrame(rows)
    W.to_csv(os.path.join(O5, "fiveyear_within_strategy.csv"), index=False)
    pd.set_option("display.width", 250)
    print(W.round(4).to_string())
    # (b) per strategy uplift of the pooled IS -> CF filter
    out = []
    for tf in ("15m", "30m"):
        g = Y[Y["timeframe"] == tf]
        tr, te = g[g["period"] == "IS"], g[g["period"] == "CF"].copy()
        Xtr = L.design(tr, FT.FEATS5)
        c2 = Xtr.columns
        lam = L.choose_lambda(Xtr.to_numpy(float), tr["R"].to_numpy(float), tr["bar_close"].to_numpy())
        m = L.ridge_fit(Xtr.to_numpy(float), tr["R"].to_numpy(float), lam)
        te["pred"] = L.ridge_pred(m, L.design(te, FT.FEATS5, c2).to_numpy(float))
        te["thr"] = te.groupby("year")["pred"].transform(lambda s: s.quantile(2 / 3))   # pooled threshold
        te["keep"] = te["pred"] >= te["thr"]
        for s, h in te.groupby("strategy"):
            if len(h) < 300:
                continue
            k = h["keep"].to_numpy()
            yv = h["R"].to_numpy(float)
            rv = h["roe"].to_numpy(float)
            # day-cluster SE of mean(kept) - mean(all)
            u, inv = np.unique(h["day"].to_numpy(), return_inverse=True)
            G = len(u)
            sk = np.bincount(inv, weights=yv * k, minlength=G)
            nk = np.bincount(inv, weights=k.astype(float), minlength=G)
            sa = np.bincount(inv, weights=yv, minlength=G)
            na = np.bincount(inv, minlength=G).astype(float)
            Nk, Na = nk.sum(), na.sum()
            mk, ma = sk.sum() / max(Nk, 1), sa.sum() / Na
            infl = (sk - mk * nk) / max(Nk, 1) - (sa - ma * na) / Na
            se = float(np.sqrt(G / max(G - 1, 1) * (infl ** 2).sum()))
            infl_k = (sk - mk * nk) / max(Nk, 1)
            se_k = float(np.sqrt(G / max(G - 1, 1) * (infl_k ** 2).sum()))
            out.append({"tf": tf, "strategy": s, "family": None, "n_cf": len(h), "kept_share": float(k.mean()),
                        "mean_R_cf": ma, "mean_R_kept": mk, "se_mean_R_kept": se_k, "uplift": mk - ma, "se_uplift": se,
                        "mean_roe_cf": float(rv.mean()), "mean_roe_kept": float(rv[k].mean()) if k.any() else np.nan,
                        "signals_per_day_cf": len(h) / 821.0})
    U = pd.DataFrame(out).sort_values(["tf", "mean_R_kept"], ascending=[True, False])
    U.to_csv(os.path.join(O5, "fiveyear_filter_by_strategy.csv"), index=False)
    print(U.round(3).to_string())


if __name__ == "__main__":
    main()
