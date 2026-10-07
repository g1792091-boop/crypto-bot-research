"""Verifier: are the HTF 'position open' / 'regime trend' effects a cost (stop-width) confound?

    python3 -I vhtf_confound.py <v_htf_feats_tfbars.pkl> <v_tf_all.pkl> <out_csv>

Re-estimates agree-minus-neutral and agree-minus-against (FE strategy x tf, day-clustered SE) for:
  (a) net R (as before), (b) gross R (net + 0.14% round trip / stop fraction), (c) net R with fixed effects
  strategy x tf x cost-decile (cost decile within tf), and reports mean cost_R by state.
"""
import site
import sys

sys.dont_write_bytecode = True
sys.path.append(site.getusersitepackages())
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

FE, SIMP, OUT = sys.argv[1:4]
DAY = 86_400_000


def fe(y, a, strat, cl):
    if len(y) < 30 or a.min() == a.max():
        return np.nan, np.nan
    ym = pd.Series(y).groupby(strat).transform("mean").to_numpy()
    am = pd.Series(a).groupby(strat).transform("mean").to_numpy()
    yd, ad = y - ym, a - am
    sxx = (ad ** 2).sum()
    b = (ad * yd).sum() / sxx
    e = yd - b * ad
    sc = pd.Series(ad * e).groupby(cl).sum().to_numpy()
    G = len(sc)
    return b, np.sqrt(G / (G - 1) * (sc ** 2).sum()) / sxx


def main():
    L = pd.read_pickle(FE)
    S = pd.read_pickle(SIMP)
    for k in ("strategy", "tf", "coin"):
        S[k] = S[k].astype(str)
    S = S[S.tf.isin(["15m", "30m"]) & (S.lev > 0) & S.R.notna()][["strategy", "tf", "coin", "close_ms", "side",
                                                                    "atr_frac"]]
    L = L.merge(S, on=["strategy", "tf", "coin", "close_ms", "side"], how="left")
    print("joined atr:", L.atr_frac.notna().mean(), len(L))
    L["cost"] = 0.0014 / (2 * L.atr_frac + 0.0002)
    L["gross"] = L.R + L.cost
    L["cdec"] = L.groupby("tf").cost.transform(lambda x: pd.qcut(x, 10, labels=False, duplicates="drop"))
    L["day"] = L.close_ms // DAY
    rows = []
    for ltf in ("15m", "30m"):
        for w, wl in ((0, "IS"), (1, "CF")):
            b = L[(L.tf == ltf) & (L.win == w)]
            st = (b.strategy + "|" + b.tf).to_numpy()
            st2 = (b.strategy + "|" + b.tf + "|" + b.cdec.astype(str)).to_numpy()
            for d in ("reg_1h", "reg_4h", "sig_4h", "posA_1h", "posA_4h", "posB_1h", "posB_4h"):
                v = b[d].to_numpy()
                a = (v == 1).astype(float)
                for cmp, m in (("an", v != -1), ("aa", v != 0)):
                    r = dict(ltf=ltf, win=wl, d=d, cmp=cmp)
                    for lab, y, s in (("net", b.R.to_numpy(float), st), ("gross", b.gross.to_numpy(float), st),
                                      ("net_costFE", b.R.to_numpy(float), st2)):
                        be, se = fe(y[m], a[m], s[m], b.day.to_numpy()[m])
                        r[lab], r[f"t_{lab}"] = be, be / se
                    rows.append(r)
                rows[-1]["cost_agree"] = b.cost[v == 1].mean()
                rows[-1]["cost_against"] = b.cost[v == -1].mean()
                rows[-1]["cost_neutral"] = b.cost[v == 0].mean()
    P = pd.DataFrame(rows)
    P.to_csv(OUT, index=False)
    pd.set_option("display.width", 250)
    print(P.round(3).to_string())


if __name__ == "__main__":
    main()
