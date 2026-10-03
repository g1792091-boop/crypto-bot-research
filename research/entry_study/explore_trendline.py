"""Descriptive follow-up of the trendline study (NOT pre-registered, NOT used for any decision).

    python3 research/entry_study/explore_trendline.py [cache_dir] [out_dir]

PREREG_TRENDLINE.md had no candidate, so its section 6 / 7 checks never ran. But several primary tests
went clearly the OTHER way (most of all T3: a live same-side line within 2 ATR behind the entry goes
with worse trades, in random entries as well). A one-sided pre-registered test does not count that as
a finding. This script only describes it: for the random entries and the strategies pooled, per
timeframe and period, the T1..T4 differences (hypothesis sign: + = the pre-registered better group is
better) overall, by side, and leverage-tier weighted exactly like section 6 (2) (tiers = traded
leverage, both groups >= 10 trades, weights = the tier's trades), plus the trade share of each tier
per group. No p-values, no tests, no new trials: it reads the locked run's per-pair cache
(analysis_trendline.py stage 1) and writes out/trendline_explore.json.
"""

from __future__ import annotations

import json
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import analysis_trendline as AT  # noqa: E402


def _diff(test: str, roe: np.ndarray, g: np.ndarray) -> dict:
    r0, r1 = roe[g == 0], roe[g == 1]
    m0 = float(r0.mean()) if len(r0) else np.nan
    m1 = float(r1.mean()) if len(r1) else np.nan
    return dict(n0=int(len(r0)), n1=int(len(r1)), mean0=m0, mean1=m1,
                diff=(m1 - m0) if AT.GOOD[test] == 1 else (m0 - m1))


def describe(df: pd.DataFrame) -> dict:
    roe = df["roe"].to_numpy()
    lev = df["lev"].to_numpy()
    side = df["side"].to_numpy()
    out = {"n_trades": int(len(df)), "mean_roe": float(roe.mean()) if len(df) else None}
    for t in AT.TESTS:
        g = df[AT.TEST_FEATURE[t]].to_numpy()
        d = _diff(t, roe, g)
        tiers, wsum, wtot = [], 0.0, 0
        for lv in np.unique(lev):
            sel = lev == lv
            x = _diff(t, roe[sel], g[sel])
            use = x["n0"] >= AT.LEV_MIN_GROUP and x["n1"] >= AT.LEV_MIN_GROUP
            tiers.append(dict(lev=float(lv), used=use, share_of_group0=x["n0"] / max(d["n0"], 1),
                              share_of_group1=x["n1"] / max(d["n1"], 1), **x))
            if use:
                wsum += x["diff"] * (x["n0"] + x["n1"])
                wtot += x["n0"] + x["n1"]
        out[t] = dict(**d, lev_weighted_diff=wsum / wtot if wtot else None, lev_tiers=tiers,
                      by_side={("long" if s == 1 else "short"): _diff(t, roe[side == s], g[side == s]) for s in (1, -1)})
    return out


def main(cache: str | None = None, out: str | None = None) -> dict:
    cache = cache or AT.DEFAULT_CACHE
    out = out or AT.DEFAULT_OUT
    doc = {"note": "Descriptive only, not pre-registered, no p-values, not used for any decision. Differences in "
                   "the hypothesis sign of PREREG_TRENDLINE.md section 4 (+ = the pre-registered better group "
                   "is better). lev_weighted_diff = section 6 (2) method (tiers with >= 10 trades in both groups).",
           "cache": cache, "by_tf_period": {}}
    for tf in AT.ALL_TFS:
        doc["by_tf_period"][tf] = {}
        for p in AT.PERIODS:
            blk = {}
            for unit, lab in ((AT.RANDOM_UNIT, "random_entries"), (AT.ALL_UNIT, "strategies_pooled")):
                blk[lab] = describe(AT._unit_trades(tf, unit, p, cache))
            doc["by_tf_period"][tf][str(p)] = blk
            print(tf, p, {lab: {t: round(b[t]["diff"] * 100, 2) for t in AT.TESTS} for lab, b in blk.items()},
                  flush=True)
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "trendline_explore.json"), "w") as fh:
        json.dump(AT.A._clean(doc), fh, indent=1)
    return doc


if __name__ == "__main__":
    main(*(sys.argv[1:3]))
