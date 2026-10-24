"""Month-clustered t of the one-position bot effect (filtered bot - unfiltered bot), base / woo / x2 / d1 costs, per
seed, plus the pooled and unique-entry month t (each month = one cluster).     python3 vc_bot_t.py"""
import os, sys
sys.path.insert(0, "/home/user/crypto-bot-research/analysis/review1024/roles/data")
import numpy as np
import pandas as pd
from vc_analyze import PER, bot, IND
from common import DAY

def mstats(t, x):
    m = pd.to_datetime(np.asarray(t, np.int64), unit="ms").to_period("M").astype(str)
    return pd.Series(np.asarray(x, float)).groupby(np.asarray(m)).mean()

def tstat(d):
    d = d.dropna()
    return float(d.mean() / (d.std(ddof=1) / np.sqrt(len(d)))), len(d), float((d > 0).mean())

rows = []
for tf in ("15m", "30m"):
    S = pd.read_pickle(os.path.join(IND, f"{tf}.pkl"))
    sd = S.side.to_numpy()
    S["f1"] = S.v4_1h.to_numpy() == sd
    S["f2"] = S.f1.to_numpy() & (S.dir_4h.to_numpy() == sd)
    for per in ("SEL", "CONF"):
        lo, hi = PER[per]
        P = S[(S.t >= lo) & (S.t < hi)]
        for v, dl in (("base", 0), ("woo", 0), ("x2", 0), ("d1", 1)):
            Q = P[(P[f"{v}_why"] != 3) & (P[f"{v}_opp_why"] != 3) & (P[f"{v}_k"] >= 0)]
            for f in ("f1", "f2"):
                # pooled and unique month t
                ma = mstats(Q.t, Q[f"{v}_roe"]); mf = mstats(Q.t[Q[f]], Q[f"{v}_roe"][Q[f]])
                tp = tstat(mf - ma)
                U = Q.drop_duplicates(["coin", "e", "side"])
                ua = mstats(U.t, U[f"{v}_roe"]); uf = mstats(U.t[U[f]], U[f"{v}_roe"][U[f]])
                tu = tstat(uf - ua)
                for seed in (1, 2, 3):
                    Ta = Q[bot(Q, v, dl, seed)]
                    Fq = Q[Q[f]]
                    Tf = Fq[bot(Fq, v, dl, seed)]
                    d = mstats(Tf.t, Tf[f"{v}_roe"]) - mstats(Ta.t, Ta[f"{v}_roe"])
                    tb = tstat(d)
                    rows.append({"tf": tf, "per": per, "var": v, "filter": f, "seed": seed,
                                 "pool_eff": tp[0] * 0 + float((mf - ma).mean()), "pool_t": tp[0], "uni_t": tu[0],
                                 "bot_all": Ta[f"{v}_roe"].mean(), "bot_f": Tf[f"{v}_roe"].mean(),
                                 "bot_eff": Tf[f"{v}_roe"].mean() - Ta[f"{v}_roe"].mean(), "bot_t": tb[0],
                                 "months": tb[1], "months_pos": tb[2], "n_all": len(Ta), "n_f": len(Tf)})
                r = rows[-1]
                print(tf, per, v, f, "pool t %.2f uni t %.2f | bot eff %.2f t %.2f months+ %.0f%%" %
                      (tp[0], tu[0], 100 * r["bot_eff"], r["bot_t"], 100 * r["months_pos"]), flush=True)
pd.DataFrame(rows).to_csv("vc_bot_t.csv", index=False, float_format="%.5g")
