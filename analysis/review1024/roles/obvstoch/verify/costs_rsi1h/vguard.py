"""Executability reads on vcell.py rows: (a) the live WOO X Pro executor's guard (paperbot/executor.py _liq_ok:
refuse an entry unless 1/lev - MMR > stop distance + 0.2 %), MMR 0.5 % all coins or 0.5 % BTC/ETH and 1 % others;
(b) break-even extra round-trip cost; (c) per-period sign table across variants. Writes vguard.csv, vguard.json.
    python3 vguard.py"""
import os
import sys
import json

sys.path.insert(0, "/home/user/crypto-bot-research/analysis/review1024/roles/data")
from common import *  # noqa
from vsum import P, clt, one_pos, acct, LEV, PB  # noqa  (vsum re-runs its summary on import; cheap)

HERE = os.path.dirname(os.path.abspath(__file__))
A = pd.read_csv(os.path.join(HERE, "rows_all.csv.gz"))
A["roe"] = LEV * A.r
A["day"] = A.t // DAY
recs = []
for vn in ("base", "cost2"):
    V = A[(A.variant == vn) & (A.why != 3) & (A.why_opp != 3)]
    for guard, mm in (("none", None), ("mmr0.5", {}), ("mmr0.5_1", {"BTCUSDT": 0.005, "ETHUSDT": 0.005})):
        if mm is None:
            G = V
        else:
            mmr = V.coin.map(mm).fillna(0.005 if guard == "mmr0.5" else 0.01)
            G = V[(1 / LEV - mmr) > V.stopd + 0.002]
        for per, (a, b) in P.items():
            X = G[(G.t >= a) & (G.t < b)]
            if not len(X):
                continue
            T = one_pos(X)
            fx, dd = acct(T.roe.to_numpy() + LEV * PB)
            recs.append({"variant": vn, "guard": guard, "period": per, "n": len(X), "kept_share":
                         len(X) / max(1, len(V[(V.t >= a) & (V.t < b)])), "mean": X.roe.mean(),
                         "mean_pb": X.roe.mean() + LEV * PB, "t_pb": clt(X.roe.to_numpy() + LEV * PB, X.day.to_numpy()),
                         "op_n": len(T), "op_mean_pb": T.roe.mean() + LEV * PB, "op_x_pb_m40": fx, "op_dd_pb_m40": dd})
R = pd.DataFrame(recs)
R.to_csv(os.path.join(HERE, "vguard.csv"), index=False, float_format="%.5g")
pd.set_option("display.width", 250)
print(R.round(4).to_string())
B = A[(A.variant == "base") & (A.why != 3) & (A.why_opp != 3)]
be = {}
for per in ("SEL", "CONF", "YTD", "FIVE"):
    a, b = P[per]
    X = B[(B.t >= a) & (B.t < b)]
    m_pb = X.roe.mean() + LEV * PB
    be[per] = {"mean_pb_roe": m_pb, "breakeven_extra_roundtrip_cost_pct": 100 * m_pb / LEV,
               "breakeven_extra_per_side_pct": 100 * m_pb / LEV / 2}
print(json.dumps(be, indent=1))
json.dump(be, open(os.path.join(HERE, "vguard.json"), "w"), indent=1)
