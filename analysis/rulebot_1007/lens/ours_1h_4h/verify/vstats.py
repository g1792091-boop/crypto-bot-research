"""Verifier stats on the own 5-year sims (vsim.py output).

    python3 -I vstats.py <v_tf_all.pkl> <v_5m_htf.pkl> <their fy_cells.csv> <their tf_summary_5y.csv> <out_dir>

Cluster-robust SE of a mean: se = sqrt(G/(G-1) * sum_g (sum_i (x_i - m))^2) / N, clusters = UTC day (as claimed) and,
as a robustness check, ISO week. gross_A = R + 0.0014 / (2 atr_frac + 0.0002) (the analyst's definition, funding not
added back); gross_B = price-only R (vsim gross_R: fees, slippage, funding all added back).
"""
import site
import sys
from math import erf, sqrt

sys.dont_write_bytecode = True
sys.path.append(site.getusersitepackages())
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

TF_ALL, M5, THEIR_CELLS, THEIR_TF, OUTD = sys.argv[1:6]
DAY = 86_400_000
WEEK = 7 * DAY


def cl(x, c):
    x = np.asarray(x, float)
    n = len(x)
    if n < 3:
        return np.nan, np.nan, 0
    m = x.mean()
    s = pd.Series(x - m).groupby(np.asarray(c)).sum().to_numpy()
    G = len(s)
    if G < 3:
        return m, np.nan, G
    return m, np.sqrt(G / (G - 1) * (s ** 2).sum()) / n, G


def p2(t):
    return 2 * (1 - 0.5 * (1 + erf(abs(t) / sqrt(2)))) if t == t else np.nan


def bh(p):
    p = np.asarray(p, float)
    q = np.full(len(p), np.nan)
    ok = np.isfinite(p)
    pp = p[ok]
    o = np.argsort(pp)
    r = pp[o] * len(pp) / np.arange(1, len(pp) + 1)
    r = np.minimum.accumulate(r[::-1])[::-1]
    qq = np.empty_like(pp)
    qq[o] = np.minimum(r, 1)
    q[ok] = qq
    return q


def prep(D):
    D = D.copy()
    for k in ("strategy", "tf", "coin"):
        D[k] = D[k].astype(str)
    D["day"] = D["close_ms"] // DAY
    D["week"] = (D["close_ms"] + 3 * DAY) // WEEK
    D["gross_A"] = D["R"] + 0.0014 / (2 * D["atr_frac"] + 0.0002)
    D["cost_A"] = D["gross_A"] - D["R"]
    return D


def main():
    A = prep(pd.read_pickle(TF_ALL))
    B = prep(pd.read_pickle(M5))
    out = []
    for lab, D in (("tfbars", A), ("5mbars", B)):
        Z = D[(D.lev > 0) & D.R.notna()]
        for tf, g in Z.groupby("tf"):
            for w, wl in ((None, "ALL"), (0, "IS"), (1, "CF")):
                gg = g if w is None else g[g.win == w]
                m, se, G = cl(gg.R, gg.day)
                mw, sew, Gw = cl(gg.R, gg.week)
                ga, sga, _ = cl(gg.gross_A, gg.day)
                gb, sgb, _ = cl(gg.gross_R, gg.day)
                out.append(dict(res=lab, tf=tf, window=wl, n=len(gg), mean_R=m, lo=m - 1.96 * se, hi=m + 1.96 * se,
                                se_day=se, se_week=sew, grossA=ga, grossA_lo=ga - 1.96 * sga, grossA_hi=ga + 1.96 * sga,
                                grossB=gb, grossB_lo=gb - 1.96 * sgb, grossB_hi=gb + 1.96 * sgb,
                                costA=gg.cost_A.mean(), costB=(gg.gross_R - gg.R).mean(), sd_R=gg.R.std(),
                                win=100 * (gg.roe > 0).mean()))
    T = pd.DataFrame(out)
    T.to_csv(f"{OUTD}/v_tf_summary.csv", index=False)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 40)
    print(T.round(4).to_string())
    print("THEIR tf_summary_5y:")
    print(pd.read_csv(THEIR_TF).round(4).to_string())

    # ---- per strategy x tf cells (1h / 4h), both resolutions
    span = {tf: (g.close_ms.max() - g.close_ms.min()) / DAY for tf, g in A.groupby("tf")}
    rows = []
    for lab, D in (("tfbars", A), ("5mbars", B)):
        for (s, tf), g in D[D.tf.isin(["1h", "4h"])].groupby(["strategy", "tf"]):
            z = g[(g.lev > 0) & g.R.notna()]
            d = dict(res=lab, strategy=s, tf=tf, signals=len(g), sized_share=(g.lev > 0).mean(),
                     sized_per_day=(g.lev > 0).sum() / span[tf], n=len(z))
            m, se, G = cl(z.R, z.day)
            d.update(mean_R=m, t=m / se if se == se and se > 0 else np.nan)
            mw, sew, _ = cl(z.R, z.week)
            d["t_week"] = m / sew if sew == sew and sew > 0 else np.nan
            for gc in ("gross_A", "gross_R"):
                mg, sg, _ = cl(z[gc], z.day)
                mgw, sgw, _ = cl(z[gc], z.week)
                d[f"{gc}"] = mg
                d[f"{gc}_t"] = mg / sg if sg == sg and sg > 0 else np.nan
                d[f"{gc}_t_week"] = mgw / sgw if sgw == sgw and sgw > 0 else np.nan
            for w, wl in ((0, "is"), (1, "cf")):
                zz = z[z.win == w]
                mm, ss, _ = cl(zz.R, zz.day)
                d[f"{wl}_n"], d[f"{wl}_R"], d[f"{wl}_t"] = len(zz), mm, mm / ss if ss == ss and ss > 0 else np.nan
                ga, sa, _ = cl(zz.gross_A, zz.day)
                d[f"{wl}_grossA"], d[f"{wl}_grossA_t"] = ga, ga / sa if sa == sa and sa > 0 else np.nan
                gb, sb, _ = cl(zz.gross_R, zz.day)
                d[f"{wl}_grossB"], d[f"{wl}_grossB_t"] = gb, gb / sb if sb == sb and sb > 0 else np.nan
            yr = pd.to_datetime(z.close_ms, unit="ms").dt.year.to_numpy()
            ym = z.groupby(yr)["R"].mean()
            d["years_pos"], d["years"] = int((ym > 0).sum()), len(ym)
            d["years_detail"] = " ".join(f"{k}:{v:+.3f}" for k, v in ym.items())
            d["win"] = 100 * (z.roe > 0).mean() if len(z) else np.nan
            x = z.R.to_numpy()
            d["payoff"] = x[x > 0].mean() / -x[x <= 0].mean() if (x > 0).any() and (x <= 0).any() else np.nan
            d["median_hold_h"] = (np.median(z.held) * (TFM[tf] if lab == "tfbars" else 5) / 60) if len(z) else np.nan
            for c, gc_ in g.groupby("coin"):
                d[f"sized_{c}"] = (gc_.lev > 0).mean()
                zc = z[z.coin == c]
                d[f"n_{c}"], d[f"R_{c}"] = len(zc), zc.R.mean() if len(zc) else np.nan
            rows.append(d)
    C = pd.DataFrame(rows)
    for lab in ("tfbars", "5mbars"):
        m = C.res == lab
        C.loc[m, "grossA_bh_q"] = bh(C.loc[m, "gross_A_t"].map(p2))
        C.loc[m, "grossB_bh_q"] = bh(C.loc[m, "gross_R_t"].map(p2))
        C.loc[m, "net_bh_q"] = bh(C.loc[m, "t"].map(p2))
    C.to_csv(f"{OUTD}/v_cells_1h_4h.csv", index=False)
    F = pd.read_csv(THEIR_CELLS)
    F = F[F.tf.isin(["1h", "4h"])]
    J = C[C.res == "tfbars"].merge(F, on=["strategy", "tf"], how="outer")
    J["d_n"] = J["n"] - J["fy_n"]
    J["d_R"] = J["mean_R"] - J["fy_mean_R"]
    J["d_grossA"] = J["gross_A"] - J["fy_gross_R"]
    print("cells compared:", len(J), "max |d_R|", J.d_R.abs().max(), "max |d_n|", J.d_n.abs().max(),
          "max |d_grossA|", J.d_grossA.abs().max())
    print(J.sort_values("d_R", key=abs, ascending=False)[["strategy", "tf", "n", "fy_n", "mean_R", "fy_mean_R", "gross_A",
                                                           "fy_gross_R"]].head(8).to_string())
    cols = ["res", "strategy", "tf", "n", "sized_per_day", "mean_R", "t", "is_R", "cf_R", "gross_A", "gross_A_t",
            "is_grossA_t", "cf_grossA_t", "grossA_bh_q", "gross_R", "gross_R_t", "is_grossB_t", "cf_grossB_t",
            "grossB_bh_q", "gross_A_t_week", "years_pos", "years_detail"]
    print(C.sort_values("gross_A_t", ascending=False)[cols].head(14).round(4).to_string())


TFM = {"15m": 15, "30m": 30, "1h": 60, "4h": 240}

if __name__ == "__main__":
    main()
