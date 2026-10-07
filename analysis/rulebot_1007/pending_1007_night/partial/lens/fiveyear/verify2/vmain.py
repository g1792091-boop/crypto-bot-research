"""Independent reconciliation from MY 5-year sims (my_core_*.csv, my_ds_*.csv) and the live replay table.
python3 -I -B vmain.py <verify_dir> <out_real_dir> <their_out_dir>"""
import os
import sys
from math import erf, sqrt

sys.path.append('/root/.local/lib/python3.11/site-packages')
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

V, RD, TH = sys.argv[1:4]
NSD = 86400 * 10 ** 9
S0, S1 = pd.Timestamp("2021-08-01").value, pd.Timestamp("2026-09-30").value
CF0 = pd.Timestamp("2024-07-01").value
DAYS = (S1 - S0) / NSD
L3B, L4 = 0.6986111111111111, 1.5034722222222223
rng = np.random.default_rng(424242)
B = 20000
pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 40)


def bh(p):
    p = np.asarray(p, float)
    out = np.full(len(p), np.nan)
    ok = np.isfinite(p)
    pv = p[ok]
    m = len(pv)
    if not m:
        return out
    o = np.argsort(pv)
    q = np.minimum.accumulate((pv[o] * m / np.arange(1, m + 1))[::-1])[::-1]
    r = np.empty(m)
    r[o] = np.minimum(q, 1)
    out[ok] = r
    return out


def clmean(x, cl):
    x = np.asarray(x, float)
    cl = np.asarray(cl)
    ok = np.isfinite(x)
    x, cl = x[ok], cl[ok]
    n = len(x)
    if n < 3:
        return (x.mean() if n else np.nan), np.nan, n
    mu = x.mean()
    s = pd.Series(x - mu).groupby(cl).sum().to_numpy()
    G = len(s)
    return mu, np.sqrt((s ** 2).sum() * G / max(G - 1, 1)) / n, n


# ------------------------------------------------------------------ 5-year (my sims)
parts = []
for tf in ("5m", "15m", "30m", "1h", "4h"):
    d = pd.read_csv(os.path.join(V, f"my_core_{tf}.csv"))
    d["kind"] = "strategy"
    d["frac"] = 0.25 if tf == "5m" else 1.0
    parts.append(d)
for tf in ("15m", "30m", "1h", "4h"):
    d = pd.read_csv(os.path.join(V, f"my_ds_{tf}.csv"))
    d["kind"] = "ds200"
    d["frac"] = 1.0
    parts.append(d)
FY = pd.concat(parts, ignore_index=True)
FY = FY[(FY.ts >= S0) & (FY.ts < S1)]
FY["sized"] = FY["lev"] > 0
FY["week"] = (FY["ts"] // NSD + 3) // 7
FY["cf"] = FY["ts"] >= CF0
print("5y rows", len(FY))

# ------------------------------------------------------------------ live replay
RP = pd.read_csv(os.path.join(RD, "replay_signals.csv"))
RP["run"] = RP["run"].map({"run-20261005T183457Z": "v3b", "current": "v4"})
RP = RP[RP["kind"].isin(["strategy", "ds200"])]
RP["tf"] = RP["timeframe"]
RP["cl"] = RP["run"] + ":" + RP["bar_close"].astype(str)
RP["hourcl"] = RP["run"] + ":" + (RP["bar_close"] // 3600000).astype(str)
TR = RP[RP.status == "TRADED"]

# ------------------------------------------------------------------ tf-level
out = []
for (kind, tf), g in FY.groupby(["kind", "tf"]):
    s = g[g.sized]
    mu, se, n = clmean(s.R, s.week)
    d = dict(kind=kind, tf=tf, signals_per_day=len(g) / g.frac.iloc[0] / DAYS, sized_share=g.sized.mean(), n=n, mean_R=mu,
             t_week=mu / se, gross_R=s.gR.mean(), cost_R=s.gR.mean() - mu, is_R=s.R[~s.cf].mean(), cf_R=s.R[s.cf].mean(),
             is_gR=s.gR[~s.cf].mean(), cf_gR=s.gR[s.cf].mean(), med_sf=s.stop_frac.median())
    lv = TR[(TR.kind == kind) & (TR.tf == tf)]
    if len(lv):
        lo, hi = lv.stop_frac.quantile(0.1), lv.stop_frac.quantile(0.9)
        q = s[(s.stop_frac >= lo) & (s.stop_frac <= hi)]
        d.update(nowvol_R=q.R.mean(), nowvol_gR=q.gR.mean(), nowvol_share=len(q) / len(s), live_sf_p10=lo, live_sf_p90=hi,
                 live_med_sf=lv.stop_frac.median())
        # pooled per-tf live range (all kinds, as the analyst did)
        lva = TR[TR.tf == tf]
        lo2, hi2 = lva.stop_frac.quantile(0.1), lva.stop_frac.quantile(0.9)
        q2 = s[(s.stop_frac >= lo2) & (s.stop_frac <= hi2)]
        d["nowvol_R_pooledrange"] = q2.R.mean()
    out.append(d)
TFS = pd.DataFrame(out)
print(TFS.to_string())
TFS.to_csv(os.path.join(V, "v_tf_summary.csv"), index=False)

# quintiles of stop_frac, core 15m
g = FY[(FY.kind == "strategy") & (FY.tf == "15m") & FY.sized]
qs = np.quantile(g.stop_frac, [0, .2, .4, .6, .8, 1])
b = np.clip(np.searchsorted(qs, g.stop_frac, side="right") - 1, 0, 4)
print("core 15m quintiles sf", np.round(qs, 5))
print(pd.DataFrame({"b": b, "R": g.R, "gR": g.gR}).groupby("b").agg(R=("R", "mean"), gR=("gR", "mean")).assign(cost=lambda x: x.gR - x.R))


# ------------------------------------------------------------------ windows
def window_dist(ts, val, sf, lens, B, contiguous=False):
    o = np.argsort(ts)
    ts, val, sf = ts[o], val[o], sf[o]
    cs = np.r_[0, np.cumsum(val)]
    cf = np.r_[0, np.cumsum(sf)]
    tot_s = np.zeros(B)
    tot_n = np.zeros(B)
    tot_f = np.zeros(B)
    if contiguous:
        lens = (sum(lens),)
    for L in lens:
        st = rng.uniform(S0, S1 - L * NSD, B)
        i0 = np.searchsorted(ts, st)
        i1 = np.searchsorted(ts, st + L * NSD)
        tot_s += cs[i1] - cs[i0]
        tot_f += cf[i1] - cf[i0]
        tot_n += i1 - i0
    with np.errstate(invalid="ignore", divide="ignore"):
        return tot_s / tot_n, tot_n, tot_f / tot_n


def pct(dist, x):
    d = dist[np.isfinite(dist)]
    p = (d < x).mean() + 0.5 * (d == x).mean()
    return p, min(1, 2 * min(p, 1 - p))


W = []
for (kind, tf), g in FY.groupby(["kind", "tf"]):
    if tf == "5m":
        continue
    s = g[g.sized]
    lv = TR[(TR.kind == kind) & (TR.tf == tf)]
    unres = RP[(RP.kind == kind) & (RP.tf == tf) & (RP.status == "UNRESOLVED")]
    live_mu = lv.R.mean()
    live_mark = np.r_[lv.R.to_numpy(float), unres.mark_R.dropna().to_numpy(float)].mean()
    lsf = lv.stop_frac.mean()
    lens = (L3B, L4) if (lv.run == "v3b").any() else (L4,)
    for mode in ("indep", "contig"):
        m, n, f = window_dist(s.ts.to_numpy(), s.R.to_numpy(float), s.stop_frac.to_numpy(float), lens, B, contiguous=(mode == "contig"))
        ok = n > 0
        p, p2 = pct(m[ok], live_mu)
        pm, _ = pct(m[ok], live_mark)
        match = ok & (np.abs(f / lsf - 1) <= 0.15)
        pmt, p2mt = pct(m[match], live_mu) if match.sum() > 50 else (np.nan, np.nan)
        W.append(dict(kind=kind, tf=tf, mode=mode, lens="+".join(f"{x:.2f}" for x in lens), live_n=len(lv), live_R=live_mu,
                      live_R_incl_mark=live_mark, n_unres=len(unres), pct_live=p, p_two=p2, pct_live_incl_mark=pm,
                      w_p05=np.percentile(m[ok], 5), w_p50=np.percentile(m[ok], 50), w_p95=np.percentile(m[ok], 95),
                      live_sf_pct=pct(f[ok], lsf)[0], matched=int(match.sum()), m_p50=np.percentile(m[match], 50) if match.sum() else np.nan,
                      pct_matched=pmt, p_two_matched=p2mt))
WT = pd.DataFrame(W)
print(WT.to_string())
WT.to_csv(os.path.join(V, "v_windows.csv"), index=False)

# ------------------------------------------------------------------ per cell
cells = []
for (kind, st, tf), g in FY.groupby(["kind", "strategy", "tf"]):
    s = g[g.sized]
    mu, se, n = clmean(s.R, s.week)
    gmu, gse, _ = clmean(s.gR, s.week)
    d = dict(kind=kind, strategy=st, tf=tf, fy_per_day=len(g) / g.frac.iloc[0] / DAYS, fy_n=n, fy_R=mu, fy_t=mu / se if se else np.nan,
             fy_is=s.R[~s.cf].mean(), fy_cf=s.R[s.cf].mean(), fy_gR=gmu, fy_gt=gmu / gse if gse else np.nan,
             fy_gis=s.gR[~s.cf].mean(), fy_gcf=s.gR[s.cf].mean(), fy_sized_per_day=n / g.frac.iloc[0] / DAYS)
    lv = TR[(TR.kind == kind) & (TR.strategy == st) & (TR.tf == tf)]
    lm, lse, ln = clmean(lv.R, lv.cl)
    d.update(live_n=ln, live_R=lm, live_se=lse)
    cells.append(d)
C = pd.DataFrame(cells)
for k in ("strategy", "ds200"):
    m = C.kind == k
    C.loc[m, "fy_p_pos"] = [0.5 * (1 - erf(x / sqrt(2))) if np.isfinite(x) else np.nan for x in C.loc[m, "fy_t"]]


def fyc(r):
    if not np.isfinite(r.fy_R) or r.fy_n < 30:
        return "fy_thin"
    if r.fy_R > 0 and r.fy_is > 0 and r.fy_cf > 0:
        return "P"
    if np.isfinite(r.fy_t) and r.fy_t <= -2:
        return "N_gross+" if r.fy_gR > 0 else "NN"
    return "Z"


def lvc(r):
    if r.tf == "5m":
        return "L_v3a"
    if not r.live_n or r.live_n < 15 or not np.isfinite(r.live_R):
        return "L_thin"
    if np.isfinite(r.live_se) and r.live_R + 2 * r.live_se < 0:
        return "L--"
    if np.isfinite(r.live_se) and r.live_R - 2 * r.live_se > 0:
        return "L++"
    return "L+" if r.live_R > 0 else "L-"


G = {("P", "L++"): "A", ("P", "L+"): "A", ("P", "L-"): "B", ("P", "L_thin"): "B", ("P", "L--"): "C",
     ("Z", "L++"): "B", ("Z", "L+"): "B", ("Z", "L-"): "C", ("Z", "L_thin"): "C", ("Z", "L--"): "D",
     ("N_gross+", "L++"): "C", ("N_gross+", "L+"): "C", ("N_gross+", "L-"): "D", ("N_gross+", "L_thin"): "D", ("N_gross+", "L--"): "F",
     ("NN", "L++"): "D", ("NN", "L+"): "D", ("NN", "L-"): "F", ("NN", "L_thin"): "F", ("NN", "L--"): "F"}
C["fyc"] = C.apply(fyc, axis=1)
C["lvc"] = C.apply(lvc, axis=1)
C["grade_mine"] = [G.get((a, b), "n/a") for a, b in zip(C.fyc, C.lvc)]
T = pd.read_csv(os.path.join(TH, "fiveyear_vs_live.csv"))
T = T[["kind", "strategy", "tf", "grade", "fy_class", "live_class", "fy_mean_R", "fy_gross_R", "live_rp_n", "live_rp_mean_R", "live_rp_se_R"]]
C = C.merge(T, on=["kind", "strategy", "tf"], how="outer")
C.to_csv(os.path.join(V, "v_cells.csv"), index=False)
x = C[C.tf != "5m"]
print("grade counts mine (15m-4h)", x.grade_mine.value_counts().to_dict())
print("grade counts theirs (15m-4h)", x.grade.value_counts().to_dict(), "all theirs", C.grade.value_counts().to_dict())
dif = x[(x.grade_mine != x.grade)]
print("grade disagreements", len(dif))
print(dif[["kind", "strategy", "tf", "grade_mine", "grade", "fyc", "fy_class", "lvc", "live_class", "live_n", "live_rp_n", "live_R", "live_rp_mean_R", "live_se", "live_rp_se_R"]].to_string())
print("max |fy_R - theirs|", (x.fy_R - x.fy_mean_R).abs().max(), "max |live_R - theirs|", (x.live_R - x.live_rp_mean_R).abs().max())

# ------------------------------------------------------------------ F4: positive cells / gross BH
pos = C[(C.fy_n >= 30) & (C.fy_R > 0)].sort_values("fy_R", ascending=False)
print("positive net cells n>=30:\n", pos[["kind", "strategy", "tf", "fy_n", "fy_R", "fy_t", "fy_is", "fy_cf", "fy_gR", "fy_sized_per_day"]].to_string())
gg = C[C.fy_n >= 200].copy()
gg["gp"] = [0.5 * (1 - erf(t / sqrt(2))) for t in gg.fy_gt]
gg["gq"] = bh(gg.gp.to_numpy())
print("cells n>=200:", len(gg))
print(gg[gg.gq < 0.1].sort_values("gq")[["kind", "strategy", "tf", "fy_n", "fy_gR", "fy_gt", "gq", "fy_gis", "fy_gcf", "fy_R"]].to_string())
# DS positive at 15m-1h
print("DS cells net>0 at 15m/30m/1h:", int(((C.kind == "ds200") & C.tf.isin(["15m", "30m", "1h"]) & (C.fy_R > 0)).sum()))
print("DS cells net>0 both halves 15m-1h:", C[(C.kind == "ds200") & C.tf.isin(["15m", "30m", "1h"]) & (C.fy_is > 0) & (C.fy_cf > 0)][["strategy", "tf", "fy_n", "fy_is", "fy_cf"]].to_string())

# ------------------------------------------------------------------ rank agreement / positive count
for kind in ("strategy", "ds200"):
    y = C[(C.kind == kind) & (C.tf != "5m") & (C.live_n >= 10)].dropna(subset=["fy_R", "live_R"])
    ra, rb = y.fy_R.rank().to_numpy(), y.live_R.rank().to_numpy()
    rho = np.corrcoef(ra, rb)[0, 1]
    perm = np.array([np.corrcoef(ra, rng.permutation(rb))[0, 1] for _ in range(5000)])
    # expected number of live-positive cells if true mean = 5y mean (normal approx with live SE)
    z = y.live_se.to_numpy(float)
    okz = np.isfinite(z) & (z > 0)
    exp_pos = np.sum([0.5 * (1 + erf(m / (s * sqrt(2)))) for m, s in zip(y.fy_R[okz], z[okz])])
    zz = (y.live_R[okz] - y.fy_R[okz]) / z[okz]
    print(kind, "cells", len(y), "spearman", round(rho, 3), "perm p", float((np.abs(perm) >= abs(rho)).mean()),
          "live positive", int((y.live_R > 0).sum()), "(with SE:", int((y.live_R[okz] > 0).sum()), ") expected", round(exp_pos, 1),
          "z sd", round(float(np.std(zz)), 2), "|z|>2", int((np.abs(zz) > 2).sum()), "of", int(okz.sum()))
