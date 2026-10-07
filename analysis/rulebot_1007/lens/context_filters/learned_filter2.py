#!/usr/bin/env python3
"""Variants of learned_filter.py: which feature groups carry the transfer; coefficients; per-tf uplift.
    python3 -I learned_filter2.py <lens_dir> <out_dir>"""
import os, site, sys
sys.dont_write_bytecode = True
sys.path.append(site.getusersitepackages())
sys.path.insert(0, sys.argv[1])
import numpy as np, pandas as pd
import learned_filter as L
import features as F
OUT = sys.argv[2]
D = L.D
core = D[D["kind"] == "strategy"]
CH = L.FEATS_CHART
variants = {
    "chart only": CH,
    "chart minus stop_t": [f for f in CH if f != "stop_t"],
    "chart minus momentum (ema_s di_s boxpos_s rangepos_s htfpos_s adx_b)": [f for f in CH if f not in ("ema_s", "di_s", "boxpos_s", "rangepos_s", "htfpos_s", "adx_b")],
    "all minus side": [f for f in F.FEATURES if f != "side"],
    "stop_t only": ["stop_t"],
}
rows = []
coefs = []
for name, feats in variants.items():
    for lab, tr, te in (("v3a->v3b+v4 core", core[core.run == "v3a"], core[core.run.isin(["v3b", "v4"])]),
                        ("v3a core->v4 ds200", core[core.run == "v3a"], D[(D.run == "v4") & (D.kind == "ds200")]),
                        ("v4 all->v3a+v3b core", D[D.run == "v4"], core[core.run.isin(["v3a", "v3b"])])):
        r = L.run_one(tr, te, feats, f"{lab} | {name}", null_draws=200, seed=len(rows))
        # per tf uplift
        test = te.reset_index(drop=True)
        Xtr_df = L.design(tr, feats); cols = Xtr_df.columns
        m = L.ridge_fit(Xtr_df.to_numpy(float), tr["R"].to_numpy(float), r["lambda"])
        p = L.ridge_pred(m, L.design(test, feats, cols).to_numpy(float))
        keep = L.uplift(test, p, 1 / 3)
        for tf in ("15m", "30m"):
            mm = (test["timeframe"] == tf).to_numpy()
            y = test["R"].to_numpy(float)
            r[f"uplift_top3rd_{tf}"] = float(y[mm & keep].mean() - y[mm].mean())
            g = test["gross"].to_numpy(float)
            r[f"uplift_gross_top3rd_{tf}"] = float(g[mm & keep].mean() - g[mm].mean())
        rows.append(r)
        if name == "chart only":
            w = pd.Series(m[0], index=cols, name=lab)
            coefs.append(w)
R = pd.DataFrame(rows)
R.to_csv(os.path.join(OUT, "learned_filter_variants.csv"), index=False)
C = pd.concat(coefs, axis=1)
C.to_csv(os.path.join(OUT, "learned_filter_coefs_chart.csv"))
pd.set_option("display.width", 250)
print(R[["model", "lambda", "test_spearman", "insample_uplift_top3rd", "uplift_top3rd", "ci95_top3rd", "mean_R_kept_top3rd", "mean_R_all_test", "p_uplift_vs_null", "uplift_top3rd_15m", "uplift_top3rd_30m", "uplift_gross_top3rd_15m", "uplift_gross_top3rd_30m"]].round(3).to_string())
C["sum_abs"] = C.abs().sum(1)
print(C.sort_values("sum_abs", ascending=False).head(25).round(4).to_string())
