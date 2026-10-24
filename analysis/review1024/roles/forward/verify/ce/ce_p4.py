"""Adversarial check (lens: costs, executability, overlap) of the claim: P4 = trend bot 18 members (default numbers)
+ full 10-22 checks, one position, a2 exits (2 ATR, 30x, ladder) is +2.16 %/trade over 10/06-10/24 (49 trades).

1. reproduce P4 independently (own member mask, own one-position loop) from the cached signal table
2. re-walk every P4 candidate with frloss.walk2 at 1x / 1.5x / 2x / 3x the round-trip cost (ladder levels move too)
3. liquidation realism: 30x isolated, maintenance margin 0.5 % / 1 % -> a 2 ATR stop beyond the liquidation price is
   (a) liquidated at -100 % on the path, (b) refused (combo stop mode "atr"), (c) pulled in (atr_fit)
4. the live bot's own leverage (BTC 40x) and its entry blocks (KST weekend, macro +-30, NYSE open +-30)
5. hold time (funding exposure) and a funding stress
Run from this folder without -I:  python3 ce_p4.py"""
import os, sys, json
sys.path.insert(0, "/home/user/crypto-bot-research/analysis/review1024/roles/forward")
from fw_lib import *  # noqa
from fw_combo import add_roe, goal
from frloss import walk2

OUTJ = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ce_p4.json")
TFI = {t: i for i, t in enumerate(TFS)}


def onepos(Y, kcol):
    """own one-position loop: order by entry minute, then coin, then tf (= prespec prio coin*10+tf)."""
    Y = Y.copy()
    Y["prio"] = Y.coin.astype(int) * 10 + Y.tf.map(TFI).astype(int)
    Y = Y.sort_values(["e", "prio"]).reset_index(drop=True)
    took = np.zeros(len(Y), bool)
    busy = -1
    for i, (e, k) in enumerate(zip(Y.e.to_numpy(np.int64), Y[kcol].to_numpy(np.int64))):
        if k < 0:
            continue
        if e > busy:
            took[i] = True
            busy = e + k
    return Y[took]


def summ(T, rcol, a=None, b=None):
    x = np.maximum(T[rcol].to_numpy(float), -1.0)
    if not len(x):
        return {"n": 0}
    eq = np.cumprod(1 + 0.4 * x)
    pk = np.maximum.accumulate(np.r_[1.0, eq])[1:]
    out = {"n": int(len(x)), "mean": round(float(x.mean()), 5), "win": round(float((x > 0).mean()), 4),
           "final_x40": round(float(eq[-1]), 4), "maxdd40": round(float((1 - eq / pk).max()), 4),
           "worst": round(float(x.min()), 4), "n_le_-0.9": int((x <= -0.9).sum())}
    return out


def main():
    S = add_roe(load("sig"))
    mem = json.load(open(os.path.join(REPO, "deploy", "combo.trend.json")))["members"]
    mm = np.zeros(len(S), bool)
    for it in mem:
        mm |= (S.name.to_numpy() == it["strategy"]) & (S.tf.to_numpy() == it["tf"])
    P = S[mm & (S.tj_why_1022.to_numpy() == "")].copy().reset_index(drop=True)
    res = {"members": len(mem), "candidates": len(P)}
    a, b = PERIOD["all"]
    P = P[(P.t >= a) & (P.t < b)].reset_index(drop=True)
    # ---------------- 1. reproduce
    base = P[P.a2_why != 3]
    rep = {}
    for per in ("all", "H1", "H2"):
        pa, pb = PERIOD[per]
        Y = base[(base.t >= pa) & (base.t < pb)]
        T = onepos(Y, "a2_k")
        rep[per] = summ(T, "a2_roe")
        Yo = P[(P.t >= pa) & (P.t < pb) & (P.a2_opp_why != 3)]
        rep[per + "_coinflip"] = summ(onepos(Yo, "a2_opp_k"), "a2_opp_roe")
        Yw = P[(P.t >= pa) & (P.t < pb) & (P.w35_why != 3)]
        rep[per + "_w35"] = summ(onepos(Yw, "w35_k"), "w35_roe")
    res["reproduce"] = rep
    T0all = onepos(base, "a2_k")
    res["taken_hold_min"] = {"mean": float(T0all.a2_k.mean()), "median": float(T0all.a2_k.median()),
                             "max": int(T0all.a2_k.max()), "sum_hours": float(T0all.a2_k.sum() / 60)}
    res["taken_by_tf"] = T0all.groupby("tf").a2_roe.agg(["count", "mean"]).round(4).reset_index().to_dict("records")
    res["taken_by_side"] = T0all.groupby("side").a2_roe.agg(["count", "mean"]).round(4).reset_index().to_dict("records")
    res["taken_by_coin"] = T0all.groupby("coin").a2_roe.agg(["count", "mean"]).round(4).reset_index().to_dict("records")
    res["taken_blk"] = T0all.blk.value_counts().to_dict()
    # ---------------- 2-5 re-walks
    rows = []
    walked = {}
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
            j = e // TF_MIN[tf] - 1
            atr = G[f"atr14_{tf}"][j]
            atrd = 2.0 * atr / o[e]
            for sdn, sg in (("", 1), ("_opp", -1)):
                side = Q.side.to_numpy() * sg
                for s in (1, -1):
                    q = side == s
                    if not q.any():
                        continue
                    es = np.ascontiguousarray(e[q])
                    ad = np.ascontiguousarray(atrd[q])
                    for lev_lab, lev in (("30x", 30.0), ("live", 40.0 if coin == "BTCUSDT" else 30.0)):
                        for cm in (1.0, 1.5, 2.0, 3.0):
                            cost = COST * cm
                            r, k, w, mae, mfe = walk2(o, h, l, c, cumf, es, s, lev, cost, FL, STEP, GAP, ad, -1.0, n)
                            key = (lev_lab, cm, "nocheck")
                            walked.setdefault((key, sdn), []).append(pd.DataFrame({"idx": Q.index[q], "r": r, "k": k,
                                                                                     "why": w, "lev": lev, "atrd": ad}))
                            for mmr in (0.005, 0.01):
                                liqd = 1.0 / lev - mmr
                                rs = -1.0 + lev * (mmr - cost)
                                r2, k2, w2, _, _ = walk2(o, h, l, c, cumf, es, s, lev, cost, FL, STEP, GAP, ad, rs, n)
                                beyond = ad > liqd
                                rl = r2.copy()
                                rl[beyond & (w2 == 0)] = -1.0 / lev       # liquidated: whole margin lost
                                walked.setdefault(((lev_lab, cm, f"liq{mmr}"), sdn), []).append(
                                    pd.DataFrame({"idx": Q.index[q], "r": rl, "k": k2, "why": w2, "lev": lev,
                                                  "atrd": ad, "beyond": beyond}))
                                # atr_fit: stop pulled in to the liquidation level, ROE as walked (about -0.89)
                                walked.setdefault(((lev_lab, cm, f"fit{mmr}"), sdn), []).append(
                                    pd.DataFrame({"idx": Q.index[q], "r": r2, "k": k2, "why": w2, "lev": lev,
                                                  "atrd": ad, "beyond": beyond}))
                                # refuse: drop entries whose 2 ATR stop is beyond the liquidation price (mode "atr")
                                walked.setdefault(((lev_lab, cm, f"refuse{mmr}"), sdn), []).append(
                                    pd.DataFrame({"idx": Q.index[q], "r": r, "k": np.where(beyond, -1, k), "why": w,
                                                  "lev": lev, "atrd": ad, "beyond": beyond}))
        drop(coin)
    # sanity: 30x, 1x cost, nocheck == a2_r
    W = pd.concat(walked[(("30x", 1.0, "nocheck"), "")]).set_index("idx").sort_index()
    res["sanity_max_abs_diff_r"] = float(np.nanmax(np.abs(W.r.to_numpy() - P.loc[W.index, "a2_r"].to_numpy())))
    res["sanity_k_equal"] = bool((W.k.to_numpy() == P.loc[W.index, "a2_k"].to_numpy()).all())
    Bn = W.loc[P.index]
    res["share_2atr_beyond_liq_30x_mmr0.5"] = float((Bn.atrd > 1 / 30 - 0.005).mean())
    for (key, sdn), parts in walked.items():
        W = pd.concat(parts).set_index("idx").sort_index()
        X = P.copy()
        X["rr"] = W.r.reindex(X.index).to_numpy()
        X["kk"] = W.k.reindex(X.index).to_numpy()
        X["ww"] = W.why.reindex(X.index).to_numpy()
        X["roe_"] = np.maximum(W.lev.reindex(X.index).to_numpy() * X.rr, -1.0)
        for blocks in (False, True):
            for per in ("all", "H1", "H2"):
                pa, pb = PERIOD[per]
                Y = X[(X.t >= pa) & (X.t < pb) & (X.ww != 3)]
                if blocks:
                    Y = Y[Y.blk == 0]
                T = onepos(Y, "kk")
                d = summ(T, "roe_")
                row = {"lev": key[0], "cost_x": key[1], "check": key[2], "side": "opp" if sdn else "signal",
                       "blocks": blocks, "period": per, **d}
                if per == "H2" and not sdn and key[2] in ("nocheck", "liq0.005") and key[1] in (1.0, 2.0):
                    T2 = T.copy()
                    T2["x_roe"] = T2.roe_
                    gg = goal(T2, "x", 0.4, PERIOD["H2"])
                    row.update({k: round(v, 4) if isinstance(v, float) else v for k, v in gg.items()})
                rows.append(row)
    R = pd.DataFrame(rows)
    R.to_csv(os.path.join(os.path.dirname(OUTJ), "ce_p4_variants.csv"), index=False, float_format="%.5g")
    json.dump(res, open(OUTJ, "w"), indent=1, default=str)
    print(json.dumps(res, indent=1, default=str))
    show = R[(R.side == "signal") & (R.period.isin(["all", "H2"]))]
    print(show[["lev", "cost_x", "check", "blocks", "period", "n", "mean", "win", "final_x40", "maxdd40", "n_le_-0.9"]
               + [c for c in ("p_x6", "p_lose50_first", "p_lose90_first", "median_x") if c in R]].to_string())


if __name__ == "__main__":
    main()
