"""Follow-ups on fy_htf.py (5-year HTF agreement):
 (1) per-strategy cells again with a minimum of 30 signals in BOTH the agree and the against group in IS (the
     first pass let groups of 1-2 signals through, whose clustered t-values are meaningless); BH over the cells
     that pass, then the CF value of each BH survivor.
 (2) an explicitly exploratory "all HTF evidence" score per signal: sum of the agree(+1)/against(-1) states of
     mkt_regime_4h, mkt_ema_4h, mkt_ema_1h, same_sig_1h, same_sig_4h (range -5..+5); mean R by score bucket,
     IS and CF, 15m and 30m. Shows the best case of an 'agree with 1h/4h' filter.

    python3 -I fy_htf_extra.py <work_dir>
"""
import site
import sys
from math import erf, sqrt

sys.dont_write_bytecode = True
sys.path.append(site.getusersitepackages())
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

W = sys.argv[1]


def p2(t):
    return 2 * (1 - 0.5 * (1 + erf(abs(t) / sqrt(2)))) if t == t else np.nan


def cl_mean(x, cl):
    m = x.mean()
    s = pd.Series(x - m).groupby(cl).sum().to_numpy()
    G = len(s)
    se = np.sqrt(G / (G - 1) * (s ** 2).sum()) / len(x) if G > 2 else np.nan
    return m, se


def main():
    S = pd.read_csv(f"{W}/fy_htf_by_strategy.csv")
    ok = (S["is_n_agree"] >= 30) & (S["is_n_against"] >= 30) & S["is_t"].notna()
    T = S[ok].copy()
    p = T["is_t"].map(p2).to_numpy()
    o = np.argsort(p)
    q = np.empty_like(p)
    q[o] = np.minimum.accumulate((p[o] * len(p) / np.arange(1, len(p) + 1))[::-1])[::-1]
    T["is_bh_q_min30"] = np.minimum(q, 1)
    T.to_csv(f"{W}/fy_htf_by_strategy_min30.csv", index=False)
    sv = T[T["is_bh_q_min30"] < 0.05]
    pd.set_option("display.width", 250)
    print("cells with >= 30 agree and >= 30 against in IS:", len(T), " BH survivors:", len(sv))
    print(sv[["strategy", "ltf", "def", "is_aa", "is_t", "is_n_agree", "is_n_against", "cf_aa", "cf_t", "cf_n_agree",
              "cf_n_against", "is_mean_R_agree", "cf_mean_R_agree", "cf_mean_R_all", "is_bh_q_min30"]].round(3).to_string())
    for d in sorted(T["def"].unique()):
        x = T[(T["def"] == d) & T["cf_aa"].notna()]
        if len(x) > 5:
            print(f"{d}: cells {len(x)}, IS>0 {int((x.is_aa > 0).sum())}, CF>0 {int((x.cf_aa > 0).sum())}, "
                  f"IS-CF corr {np.corrcoef(x.is_aa, x.cf_aa)[0, 1]:.3f}")

    L = pd.read_pickle(f"{W}/fy_ltf_features.pkl")
    comps = ["mkt_regime_4h", "mkt_ema_4h", "mkt_ema_1h", "same_sig_1h", "same_sig_4h"]
    L["htf_score"] = L[comps].sum(axis=1)
    L["bucket"] = pd.cut(L["htf_score"], [-6, -3, -1, 0, 2, 5], labels=["<=-3", "-2..-1", "0", "+1..+2", ">=+3"])
    rows = []
    for ltf in ("15m", "30m"):
        for w, wl in ((0, "IS"), (1, "CF")):
            base = L[(L["tf"] == ltf) & (L["win"] == w)]
            for b, g in base.groupby("bucket", observed=True):
                m, se = cl_mean(g["R"].to_numpy(float), g["day"].to_numpy())
                rows.append({"ltf": ltf, "window": wl, "bucket": b, "n": len(g), "share": len(g) / len(base),
                             "mean_R": m, "se": se, "win_pct": 100 * (g["roe"] > 0).mean(),
                             "long_share": (g["side"] > 0).mean()})
    B = pd.DataFrame(rows)
    B.to_csv(f"{W}/fy_htf_score_buckets.csv", index=False)
    print(B.round(4).to_string())


if __name__ == "__main__":
    main()
