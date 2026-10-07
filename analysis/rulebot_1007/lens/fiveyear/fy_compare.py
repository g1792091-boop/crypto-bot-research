"""Live vs 5-year reconciliation per strategy x timeframe (36 core + 44 DeepSeek + reel 5m).

    python3 -I -B fy_compare.py <work_out_dir> <out_real_dir> <export_dir> <repo>

Inputs (read-only): <work_out_dir>/fy36_<tf>.pkl.gz, fyds_<tf>.pkl.gz (my 5-year per-signal reruns), live_signals.csv,
live_cells.csv; <out_real_dir>/trades_enriched.csv, fiveyear_ref.csv; repo research/deepseek200/out/results.csv,
research/reel5m/out/h1_trades.csv.gz, research/levstop/out/levstop.json; export current/d3_shadows.csv (reel shadows).
Outputs to <work_out_dir>: fiveyear_vs_live.csv (one row per kind x strategy x tf), fy_tf_summary.csv, fy_tf_windows.csv,
fy_volbucket.csv, fy_rank_agreement.csv, fy_top_lists.csv, fy_reel.csv, fy_levstop_check.csv.

Units: R = net pnl / (qty x |fill - initial 2 ATR stop|) = (ROE / leverage) / stop_frac; ret = ROE / leverage = net return
per unit notional. 5-year 'v4n' = paper v4 'normal' leverage (30x/30%, then 20x/20%, $5,000); 'tw' = old tier walk.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.append('/root/.local/lib/python3.11/site-packages')
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

W, RD, EX, REPO = sys.argv[1:5]
NS_DAY = 86_400 * 10 ** 9
S0, S1 = pd.Timestamp("2021-08-01").value, pd.Timestamp("2026-09-30").value
LAST12 = pd.Timestamp("2025-09-30").value
RP_LENS = (0.6986111111111111, 1.5034722222222223)     # v3b, v4 run lengths (days)
V3A_LEN = (2.6075569791666666,)
B = 4000
TFS = ("5m", "15m", "30m", "1h", "4h")
rng = np.random.default_rng(20261007)
STARTS = {L: rng.uniform(S0, S1 - L * NS_DAY, B) for L in set(RP_LENS) | set(V3A_LEN)}


def bh(p, q=0.05):
    p = np.asarray(p, float)
    out = np.full(len(p), np.nan)
    ok = np.isfinite(p)
    if not ok.any():
        return out
    pv = p[ok]
    m = len(pv)
    o = np.argsort(pv)
    ranked = pv[o] * m / np.arange(1, m + 1)
    qv = np.minimum.accumulate(ranked[::-1])[::-1]
    r = np.empty(m)
    r[o] = np.minimum(qv, 1)
    out[ok] = r
    return out


def week_of(ts):
    days = ts // NS_DAY
    return (days + 3) // 7


def cl_mean(x, cl):
    x = np.asarray(x, float)
    ok = np.isfinite(x)
    x, cl = x[ok], np.asarray(cl)[ok]
    n = len(x)
    if n < 3:
        return (x.mean() if n else np.nan), np.nan, n
    mu = x.mean()
    s = pd.Series(x - mu).groupby(cl).sum().to_numpy()
    G = len(s)
    se = np.sqrt((s ** 2).sum() * G / max(G - 1, 1)) / n
    return mu, se, n


class Win:
    """Cumulative sums over time-sorted signals for fast window statistics."""

    def __init__(self, ts, val, valid, extra=None):
        o = np.argsort(ts, kind="stable")
        self.ts = ts[o]
        v = np.where(valid[o], val[o], 0.0)
        self.cs = np.concatenate([[0.0], np.cumsum(v)])
        self.cn = np.concatenate([[0], np.cumsum(valid[o].astype(np.int64))])
        self.extra = None if extra is None else np.concatenate([[0.0], np.cumsum(np.where(valid[o], extra[o], 0.0))])

    def draw(self, lens):
        s = np.zeros(B)
        n = np.zeros(B)
        a = np.zeros(B)
        e = np.zeros(B)
        for L in lens:
            st = STARTS[L]
            i0 = np.searchsorted(self.ts, st)
            i1 = np.searchsorted(self.ts, st + L * NS_DAY)
            s += self.cs[i1] - self.cs[i0]
            n += self.cn[i1] - self.cn[i0]
            a += i1 - i0
            if self.extra is not None:
                e += self.extra[i1] - self.extra[i0]
        with np.errstate(invalid="ignore", divide="ignore"):
            return s / n, n, a, (e / n if self.extra is not None else None)


def pct_of(dist, x):
    d = dist[np.isfinite(dist)]
    if not len(d) or not np.isfinite(x):
        return np.nan, np.nan
    pct = (d < x).mean() + 0.5 * (d == x).mean()
    return pct, min(1.0, 2 * min(pct, 1 - pct))


# ------------------------------------------------------------------ load 5-year
parts = []
meta_days = {}
for tf in TFS:
    d = pd.read_pickle(os.path.join(W, f"fy36_{tf}.pkl.gz"))
    d["kind"] = "strategy"
    parts.append(d)
m36 = pd.read_csv(os.path.join(W, "fy36_meta.csv")).set_index("tf")["days"]
mds = pd.read_csv(os.path.join(W, "fyds_meta.csv")).set_index("tf")["days"]
for tf in ("15m", "30m", "1h", "4h"):
    d = pd.read_pickle(os.path.join(W, f"fyds_{tf}.pkl.gz"))
    d["kind"] = "ds200"
    parts.append(d)
FY = pd.concat(parts, ignore_index=True)
for c in ("strategy", "coin", "tf", "kind"):
    FY[c] = FY[c].astype(str)
FY["ok"] = (FY["v4n_lev"] > 0) & FY["v4n_done"]
FY["okt"] = (FY["tw_lev"] > 0) & FY["tw_done"].fillna(False).astype(bool)
FY["gR"] = FY["v4n_gross"] / FY["stop_frac"]
FY["week"] = week_of(FY["ts"].to_numpy())
print("5y rows", len(FY), flush=True)

LS = pd.read_csv(os.path.join(W, "live_signals.csv"))
LC = pd.read_csv(os.path.join(W, "live_cells.csv"))
# live volatility now: the replay (v3b + v4) stop_frac distribution per tf
live_sf = LS[(LS["source"] == "replay") & (LS["status"] == "TRADED")].groupby("tf")["stop_frac"].quantile([0.1, 0.5, 0.9]).unstack()
live_sf_v3a = LS[(LS["run"] == "v3a")].groupby("tf")["stop_frac"].quantile([0.1, 0.5, 0.9]).unstack()

# ------------------------------------------------------------------ external 5-year references
ref = pd.read_csv(os.path.join(RD, "fiveyear_ref.csv"))
prof = ref[ref["source"] == "profiles_binance"].set_index(["strategy", "timeframe"])
dsr = pd.read_csv(os.path.join(REPO, "research", "deepseek200", "out", "results.csv"))
lv = json.load(open(os.path.join(REPO, "research", "levstop", "out", "levstop.json")))
lv_cols = lv["columns"]

# ------------------------------------------------------------------ per cell
rows = []
cell_keys = sorted(set(zip(FY["kind"], FY["strategy"], FY["tf"])) |
                   set((k, s, t) for k, s, t in zip(LC["kind"], LC["strategy"], LC["tf"]) if k in ("strategy", "ds200")))
G = {k: g for k, g in FY.groupby(["kind", "strategy", "tf"], sort=False)}
for kind, st, tf in cell_keys:
    d = dict(kind=kind, strategy=st, tf=tf)
    g = G.get((kind, st, tf))
    if g is not None and len(g):
        days = (m36 if kind == "strategy" else mds)[tf]
        ok = g["ok"].to_numpy()
        R = g["v4n_R"].to_numpy(float)
        mu, se, n = cl_mean(R[ok], g["week"].to_numpy()[ok])
        win = g["win"].to_numpy()
        ts = g["ts"].to_numpy()
        sf = g["stop_frac"].to_numpy(float)
        d.update(fy_signals=len(g), fy_per_day=len(g) / days, fy_sized_share=ok.mean(), fy_n=n,
                 fy_mean_R=mu, fy_se_R_week=se, fy_t=mu / se if se and se > 0 else np.nan,
                 fy_is_mean_R=np.nanmean(R[ok & (win == 0)]) if (ok & (win == 0)).any() else np.nan,
                 fy_cf_mean_R=np.nanmean(R[ok & (win == 1)]) if (ok & (win == 1)).any() else np.nan,
                 fy_last12_mean_R=np.nanmean(R[ok & (ts >= LAST12)]) if (ok & (ts >= LAST12)).any() else np.nan,
                 fy_last12_n=int((ok & (ts >= LAST12)).sum()),
                 fy_win_pct=100 * (R[ok] > 0).mean() if ok.any() else np.nan,
                 fy_mean_ret=np.nanmean(g["v4n_ret"].to_numpy(float)[ok]) if ok.any() else np.nan,
                 fy_gross_R=np.nanmean(g["gR"].to_numpy(float)[ok]) if ok.any() else np.nan,
                 fy_median_stop_frac=np.median(sf[ok]) if ok.any() else np.nan,
                 fy_mean_hold_bars=np.nanmean(g["v4n_held"].to_numpy(float)[ok]) if ok.any() else np.nan)
        d["fy_cost_R"] = d["fy_gross_R"] - d["fy_mean_R"]
        # 5-year mean at today's volatility: signals whose stop_frac is inside the live p10..p90 range of this tf
        if tf in live_sf.index:
            lo_, hi_ = live_sf.loc[tf, 0.1], live_sf.loc[tf, 0.9]
        elif tf in live_sf_v3a.index:
            lo_, hi_ = live_sf_v3a.loc[tf, 0.1], live_sf_v3a.loc[tf, 0.9]
        else:
            lo_ = hi_ = np.nan
        q = ok & (sf >= lo_) & (sf <= hi_)
        d["fy_nowvol_n"] = int(q.sum())
        d["fy_nowvol_mean_R"] = np.nanmean(R[q]) if q.any() else np.nan
        d["fy_nowvol_gross_R"] = np.nanmean(g["gR"].to_numpy(float)[q]) if q.any() else np.nan
        if kind == "strategy":
            okt = g["okt"].to_numpy()
            d.update(fy_tw_n=int(okt.sum()), fy_tw_mean_R=np.nanmean(g["tw_R"].to_numpy(float)[okt]) if okt.any() else np.nan,
                     fy_tw_mean_roe=np.nanmean(g["tw_roe"].to_numpy(float)[okt]) if okt.any() else np.nan,
                     fy_tw_mean_ret=np.nanmean(g["tw_ret"].to_numpy(float)[okt]) if okt.any() else np.nan)
            cell = lv["cells"].get(f"{st}|{tf}", {}).get("30|2.0")
            if cell:
                d["levstop_30x_mean_ret"] = cell[lv_cols.index("mean_roe")] / 30.0
                d["levstop_30x_p_pos"] = cell[lv_cols.index("p_pos")]
            if (st, tf) in prof.index:
                p = prof.loc[(st, tf)]
                d.update(prof_mean_roe=p["mean_roe"], prof_mean_roe_t=p["mean_roe_t"], prof_ret_notional=p["mean_ret_notional"],
                         prof_per_day=p["per_day"], prof_is_mean_roe=p["mean_roe_is"], prof_cf_mean_roe=p["mean_roe_cf"])
        else:
            for x in ("X5_TRAIL2", "X2_SL15_TP3"):
                r = dsr[(dsr["tf"] == tf) & (dsr["entry"] == st) & (dsr["exit"] == x)]
                if len(r):
                    r = r.iloc[0]
                    d.update({f"prereg_{x}_is_mean_pct": r["is_mean_pct"], f"prereg_{x}_cf_mean_pct": r["cf_mean_pct"],
                              f"prereg_{x}_pre_mean_pct": r["pre_mean_pct"], f"prereg_{x}_is_gross_pct": r["is_gross_mean_pct"],
                              f"prereg_{x}_cf_gross_pct": r["cf_gross_mean_pct"], f"prereg_{x}_stage1": bool(r["stage1"]),
                              f"prereg_{x}_candidate": bool(r["candidate"]), f"prereg_{x}_trades_per_day": (r["is_n"] + r["cf_n"]) / days})
        # ---------------- windows: live replay (v3b + v4) and v3a
        lc = LC[(LC["kind"] == kind) & (LC["strategy"] == st) & (LC["tf"] == tf)]
        lc = lc.iloc[0] if len(lc) else None
        wv = Win(ts, R, ok)
        if lc is not None:
            runs = str(lc["runs"]).split()
            lens = tuple(L for L, lab in zip(RP_LENS, ("v3b", "v4")) if lab in runs)
            if lens:
                mR, nR, nA, _ = wv.draw(lens)
                live_cnt = np.nansum([lc.get("sig_v3b", np.nan) if "v3b" in runs else 0, lc.get("sig_v4", np.nan) if "v4" in runs else 0])
                pc, p2 = pct_of(mR[nR > 0], lc["rp_mean_R"]) if lc["rp_n"] > 0 else (np.nan, np.nan)
                fpc, fp2 = pct_of(nA, live_cnt)
                d.update(win_rp_lens="+".join(f"{x:.2f}" for x in lens), win_rp_share_nonempty=(nR > 0).mean(),
                         win_rp_p05=np.nanpercentile(mR[nR > 0], 5) if (nR > 0).any() else np.nan,
                         win_rp_p50=np.nanpercentile(mR[nR > 0], 50) if (nR > 0).any() else np.nan,
                         win_rp_p95=np.nanpercentile(mR[nR > 0], 95) if (nR > 0).any() else np.nan,
                         win_rp_pct_live=pc, win_rp_p_two=p2,
                         win_rp_cnt_p05=np.percentile(nA, 5), win_rp_cnt_p50=np.percentile(nA, 50), win_rp_cnt_p95=np.percentile(nA, 95),
                         live_rp_signals=live_cnt, win_rp_cnt_pct_live=fpc, win_rp_cnt_p_two=fp2)
            if "v3a" in runs and kind == "strategy":
                okt = g["okt"].to_numpy()
                wt = Win(ts, g["tw_R"].to_numpy(float), okt)
                mR, nR, nA, _ = wt.draw(V3A_LEN)
                pc, p2 = pct_of(mR[nR > 0], lc["v3a_mean_R"]) if lc["v3a_n"] > 0 else (np.nan, np.nan)
                fpc, fp2 = pct_of(nA, lc.get("sig_v3a", np.nan))
                d.update(win_v3a_p05=np.nanpercentile(mR[nR > 0], 5) if (nR > 0).any() else np.nan,
                         win_v3a_p50=np.nanpercentile(mR[nR > 0], 50) if (nR > 0).any() else np.nan,
                         win_v3a_p95=np.nanpercentile(mR[nR > 0], 95) if (nR > 0).any() else np.nan,
                         win_v3a_pct_live=pc, win_v3a_p_two=p2, win_v3a_cnt_p50=np.percentile(nA, 50),
                         win_v3a_cnt_pct_live=fpc, win_v3a_cnt_p_two=fp2)
    lc = LC[(LC["kind"] == kind) & (LC["strategy"] == st) & (LC["tf"] == tf)]
    if len(lc):
        lc = lc.iloc[0]
        for c in ("runs", "rp_n", "rp_clusters", "rp_mean_R", "rp_se_R", "rp_mean_ret", "rp_win_pct", "rp_unresolved",
                  "rp_mean_R_incl_mark", "rp_rejected_sizing", "v3a_n", "v3a_clusters", "v3a_mean_R", "v3a_se_R", "v3a_mean_ret",
                  "all_n", "all_mean_R", "all_se_R", "entered_n", "entered_mean_R", "entered_mean_ret",
                  "sig_v3a", "sig_v3b", "sig_v4", "live_days", "live_signals_per_day", "rp_median_stop_frac"):
            d["live_" + c if not c.startswith("live_") else c] = lc[c]
    rows.append(d)
T = pd.DataFrame(rows)
print("cells", len(T), flush=True)

# ------------------------------------------------------------------ derived columns, multiple testing
T["freq_ratio_live_vs_5y"] = T["live_signals_per_day"] / T["fy_per_day"]
T["live_rp_t"] = T["live_rp_mean_R"] / T["live_rp_se_R"]
T["live_v3a_t"] = T["live_v3a_mean_R"] / T["live_v3a_se_R"]
for k in ("strategy", "ds200"):
    m = T["kind"] == k
    T.loc[m, "win_rp_q_bh"] = bh(T.loc[m, "win_rp_p_two"].to_numpy())
    T.loc[m, "win_rp_cnt_q_bh"] = bh(T.loc[m, "win_rp_cnt_p_two"].to_numpy())
    T.loc[m, "win_v3a_q_bh"] = bh(T.loc[m, "win_v3a_p_two"].to_numpy())
    T.loc[m, "win_v3a_cnt_q_bh"] = bh(T.loc[m, "win_v3a_cnt_p_two"].to_numpy())
    # 5-year one-sided p of mean R > 0 (week-clustered normal approx), BH over the cells of the kind
    from math import erf, sqrt
    z = T.loc[m, "fy_t"].to_numpy(float)
    T.loc[m, "fy_p_pos"] = [0.5 * (1 - erf(x / sqrt(2))) if np.isfinite(x) else np.nan for x in z]
    T.loc[m, "fy_q_pos"] = bh(T.loc[m, "fy_p_pos"].to_numpy())


def fy_class(r):
    if not np.isfinite(r.get("fy_mean_R", np.nan)) or r.get("fy_n", 0) < 30:
        return "fy_thin"
    t, mu = r["fy_t"], r["fy_mean_R"]
    halves_pos = (r["fy_is_mean_R"] > 0) and (r["fy_cf_mean_R"] > 0)
    if mu > 0 and halves_pos:
        return "P"                    # net positive, both halves
    if np.isfinite(t) and t <= -2:
        return "N_gross+" if r["fy_gross_R"] > 0 else "NN"
    return "Z"                        # not distinguishable from zero after costs (|t| < 2 or halves disagree)


def live_sample(r):
    """Main live every-signal sample: replay (v3b + v4) for 15m..4h, v3a (tier walk) for 5m."""
    if r["tf"] == "5m":
        return r.get("live_v3a_n", 0) or 0, r.get("live_v3a_mean_R", np.nan), r.get("live_v3a_se_R", np.nan)
    return r.get("live_rp_n", 0) or 0, r.get("live_rp_mean_R", np.nan), r.get("live_rp_se_R", np.nan)


def live_class(r):
    n, mu, se = live_sample(r)
    if not n or n < 15 or not np.isfinite(mu):
        return "L_thin"
    if np.isfinite(se) and mu + 2 * se < 0:
        return "L--"
    if np.isfinite(se) and mu - 2 * se > 0:
        return "L++"
    return "L+" if mu > 0 else "L-"


GRADE = {("P", "L++"): "A", ("P", "L+"): "A", ("P", "L-"): "B", ("P", "L_thin"): "B", ("P", "L--"): "C",
         ("Z", "L++"): "B", ("Z", "L+"): "B", ("Z", "L-"): "C", ("Z", "L_thin"): "C", ("Z", "L--"): "D",
         ("N_gross+", "L++"): "C", ("N_gross+", "L+"): "C", ("N_gross+", "L-"): "D", ("N_gross+", "L_thin"): "D", ("N_gross+", "L--"): "F",
         ("NN", "L++"): "D", ("NN", "L+"): "D", ("NN", "L-"): "F", ("NN", "L_thin"): "F", ("NN", "L--"): "F"}
T["fy_class"] = T.apply(fy_class, axis=1)
T["live_class"] = T.apply(live_class, axis=1)
T["grade"] = [GRADE.get((a, b), "n/a") for a, b in zip(T["fy_class"], T["live_class"])]
T["live_sample_n"] = [live_sample(r)[0] for _, r in T.iterrows()]
T["live_sample_mean_R"] = [live_sample(r)[1] for _, r in T.iterrows()]
T = T.sort_values(["kind", "tf", "grade", "fy_mean_R"], ascending=[True, True, True, False])
T.to_csv(os.path.join(W, "fiveyear_vs_live.csv"), index=False)

# ------------------------------------------------------------------ tf level (pooled over strategies of a kind)
tfrows, wrows = [], []
for kind in ("strategy", "ds200"):
    for tf in TFS:
        g = FY[(FY["kind"] == kind) & (FY["tf"] == tf)]
        if not len(g):
            continue
        ok = g["ok"].to_numpy()
        R = g["v4n_R"].to_numpy(float)
        sf = g["stop_frac"].to_numpy(float)
        mu, se, n = cl_mean(R[ok], g["week"].to_numpy()[ok])
        days = (m36 if kind == "strategy" else mds)[tf]
        d = dict(kind=kind, tf=tf, fy_signals=len(g), fy_per_day=len(g) / days, fy_sized_share=ok.mean(), fy_mean_R=mu, fy_t=mu / se,
                 fy_is_mean_R=np.nanmean(R[ok & (g["win"].to_numpy() == 0)]), fy_cf_mean_R=np.nanmean(R[ok & (g["win"].to_numpy() == 1)]),
                 fy_last12_mean_R=np.nanmean(R[ok & (g["ts"].to_numpy() >= LAST12)]),
                 fy_gross_R=np.nanmean(g["gR"].to_numpy(float)[ok]), fy_win_pct=100 * (R[ok] > 0).mean(),
                 fy_median_stop_frac=np.median(sf[ok]), fy_mean_ret=np.nanmean(g["v4n_ret"].to_numpy(float)[ok]),
                 fy_cells=g["strategy"].nunique(),
                 fy_cells_pos=int((g[ok].groupby("strategy")["v4n_R"].mean() > 0).sum()))
        d["fy_cost_R"] = d["fy_gross_R"] - d["fy_mean_R"]
        if kind == "strategy":
            okt = g["okt"].to_numpy()
            d["fy_tw_mean_R"] = np.nanmean(g["tw_R"].to_numpy(float)[okt])
        ls = LS[(LS["kind"] == kind) & (LS["tf"] == tf) & (LS["status"] == "TRADED")]
        rp = ls[ls["source"] == "replay"]
        v3 = ls[ls["run"] == "v3a"]
        for lab, x in (("rp", rp), ("v3a", v3)):
            m_, s_, n_ = cl_mean(x["R"].to_numpy(float), x["cluster"].to_numpy())
            d.update({f"live_{lab}_n": n_, f"live_{lab}_mean_R": m_, f"live_{lab}_se_R": s_,
                      f"live_{lab}_median_stop_frac": x["stop_frac"].median() if len(x) else np.nan})
        # nowvol: 5-year signals inside the live p10..p90 stop_frac range
        src = live_sf if tf in live_sf.index else live_sf_v3a
        if tf in src.index:
            q = ok & (sf >= src.loc[tf, 0.1]) & (sf <= src.loc[tf, 0.9])
            d["fy_nowvol_mean_R"] = np.nanmean(R[q])
            d["fy_nowvol_gross_R"] = np.nanmean(g["gR"].to_numpy(float)[q])
            d["fy_nowvol_share_of_signals"] = q.sum() / ok.sum()
        # windows: pooled live replay vs pooled 5-year windows; regime-matched by window mean stop_frac
        for lab, lens, col, okc, live_df in (("rp", RP_LENS, "v4n_R", ok, rp), ("v3a", V3A_LEN, "tw_R", g["okt"].to_numpy() if kind == "strategy" else None, v3)):
            if okc is None or not len(live_df):
                continue
            wv = Win(g["ts"].to_numpy(), g[col].to_numpy(float), okc, extra=sf)
            mR, nR, nA, msf = wv.draw(lens)
            live_mu = live_df["R"].mean()
            live_msf = live_df["stop_frac"].mean()
            pc, p2 = pct_of(mR[nR > 0], live_mu)
            match = (nR > 0) & (np.abs(msf / live_msf - 1) <= 0.15)
            pcm, p2m = pct_of(mR[match], live_mu)
            nlive = len(live_df)
            wrows.append(dict(kind=kind, tf=tf, sample=lab, live_n=nlive, live_mean_R=live_mu, live_mean_stop_frac=live_msf,
                              win_p05=np.nanpercentile(mR[nR > 0], 5), win_p50=np.nanpercentile(mR[nR > 0], 50),
                              win_p95=np.nanpercentile(mR[nR > 0], 95), win_mean_n=nR.mean(), pct_live=pc, p_two=p2,
                              win_mean_stop_frac_p50=np.nanpercentile(msf[nR > 0], 50),
                              live_stop_frac_pct_in_5y_windows=pct_of(msf[nR > 0], live_msf)[0],
                              matched_windows=int(match.sum()),
                              matched_p05=np.nanpercentile(mR[match], 5) if match.any() else np.nan,
                              matched_p50=np.nanpercentile(mR[match], 50) if match.any() else np.nan,
                              matched_p95=np.nanpercentile(mR[match], 95) if match.any() else np.nan,
                              matched_pct_live=pcm, matched_p_two=p2m))
        tfrows.append(d)
TF = pd.DataFrame(tfrows)
TF.to_csv(os.path.join(W, "fy_tf_summary.csv"), index=False)
TW = pd.DataFrame(wrows)
TW.to_csv(os.path.join(W, "fy_tf_windows.csv"), index=False)

# ------------------------------------------------------------------ volatility buckets (5-year, pooled per kind x tf)
vb = []
for (kind, tf), g in FY[FY["ok"]].groupby(["kind", "tf"]):
    qs = np.quantile(g["stop_frac"], [0, 0.2, 0.4, 0.6, 0.8, 1.0])
    b_ = np.clip(np.searchsorted(qs, g["stop_frac"], side="right") - 1, 0, 4)
    for k_ in range(5):
        x = g[b_ == k_]
        vb.append(dict(kind=kind, tf=tf, stop_frac_quintile=k_ + 1, sf_lo=qs[k_], sf_hi=qs[k_ + 1], n=len(x),
                       mean_R=x["v4n_R"].mean(), gross_R=x["gR"].mean(), cost_R=x["gR"].mean() - x["v4n_R"].mean(),
                       win_pct=100 * (x["v4n_R"] > 0).mean()))
pd.DataFrame(vb).to_csv(os.path.join(W, "fy_volbucket.csv"), index=False)

# ------------------------------------------------------------------ rank agreement across cells (5y vs live)
ag = []
for kind in ("strategy", "ds200"):
    for tfset in (("15m", "30m"), ("1h", "4h"), ("15m", "30m", "1h", "4h"), ("5m",)):
        x = T[(T["kind"] == kind) & T["tf"].isin(tfset)]
        if tfset == ("5m",):
            x = x[(x["live_v3a_n"] >= 10)]
            a, b = x["fy_tw_mean_R"].to_numpy(float), x["live_v3a_mean_R"].to_numpy(float)
            lab = "v3a"
        else:
            x = x[(x["live_rp_n"] >= 10)]
            a, b = x["fy_mean_R"].to_numpy(float), x["live_rp_mean_R"].to_numpy(float)
            lab = "rp"
        ok = np.isfinite(a) & np.isfinite(b)
        a, b = a[ok], b[ok]
        if len(a) < 5:
            continue
        ra, rb = pd.Series(a).rank().to_numpy(), pd.Series(b).rank().to_numpy()
        rho = np.corrcoef(ra, rb)[0, 1]
        perm = np.array([np.corrcoef(ra, rng.permutation(rb))[0, 1] for _ in range(5000)])
        ag.append(dict(kind=kind, tfs="+".join(tfset), live_sample=lab, cells=len(a), spearman=rho,
                       p_perm_two=float((np.abs(perm) >= abs(rho)).mean()),
                       sign_5y_neg=int((a < 0).sum()), sign_live_neg=int((b < 0).sum()),
                       both_neg=int(((a < 0) & (b < 0)).sum()), both_pos=int(((a > 0) & (b > 0)).sum()),
                       fy_pos_live_neg=int(((a > 0) & (b < 0)).sum()), fy_neg_live_pos=int(((a < 0) & (b > 0)).sum())))
    # v3a vs replay agreement (live out-of-sample across runs), same cells
    x = T[(T["kind"] == kind) & (T["live_v3a_n"] >= 10) & (T["live_rp_n"] >= 10)]
    if len(x) >= 5:
        a, b = x["live_v3a_mean_R"].to_numpy(float), x["live_rp_mean_R"].to_numpy(float)
        ra, rb = pd.Series(a).rank().to_numpy(), pd.Series(b).rank().to_numpy()
        rho = np.corrcoef(ra, rb)[0, 1]
        perm = np.array([np.corrcoef(ra, rng.permutation(rb))[0, 1] for _ in range(5000)])
        ag.append(dict(kind=kind, tfs="15m..4h", live_sample="v3a_vs_rp", cells=len(a), spearman=rho,
                       p_perm_two=float((np.abs(perm) >= abs(rho)).mean()), sign_5y_neg=int((a < 0).sum()),
                       sign_live_neg=int((b < 0).sum()), both_neg=int(((a < 0) & (b < 0)).sum()),
                       both_pos=int(((a > 0) & (b > 0)).sum()), fy_pos_live_neg=int(((a > 0) & (b < 0)).sum()),
                       fy_neg_live_pos=int(((a < 0) & (b > 0)).sum())))
pd.DataFrame(ag).to_csv(os.path.join(W, "fy_rank_agreement.csv"), index=False)

# ------------------------------------------------------------------ top lists
tl = []
for kind in ("strategy", "ds200"):
    for grp, tfset in (("15m/30m", ("15m", "30m")), ("1h/4h", ("1h", "4h"))):
        x = T[(T["kind"] == kind) & T["tf"].isin(tfset) & (T["fy_n"] >= 100)]
        for _, r in x.sort_values("fy_mean_R", ascending=False).head(10).iterrows():
            tl.append(dict(list="5y_best", kind=kind, group=grp, strategy=r["strategy"], tf=r["tf"], fy_mean_R=r["fy_mean_R"], fy_t=r["fy_t"],
                           fy_gross_R=r["fy_gross_R"], live_rp_n=r.get("live_rp_n"), live_rp_mean_R=r.get("live_rp_mean_R"), grade=r["grade"]))
        y = T[(T["kind"] == kind) & T["tf"].isin(tfset) & (T["live_rp_n"] >= 15)]
        for _, r in y.sort_values("live_rp_mean_R", ascending=False).head(10).iterrows():
            tl.append(dict(list="live_best", kind=kind, group=grp, strategy=r["strategy"], tf=r["tf"], fy_mean_R=r["fy_mean_R"], fy_t=r["fy_t"],
                           fy_gross_R=r["fy_gross_R"], live_rp_n=r.get("live_rp_n"), live_rp_mean_R=r.get("live_rp_mean_R"), grade=r["grade"]))
        for _, r in y.sort_values("live_rp_mean_R", ascending=True).head(5).iterrows():
            tl.append(dict(list="live_worst", kind=kind, group=grp, strategy=r["strategy"], tf=r["tf"], fy_mean_R=r["fy_mean_R"], fy_t=r["fy_t"],
                           fy_gross_R=r["fy_gross_R"], live_rp_n=r.get("live_rp_n"), live_rp_mean_R=r.get("live_rp_mean_R"), grade=r["grade"]))
pd.DataFrame(tl).to_csv(os.path.join(W, "fy_top_lists.csv"), index=False)

# ------------------------------------------------------------------ levstop cross-check (fixed 30x, no sizing checks)
x = T[(T["kind"] == "strategy") & T["levstop_30x_mean_ret"].notna() & T["fy_mean_ret"].notna()]
pd.DataFrame([dict(cells=len(x), corr=np.corrcoef(x["levstop_30x_mean_ret"], x["fy_mean_ret"])[0, 1],
                   median_abs_diff=np.median(np.abs(x["levstop_30x_mean_ret"] - x["fy_mean_ret"])),
                   mean_levstop=x["levstop_30x_mean_ret"].mean(), mean_mine=x["fy_mean_ret"].mean())]).to_csv(
    os.path.join(W, "fy_levstop_check.csv"), index=False)

# ------------------------------------------------------------------ reel 5m
rt = pd.read_csv(os.path.join(REPO, "research", "reel5m", "out", "h1_trades.csv.gz"))
rt = rt[rt["split"].isin(["is", "oos"])].copy()
rt["ts"] = pd.to_datetime(rt["entry_ts"]).astype("int64")
te = pd.read_csv(os.path.join(RD, "trades_enriched.csv"))
lr = te[te["kind"] == "reel"]
sh = pd.read_csv(os.path.join(EX, "current", "d3_shadows.csv"))
sh = sh[(sh["kind"] == "skipped") & sh["account_id"].astype(str).str.startswith("REEL")].drop_duplicates("key")
sh_ret = (sh["roe"] / 30.0).dropna()          # the reel account trades at 30x (all 13 trades: 30x)
live_ret = np.concatenate([lr["roe_per_lev"].to_numpy(float), sh_ret.to_numpy(float)])
wv = Win(rt["ts"].to_numpy(), rt["net"].to_numpy(float), np.ones(len(rt), bool))
mR, nR, nA, _ = wv.draw((1.5034722222222223,))
pc, p2 = pct_of(mR[nR > 0], live_ret.mean())
wr = Win(rt["ts"].to_numpy(), rt["r_net"].to_numpy(float), np.ones(len(rt), bool))
mRr, nRr, _, _ = wr.draw((1.5034722222222223,))
pcr, p2r = pct_of(mRr[nRr > 0], lr["R"].mean())
days_reel = (pd.Timestamp("2026-09-30") - pd.Timestamp("2021-08-01")).days
reel = dict(fy_trades=len(rt), fy_trades_per_day=len(rt) / days_reel, fy_mean_net_ret=rt["net"].mean(), fy_mean_gross_ret=rt["gross"].mean(),
            fy_mean_r_net=rt["r_net"].mean(), fy_is_mean_net=rt.loc[rt["split"] == "is", "net"].mean(),
            fy_cf_mean_net=rt.loc[rt["split"] == "oos", "net"].mean(), fy_win_pct=100 * (rt["net"] > 0).mean(),
            fy_median_sl_dist=rt["sl_dist"].median(),
            live_trades=len(lr), live_mean_R=lr["R"].mean(), live_mean_ret=lr["roe_per_lev"].mean(), live_win_pct=100 * (lr["pnl"] > 0).mean(),
            live_shadow_n=len(sh_ret), live_all_n=len(live_ret), live_all_mean_ret=live_ret.mean(),
            live_signals_per_day=(len(lr) + len(sh)) / 1.5034722222222223,
            win_ret_p05=np.nanpercentile(mR[nR > 0], 5), win_ret_p50=np.nanpercentile(mR[nR > 0], 50), win_ret_p95=np.nanpercentile(mR[nR > 0], 95),
            win_ret_pct_live=pc, win_ret_p_two=p2, win_cnt_p50=np.percentile(nA, 50),
            win_rnet_p05=np.nanpercentile(mRr[nRr > 0], 5), win_rnet_p95=np.nanpercentile(mRr[nRr > 0], 95),
            win_rnet_pct_live_trades=pcr, win_rnet_p_two=p2r,
            live_median_stop_frac=lr["stop_frac"].median())
pd.DataFrame([reel]).to_csv(os.path.join(W, "fy_reel.csv"), index=False)
print("done")
