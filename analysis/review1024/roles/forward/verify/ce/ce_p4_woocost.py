"""P4 a2 (30x, 2 ATR, ladder) one-position bot re-walked at the WOO X Pro round-trip cost MEASURED on the live
executor (11 closed trades of the trend bot, 10/20-10/23: commission 0.084 % + slippage 0.0875 % = 0.1716 % of the
entry notional = 1.384 x the study's 0.124 %), with and without TetherMax payback (90 % of the 0.042 % taker each
side = 0.0756 % round trip). Run without -I:  python3 ce_p4_woocost.py"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ce_p4 import *  # noqa


def main():
    S = add_roe(load("sig"))
    mem = json.load(open(os.path.join(REPO, "deploy", "combo.trend.json")))["members"]
    mm = np.zeros(len(S), bool)
    for it in mem:
        mm |= (S.name.to_numpy() == it["strategy"]) & (S.tf.to_numpy() == it["tf"])
    P = S[mm & (S.tj_why_1022.to_numpy() == "")].copy().reset_index(drop=True)
    a, b = PERIOD["all"]
    P = P[(P.t >= a) & (P.t < b)].reset_index(drop=True)
    costs = {"study_0.124": COST, "woo_measured_0.1716": 0.001716, "woo_measured_minus_payback": 0.001716 - PAYBACK,
             "study_minus_payback": COST - PAYBACK}
    out = {}
    parts = {k: [] for k in costs}
    for ci, coin in enumerate(COINS):
        Pc = P[P.coin == ci]
        if not len(Pc):
            continue
        g = grid(coin)
        o, h, l, c = g["o"], g["h"], g["l"], g["c"]
        cumf = np.cumsum(g["fund"])
        n = g["n"]
        G = np.load(os.path.join(OUT, "grid", f"{coin}.npz"))
        for tf in Pc.tf.unique():
            Q = Pc[Pc.tf == tf]
            e = Q.e.to_numpy(np.int64)
            atrd = 2.0 * G[f"atr14_{tf}"][e // TF_MIN[tf] - 1] / o[e]
            side = Q.side.to_numpy()
            for s in (1, -1):
                q = side == s
                if not q.any():
                    continue
                for lab, cost in costs.items():
                    r, k, w, _, _ = walk2(o, h, l, c, cumf, np.ascontiguousarray(e[q]), s, 30.0, cost, FL, STEP, GAP,
                                          np.ascontiguousarray(atrd[q]), -1.0, n)
                    parts[lab].append(pd.DataFrame({"idx": Q.index[q], "r": r, "k": k, "why": w}))
        drop(coin)
    for lab in costs:
        W = pd.concat(parts[lab]).set_index("idx").reindex(P.index)
        X = P.copy()
        X["kk"], X["ww"] = W.k.to_numpy(), W.why.to_numpy()
        X["roe_"] = np.maximum(30.0 * W.r.to_numpy(), -1.0)
        for blocks in (False, True):
            for per in ("all", "H2"):
                pa, pb = PERIOD[per]
                Y = X[(X.t >= pa) & (X.t < pb) & (X.ww != 3)]
                if blocks:
                    Y = Y[Y.blk == 0]
                T = onepos(Y, "kk")
                d = summ(T, "roe_")
                if per == "H2":
                    T2 = T.copy()
                    T2["x_roe"] = T2.roe_
                    d.update({k: round(v, 4) if isinstance(v, float) else v for k, v in goal(T2, "x", 0.4, PERIOD["H2"]).items()})
                out[f"{lab}|blocks={blocks}|{per}"] = d
    json.dump(out, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "ce_p4_woocost.json"), "w"), indent=1)
    for k, v in out.items():
        print(k, v)


if __name__ == "__main__":
    main()
