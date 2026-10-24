"""Verifier stage C: p-values of the real 1h-judge effects against the circular-shift null (A) and the direction-only
null (B) from v_perm.py runs (/dev/shm/claude_verify_fy/null_*.pkl).    python3 v_summary.py -> v_null_summary.csv"""
import glob
import os
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
R = pd.read_csv(os.path.join(HERE, "v_real.csv"))
N = pd.concat([pd.read_pickle(p) for p in sorted(glob.glob("/dev/shm/claude_verify_fy/null_*.pkl"))], ignore_index=True)
A = N[N.kind == "A"]
B = N[N.kind == "B"]
nsh = A["shift"].nunique()
print("shifts", nsh)
rows = []
for src in ("j_V4OF4", "j_DIR"):
    for tf in ("15m", "30m"):
        r = R[(R.src == src) & (R.tf == tf)].iloc[0]
        a = A[(A.src == src) & (A.tf == tf)]
        b = B[(B.src == src) & (B.tf == tf)]
        d = {"src": src, "tf": tf, "eff_SEL": r.eff_SEL, "eff_CONF": r.eff_CONF, "flip_SEL": r.flip_SEL,
             "flip_CONF": r.flip_CONF, "years_pos": r.years_pos, "years_flip_pos": r.years_flip_pos}
        # null A (shifted series): one-sided p
        d["A_p_effSEL"] = (a.eff_SEL >= r.eff_SEL).mean()
        d["A_p_effCONF"] = (a.eff_CONF >= r.eff_CONF).mean()
        d["A_p_both"] = ((a.eff_SEL >= r.eff_SEL) & (a.eff_CONF >= r.eff_CONF)).mean()
        d["A_p_6years"] = (a.years_pos >= 6).mean()
        d["A_p_flipSEL"] = (a.flip_SEL >= r.flip_SEL).mean()
        d["A_p_flipCONF"] = (a.flip_CONF >= r.flip_CONF).mean()
        d["A_sd_effSEL"], d["A_sd_effCONF"] = a.eff_SEL.std(), a.eff_CONF.std()
        d["A_sd_flipSEL"], d["A_sd_flipCONF"] = a.flip_SEL.std(), a.flip_CONF.std()
        # null B (agree hours kept, side from the shifted V39): what the time selection gives without direction
        d["B_mean_effSEL"], d["B_mean_effCONF"] = b.eff_SEL.mean(), b.eff_CONF.mean()
        d["B_p_effSEL"] = (b.eff_SEL >= r.eff_SEL).mean()
        d["B_p_effCONF"] = (b.eff_CONF >= r.eff_CONF).mean()
        d["B_p_6years"] = (b.years_pos >= 6).mean()
        d["B_p_flipSEL"] = (b.flip_SEL >= r.flip_SEL).mean()
        d["B_p_flipCONF"] = (b.flip_CONF >= r.flip_CONF).mean()
        rows.append(d)
# whole 1h search (every source, both tfs): max over sources of min(eff SEL, eff CONF) and of min(flip SEL, flip CONF)
for stat, f in (("min_eff", lambda q: np.minimum(q.eff_SEL, q.eff_CONF)),
                ("min_flip", lambda q: np.minimum(q.flip_SEL, q.flip_CONF)),
                ("eff_CONF", lambda q: q.eff_CONF), ("years6", lambda q: (q.years_pos >= 6).astype(float))):
    real_v4 = {tf: float(f(R[(R.src == "j_V4OF4") & (R.tf == tf)]).iloc[0]) for tf in ("15m", "30m")}
    mx = A.assign(v=f(A)).groupby(["shift", "tf"]).v.max()
    cnt6 = A.assign(v=f(A)).groupby(["shift", "tf"]).v.sum() if stat == "years6" else None
    for tf in ("15m", "30m"):
        m = mx.xs(tf, level="tf")
        rr = R[R.tf == tf]
        d = {"src": "WHOLE_1h_SEARCH", "tf": tf, "stat": stat, "real_V4OF4": real_v4[tf],
             "real_max_all_sources": float(f(rr).max()), "null_p_max_ge_V4OF4": float((m >= real_v4[tf]).mean()),
             "null_max_median": float(m.median()), "null_max_p95": float(m.quantile(0.95))}
        if stat == "years6":
            c = cnt6.xs(tf, level="tf")
            d["real_count"] = float(f(rr).sum())
            d["null_count_mean"] = float(c.mean())
            d["null_count_p95"] = float(c.quantile(0.95))
            d["null_p_count_ge_real"] = float((c >= d["real_count"]).mean())
        rows.append(d)
S = pd.DataFrame(rows)
S.to_csv(os.path.join(HERE, "v_null_summary.csv"), index=False, float_format="%.5g")
pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 40)
print(S.T.to_string())
