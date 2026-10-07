#!/usr/bin/env python3
"""5-year check of the family hypotheses (H1, H2, H3, H4, H7 - H5/H6 need regime labels not rebuilt here) and of the
single per-strategy live survivor (N18_VWMA_MACD 15m, high ER vs low ER), plus that contrast for every strategy
(is N18 special?). Strata strategy x year x side, KST-day clusters (CR1).

    python3 -I fiveyear_tests3.py <lens_dir> <live_out_dir> <out5y_dir>
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
from stats_util import cr_contrast  # noqa: E402

LENS, LIVE_OUT, O5 = sys.argv[1:4]


def c2(y, col, hi, lo, by):
    x = y[y[col].isin([hi, lo])]
    runs = [{"y": g["R"].to_numpy(float), "inb": (g[col] == hi).to_numpy(), "bc": g["bar_close"].to_numpy(np.int64)}
            for _, g in x.groupby(by)]
    d, se, _ = cr_contrast(runs, hours=24.0, min_each=10)
    return d, se, int((x[col] == hi).sum()), int((x[col] == lo).sum())


def main():
    live = pd.read_csv(os.path.join(LIVE_OUT, "signals_bucketed.csv.gz"), usecols=["strategy", "family"])
    fam = live.drop_duplicates("strategy").set_index("strategy")["family"]
    X = pd.read_csv(os.path.join(O5, "fiveyear_signals.csv.gz"))
    X = X[X["R"].notna()]
    Y = FT.to_live_cols(X)
    Y["family"] = Y["strategy"].map(fam).fillna("other")
    rows = []
    for hid, fm, f, hi, lo, sgn in F.HYP:
        if f == "regime_s":
            continue
        col = F.bucket_col(f)
        for tf in ("15m", "30m"):
            y = Y[(Y["timeframe"] == tf) & ((Y["family"] == fm) if fm != "*" else True)]
            d, se, ni, no = c2(y, col, hi, lo, ["strategy", "year", "side"])
            per = []
            for yr, g in y.groupby("year"):
                dd, _, _, _ = c2(g, col, hi, lo, ["strategy", "side"])
                per.append(dd)
            rows.append({"test": hid, "tf": tf, "n_hi": ni, "n_lo": no, "d": d, "se": se, "z": d / se,
                         "expected_sign": sgn, "years_expected_sign": int(np.sum(np.sign(per) == sgn)),
                         "years": len(per)})
    for tf in ("15m", "30m"):
        y = Y[Y["timeframe"] == tf]
        for s, g in y.groupby("strategy"):
            d, se, ni, no = c2(g, "er_t", "high", "low", ["year", "side"])
            if ni >= 200 and no >= 200:
                rows.append({"test": f"ER high-low {s}", "tf": tf, "n_hi": ni, "n_lo": no, "d": d, "se": se,
                             "z": d / se, "expected_sign": 1 if fam.get(s) == "trend" else np.nan})
    T = pd.DataFrame(rows)
    T.to_csv(os.path.join(O5, "fiveyear_hypotheses.csv"), index=False)
    pd.set_option("display.width", 250)
    print(T.round(3).to_string())


if __name__ == "__main__":
    main()
