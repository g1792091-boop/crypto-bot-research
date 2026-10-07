"""Verifier: per-strategy HTF vs LTF (5-year), live every-signal per cell, and the analyst's grade rule re-applied
to the verifier's own numbers (tf-bar exits and 5m-bar exits).

    python3 -I vcards.py <v_tf_all.pkl> <v_5m_htf.pkl> <v_5m_ltf.pkl> <v_live_es.csv> <their cards_1h_4h.csv> <out_dir>
"""
import site
import sys
from math import erf, sqrt

sys.dont_write_bytecode = True
sys.path.append(site.getusersitepackages())
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

TFA, H5, L5, ESF, THEIRS, OUTD = sys.argv[1:7]
DAY = 86_400_000
RNG = np.random.default_rng(99)


def p2(t):
    return 2 * (1 - 0.5 * (1 + erf(abs(t) / sqrt(2)))) if t == t else np.nan


def bh(p):
    p = np.asarray(p, float)
    q = np.full(len(p), np.nan)
    ok = np.isfinite(p)
    pp = p[ok]
    o = np.argsort(pp)
    r = np.minimum.accumulate((pp[o] * len(pp) / np.arange(1, len(pp) + 1))[::-1])[::-1]
    qq = np.empty_like(pp)
    qq[o] = np.minimum(r, 1)
    q[ok] = qq
    return q


def clm(x, c):
    x = np.asarray(x, float)
    if len(x) < 3:
        return np.nan, np.nan
    m = x.mean()
    s = pd.Series(x - m).groupby(np.asarray(c)).sum().to_numpy()
    G = len(s)
    if G < 3:
        return m, np.nan
    return m, np.sqrt(G / (G - 1) * (s ** 2).sum()) / len(x)


def diff_cl(y, x, c):
    if x.sum() < 3 or (1 - x).sum() < 3:
        return np.nan, np.nan
    xd = x - x.mean()
    sxx = (xd ** 2).sum()
    b = (xd * (y - y.mean())).sum() / sxx
    e = y - y.mean() - b * xd
    sc = pd.Series(xd * e).groupby(c).sum().to_numpy()
    G = len(sc)
    return b, np.sqrt(G / (G - 1) * (sc ** 2).sum()) / sxx


def boot(x, c, B=4000):
    s = pd.DataFrame({"x": np.asarray(x, float), "c": c}).groupby("c")["x"].agg(["sum", "size"])
    G = len(s)
    if len(x) < 3 or G < 3:
        return np.nan, np.nan, G
    i = RNG.integers(0, G, size=(B, G))
    m = s["sum"].to_numpy()[i].sum(1) / s["size"].to_numpy()[i].sum(1)
    return np.percentile(m, 2.5), np.percentile(m, 97.5), G


def boot_diff(a, ca, b, cb, B=4000):
    def pr(x, c):
        s = pd.DataFrame({"x": np.asarray(x, float), "c": c}).groupby("c")["x"].agg(["sum", "size"])
        return s["sum"].to_numpy(), s["size"].to_numpy()
    if len(a) < 3 or len(b) < 3:
        return np.nan, np.nan, 0
    sa, na = pr(a, ca)
    sb, nb = pr(b, cb)
    if len(sa) < 3 or len(sb) < 3:
        return np.nan, np.nan, len(sa)
    ia = RNG.integers(0, len(sa), size=(B, len(sa)))
    ib = RNG.integers(0, len(sb), size=(B, len(sb)))
    d = sa[ia].sum(1) / na[ia].sum(1) - sb[ib].sum(1) / nb[ib].sum(1)
    return np.percentile(d, 2.5), np.percentile(d, 97.5), len(sa)


def prep(D):
    D = D.copy()
    for k in ("strategy", "tf", "coin"):
        D[k] = D[k].astype(str)
    D = D[(D.lev > 0) & D.R.notna()].copy()
    D["day"] = D.close_ms // DAY
    D["gross"] = D.R + 0.0014 / (2 * D.atr_frac + 0.0002)
    return D


def tfcompare(D, lab):
    rows = []
    for s, g in D.groupby("strategy"):
        ltf = g[g.tf.isin(["15m", "30m"])]
        for htf in ("1h", "4h"):
            h = g[g.tf == htf]
            both = pd.concat([ltf.assign(_x=0.0), h.assign(_x=1.0)])
            d = dict(res=lab, strategy=s, htf=htf, n_htf=len(h), net_htf=h.R.mean(), net_ltf=ltf.R.mean())
            for meas in ("R", "gross"):
                for w, wl in ((None, "all"), (0, "is"), (1, "cf")):
                    bb = both if w is None else both[both.win == w]
                    b, se = diff_cl(bb[meas].to_numpy(float), bb._x.to_numpy(float), bb.day.to_numpy())
                    d[f"d_{meas}_{wl}"], d[f"t_{meas}_{wl}"] = b, (b / se if se == se and se > 0 else np.nan)
            rows.append(d)
    T = pd.DataFrame(rows)
    for meas in ("R", "gross"):
        T[f"q_{meas}"] = bh(T[f"t_{meas}_all"].map(p2))
    return T


def main():
    A = prep(pd.read_pickle(TFA))
    H = prep(pd.read_pickle(H5))
    L = prep(pd.read_pickle(L5))
    B5 = pd.concat([H, L], ignore_index=True)
    T = pd.concat([tfcompare(A, "tfbars"), tfcompare(B5, "5mbars")], ignore_index=True)
    T.to_csv(f"{OUTD}/v_tfcompare.csv", index=False)
    for lab in ("tfbars", "5mbars"):
        t = T[(T.res == lab) & T.t_R_all.notna()]
        print(lab, "comparisons:", len(t), " HTF net better q<0.05:", int(((t.q_R < 0.05) & (t.d_R_all > 0)).sum()),
              " HTF net point estimate better:", int((t.d_R_all > 0).sum()), " worse:", int((t.d_R_all < 0).sum()),
              " gross better q<0.05:", int(((t.q_gross < 0.05) & (t.d_gross_all > 0)).sum()),
              " gross worse q<0.05:", int(((t.q_gross < 0.05) & (t.d_gross_all < 0)).sum()))
        print(t.sort_values("t_gross_all")[["strategy", "htf", "n_htf", "d_R_all", "t_R_all", "d_gross_all", "t_gross_all",
                                            "d_gross_is", "d_gross_cf", "q_gross"]].iloc[np.r_[0:3, -3:0]].round(3).to_string())
        print("  HTF net worse than LTF:", t[t.d_R_all < 0][["strategy", "htf", "n_htf", "d_R_all", "t_R_all"]].round(3).to_string())

    # ---- per cell: own 5y + own live every-signal, analyst's grade rule
    ES = pd.read_csv(ESF)
    ES = ES[(ES.status == "TRADED") & ES.R.notna()]
    rows = []
    span = {tf: (g.close_ms.max() - g.close_ms.min()) / DAY for tf, g in A.groupby("tf")}
    for lab, D in (("tfbars", A), ("5mbars", B5)):
        for s in sorted(A.strategy.unique()):
            for tf in ("1h", "4h"):
                z = D[(D.strategy == s) & (D.tf == tf)]
                d = dict(res=lab, strategy=s, tf=tf, fy_n=len(z))
                m, se = clm(z.R, z.day)
                d["fy_mean_R"], d["fy_t_R"] = m, (m / se if se == se and se > 0 else np.nan)
                mg, sg = clm(z.gross, z.day)
                d["fy_gross_R"], d["fy_gross_t"] = mg, (mg / sg if sg == sg and sg > 0 else np.nan)
                for w, wl in ((0, "is"), (1, "cf")):
                    zz = z[z.win == w]
                    mm, ss = clm(zz.R, zz.day)
                    d[f"fy_{wl}_mean_R"], d[f"fy_{wl}_t_R"] = mm, (mm / ss if ss == ss and ss > 0 else np.nan)
                    gg, sgg = clm(zz.gross, zz.day)
                    d[f"fy_{wl}_gross"], d[f"fy_{wl}_gross_t"] = gg, (gg / sgg if sgg == sgg and sgg > 0 else np.nan)
                e = ES[(ES.strategy == s) & (ES.tf == tf)]
                d["es_n"], d["es_mean_R"] = len(e), (e.R.mean() if len(e) else np.nan)
                lo, hi, G = boot(e.R, e.cl)
                d["es_lo"], d["es_hi"], d["es_G"] = lo, hi, G
                for rk in ("v3a", "v3b", "v4"):
                    ee = e[e.rk == rk]
                    d[f"es_{rk}_n"], d[f"es_{rk}_R"] = len(ee), (ee.R.mean() if len(ee) else np.nan)
                ltf = ES[(ES.strategy == s) & ES.tf.isin(["15m", "30m"])]
                d["es_ltf_n"], d["es_ltf_R"] = len(ltf), (ltf.R.mean() if len(ltf) else np.nan)
                d["live_htf_minus_ltf"] = d["es_mean_R"] - d["es_ltf_R"] if len(e) and len(ltf) else np.nan
                lo2, hi2, Ga = boot_diff(e.R, e.cl.to_numpy(), ltf.R, ltf.cl.to_numpy())
                d["live_d_lo"], d["live_d_hi"], d["live_d_G_htf"] = lo2, hi2, Ga
                rows.append(d)
    C = pd.DataFrame(rows)

    def grade(r):
        fy_n = r["fy_n"]
        es_n = r["es_n"]
        if fy_n < 100 and es_n < 10:
            return "U"
        if (r["fy_is_t_R"] >= 2 and r["fy_cf_t_R"] >= 2 and r["fy_is_mean_R"] > 0 and r["fy_cf_mean_R"] > 0
                and r["es_lo"] > 0):
            return "A"
        if (r["fy_is_gross_t"] >= 2 and r["fy_cf_gross_t"] >= 2 and r["fy_mean_R"] > -0.05
                and (es_n < 10 or r["es_mean_R"] > -0.10)):
            return "B"
        if (r["fy_t_R"] <= -2 and r["fy_gross_R"] <= -0.02) or (es_n >= 8 and r["es_hi"] < 0):
            return "D"
        return "C"
    C["grade"] = [grade(r) for r in C.to_dict("records")]
    for lab in ("tfbars", "5mbars"):
        m = C.res == lab
        C.loc[m, "gross_q72"] = bh(C.loc[m, "fy_gross_t"].map(p2))
    C.to_csv(f"{OUTD}/v_cards.csv", index=False)
    th = pd.read_csv(THEIRS)[["strategy", "tf", "grade", "es_n", "es_mean_R", "es_ci95_lo", "es_ci95_hi"]]
    J = C.merge(th, on=["strategy", "tf"], suffixes=("", "_their"))
    for lab in ("tfbars", "5mbars"):
        j = J[J.res == lab]
        print(lab, "grade counts own:", j.grade.value_counts().to_dict(), " theirs:", j.grade_their.value_counts().to_dict())
        print("  disagreements:", j[j.grade != j.grade_their][["strategy", "tf", "grade", "grade_their", "fy_n", "fy_mean_R",
                                                                "fy_gross_R", "fy_gross_t", "fy_is_gross_t",
                                                                "fy_cf_gross_t", "es_n", "es_mean_R", "es_lo",
                                                                "es_hi"]].round(3).to_string())
    j = J[J.res == "tfbars"]
    print("live es_n equal:", (j.es_n == j.es_n_their).mean(), " es mean max diff:",
          (j.es_mean_R - j.es_mean_R_their).abs().max())
    print("gross negative cells with BH q<0.05 (tfbars):",
          C[(C.res == "tfbars") & (C.gross_q72 < 0.05)][["strategy", "tf", "fy_gross_R", "fy_gross_t", "gross_q72"]].round(4).to_string())
    print("D-graded cells (tfbars) gross t:", C[(C.res == "tfbars") & (C.grade == "D")][["strategy", "tf", "fy_n", "fy_gross_R",
                                                                                       "fy_gross_t", "gross_q72", "es_n", "es_lo", "es_hi", "es_G"]].round(3).to_string())
    x = C[(C.res == "tfbars") & (C.tf == "1h") & (C.es_n >= 20)]
    print("1h cells es_n>=20:", x[["strategy", "es_n", "es_mean_R", "es_lo", "es_hi", "es_G", "es_v3a_R", "es_v3b_R", "es_v4_R",
                                   "es_v3a_n", "es_v3b_n", "es_v4_n"]].round(3).to_string())
    y = C[(C.res == "tfbars") & (C.live_d_lo > 0)]
    print("live HTF-LTF CI>0:", y[["strategy", "tf", "es_n", "es_G", "es_mean_R", "es_ltf_R", "live_htf_minus_ltf", "live_d_lo",
                                   "live_d_hi"]].round(3).to_string())
    print("cells with live diff computed:", int(C[(C.res == "tfbars")].live_d_lo.notna().sum()))


if __name__ == "__main__":
    main()
