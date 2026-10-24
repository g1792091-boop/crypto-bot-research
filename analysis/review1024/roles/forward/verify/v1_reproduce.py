"""Verifier 1: reproduce the principle numbers from sig.pkl.gz and test them against luck.
  A. headline with / against / neutral (Jdir, auto, w35, non-trend entries), halves, sides, mappings
  B. side-mix decomposition: how much of the pooled gap is just 'with' being mostly shorts in a falling month
  C. stratified gap within (side, UTC day) and within (coin, side, day) cells, day-cluster bootstrap CI
  D. placebo judges: the same judge read k hours / days EARLIER (wrong timing, same regime) -> null distribution of gap
  E. mapping comparison: CI of each mapping's gap and of 15m/30m->1h minus 1h->4h; 4h->1d reversal CI
Run from this folder without -I: python3 v1_reproduce.py"""
import sys
import os
sys.path.insert(0, "/home/user/crypto-bot-research/analysis/review1024/roles/forward")
from fw_lib import *  # noqa
import json

S = load("sig")
S = S[S.role != "trend"].reset_index(drop=True)
side = S.side.to_numpy()
t = S.t.to_numpy(np.int64)
day = S.day.to_numpy()
coin = S.coin.to_numpy()
tf = S.tf.to_numpy()
r = roe(S, "w35")
fin = np.isfinite(r)


def auto_state(src):
    a = np.zeros(len(S), np.int8)
    for t_, h_ in AUTO.items():
        m = tf == t_
        a[m] = state(S, src, h_)[m]
    return a


al = auto_state("Jdir") * side
out = {}
# ---------------- A
def grp(m):
    return {"n": int(m.sum()), "n_fin": int((m & fin).sum()), "mean": float(np.nanmean(r[m]))}

A = {}
for per, (a, b) in PERIOD.items():
    mp = (t >= a) & (t < b)
    for cl, c in (("with", 1), ("against", -1), ("neutral", 0)):
        A[f"{per}_{cl}"] = grp(mp & (al == c))
        for sd, s in (("L", 1), ("S", -1)):
            A[f"{per}_{cl}_{sd}"] = grp(mp & (al == c) & (side == s))
out["A"] = A
print("A headline", json.dumps({k: (v["n"], round(100 * v["mean"], 2)) for k, v in A.items()}))


# ---------------- day bootstrap helper on arbitrary statistic built from per-day sums
def boot_days(stat_fn, days_u, n_boot=4000, seed=11):
    rng = np.random.default_rng(seed)
    vals = []
    for _ in range(n_boot):
        d = rng.choice(days_u, len(days_u), replace=True)
        vals.append(stat_fn(d))
    return np.array(vals)


# ---------------- B. side-mix decomposition
def side_decomp(mp):
    w, g = mp & (al == 1) & fin, mp & (al == -1) & fin
    gap = r[w].mean() - r[g].mean()
    within = {}
    for sd, s in (("L", 1), ("S", -1)):
        within[sd] = r[w & (side == s)].mean() - r[g & (side == s)].mean()
    shareL_w, shareL_g = (side[w] > 0).mean(), (side[g] > 0).mean()
    # standardise both groups to the pooled side mix of (with+against)
    pL = (side[w | g] > 0).mean()
    std_gap = pL * within["L"] + (1 - pL) * within["S"]
    return {"gap": gap, "within_L": within["L"], "within_S": within["S"], "shareL_with": shareL_w,
            "shareL_against": shareL_g, "side_std_gap": std_gap, "side_mix_part": gap - std_gap}

B = {per: side_decomp((t >= a) & (t < b)) for per, (a, b) in PERIOD.items()}
out["B"] = B
print("B side decomposition", json.dumps({k: {kk: round(100 * vv, 2) if 'share' not in kk else round(vv, 3)
                                               for kk, vv in v.items()} for k, v in B.items()}))


# ---------------- C. stratified gap within (side, day) and (coin, side, day)
def strat_gap(mp, keys):
    """Mean over strata of (mean with - mean against), weighted by min(n_with, n_against) ... use n_with+n_against."""
    df = pd.DataFrame({"k": keys, "r": r, "al": al, "m": mp & fin})
    df = df[df.m & (df.al != 0)]
    g = df.groupby(["k", "al"]).r.agg(["sum", "count"]).unstack("al")
    g = g.dropna()
    mw = g[("sum", 1)] / g[("count", 1)]
    ma = g[("sum", -1)] / g[("count", -1)]
    wgt = g[("count", 1)] + g[("count", -1)]
    return g, mw, ma, wgt

C = {}
for per, (a, b) in PERIOD.items():
    mp = (t >= a) & (t < b)
    for lab, keys in (("side_day", side.astype(np.int64) * 100000 + day),
                      ("coin_side_day", (coin.astype(np.int64) * 10 + (side + 1)) * 100000 + day),
                      ("coin_side_tf_day", ((coin.astype(np.int64) * 10 + (side + 1)) * 10 +
                                            pd.Series(tf).map({"15m": 0, "30m": 1, "1h": 2, "4h": 3}).to_numpy())
                       * 100000 + day)):
        g, mw, ma, wgt = strat_gap(mp, keys)
        est = float(((mw - ma) * wgt).sum() / wgt.sum())
        # day bootstrap: strata belong to a day
        dd = (g.index.to_numpy() % 100000)
        du = np.unique(dd)
        diff = (mw - ma).to_numpy()
        w_ = wgt.to_numpy()
        rng = np.random.default_rng(5)
        bs = []
        pos = {d: np.where(dd == d)[0] for d in du}
        for _ in range(4000):
            pick = rng.choice(du, len(du))
            ii = np.concatenate([pos[d] for d in pick])
            bs.append((diff[ii] * w_[ii]).sum() / w_[ii].sum())
        bs = np.array(bs)
        C[f"{per}_{lab}"] = {"strata": int(len(g)), "n": int(wgt.sum()), "gap": est,
                             "lo": float(np.percentile(bs, 2.5)), "hi": float(np.percentile(bs, 97.5)),
                             "p_le0": float(np.mean(bs <= 0))}
out["C"] = C
print("C stratified", json.dumps({k: {kk: (round(100 * vv, 2) if kk in ("gap", "lo", "hi") else vv)
                                       for kk, vv in v.items()} for k, v in C.items()}))

# ---------------- D. placebo: lagged judge
STD = os.path.join(SCR, "data", "states")


def lagged_align(lag_ms):
    a = np.zeros(len(S), np.int8)
    for t_, h_ in AUTO.items():
        for ci, cn in enumerate(COINS):
            m = (tf == t_) & (coin == ci)
            if not m.any():
                continue
            Z = np.load(os.path.join(STD, f"{cn}_{h_}.npz"))
            close = Z["ts"] + TF_MIN[h_] * MIN
            idx = np.searchsorted(close, t[m] - lag_ms, side="right") - 1
            ok = idx >= 0
            d = np.zeros(m.sum(), np.float64)
            d[ok] = np.nan_to_num(Z["j_dir"][idx[ok]])
            nb = Z["nb"][np.maximum(idx, 0)]
            d[nb < 120] = 0
            a[m] = d.astype(np.int8)
    return a * side


# sanity: lag 0 reproduces the stored judge
a0 = lagged_align(0)
out["D_lag0_match"] = float(np.mean(a0 == al))
print("D lag0 match", out["D_lag0_match"])
D = []
for per, (pa, pb) in PERIOD.items():
    mp = (t >= pa) & (t < pb) & fin
    for lag_h in [0, 6, 12, 24, 36, 48, 72, 96, 120, 144, 168, 240, 336, 504, 720]:
        aa = a0 if lag_h == 0 else lagged_align(lag_h * HOUR)
        w, g = mp & (aa == 1), mp & (aa == -1)
        D.append({"period": per, "lag_h": lag_h, "n_with": int(w.sum()), "n_against": int(g.sum()),
                  "with": float(r[w].mean()), "against": float(r[g].mean()), "gap": float(r[w].mean() - r[g].mean()),
                  "shareL_with": float((side[w] > 0).mean()),
                  "gapL": float(r[w & (side > 0)].mean() - r[g & (side > 0)].mean()),
                  "gapS": float(r[w & (side < 0)].mean() - r[g & (side < 0)].mean())})
D = pd.DataFrame(D)
out["D"] = D.to_dict("records")
print(D.assign(**{c: (100 * D[c]).round(2) for c in ("with", "against", "gap", "gapL", "gapS")}).to_string())

# ---------------- E. mapping comparison with CIs
def cell_means(mp, aa):
    """per-day sums / counts for with and against."""
    du = np.unique(day[mp])
    res = {}
    for cl, c in (("w", 1), ("g", -1)):
        m = mp & (aa == c)
        s = pd.Series(r[m]).groupby(day[m]).agg(["sum", "count"]).reindex(du).fillna(0)
        res[cl] = (s["sum"].to_numpy(), s["count"].to_numpy())
    return du, res


E = {}
maps = {"15m>1h": ("15m", "1h"), "30m>1h": ("30m", "1h"), "1h>4h": ("1h", "4h"), "4h>1d": ("4h", "1d"),
        "15m>4h": ("15m", "4h"), "30m>4h": ("30m", "4h"), "1h>1d": ("1h", "1d")}
mp_all = fin & (t >= PERIOD["all"][0]) & (t < PERIOD["all"][1])
dU = np.unique(day[mp_all])
sums = {}
for k, (t_, h_) in maps.items():
    m = mp_all & (tf == t_)
    aa = state(S, "Jdir", h_) * side
    for cl, c in (("w", 1), ("g", -1)):
        mm = m & (aa == c)
        s = pd.Series(r[mm]).groupby(day[mm]).agg(["sum", "count"]).reindex(dU).fillna(0)
        sums[(k, cl)] = (s["sum"].to_numpy(), s["count"].to_numpy())
rng = np.random.default_rng(17)
IDX = rng.integers(0, len(dU), (4000, len(dU)))


def gapb(k):
    sw, cw = sums[(k, "w")]
    sg, cg = sums[(k, "g")]
    return sw[IDX].sum(1) / np.maximum(cw[IDX].sum(1), 1) - sg[IDX].sum(1) / np.maximum(cg[IDX].sum(1), 1), \
        sw.sum() / cw.sum() - sg.sum() / cg.sum()

G = {}
for k in maps:
    bs, est = gapb(k)
    G[k] = bs
    E[k] = {"gap": float(est), "lo": float(np.percentile(bs, 2.5)), "hi": float(np.percentile(bs, 97.5)),
            "p_le0": float(np.mean(bs <= 0)), "p_ge0": float(np.mean(bs >= 0)),
            "n_with": int(sums[(k, 'w')][1].sum()), "n_against": int(sums[(k, 'g')][1].sum())}
for a_, b_ in (("15m>1h", "1h>4h"), ("30m>1h", "1h>4h"), ("30m>1h", "30m>4h"), ("15m>1h", "15m>4h"),
               ("1h>4h", "1h>1d"), ("30m>1h", "4h>1d")):
    d = G[a_] - G[b_]
    E[f"{a_} minus {b_}"] = {"diff": float(E[a_]["gap"] - E[b_]["gap"]), "lo": float(np.percentile(d, 2.5)),
                              "hi": float(np.percentile(d, 97.5)), "p_le0": float(np.mean(d <= 0))}
out["E"] = E
print("E mappings", json.dumps({k: {kk: (round(100 * vv, 2) if kk in ("gap", "lo", "hi", "diff") else vv)
                                     for kk, vv in v.items()} for k, v in E.items()}, indent=0))
json.dump(out, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "v1_out.json"), "w"), indent=1,
          default=float)
