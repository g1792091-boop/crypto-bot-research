#!/usr/bin/env python3
"""Grades for the DeepSeek-44 cards (mechanical rules below), merged-duplicate map, final cards_deepseek.csv.

    python3 -I grade.py <out_dir_of_cards.py> <replay_signals.csv>

RULES (applied in this order; a card gets the first that matches):
  N   no live evidence: fewer than 5 replayed trades of every submitted signal (judged on the 5-year line only)
  X   merged duplicate: the definition is (by its PREREG definition) nested in, or in the live window >= 85 %
      of its signals coincide with, a kept sibling at the same tf; or the same signal stream at another tf
  D   drop for AI: testable (>= 10 replayed trades, >= 8 clusters) and significantly negative after BH
      (q <= 0.10 on p(mean R < 0) over all testable cells), OR mean replay R < 0 with >= 5 trades AND the 5-year
      best-exit net mean (periods 1+2) in the worst third of its timeframe
  A   AI trader on evidence: testable, BH q <= 0.10 on p(mean R > 0), 95 % cluster CI above 0 with 1h and 4h
      clusters, side-balanced R > 0, and in the 5-year at least one exit positive in all three periods
  W   watch (an exploratory AI slot at most, never a 12/31 candidate on this evidence): testable, mean R > 0,
      side-balanced R > 0 (not only shorts in a falling market), mean R without the best trade > 0,
      R vs peers (same tf, side, 4h block) > 0, and the 5-year best-exit net mean in the better half of its tf
  C   everything else: keep as a cost-free rule account, no AI trader
"""
from __future__ import annotations

import os
import site
import sys

sys.dont_write_bytecode = True
sys.path.append(site.getusersitepackages())
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

# kept representative <- merged member (same tf unless noted). Nesting from PREREG_DEEPSEEK200.md section 5;
# live overlap from dup_pairs_ds.csv (printed for every pair below).
MERGE = {
    "F5_BOX_HTF": "F5_BOX",          # F5_BOX + higher-tf ADX<20 filter (subset by definition; identical live @15m/30m)
    "F13_RAID_PD": "F11_RAID",       # F11_RAID + premium/discount filter (subset; 36/38 @15m, identical @1h/4h)
    "F11_TSOUP": "F11_RAID",         # 20-bar turtle soup; 22 of 25 live signals @15m are also RAID signals
    "F17_Z_HL": "F17_Z",             # F17_Z + half-life gate (subset; 47/50 @15m, identical @1h/4h)
    "F12_MSS_DISP": "F12_MSS",       # F12_MSS + displacement body (subset by definition)
    "F13_FVG_PD": "F9_FVG",          # F9_FVG + premium/discount filter (subset by definition)
    "F10_M2022": "F9_FVG",           # FVG zones after raid + displacement MSS (subset of F9_FVG zones)
    "F16_FIB618": "F10_OTE",         # 61.8 % retracement vs the 62-79 % OTE zone (14/14 @15m, identical @4h)
    "F7_RF_ONLY": "F7_RF_TRIPLE",    # 75 % of RF_ONLY signals are RF_TRIPLE signals @15m/30m
}
# same stream at several timeframes: keep the first listed tf
SAME_STREAM = {("F15_OPEN0000", "30m"): "F15_OPEN0000@15m", ("F15_OPEN0000", "1h"): "F15_OPEN0000@15m",
               ("F15_OPEN0930", "30m"): "F15_OPEN0930@15m"}


def bh(p, q=0.10):
    p = np.asarray(p, float)
    n = len(p)
    o = np.argsort(p)
    r = p[o] * n / (np.arange(n) + 1)
    qv = np.minimum.accumulate(r[::-1])[::-1]
    out = np.empty(n)
    out[o] = np.minimum(qv, 1)
    return out


def main(out_dir, replay_csv):
    C = pd.read_csv(os.path.join(out_dir, "cards_deepseek_raw.csv"))
    DP = pd.read_csv(os.path.join(out_dir, "dup_pairs_ds.csv"))
    # drift-neutral side flip per cell
    P = pd.read_csv(replay_csv)
    P = P[(P["kind"] == "ds200") & (P["run"] == "current") & (P["status"] == "TRADED") & (P["flip_status"] == "TRADED")]
    P = P[np.isfinite(P["R"]) & np.isfinite(P["flip_R"])].copy()
    P["h"] = 0.5 * (P["R"] - P["flip_R"])
    sf = P.groupby(["strategy", "timeframe"]).apply(lambda g: pd.Series({
        "sf_excess_long": g.loc[g["side"] > 0, "h"].mean(), "sf_excess_short": g.loc[g["side"] < 0, "h"].mean(),
        "sf_n_long": int((g["side"] > 0).sum()), "sf_n_short": int((g["side"] < 0).sum())}), include_groups=False).reset_index()
    sf["sf_excess_drift_neutral"] = np.where((sf["sf_n_long"] >= 3) & (sf["sf_n_short"] >= 3),
                                             0.5 * (sf["sf_excess_long"] + sf["sf_excess_short"]), np.nan)
    C = C.merge(sf.rename(columns={"strategy": "definition"}), on=["definition", "timeframe"], how="left")

    # fixed-leverage replay (levreplay.py): mean R (traded + unresolved marked to the last close), entered share
    LV = pd.read_csv(os.path.join(out_dir, "lev_replay_signals.csv"))
    LV["Rv"] = np.where(LV["status"] == "TRADED", LV["R"], np.where(LV["status"] == "UNRESOLVED", LV["mark_R"], np.nan))
    lv = LV.groupby(["strategy", "timeframe", "lev_fixed"]).agg(Rv=("Rv", "mean"), entered=("Rv", lambda s: s.notna().mean()))
    lv = lv.unstack("lev_fixed")
    lv.columns = [f"lev{b}_{'mean_R' if a == 'Rv' else 'entered_share'}" for a, b in lv.columns]
    C = C.merge(lv.reset_index().rename(columns={"strategy": "definition"}), on=["definition", "timeframe"], how="left")
    # 5-year stage-1: what results.csv says vs what RESULTS_DEEPSEEK200.md says (not resolved here)
    md_stage1 = {("F1_RSI_DIV", "4h"): "X2_SL15_TP3", ("F10_M2022", "4h"): "X5_TRAIL2"}
    C["y_stage1_per_results_csv"] = np.where(C["yx5_stage1"].fillna(False), "X5_TRAIL2",
                                             np.where(C["yx2_stage1"].fillna(False), "X2_SL15_TP3", ""))
    C["y_stage1_per_results_md"] = [md_stage1.get((a, b), "") for a, b in zip(C["definition"], C["timeframe"])]
    C["testable"] = (C["rp_traded"] >= 10) & (C["rp_G"] >= 8)
    m = C["testable"] & C["rp_p_gt0"].notna()
    C.loc[m, "bh_q_gt0_testable"] = bh(C.loc[m, "rp_p_gt0"].to_numpy())
    C.loc[m, "bh_q_lt0_testable"] = bh(C.loc[m, "rp_p_lt0"].to_numpy())
    C["n_testable_cells"] = int(m.sum())
    C["y_tf_median_mean12"] = C.groupby("timeframe")["y_best_mean12_pct"].transform("median")
    C["y_tf_q33_mean12"] = C.groupby("timeframe")["y_best_mean12_pct"].transform(lambda s: s.quantile(1 / 3))

    grades, why, keep = [], [], []
    for r in C.itertuples(index=False):
        rep = MERGE.get(r.definition)
        ss = SAME_STREAM.get((r.definition, r.timeframe))
        kept_as = f"{rep}@{r.timeframe}" if rep else (ss or f"{r.definition}@{r.timeframe}")
        keep.append(kept_as)
        n = r.rp_traded if r.rp_traded == r.rp_traded else 0
        y_all3 = bool(r.yx5_all3_positive) or bool(r.yx2_all3_positive)
        if n < 5:
            grades.append("N")
            why.append(f"{int(n)} replayed trades (live signals {int(r.live_signals)}); 5-year best-exit net "
                       f"{r.y_best_mean12_pct:+.3f}%/trade, rank {int(r.y_rank_in_tf)}/{int(r.y_defs_in_tf)} at {r.timeframe}")
            continue
        if rep or ss:
            grades.append("X")
            why.append(f"merged into {kept_as}")
            continue
        if (r.testable and r.bh_q_lt0_testable <= 0.10) or (r.rp_mean_R < 0 and r.y_best_mean12_pct <= r.y_tf_q33_mean12):
            grades.append("D")
            if r.testable and r.bh_q_lt0_testable <= 0.10:
                why.append(f"significantly negative: replay mean R {r.rp_mean_R:+.2f} (n {int(n)}, BH q(mean<0) "
                           f"{r.bh_q_lt0_testable:.3f}); 5-year {r.y_best_mean12_pct:+.3f}%/trade")
            else:
                why.append(f"replay mean R {r.rp_mean_R:+.2f} (n {int(n)}) and 5-year {r.y_best_mean12_pct:+.3f}%/trade in the "
                           f"worst third of its tf (<= {r.y_tf_q33_mean12:+.3f})")
            continue
        if (r.testable and r.bh_q_gt0_testable <= 0.10 and r.rp_lo > 0 and r.rp_lo_4h > 0
                and r.rp_side_balanced_R > 0 and y_all3):
            grades.append("A")
            why.append("all A conditions met")
            continue
        if (r.testable and r.rp_mean_R > 0 and r.rp_side_balanced_R > 0 and r.rp_mean_R_ex_best > 0
                and r.rp_mean_R_vs_peers > 0 and r.y_best_mean12_pct >= r.y_tf_median_mean12):
            grades.append("W")
            why.append(f"replay +{r.rp_mean_R:.2f}R (n {int(n)}, CI {r.rp_lo:+.2f}..{r.rp_hi:+.2f}, BH q {r.bh_q_gt0_testable:.2f}); "
                       f"side-balanced {r.rp_side_balanced_R:+.2f}; vs peers {r.rp_mean_R_vs_peers:+.2f}; 5-year "
                       f"{r.y_best_mean12_pct:+.3f}%/trade (all periods negative: {not y_all3})")
            continue
        grades.append("C")
        fails = []
        if not r.testable:
            fails.append(f"not testable (n {int(n)}, clusters {int(r.rp_G) if r.rp_G == r.rp_G else 0})")
        if not r.rp_mean_R > 0:
            fails.append(f"replay mean R {r.rp_mean_R:+.2f}")
        if r.rp_mean_R > 0 and not r.rp_side_balanced_R > 0:
            fails.append(f"side-balanced R {r.rp_side_balanced_R:+.2f}")
        if r.rp_mean_R > 0 and not r.rp_mean_R_ex_best > 0:
            fails.append(f"without best trade {r.rp_mean_R_ex_best:+.2f}")
        if r.rp_mean_R > 0 and not r.rp_mean_R_vs_peers > 0:
            fails.append(f"vs peers {r.rp_mean_R_vs_peers:+.2f}")
        if not r.y_best_mean12_pct >= r.y_tf_median_mean12:
            fails.append(f"5-year {r.y_best_mean12_pct:+.3f}% below tf median {r.y_tf_median_mean12:+.3f}")
        why.append("; ".join(fails))
    C["grade"] = grades
    C["grade_reason"] = why
    C["kept_as"] = keep
    C["ai_entry_tf"] = C["timeframe"].isin(["15m", "30m"])
    lead = ["family", "definition", "timeframe", "grade", "grade_reason", "kept_as", "ai_entry_tf", "live_signals_per_day",
            "acct_n", "acct_mean_R", "acct_pnl_sum", "rp_traded", "rp_mean_R", "rp_lo", "rp_hi", "rp_G", "bh_q_gt0_testable",
            "bh_q_lt0_testable", "rp_side_balanced_R", "rp_mean_R_vs_peers", "rp_mean_R_ex_best", "rp_mean_gross_R",
            "sf_excess_R", "sf_p_better", "sf_excess_drift_neutral", "y_best_exit", "y_best_mean12_pct", "y_rank_in_tf",
            "y_any_stage1", "y_any_all3_positive"]
    C = C[lead + [c for c in C.columns if c not in lead]]
    C.to_csv(os.path.join(out_dir, "cards_deepseek.csv"), index=False)
    print(C.groupby(["timeframe", "grade"]).size().unstack(fill_value=0))
    print("testable cells", int(m.sum()), "BH q_gt0<=0.10:", int((C["bh_q_gt0_testable"] <= 0.10).sum()),
          "BH q_lt0<=0.10:", int((C["bh_q_lt0_testable"] <= 0.10).sum()))
    show = ["definition", "timeframe", "grade", "grade_reason"]
    print(C[C["grade"].isin(["A", "W", "D"])][show].to_string(index=False))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
