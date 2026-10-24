"""Exploratory family C (PLAN.md section 2): OBV trend (4) x Stoch RSI timing (2) x 5 mappings = 40 cells with exit w35x =
w35 + before the first lock, exit at the next minute's open when (a) the opposite timing signal fires on the entry tf
or (b) the cell's higher-bar trend state reads the other way at a closed higher bar (frdeep.walk3 flag). Select on SEL
(BH over the 40, q = 0.10; none -> top 3 by t), read CONF once, then PRE / YTD / FWD / FIVE. The w35 result on the same
rows is shown for the paired comparison. Writes tierc_sel.csv, tierc_all.csv.

    python3 tierc.py
"""
import oscore as O
from oscore import *
from frdeep import walk3
from scipy.stats import norm

CELLS = [(tf, htf, T, Ot) for (tf, htf) in O.MAPS for T in O.OBV_TRENDS for Ot in O.SRSI]


def coin_work(coin):
    Z = O.load(coin)
    g = grid(coin)
    n = g["n"]
    cumf = np.cumsum(g["fund"])
    res = {}
    for (tf, htf, T, Ot) in CELLS:
        pre = f"{tf}_"
        e = Z[pre + "e"]
        sig = Z[pre + "sig_" + Ot]
        st = Z[f"{pre}st_{htf}_{T}"]
        for s in (1, -1):
            m = (sig == s) & (st == s) & (e < n)
            es = e[m].astype(np.int64)
            flag = np.zeros(n + 1, bool)
            fm = ((sig == -s) | (st == -s)) & (e < n)
            flag[e[fm]] = True
            a = walk3(g["o"], g["h"], g["l"], g["c"], cumf, es, s, 35.0, COST, FL, STEP, GAP, -0.50, 9.0, 0.01, 0, flag, True,
                      g["c"], g["o"], 0.0, n)
            lab = "L" if s > 0 else "S"
            res[(tf, htf, T, Ot, s)] = (es, a[0], a[1], a[2], Z[pre + "day"][m], Z[f"{pre}w35_{lab}_r"][m],
                                        Z[f"{pre}w35_{lab}_w"][m])
    drop(coin)
    return coin, res


if __name__ == "__main__":
    from multiprocessing import get_context
    with get_context("fork").Pool(3) as pool:
        RES = dict(pool.imap_unordered(coin_work, COINS))
    recs = []
    for (tf, htf, T, Ot) in CELLS:
        for per in ("SEL", "CONF", "PRE", "YTD", "FWD", "FIVE"):
            a_, b_ = O.P[per]
            xs, ws, days, why = [], [], [], []
            for coin in COINS:
                for s in (1, -1):
                    es, r, k, w, day, r35, w35 = RES[coin][(tf, htf, T, Ot, s)]
                    t = T0 + es * MIN
                    m = (t >= a_) & (t < b_) & (w != 3) & (w35 != 3) & np.isfinite(r35)
                    xs.append(35.0 * r[m])
                    ws.append(35.0 * r35[m].astype(float))
                    days.append(day[m])
                    why.append(w[m])
            x, x35, d, wy = (np.concatenate(v) for v in (xs, ws, days, why))
            n, mu, se, tt = O.cl_stats(x, d)
            _, mud, _, td = O.cl_stats(x - x35, d)
            recs.append({"cell": f"{T}@{htf}>{Ot}@{tf}|w35x", "period": per, "n": n, "mean_roe": mu, "t_abs": tt,
                         "p_abs": float(norm.sf(tt)) if np.isfinite(tt) else 1.0, "mean_w35_same": float(x35.mean()) if n else np.nan,
                         "mean_x_minus_w35": mud, "t_x_minus_w35": td, "early_exit_share": float((wy == 5).mean()) if n else np.nan,
                         "win": float((x > 0).mean()) if n else np.nan})
    R = pd.DataFrame(recs)
    S = R[R.period == "SEL"].copy()
    S["q_abs"] = O.bh(np.where(S.n >= 200, S.p_abs, 1.0))
    el = S[(S.n >= 200) & (S.mean_roe > 0) & (S.q_abs <= 0.10)].sort_values("t_abs", ascending=False)
    picks = el.cell.tolist() if len(el) else S[S.n >= 200].sort_values("t_abs", ascending=False).head(3).cell.tolist()
    S["picked"] = S.cell.isin(picks)
    S["pick_kind"] = "BH_pass" if len(el) else "best_not_significant"
    S.to_csv("tierc_sel.csv", index=False)
    C = R[(R.period == "CONF") & R.cell.isin(picks)].copy()
    C["p_holm"] = O.holm(C.p_abs.to_numpy())
    C["confirmed"] = (C.mean_roe > 0) & (C.p_holm < 0.05)
    R.to_csv("tierc_all.csv", index=False)
    pd.set_option("display.width", 220)
    print("SEL: positive", int((S.mean_roe > 0).sum()), "of", len(S), "BH pass", len(el))
    print(S.sort_values("t_abs", ascending=False).head(5)[["cell", "n", "mean_roe", "t_abs", "q_abs", "mean_w35_same",
                                                           "mean_x_minus_w35", "early_exit_share"]].round(4).to_string())
    print("CONF (picked, one read):")
    print(C[["cell", "n", "mean_roe", "t_abs", "p_holm", "confirmed", "mean_w35_same", "mean_x_minus_w35"]].round(4).to_string())
    print(R.groupby("period")[["mean_roe", "mean_w35_same", "mean_x_minus_w35", "early_exit_share", "win"]].mean().round(4))
