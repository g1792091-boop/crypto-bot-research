"""vco (cost/executability/overlap verifier) step 1: recompute gross_vs_cost, fwd_trend_luck, one-position overlap
from the trade files only. Run: python3 vco_check1.py <livebot folder>"""
import os, sys
import numpy as np, pandas as pd
LB = sys.argv[1]
COST = 2 * (0.00042 + 0.0002); PAYBACK = 2 * 0.9 * 0.00042
MS = lambda s: int(pd.Timestamp(s, tz="UTC").value // 10**6)
P = {"select": (MS("2020-03-01"), MS("2024-01-01")), "conf+late": (MS("2024-01-01"), MS("2026-10-05 15:00")),
     "fwd": (MS("2026-10-05 15:00"), MS("2026-10-24 15:00"))}
rows, luck, ov = [], [], []
for v in ["B0","B1","B2","B3","B4","B5","B6","B7","B8","B9","B10","W0","W3"]:
    T = pd.read_csv(os.path.join(LB, "trades", f"trades_{v}.csv.gz"))
    lev = np.where(T.coin == 0, 40.0, 30.0)
    T["cost"] = lev * COST; T["pb"] = lev * PAYBACK
    # funding part of each trade (needs grid; skip) -> gross = net + cost
    # overlap: one position across coins: next entry minute index is per coin grid; grids share T0 so e is comparable
    S = T.sort_values("e")
    ex = (S.e + S.tb_k).to_numpy(); en = S.e.to_numpy()
    nov = int((en[1:] < ex[:-1]).sum())
    nov_eq = int((en[1:] == ex[:-1]).sum())
    ov.append({"v": v, "n": len(S), "overlap_next_before_exit": nov, "next_at_exit_minute": nov_eq,
               "open_at_end": int((S.tb_why == 3).sum())})
    for pn, (a, b) in P.items():
        Q = T[(T.t >= a) & (T.t < b)]
        rows.append({"v": v, "p": pn, "n": len(Q), "net": 100*Q.tb_roe.mean(), "gross": 100*(Q.tb_roe + Q.cost).mean(),
                     "cost": 100*Q.cost.mean(), "payback": 100*Q.pb.mean(), "net_pb": 100*(Q.tb_roe+Q.pb).mean(),
                     "win": 100*(Q.tb_roe > 0).mean(), "opp": 100*Q.tb_opp_roe.mean(),
                     "btc_share": 100*(Q.coin == 0).mean(), "sd": 100*Q.tb_roe.std()})
        if pn == "fwd":
            sh = np.where(Q.side < 0, Q.tb_roe, Q.tb_opp_roe); lo = np.where(Q.side > 0, Q.tb_roe, Q.tb_opp_roe)
            ss = (Q.side < 0).mean()
            luck.append({"v": v, "n": len(Q), "short_share": ss, "own": 100*Q.tb_roe.mean(), "opp": 100*Q.tb_opp_roe.mean(),
                         "always_short": 100*sh.mean(), "always_long": 100*lo.mean(),
                         "same_tilt_random": 100*(ss*sh.mean() + (1-ss)*lo.mean()),
                         "se_own": 100*Q.tb_roe.std()/np.sqrt(len(Q))})
pd.set_option("display.width", 250)
R = pd.DataFrame(rows); print(R.round(3).to_string(index=False))
print(pd.DataFrame(luck).round(3).to_string(index=False))
print(pd.DataFrame(ov).to_string(index=False))
R.to_csv(os.path.join(LB, "verify", "vco_gross.csv"), index=False, float_format="%.4f")
