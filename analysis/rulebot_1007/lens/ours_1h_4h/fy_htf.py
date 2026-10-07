"""5-year test: does a 15m/30m signal do better when it agrees with the 1h/4h state (market or the same strategy)?

    python3 -I fy_htf.py <fy_signals.pkl> <signals_dir> <repo> <out_dir>

Outcome: R of the 15m/30m signal under the current live rules (fy_sim.py), sized and resolved signals only.
States, all taken from 1h / 4h bars (or signals) CLOSED at or before the 15m/30m signal's bar close:
  mkt_regime_{1h,4h}  paperbot.context.regime label of the last REGIME_N closed bars (the live ctx 'htf_regime'
                      definition; live uses 1h for 15m and 4h for 30m): trend_up/trend_down vs side = agree/against,
                      box/chop/unknown = neutral
  mkt_mom_{1h,4h}     sign of close - close 4 bars earlier on that timeframe (4 h / 16 h)
  mkt_ema_{1h,4h}     close above / below EMA20 of that timeframe
  same_sig_{1h,4h}    the same strategy's latest signal on the same coin at that timeframe, if it closed within the
                      last 4 bars (4 h / 16 h): same side = agree, other side = against, none = neutral
  same_pos_{1h,4h}    the same strategy's latest SIZED signal on the same coin at that timeframe whose simulated
                      house-exit trade is still open at the signal time (a one-position rule account's "position")
Contrast agree - against (and agree - neutral) is estimated within strategy x timeframe (fixed effects, so a
strategy's style does not leak into the contrast) with standard errors clustered by UTC day. IS = 2021-08..2024-06
(discovery), CF = 2024-07..2026-09 (confirmation). Per strategy: the same contrast in IS with BH over all
strategy x ltf x definition cells, then the CF value of each cell.
Writes fy_htf_pooled.csv, fy_htf_by_strategy.csv, fy_htf_groups.csv, fy_ltf_features.pkl.
"""
import os
import site
import sys
from collections import namedtuple

sys.dont_write_bytecode = True
sys.path.append(site.getusersitepackages())
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

IN, SIG, REPO, OUTD = sys.argv[1:5]
sys.path.insert(0, REPO)
from paperbot.context import REGIME_N, regime  # noqa: E402

TFMS = {"1h": 3_600_000, "4h": 14_400_000}
COINS = ("BTCUSD", "ETHUSD", "SOLUSD", "DOGEUSD", "LTCUSD", "BCHUSD")
Bar = namedtuple("Bar", "high low close")
DAY = 86_400_000
DEFS = [f"{k}_{h}" for k in ("mkt_regime", "mkt_mom", "mkt_ema", "same_sig", "same_pos") for h in ("1h", "4h")]


def htf_states(coin, htf):
    z = np.load(os.path.join(SIG, f"sig_{htf}_{coin}.npz"))
    c, h, l_ = z["c"], z["h"], z["l"]
    close_ms = z["ts"] // 1_000_000 + TFMS[htf]
    n = REGIME_N[htf]
    bars = [Bar(a, b, d) for a, b, d in zip(h.tolist(), l_.tolist(), c.tolist())]
    lab = np.zeros(len(c), np.int8)          # +1 trend_up, -1 trend_down, 0 other
    for j in range(n - 1, len(c)):
        r = regime(bars[j - n + 1:j + 1], n)["label"]
        lab[j] = 1 if r == "trend_up" else -1 if r == "trend_down" else 0
    mom = np.zeros(len(c), np.int8)
    mom[4:] = np.sign(c[4:] - c[:-4]).astype(np.int8)
    k = 2 / 21
    e = np.empty(len(c))
    e[0] = c[0]
    for i in range(1, len(c)):
        e[i] = c[i] * k + e[i - 1] * (1 - k)
    ema = np.sign(c - e).astype(np.int8)
    ema[:20] = 0
    return close_ms, lab, mom, ema


def fe_contrast(df, col_a, mask):
    """Within-(strategy, tf) difference agree - other on rows `mask`, day-clustered SE (Frisch-Waugh)."""
    d = df[mask]
    if len(d) < 30 or d[col_a].nunique() < 2:
        return np.nan, np.nan, len(d)
    g = d["stratum"].to_numpy()
    y = d["R"].to_numpy(float)
    x = d[col_a].to_numpy(float)
    ym = pd.Series(y).groupby(g).transform("mean").to_numpy()
    xm = pd.Series(x).groupby(g).transform("mean").to_numpy()
    yd, xd = y - ym, x - xm
    sxx = (xd ** 2).sum()
    if sxx <= 0:
        return np.nan, np.nan, len(d)
    b = (xd * yd).sum() / sxx
    e = yd - b * xd
    sc = pd.Series(xd * e).groupby(d["day"].to_numpy()).sum().to_numpy()
    G = len(sc)
    se = np.sqrt(G / (G - 1) * (sc ** 2).sum()) / sxx
    return b, se, len(d)


def main():
    D = pd.read_pickle(IN)
    for c in ("strategy", "tf", "coin"):
        D[c] = D[c].astype(str)
    L = D[D["tf"].isin(["15m", "30m"]) & (D["lev"] > 0) & D["R"].notna()].copy()
    L = L.sort_values(["coin", "close_ms"]).reset_index(drop=True)
    # ---- market states
    for htf in ("1h", "4h"):
        for col in ("mkt_regime", "mkt_mom", "mkt_ema"):
            L[f"{col}_{htf}"] = 0
        for coin in COINS:
            cm, lab, mom, ema = htf_states(coin, htf)
            sel = (L["coin"] == coin).to_numpy()
            j = np.searchsorted(cm, L.loc[sel, "close_ms"].to_numpy(), side="right") - 1
            ok = j >= 0
            for col, arr in (("mkt_regime", lab), ("mkt_mom", mom), ("mkt_ema", ema)):
                v = np.zeros(sel.sum(), np.int8)
                v[ok] = arr[j[ok]]
                L.loc[sel, f"{col}_{htf}"] = v * L.loc[sel, "side"].to_numpy()   # +1 agree, -1 against, 0 neutral
    # ---- same-strategy states
    H = D[D["tf"].isin(["1h", "4h"])]
    for htf in ("1h", "4h"):
        L[f"same_sig_{htf}"] = 0
        L[f"same_pos_{htf}"] = 0
        Hh = H[H["tf"] == htf]
        for (s, coin), g in Hh.groupby(["strategy", "coin"]):
            sel = ((L["strategy"] == s) & (L["coin"] == coin)).to_numpy()
            if not sel.any():
                continue
            T = L.loc[sel, "close_ms"].to_numpy()
            side = L.loc[sel, "side"].to_numpy()
            g = g.sort_values("close_ms")
            cm, sd = g["close_ms"].to_numpy(), g["side"].to_numpy()
            j = np.searchsorted(cm, T, side="right") - 1
            ok = j >= 0
            v = np.zeros(len(T), np.int8)
            recent = ok & ((T - cm[np.maximum(j, 0)]) <= 4 * TFMS[htf])
            v[recent] = (sd[j[recent]] * side[recent]).astype(np.int8)
            L.loc[sel, f"same_sig_{htf}"] = v
            gs = g[g["lev"] > 0]
            if not len(gs):
                continue
            cm2, sd2, ex2 = gs["close_ms"].to_numpy(), gs["side"].to_numpy(), gs["exit_ms"].to_numpy()
            j2 = np.searchsorted(cm2, T, side="right") - 1
            ok2 = j2 >= 0
            v2 = np.zeros(len(T), np.int8)
            openp = ok2 & (T < ex2[np.maximum(j2, 0)])
            v2[openp] = (sd2[j2[openp]] * side[openp]).astype(np.int8)
            L.loc[sel, f"same_pos_{htf}"] = v2
    L["day"] = L["close_ms"] // DAY
    L["stratum"] = L["strategy"] + "|" + L["tf"]
    L.to_pickle(os.path.join(OUTD, "fy_ltf_features.pkl"))

    # ---- pooled
    rows, grows = [], []
    for ltf in ("15m", "30m"):
        for w, wl in ((0, "IS"), (1, "CF"), (None, "ALL")):
            base = L[L["tf"] == ltf] if w is None else L[(L["tf"] == ltf) & (L["win"] == w)]
            for dfn in DEFS:
                v = base[dfn]
                for lab, code in (("agree", 1), ("against", -1), ("neutral", 0)):
                    gg = base[v == code]
                    grows.append({"ltf": ltf, "window": wl, "def": dfn, "group": lab, "n": len(gg),
                                  "share": len(gg) / max(len(base), 1), "mean_R": gg["R"].mean(),
                                  "win_pct": 100 * (gg["roe"] > 0).mean() if len(gg) else np.nan,
                                  "long_share": (gg["side"] > 0).mean() if len(gg) else np.nan})
                tmp = base.assign(_a=(v == 1).astype(float))
                b1, se1, n1 = fe_contrast(tmp, "_a", (v != 0).to_numpy())
                b2, se2, n2 = fe_contrast(tmp, "_a", (v != -1).to_numpy())
                rows.append({"ltf": ltf, "window": wl, "def": dfn, "agree_minus_against": b1, "se_aa": se1,
                             "t_aa": b1 / se1 if se1 == se1 and se1 > 0 else np.nan, "n_aa": n1,
                             "agree_minus_neutral": b2, "se_an": se2,
                             "t_an": b2 / se2 if se2 == se2 and se2 > 0 else np.nan, "n_an": n2})
    P = pd.DataFrame(rows)
    P.to_csv(os.path.join(OUTD, "fy_htf_pooled.csv"), index=False)
    Gp = pd.DataFrame(grows)
    Gp.to_csv(os.path.join(OUTD, "fy_htf_groups.csv"), index=False)

    # ---- per strategy (IS discovery, CF confirmation)
    srows = []
    for (s, ltf), g in L.groupby(["strategy", "tf"]):
        for dfn in DEFS:
            d = {"strategy": s, "ltf": ltf, "def": dfn}
            for w, wl in ((0, "is"), (1, "cf")):
                gw = g[g["win"] == w]
                v = gw[dfn]
                tmp = gw.assign(_a=(v == 1).astype(float))
                b, se, n = fe_contrast(tmp, "_a", (v != 0).to_numpy())
                d[f"{wl}_aa"], d[f"{wl}_se"], d[f"{wl}_n"] = b, se, n
                d[f"{wl}_n_agree"], d[f"{wl}_n_against"] = int((v == 1).sum()), int((v == -1).sum())
                d[f"{wl}_mean_R_agree"] = gw.loc[v == 1, "R"].mean()
                d[f"{wl}_mean_R_all"] = gw["R"].mean()
            srows.append(d)
    S = pd.DataFrame(srows)
    from math import erf, sqrt
    def p2(t):
        return 2 * (1 - 0.5 * (1 + erf(abs(t) / sqrt(2)))) if t == t else np.nan
    S["is_t"] = S["is_aa"] / S["is_se"]
    S["cf_t"] = S["cf_aa"] / S["cf_se"]
    S["is_p"] = S["is_t"].map(p2)
    m = S["is_p"].notna()
    p = S.loc[m, "is_p"].to_numpy()
    o = np.argsort(p)
    q = np.empty_like(p)
    q[o] = np.minimum.accumulate((p[o] * len(p) / np.arange(1, len(p) + 1))[::-1])[::-1]
    S.loc[m, "is_bh_q"] = np.minimum(q, 1)
    S.to_csv(os.path.join(OUTD, "fy_htf_by_strategy.csv"), index=False)
    pd.set_option("display.width", 250)
    print(P.round(4).to_string())
    print("per-strategy cells tested:", int(m.sum()), "BH q<0.05 in IS:", int((S["is_bh_q"] < 0.05).sum()))
    sv = S[S["is_bh_q"] < 0.05]
    print("survivors with same sign in CF and CF t>2:", int(((np.sign(sv["is_aa"]) == np.sign(sv["cf_aa"]))
                                                             & (sv["cf_t"].abs() > 2)).sum()))
    for dfn in DEFS:
        x = S[(S["def"] == dfn) & S["is_aa"].notna() & S["cf_aa"].notna()]
        if len(x) > 5:
            print(dfn, "IS vs CF per-strategy contrast corr:", round(np.corrcoef(x["is_aa"], x["cf_aa"])[0, 1], 3),
                  "n cells", len(x))


if __name__ == "__main__":
    main()
