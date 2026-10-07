"""Extra 5-year checks: in-sample vs out-of-sample persistence across cells, heterogeneity of gross edge, frequency
agreement, cell-level window outliers, DeepSeek PREREG vs house exits, leverage arms (levstop), equity drain.

    python3 -I -B fy_extra.py <work_out_dir> <repo>
"""
import json
import os
import sys

sys.path.append('/root/.local/lib/python3.11/site-packages')
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

W, REPO = sys.argv[1:3]
NS_DAY = 86_400 * 10 ** 9
rng = np.random.default_rng(11)
out = {}


def cl_t(x, cl):
    x = np.asarray(x, float)
    n = len(x)
    if n < 10:
        return np.nan, np.nan
    mu = x.mean()
    s = pd.Series(x - mu).groupby(cl).sum().to_numpy()
    G = len(s)
    se = np.sqrt((s ** 2).sum() * G / max(G - 1, 1)) / n
    return mu, mu / se if se > 0 else np.nan


def spearman_perm(a, b, B=5000):
    ra, rb = pd.Series(a).rank().to_numpy(), pd.Series(b).rank().to_numpy()
    rho = np.corrcoef(ra, rb)[0, 1]
    perm = np.array([np.corrcoef(ra, rng.permutation(rb))[0, 1] for _ in range(B)])
    return rho, float((np.abs(perm) >= abs(rho)).mean())


parts = []
for tf in ("5m", "15m", "30m", "1h", "4h"):
    d = pd.read_pickle(os.path.join(W, f"fy36_{tf}.pkl.gz"))
    d["kind"] = "strategy"
    parts.append(d[["kind", "strategy", "coin", "tf", "ts", "win", "stop_frac", "v4n_lev", "v4n_done", "v4n_R", "v4n_gross"]])
for tf in ("15m", "30m", "1h", "4h"):
    d = pd.read_pickle(os.path.join(W, f"fyds_{tf}.pkl.gz"))
    d["kind"] = "ds200"
    parts.append(d[["kind", "strategy", "coin", "tf", "ts", "win", "stop_frac", "v4n_lev", "v4n_done", "v4n_R", "v4n_gross"]])
FY = pd.concat(parts, ignore_index=True)
for c in ("kind", "strategy", "coin", "tf"):
    FY[c] = FY[c].astype(str)
FY = FY[(FY["v4n_lev"] > 0) & FY["v4n_done"]].copy()
FY["gR"] = FY["v4n_gross"] / FY["stop_frac"]
FY["week"] = ((FY["ts"] // NS_DAY) + 3) // 7

# ---------------- per cell IS / CF (net and gross) + gross t
rows = []
for (k, s, tf), g in FY.groupby(["kind", "strategy", "tf"]):
    r = dict(kind=k, strategy=s, tf=tf, n=len(g))
    for lab, sel in (("is", g["win"] == 0), ("cf", g["win"] == 1)):
        x = g[sel]
        r[f"{lab}_n"] = len(x)
        r[f"{lab}_R"] = x["v4n_R"].mean() if len(x) else np.nan
        r[f"{lab}_gR"] = x["gR"].mean() if len(x) else np.nan
    mu, t = cl_t(g["gR"].to_numpy(), g["week"].to_numpy())
    r["gross_R"], r["gross_t"] = mu, t
    rows.append(r)
C = pd.DataFrame(rows)
C.to_csv(os.path.join(W, "fy_cells_is_cf.csv"), index=False)
pers = []
for k in ("strategy", "ds200"):
    for tf in ("5m", "15m", "30m", "1h", "4h"):
        x = C[(C["kind"] == k) & (C["tf"] == tf) & (C["is_n"] >= 200) & (C["cf_n"] >= 200)]
        if len(x) < 8:
            continue
        rho_g, p_g = spearman_perm(x["is_gR"], x["cf_gR"])
        rho_n, p_n = spearman_perm(x["is_R"], x["cf_R"])
        t = C[(C["kind"] == k) & (C["tf"] == tf) & (C["n"] >= 200)]["gross_t"].dropna()
        pers.append(dict(kind=k, tf=tf, cells=len(x), spearman_is_cf_gross=rho_g, p_gross=p_g, spearman_is_cf_net=rho_n, p_net=p_n,
                         cells_t=len(t), var_gross_t=t.var(), share_abs_gross_t_gt2=(t.abs() > 2).mean(),
                         cells_gross_t_gt2=int((t > 2).sum()), cells_gross_t_lt_m2=int((t < -2).sum()),
                         is_cf_both_gross_pos=int(((x["is_gR"] > 0) & (x["cf_gR"] > 0)).sum()),
                         is_cf_both_net_pos=int(((x["is_R"] > 0) & (x["cf_R"] > 0)).sum())))
P = pd.DataFrame(pers)
P.to_csv(os.path.join(W, "fy_is_cf_persistence.csv"), index=False)
print(P.round(3).to_string())

# ---------------- which cells have a clearly positive GROSS edge (BH 5% over cells with n >= 200)
from math import erf, sqrt  # noqa: E402
x = C[C["n"] >= 200].copy()
x["p_gross_pos"] = [0.5 * (1 - erf(t / sqrt(2))) if np.isfinite(t) else np.nan for t in x["gross_t"]]
p = x["p_gross_pos"].to_numpy()
o = np.argsort(p)
m = len(p)
q = np.empty(m)
q[o] = np.minimum.accumulate((p[o] * m / np.arange(1, m + 1))[::-1])[::-1]
x["q_gross_pos"] = np.minimum(q, 1)
x.sort_values("gross_t", ascending=False).head(25).to_csv(os.path.join(W, "fy_gross_top.csv"), index=False)
print(x.sort_values("gross_t", ascending=False).head(15)[["kind", "strategy", "tf", "n", "gross_R", "gross_t", "is_gR", "cf_gR", "is_R", "cf_R", "q_gross_pos"]].round(3).to_string())
print("cells n>=200:", m, " BH q<0.05 gross>0:", int((x["q_gross_pos"] < 0.05).sum()), " q<0.10:", int((x["q_gross_pos"] < 0.10).sum()))

# ---------------- levstop: per tf pooled mean ret per notional by leverage arm (2.0 ATR) and the tier walk
lv = json.load(open(os.path.join(REPO, "research", "levstop", "out", "levstop.json")))
cols = lv["columns"]
lr = []
for key, arms in lv["cells"].items():
    st, tf = key.split("|")
    for arm, v in arms.items():
        if not v:
            continue
        lev, k = arm.split("|")
        if k != "2.0":
            continue
        L = 40.0 if lev == "tiers" else float(lev)
        lr.append(dict(strategy=st, tf=tf, arm=lev, trades=v[cols.index("trades")], mean_roe=v[cols.index("mean_roe")],
                       mean_eq=v[cols.index("mean_eq")], liq_share=v[cols.index("liq_share")], bust_p1=v[cols.index("bust_p1")],
                       bust_p2=v[cols.index("bust_p2")], mult_p2=v[cols.index("mult_p2")]))
LR = pd.DataFrame(lr)
for c in ("trades", "mean_roe", "mean_eq", "liq_share", "bust_p1", "bust_p2", "mult_p2"):
    LR[c] = pd.to_numeric(LR[c], errors="coerce")
LR = LR.dropna(subset=["mean_roe", "trades"])
LR["ret"] = np.where(LR["arm"] == "tiers", np.nan, LR["mean_roe"] / pd.to_numeric(LR["arm"], errors="coerce"))
agg = LR.groupby(["tf", "arm"]).apply(lambda g: pd.Series(dict(
    cells=len(g), trades=g["trades"].sum(), mean_ret_w=np.average(g["ret"], weights=g["trades"]) if g["ret"].notna().all() else np.nan,
    mean_ret_unw=g["ret"].mean(),
    mean_roe_w=np.average(g["mean_roe"], weights=g["trades"]), mean_eq_w=np.average(g["mean_eq"], weights=g["trades"]),
    liq_share_w=np.average(g["liq_share"].fillna(0), weights=g["trades"]), busts=int(g["bust_p1"].fillna(0).sum() + g["bust_p2"].fillna(0).sum()),
    accounts=2 * len(g), median_mult_p2=g["mult_p2"].median())), include_groups=False).reset_index()
agg.to_csv(os.path.join(W, "fy_levstop_arms.csv"), index=False)
print(agg.round(5).to_string())

# ---------------- equity drain per trade at the AI bot's leverage range (zero-edge expectancy x leverage x margin)
TF = pd.read_csv(os.path.join(W, "fy_tf_summary.csv"))
dr = []
for _, r in TF.iterrows():
    for L, mf in ((20, 0.20), (30, 0.30), (40, 0.40), (50, 0.50)):
        for lab, ret in (("all_5y", r["fy_mean_ret"]),):
            dr.append(dict(kind=r["kind"], tf=r["tf"], lev=L, margin_frac=mf, ret_per_notional=ret,
                           equity_change_per_trade=ret * L * mf, trades_to_halve=np.log(0.5) / np.log(1 + ret * L * mf)))
pd.DataFrame(dr).to_csv(os.path.join(W, "fy_equity_drain.csv"), index=False)

# ---------------- DeepSeek: PREREG exits vs house exits per cell (both 5-year)
T = pd.read_csv(os.path.join(W, "fiveyear_vs_live.csv"))
ds = T[T["kind"] == "ds200"].copy()
ds["prereg_x5_mean_pct"] = (ds["prereg_X5_TRAIL2_is_mean_pct"] + ds["prereg_X5_TRAIL2_cf_mean_pct"]) / 2
ds["prereg_x2_mean_pct"] = (ds["prereg_X2_SL15_TP3_is_mean_pct"] + ds["prereg_X2_SL15_TP3_cf_mean_pct"]) / 2
ds["house_mean_pct"] = 100 * ds["fy_mean_ret"]
res = []
for tf, g in ds.groupby("tf"):
    g = g.dropna(subset=["prereg_x5_mean_pct", "house_mean_pct"])
    if len(g) < 5:
        continue
    r1, p1 = spearman_perm(g["prereg_x5_mean_pct"], g["house_mean_pct"])
    r2, p2 = spearman_perm(g["prereg_x2_mean_pct"], g["house_mean_pct"])
    res.append(dict(tf=tf, cells=len(g), house_mean_pct=g["house_mean_pct"].mean(), prereg_x5_mean_pct=g["prereg_x5_mean_pct"].mean(),
                    prereg_x2_mean_pct=g["prereg_x2_mean_pct"].mean(), spearman_x5_vs_house=r1, p_x5=p1, spearman_x2_vs_house=r2, p_x2=p2,
                    house_pos=int((g["house_mean_pct"] > 0).sum()), x5_pos=int((g["prereg_x5_mean_pct"] > 0).sum()),
                    x2_pos=int((g["prereg_x2_mean_pct"] > 0).sum()),
                    stage1_x5=int((g["prereg_X5_TRAIL2_stage1"] == True).sum()),
                    stage1_x2=int((g["prereg_X2_SL15_TP3_stage1"] == True).sum())))
pd.DataFrame(res).to_csv(os.path.join(W, "fy_ds_prereg_vs_house.csv"), index=False)
print(pd.DataFrame(res).round(4).to_string())

# ---------------- frequency agreement per cell and per tf
T["freq_log_ratio"] = np.log(T["freq_ratio_live_vs_5y"].replace(0, np.nan))
fq = []
for (k, tf), g in T.groupby(["kind", "tf"]):
    g2 = g[g["fy_per_day"] >= 1]
    fq.append(dict(kind=k, tf=tf, cells=len(g), live_sig_per_day_sum=g["live_signals_per_day"].sum(), fy_per_day_sum=g["fy_per_day"].sum(),
                   ratio_sum=g["live_signals_per_day"].sum() / g["fy_per_day"].sum(),
                   median_ratio_cells_ge1day=g2["freq_ratio_live_vs_5y"].median(), cells_ge1day=len(g2),
                   rp_cnt_bh_low=int(((g["win_rp_cnt_q_bh"] < 0.05) & (g["win_rp_cnt_pct_live"] < 0.5)).sum()),
                   rp_cnt_bh_high=int(((g["win_rp_cnt_q_bh"] < 0.05) & (g["win_rp_cnt_pct_live"] > 0.5)).sum()),
                   v3a_cnt_bh_low=int(((g["win_v3a_cnt_q_bh"] < 0.05) & (g["win_v3a_cnt_pct_live"] < 0.5)).sum()),
                   v3a_cnt_bh_high=int(((g["win_v3a_cnt_q_bh"] < 0.05) & (g["win_v3a_cnt_pct_live"] > 0.5)).sum()),
                   rp_R_bh_out=int((g["win_rp_q_bh"] < 0.05).sum()), v3a_R_bh_out=int((g["win_v3a_q_bh"] < 0.05).sum()),
                   rp_R_raw_p05=int((g["win_rp_p_two"] < 0.05).sum()), rp_R_tested=int(g["win_rp_p_two"].notna().sum()),
                   v3a_R_raw_p05=int((g["win_v3a_p_two"] < 0.05).sum()), v3a_R_tested=int(g["win_v3a_p_two"].notna().sum())))
pd.DataFrame(fq).to_csv(os.path.join(W, "fy_freq_tf.csv"), index=False)
print(pd.DataFrame(fq).round(3).to_string())
flag = T[(T["win_rp_cnt_q_bh"] < 0.05) | (T["win_v3a_cnt_q_bh"] < 0.05) | (T["win_rp_q_bh"] < 0.05) | (T["win_v3a_q_bh"] < 0.05)]
flag[["kind", "strategy", "tf", "fy_per_day", "live_signals_per_day", "freq_ratio_live_vs_5y", "live_rp_signals", "win_rp_cnt_p50",
      "win_rp_cnt_q_bh", "live_sig_v3a", "win_v3a_cnt_p50", "win_v3a_cnt_q_bh", "live_rp_mean_R", "win_rp_q_bh", "live_v3a_mean_R",
      "win_v3a_q_bh"]].to_csv(os.path.join(W, "fy_window_outliers.csv"), index=False)
print(flag[["kind", "strategy", "tf", "fy_per_day", "live_signals_per_day", "freq_ratio_live_vs_5y", "win_rp_cnt_q_bh", "win_v3a_cnt_q_bh",
            "live_rp_mean_R", "win_rp_q_bh", "live_v3a_mean_R", "win_v3a_q_bh"]].round(3).to_string())
