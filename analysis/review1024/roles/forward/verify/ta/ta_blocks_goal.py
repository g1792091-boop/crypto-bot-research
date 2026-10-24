"""Verifier: P4 with the live bot's own entry blocks (no_weekend / macro / US open = blk != 0), goal path at 40 %."""
import sys, os, json
sys.path.insert(0, "/home/user/crypto-bot-research/analysis/review1024/roles/forward")
from fw_lib import *  # noqa
from fw_combo import add_roe, goal

S = add_roe(load("sig"))
mem = json.load(open(os.path.join(REPO, "deploy", "combo.trend.json")))["members"]
mm = np.zeros(len(S), bool)
for it in mem:
    mm |= (S.name.to_numpy() == it["strategy"]) & (S.tf.to_numpy() == it["tf"])
X = S[mm & (S.tj_why_1022.to_numpy() == "")].copy()
X["prio"] = X.coin.astype(int) * 10 + X.tf.map({t: i for i, t in enumerate(TFS)}).astype(int)
for v in ("a2", "w35"):
    for blocks in (False, True):
        for per in ("all", "H2", "H1"):
            a, b = PERIOD[per]
            Y = X[(X.t >= a) & (X.t < b) & (X[f"{v}_why"] != 3)]
            if blocks:
                Y = Y[Y.blk == 0]
            Y = Y.reset_index(drop=True)
            T = Y[RD.one_position(Y, v, priority="prio")]
            A = RD.account(T, v, margin=0.4, start=a, end=b)
            G = goal(T, v, 0.4, (a, b)) if per != "H1" else {}
            G2 = goal(T, v, 0.4, (a, b), seed=11) if per != "H1" else {}
            print(v, "blocks" if blocks else "noblk", per, A["n"], round(A["mean_roe"], 4), round(A["win"], 3),
                  round(A["final_x"], 3), round(A["max_dd"], 3),
                  {k: round(x, 4) for k, x in G.items() if k in ("p_x6", "p_lose50_first", "p_lose90_first", "median_x")},
                  "seed11 p_x6", round(G2.get("p_x6", np.nan), 4))
