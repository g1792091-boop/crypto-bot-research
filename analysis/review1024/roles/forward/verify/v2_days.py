"""Verifier 2: where does the forward with-vs-against gap come from?  Per UTC day x side table, between-day vs
within-day decomposition (exact), and the rule bot's real house trades split within side (Simpson check) with a
day-cluster bootstrap.  Run from this folder without -I: python3 v2_days.py"""
import sys
import os
sys.path.insert(0, "/home/user/crypto-bot-research/analysis/review1024/roles/forward")
from fw_lib import *  # noqa
import json

HERE = os.path.dirname(os.path.abspath(__file__))
S = load("sig")
S = S[S.role != "trend"].reset_index(drop=True)
side = S.side.to_numpy()
tf = S.tf.to_numpy()
r = roe(S, "w35")
al = np.zeros(len(S), np.int8)
for t_, h_ in AUTO.items():
    m = tf == t_
    al[m] = (state(S, "Jdir", h_) * side)[m]
X = pd.DataFrame({"day": S.day.to_numpy(), "side": side, "al": al, "r": r, "coin": S.coin.to_numpy()})
X = X[np.isfinite(X.r) & (X.al != 0)]
T = X.groupby(["day", "side", "al"]).r.agg(["count", "mean", "sum"]).unstack("al")
T.columns = [f"{a}_{'w' if b == 1 else 'g'}" for a, b in T.columns]
T = T.fillna(0).reset_index()
T["date"] = pd.to_datetime(T.day * 86400, unit="s").dt.strftime("%m-%d")
pd.set_option("display.width", 200)
print(T[["date", "side", "count_w", "mean_w", "count_g", "mean_g"]].round(3).to_string())
# day-level contribution: total sum with / n_with - total sum against / n_against
NW, NG = T.count_w.sum(), T.count_g.sum()
T["contrib"] = T.sum_w / NW - T.sum_g / NG
print("pooled gap", round(100 * T.contrib.sum(), 2))
print("top contributions", T.sort_values("contrib", key=abs, ascending=False)[["date", "side", "count_w", "count_g", "mean_w", "mean_g", "contrib"]].head(10).round(3).to_string())
# exact decomposition: gap = sum_d (pw_d * mw_d - pg_d * mg_d), split into within (common weights) + between (weights)
# use per (day, side) cell: within = sum_c qc (mw_c - mg_c) with qc = (nw_c+ng_c)/N over cells having both;
cells = T[(T.count_w > 0) & (T.count_g > 0)]
q = (cells.count_w + cells.count_g) / (cells.count_w + cells.count_g).sum()
within = float((q * (cells.mean_w - cells.mean_g)).sum())
print("within (side, day) cells weighted gap", round(100 * within, 2), "cells", len(cells), "of", len(T))
# how many (day, side) cells have with > against
print("cells with mean_w > mean_g:", int((cells.mean_w > cells.mean_g).sum()), "of", len(cells))
# sign test p
from math import comb
k, n = int((cells.mean_w > cells.mean_g).sum()), len(cells)
p_two = min(1, 2 * min(sum(comb(n, i) for i in range(0, k + 1)), sum(comb(n, i) for i in range(k, n + 1))) / 2 ** n)
print("sign test two-sided p", round(p_two, 3))

# ---------------- rule bot real trades within side
F = RD.forward("rule")
F = F[(F.taken == 1) & F.tr_roe.notna() & F.tf.isin(TFS) & (F.coin >= 0) & ~F.group.isin(["flip"])].copy()
a = np.sign(np.nan_to_num(F.tj_dir.to_numpy())) * F.side.to_numpy()
F["al"] = a
F["day"] = (F.t.to_numpy(np.int64) // DAY)
res = {}
for lab, m in (("all", np.ones(len(F), bool)), ("nontrend", F.role.to_numpy() != "trend")):
    G = F[m]
    for sd, s in (("L", 1), ("S", -1)):
        for cl, c in (("with", 1), ("against", -1), ("neutral", 0)):
            g = G[(G.side == s) & (G.al == c)]
            res[f"{lab}_{sd}_{cl}"] = {"n": len(g), "roe": float(g.tr_roe.mean()), "pnl": float(g.tr_pnl.sum()),
                                       "w35": float((35 * g.w35_r).clip(lower=-1)[g.w35_why != 3].mean())}
    pL = (G.side > 0).mean()
    gL = res[f"{lab}_L_with"]["roe"] - res[f"{lab}_L_against"]["roe"]
    gS = res[f"{lab}_S_with"]["roe"] - res[f"{lab}_S_against"]["roe"]
    w = G[G.al == 1]
    g = G[G.al == -1]
    res[f"{lab}_pooled_gap"] = float(w.tr_roe.mean() - g.tr_roe.mean())
    res[f"{lab}_side_std_gap"] = float(pL * gL + (1 - pL) * gS)
    # within (side, day) stratified with day bootstrap
    Y = G[G.al != 0].groupby(["day", "side", "al"]).tr_roe.agg(["sum", "count"]).unstack("al").dropna()
    mw = Y[("sum", 1)] / Y[("count", 1)]
    mg = Y[("sum", -1)] / Y[("count", -1)]
    wt = Y[("count", 1)] + Y[("count", -1)]
    est = float(((mw - mg) * wt).sum() / wt.sum())
    dd = Y.index.get_level_values(0).to_numpy()
    du = np.unique(dd)
    pos = {d: np.where(dd == d)[0] for d in du}
    diff, wv = (mw - mg).to_numpy(), wt.to_numpy()
    rng = np.random.default_rng(3)
    bs = []
    for _ in range(4000):
        ii = np.concatenate([pos[d] for d in rng.choice(du, len(du))])
        bs.append((diff[ii] * wv[ii]).sum() / wv[ii].sum())
    res[f"{lab}_within_side_day"] = {"gap": est, "lo": float(np.percentile(bs, 2.5)), "hi": float(np.percentile(bs, 97.5))}
    # pooled gap day bootstrap
    s_w = w.groupby("day").tr_roe.agg(["sum", "count"]).reindex(du).fillna(0)
    s_g = g.groupby("day").tr_roe.agg(["sum", "count"]).reindex(du).fillna(0)
    I = rng.integers(0, len(du), (4000, len(du)))
    bp = s_w["sum"].to_numpy()[I].sum(1) / s_w["count"].to_numpy()[I].sum(1) - \
        s_g["sum"].to_numpy()[I].sum(1) / s_g["count"].to_numpy()[I].sum(1)
    res[f"{lab}_pooled_ci"] = [float(np.percentile(bp, 2.5)), float(np.percentile(bp, 97.5))]
    # counterfactual: drop counter-trend trades -> loss removed; but what if we instead dropped the same NUMBER of
    # longs/shorts at random? expected removed loss = n_against_L * mean_L + n_against_S * mean_S
    nL_g, nS_g = res[f"{lab}_L_against"]["n"], res[f"{lab}_S_against"]["n"]
    pnlL = G[G.side > 0].tr_pnl.mean()
    pnlS = G[G.side < 0].tr_pnl.mean()
    res[f"{lab}_against_pnl"] = float(g.tr_pnl.sum())
    res[f"{lab}_random_same_sidemix_pnl"] = float(nL_g * pnlL + nS_g * pnlS)
print(json.dumps(res, indent=1))
json.dump(res, open(os.path.join(HERE, "v2_rulebot.json"), "w"), indent=1)
