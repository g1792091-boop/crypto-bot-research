"""Verifier: 5-year HTF agreement for 15m/30m signals (own features on own sims).

    python3 -I vhtf.py <ltf.pkl (outcomes)> <htf_5m.pkl (1h/4h sims, 5m exits)> <sig_dir> <repo> <tag> <out_dir>

Outcome = R of the 15m/30m signal (sized, resolved). States at the LTF signal's bar close T, from HTF bars closed <= T:
  ema_{1h,4h}   sign(close - EMA20) (EMA seeded with the first close)
  mom_4h        sign(close - close 4 bars earlier)
  reg_{1h,4h}   paperbot.context.regime label (trend_up/down vs side; others neutral)
  sig_{1h,4h}   same strategy, same coin, latest HTF signal with bar close in (T - 4 bars, T]: same side agree
  posA_{1h,4h}  analyst's definition: latest SIZED same-coin HTF signal of the strategy whose sim exit time > T
  posB_{1h,4h}  one-position rule account of that strategy@htf across all 6 coins (signals taken in time order only
                when flat; exit at the 5m-resolution exit time): the account holds the same coin at T
Contrast agree - against and agree - neutral within strategy x tf (fixed effects), SE clustered by UTC day; also by week.
"""
import os
import site
import sys
from collections import namedtuple

sys.dont_write_bytecode = True
sys.path.append(site.getusersitepackages())
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

LTF, HTF5, SIG, REPO, TAG, OUTD = sys.argv[1:7]
sys.path.insert(0, REPO)
from paperbot.context import REGIME_N, regime  # noqa: E402

TFMS = {"1h": 3_600_000, "4h": 14_400_000}
COINS = ("BTCUSD", "ETHUSD", "SOLUSD", "DOGEUSD", "LTCUSD", "BCHUSD")
DAY = 86_400_000
Bar = namedtuple("Bar", "high low close")


def states(coin, htf):
    z = np.load(os.path.join(SIG, f"sig_{htf}_{coin}.npz"))
    c, h, l_ = z["c"], z["h"], z["l"]
    cm = z["ts"] // 1_000_000 + TFMS[htf]
    e = np.empty(len(c))
    e[0] = c[0]
    k = 2 / 21
    for i in range(1, len(c)):
        e[i] = c[i] * k + e[i - 1] * (1 - k)
    ema = np.sign(c - e)
    ema[:20] = 0
    mom = np.zeros(len(c))
    mom[4:] = np.sign(c[4:] - c[:-4])
    n = REGIME_N[htf]
    bars = [Bar(a, b, d) for a, b, d in zip(h.tolist(), l_.tolist(), c.tolist())]
    reg = np.zeros(len(c))
    for j in range(n - 1, len(c)):
        lab = regime(bars[j - n + 1:j + 1], n)["label"]
        reg[j] = 1 if lab == "trend_up" else (-1 if lab == "trend_down" else 0)
    return cm, ema, mom, reg


def fe(y, a, strat, cl, mask):
    y, a, strat, cl = y[mask], a[mask], strat[mask], cl[mask]
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


def one_position(H):
    """H: sized HTF sims of one strategy@htf across coins, sorted by entry. Returns taken rows."""
    keep = []
    free_at = -1
    for r in H.itertuples():
        if r.close_ms >= free_at:
            keep.append(r.Index)
            free_at = r.exit_ms
    return H.loc[keep]


def main():
    L = pd.read_pickle(LTF)
    for k in ("strategy", "tf", "coin"):
        L[k] = L[k].astype(str)
    L = L[L.tf.isin(["15m", "30m"]) & (L.lev > 0) & L.R.notna()].copy()
    Hs = pd.read_pickle(HTF5)
    for k in ("strategy", "tf", "coin"):
        Hs[k] = Hs[k].astype(str)
    L = L.sort_values("close_ms").reset_index(drop=True)
    T_all = L.close_ms.to_numpy()
    side_all = L.side.to_numpy()
    for htf in ("1h", "4h"):
        for col in ("ema", "mom", "reg"):
            L[f"{col}_{htf}"] = 0.0
        for coin in COINS:
            cm, ema, mom, reg = states(coin, htf)
            sel = (L.coin == coin).to_numpy()
            j = np.searchsorted(cm, T_all[sel], side="right") - 1
            ok = j >= 0
            for col, arr in (("ema", ema), ("mom", mom), ("reg", reg)):
                v = np.zeros(sel.sum())
                v[ok] = arr[j[ok]]
                L.loc[sel, f"{col}_{htf}"] = v * side_all[sel]
        # same strategy signals / positions
        Hh = Hs[Hs.tf == htf]
        sig = np.zeros(len(L))
        posA = np.zeros(len(L))
        posB = np.zeros(len(L))
        keyL = L.strategy + "|" + L.coin
        groups = {k: np.nonzero((keyL == k).to_numpy())[0] for k in keyL.unique()}
        for (s, coin), g in Hh.groupby(["strategy", "coin"]):
            ii = groups.get(f"{s}|{coin}")
            if ii is None:
                continue
            T = T_all[ii]
            g = g.sort_values("close_ms")
            cm, sd = g.close_ms.to_numpy(), g.side.to_numpy()
            j = np.searchsorted(cm, T, side="right") - 1
            rec = (j >= 0) & ((T - cm[np.maximum(j, 0)]) < 4 * TFMS[htf])
            sig[ii[rec]] = sd[j[rec]] * side_all[ii[rec]]
            gs = g[g.lev > 0]
            if len(gs):
                cm2, sd2, ex2 = gs.close_ms.to_numpy(), gs.side.to_numpy(), gs.exit_ms.to_numpy()
                j2 = np.searchsorted(cm2, T, side="right") - 1
                op = (j2 >= 0) & (T < ex2[np.maximum(j2, 0)])
                posA[ii[op]] = sd2[j2[op]] * side_all[ii[op]]
        for s, g in Hh[Hh.lev > 0].groupby("strategy"):
            P = one_position(g.sort_values(["close_ms", "coin"]))
            for coin, pc in P.groupby("coin"):
                ii = groups.get(f"{s}|{coin}")
                if ii is None:
                    continue
                T = T_all[ii]
                pc = pc.sort_values("close_ms")
                cm, sd, ex = pc.close_ms.to_numpy(), pc.side.to_numpy(), pc.exit_ms.to_numpy()
                j = np.searchsorted(cm, T, side="right") - 1
                op = (j >= 0) & (T < ex[np.maximum(j, 0)])
                posB[ii[op]] = sd[j[op]] * side_all[ii[op]]
        L[f"sig_{htf}"], L[f"posA_{htf}"], L[f"posB_{htf}"] = sig, posA, posB
    L["day"] = L.close_ms // DAY
    L["week"] = (L.close_ms + 3 * DAY) // (7 * DAY)
    L["stratum"] = L.strategy + "|" + L.tf
    defs = ["reg_1h", "reg_4h", "mom_4h", "ema_1h", "ema_4h", "sig_1h", "sig_4h", "posA_1h", "posA_4h", "posB_1h",
            "posB_4h"]
    L[["strategy", "tf", "coin", "close_ms", "side", "win", "R"] + defs].to_pickle(f"{OUTD}/v_htf_feats_{TAG}.pkl")
    rows, grows = [], []
    for ltf in ("15m", "30m"):
        for w, wl in ((0, "IS"), (1, "CF")):
            base = L[(L.tf == ltf) & (L.win == w)]
            y = base.R.to_numpy(float)
            st = base.stratum.to_numpy()
            for dfn in defs:
                v = base[dfn].to_numpy()
                a = (v == 1).astype(float)
                b1, s1 = fe(y, a, st, base.day.to_numpy(), v != 0)
                b1w, s1w = fe(y, a, st, base.week.to_numpy(), v != 0)
                b2, s2 = fe(y, a, st, base.day.to_numpy(), v != -1)
                b2w, s2w = fe(y, a, st, base.week.to_numpy(), v != -1)
                rows.append(dict(ltf=ltf, win=wl, d=dfn, aa=b1, t_aa=b1 / s1, t_aa_week=b1w / s1w, an=b2, t_an=b2 / s2,
                                 t_an_week=b2w / s2w, n_agree=int((v == 1).sum()), n_against=int((v == -1).sum()),
                                 n_neutral=int((v == 0).sum()), R_agree=y[v == 1].mean(), R_against=y[v == -1].mean(),
                                 R_neutral=y[v == 0].mean()))
    P = pd.DataFrame(rows)
    P.to_csv(f"{OUTD}/v_htf_{TAG}.csv", index=False)
    pd.set_option("display.width", 250)
    print(P.round(3).to_string())


if __name__ == "__main__":
    main()
