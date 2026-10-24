"""Stacked alignment (principle-defined, no search): 15m / 30m entries (all entry roles) taken only when the trend
judges of several higher bars agree with the signal: 1h all four judges (V4OF4) / + 4h held 3-of-4 (DIR) / + 1d held
3-of-4 (DIR). Pooled mean net ROE per trade (w35, every signal on its own) per period, vs no filter and vs the coin-flip
twin, plus the long share.      python3 stack.py  ->  stack.csv"""
from fy_analyze import *
from build_acc import judge_cols

PERIODS_ = {"SEL": (EDGES[0], EDGES[3]), "CONF": (EDGES[3], EDGES[6]), "LATE": (EDGES[5], EDGES[8]),
            "FWD": (EDGES[7], EDGES[9])}


def states_for(S, htf, src):
    idx = RD.htf_index(S, htf)
    st = np.zeros(len(S), np.int8)
    warm = np.zeros(len(S), bool)
    for ci, coin in enumerate(COINS):
        m = (S.coin.to_numpy() == ci) & (idx >= 1)
        if not m.any():
            continue
        Z = RD._states(coin, htf)
        ii = idx[m]
        warm[m] = Z["nb"][ii] >= 300
        jc, _ = judge_cols(Z, ii)
        st[m] = jc[src]
    return st, warm


def main():
    rows = []
    for tf in ("15m", "30m"):
        parts = []
        for coin in COINS:
            S = RD.signals(roles_=ENTRY_ROLES, tfs=[tf], coins=[coin], period=(int(EDGES[0]), int(EDGES[-1])))
            S = RD.add_outcomes(S, ["w35"])
            S = S[(S.w35_why != 3) & (S.w35_opp_why != 3) & np.isfinite(S.w35_r)]
            S = S[["t", "coin", "side", "w35_roe", "w35_opp_roe", "e"]].copy()
            S["tf"] = tf
            a, wa = states_for(S, "1h", "V4OF4")
            b, wb = states_for(S, "4h", "DIR")
            c, wc = states_for(S, "1d", "DIR")
            sd = S.side.to_numpy()
            S["f1"] = a == sd
            S["f2"] = S.f1 & (b == sd)
            S["f3"] = S.f2 & (c == sd)
            S["warm"] = wa & wb & wc
            parts.append(S[S.warm])
            drop(coin)
        S = pd.concat(parts, ignore_index=True)
        for per, (lo, hi) in PERIODS_.items():
            P = S[(S.t >= lo) & (S.t < hi)]
            base = P.w35_roe.mean()
            for f, lab in (("all", "no filter"), ("f1", "1h 4/4"), ("f2", "1h 4/4 + 4h"), ("f3", "1h 4/4 + 4h + 1d")):
                Q = P if f == "all" else P[P[f]]
                rows.append({"tf": tf, "per": per, "filter": lab, "n": len(Q), "mean": Q.w35_roe.mean(),
                             "opp": Q.w35_opp_roe.mean(), "eff": Q.w35_roe.mean() - base,
                             "long_share": (Q.side > 0).mean(), "mean_pb": Q.w35_roe.mean() + 35 * PAYBACK})
        log(tf, len(S))
    R = pd.DataFrame(rows)
    R.to_csv(os.path.join(HERE, "stack.csv"), index=False, float_format="%.5g")
    print(R.round(4).to_string())


if __name__ == "__main__":
    main()
