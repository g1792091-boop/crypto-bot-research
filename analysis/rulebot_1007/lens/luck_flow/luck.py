"""Luck lens: market backdrop in R units, direction tilt vs market, drift-neutral side-flip excess, luck concentration,
time clustering and effective sample size, and the per strategy x tf grading table.

    python3 -I luck.py <export_dir> <out_real_dir> <work_dir>
Writes: backdrop_R.csv, tilt_kind_tf.csv, cells_15m30m.csv (+ all tfs: cells_all.csv), luck_conc_summary.csv,
cluster_entries.csv, neff_kind_tf.csv.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import *  # noqa

E, O, W = sys.argv[1], sys.argv[2], sys.argv[3]
rng = np.random.default_rng(7)
B = 4000
pd.set_option("display.width", 250)
pd.set_option("display.max_rows", 400)


def cluster_boot(vals, cl, B=B):
    vals = np.asarray(vals, float)
    m = np.isfinite(vals)
    vals, cl = vals[m], np.asarray(cl)[m]
    u, inv = np.unique(cl, return_inverse=True)
    k = len(u)
    if k < 3:
        return np.nan, np.nan, np.nan, k
    s = np.bincount(inv, weights=vals)
    c = np.bincount(inv)
    d = rng.integers(0, k, size=(B, k))
    est = s[d].sum(1) / c[d].sum(1)
    return float(vals.mean()), float(np.percentile(est, 2.5)), float(np.percentile(est, 97.5)), k


# ============================================================ (1) backdrop in R units (exhaustive coin flip by side)
X = pd.read_csv(os.path.join(W, "cf_exhaustive_rows.csv"), low_memory=False)
X = X[X["status"] == "TRADED"].copy()
X["run_label"] = X["run"].map(RUN_LABEL)
bk = X.groupby(["run_label", "timeframe", "symbol", "side"])["R"].mean().unstack("side")
bk.columns = ["cf_short_R", "cf_long_R"]
bk["long_minus_short_R"] = bk["cf_long_R"] - bk["cf_short_R"]
bk = bk.reset_index()
mb = pd.read_csv(os.path.join(O, "market_backdrop.csv"))
mb["run_label"] = mb["run"].map(RUN_LABEL)
bk = bk.merge(mb[["run_label", "symbol", "return_pct", "realized_vol_daily_pct", "direction"]],
              on=["run_label", "symbol"], how="left")
bk.to_csv(os.path.join(W, "backdrop_R.csv"), index=False)
# side means per run x tf (all coins)
CFS = X.groupby(["run_label", "timeframe", "side"])["R"].mean().unstack("side")
CFS.columns = ["cf_short", "cf_long"]
print("== exhaustive coin flip R by side (run x tf):")
print(CFS.round(3))
print("\n== per coin, 15m:")
print(bk[bk.timeframe == "15m"].round(3).to_string())

# ============================================================ (1b) direction tilt per strategy x tf (signals)
sigs = []
for r in RUNS:
    s = pd.read_csv(os.path.join(E, r, "signal_log.csv"))
    s = s[s["status"] == "SUBMITTED"].copy()
    s["run"] = r
    sigs.append(s)
SG = pd.concat(sigs)
SG["run_label"] = SG["run"].map(RUN_LABEL)
acc_kind = {}
for r in RUNS:
    a = pd.read_csv(os.path.join(E, r, "accounts.csv"))
    acc_kind.update(dict(zip(a["strategy"], a["kind"])))
SG["kind"] = SG["strategy"].map(acc_kind).fillna("random")
eq = mb[mb["symbol"] == "EQUAL_WEIGHT_6"].set_index("run_label")["return_pct"].to_dict()
tilt = SG.groupby(["run_label", "kind", "timeframe"]).agg(n=("side", "size"), long_share=("side", lambda x: (x > 0).mean()))
tilt["market_eq_return_pct"] = [eq.get(i[0]) for i in tilt.index]
print("\n== long share of SUBMITTED signals by run x kind x tf vs equal-weight market return:")
print(tilt.round(3).to_string())
tilt.reset_index().to_csv(os.path.join(W, "tilt_kind_tf.csv"), index=False)

# ============================================================ (1c) side-flip excess split: drift-neutral vs tilt
RP = pd.read_csv(os.path.join(O, "replay_signals.csv"), low_memory=False)
RP["run_label"] = RP["run"].map(RUN_LABEL)
P = RP[(RP.status == "TRADED") & (RP.flip_status == "TRADED")].copy()
P["h"] = 0.5 * (P["R"] - P["flip_R"])
P["cf"] = 0.5 * (P["R"] + P["flip_R"])
P["blk4"] = P["run"] + "|" + (P["bar_close"] // (4 * HOUR)).astype(str)


def split(g):
    lg, sh = g[g.side > 0], g[g.side < 0]
    ex = g["h"].mean()
    el = lg["h"].mean() if len(lg) else np.nan
    es = sh["h"].mean() if len(sh) else np.nan
    bal = np.nanmean([el, es]) if len(lg) and len(sh) else np.nan
    return pd.Series({"n_pairs": len(g), "long_share": (g.side > 0).mean(), "chosen_R": g["R"].mean(),
                      "coinflip_R": g["cf"].mean(), "excess": ex, "excess_long": el, "excess_short": es,
                      "excess_drift_neutral": bal, "tilt_part": ex - bal if bal == bal else np.nan,
                      "blocks4h": g["blk4"].nunique()})


kt = P[P.kind.isin(["strategy", "ds200"])].groupby(["kind", "run_label", "timeframe"]).apply(split, include_groups=False)
print("\n== side-flip excess split (kind x run x tf):")
print(kt.round(3).to_string())
kt.reset_index().to_csv(os.path.join(W, "excess_split_kind_run_tf.csv"), index=False)
kt2 = P[P.kind.isin(["strategy", "ds200"])].groupby(["kind", "timeframe"]).apply(split, include_groups=False)
print(kt2.round(3).to_string())
kt2.reset_index().to_csv(os.path.join(W, "excess_split_kind_tf.csv"), index=False)

# ============================================================ (3) luck concentration
L = pd.read_csv(os.path.join(O, "luck_concentration.csv"))
L["run_label"] = L["run"].map(RUN_LABEL)
prof = L[(L.pnl_total > 0) & L.kind.isin(["strategy", "ds200"])].copy()
prof["nb"] = pd.cut(prof["n"], [0, 2, 4, 9, 19, 1000], labels=["1-2", "3-4", "5-9", "10-19", "20+"])
lc = prof.groupby(["kind", "nb"], observed=True).agg(accounts=("n", "size"), gone_wo_best_trade=("lucky_flag", "mean"),
                                                     med_best_trade_share=("best_trade_share", "median"),
                                                     med_best_day_share=("best_day_share", "median"))
print("\n== profitable accounts: luck concentration by n bucket")
print(lc.round(2).to_string())
lc.reset_index().to_csv(os.path.join(W, "luck_conc_summary.csv"), index=False)
# coin-flip accounts for reference
pr = L[(L.pnl_total > 0) & (L.kind == "random")]
print("coin-flip profitable accounts:", len(pr), "gone w/o best trade:", int(pr.lucky_flag.sum()),
      "median best-trade share", round(pr.best_trade_share.median(), 2))

# ============================================================ (3b) time clustering of entries
T = pd.read_csv(os.path.join(O, "trades_enriched.csv"), low_memory=False)
T["run_label"] = T["run"].map(RUN_LABEL)
NR = T[T.kind.isin(["strategy", "ds200"])].copy()
NR["minute"] = NR["entry_time"] // MIN
g = NR.groupby(["run", "symbol", "minute"])
NR["same_coin_minute"] = g["account_id"].transform("size")
NR["same_coin_minute_side"] = NR.groupby(["run", "symbol", "minute", "side"])["account_id"].transform("size")
NR["same_minute_any_coin"] = NR.groupby(["run", "minute"])["account_id"].transform("size")
ce = NR.groupby(["run_label", "kind"]).agg(trades=("R", "size"),
                                           distinct_coin_minutes=("minute", lambda x: 0),
                                           share_shared_coin_minute=("same_coin_minute", lambda x: (x > 1).mean()),
                                           share_ge5_coin_minute=("same_coin_minute", lambda x: (x >= 5).mean()),
                                           mean_cluster_size=("same_coin_minute", "mean"),
                                           share_shared_same_side=("same_coin_minute_side", lambda x: (x > 1).mean()))
for (rl, k), gg in NR.groupby(["run_label", "kind"]):
    ce.loc[(rl, k), "distinct_coin_minutes"] = gg.groupby(["symbol", "minute"]).ngroups
    ce.loc[(rl, k), "distinct_minutes"] = gg["minute"].nunique()
    ce.loc[(rl, k), "distinct_4h_blocks"] = (gg["entry_time"] // (4 * HOUR)).nunique()
allr = NR.groupby(["run", "symbol", "minute"]).size()
print("\n== entry clustering (all strategy + ds200 trades):")
print(ce.round(3).to_string())
print("largest same coin-minute clusters:", allr.sort_values(ascending=False).head(5).to_dict())
ce.reset_index().to_csv(os.path.join(W, "cluster_entries.csv"), index=False)

# effective sample size: kind x tf pooled R, iid vs clustered (coin-minute; 4h block)
nrows = []
for (k, tf), gg in NR.groupby(["kind", "tf"]):
    v = gg["R"].to_numpy(float)
    n = len(v)
    if n < 10:
        continue
    var_iid = v.var(ddof=1) / n
    out = {"kind": k, "timeframe": tf, "n_trades": n, "mean_R": v.mean()}
    for nm, cl in (("coin_minute", gg["run"] + gg["symbol"] + gg["minute"].astype(str)),
                   ("minute", gg["run"] + gg["minute"].astype(str)),
                   ("block4h", gg["run"] + (gg["entry_time"] // (4 * HOUR)).astype(str))):
        m, lo, hi, kk = cluster_boot(v, cl.to_numpy())
        var_cl = ((hi - lo) / 3.92) ** 2
        out[f"clusters_{nm}"] = kk
        out[f"deff_{nm}"] = var_cl / var_iid
        out[f"neff_{nm}"] = n * var_iid / var_cl
        out[f"ci_{nm}"] = f"[{lo:.3f}, {hi:.3f}]"
    nrows.append(out)
NE = pd.DataFrame(nrows)
print("\n== effective sample size of pooled trade R (kind x tf)")
print(NE.round(2).to_string())
NE.to_csv(os.path.join(W, "neff_kind_tf.csv"), index=False)

# replay every-signal sample: n vs n_eff by kind x tf (4h blocks)
rr = []
for (k, tf), gg in P[P.kind.isin(["strategy", "ds200"])].groupby(["kind", "timeframe"]):
    v = gg["R"].to_numpy(float)
    m, lo, hi, kk = cluster_boot(v, gg["blk4"].to_numpy())
    var_iid = v.var(ddof=1) / len(v)
    var_cl = ((hi - lo) / 3.92) ** 2
    me, loe, hie, _ = cluster_boot(gg["h"].to_numpy(float), gg["blk4"].to_numpy())
    rr.append({"kind": k, "timeframe": tf, "n_signals": len(v), "blocks4h": kk, "mean_R": m, "ci": f"[{lo:.3f}, {hi:.3f}]",
               "neff": len(v) * var_iid / var_cl, "excess": me, "excess_ci": f"[{loe:.3f}, {hie:.3f}]"})
print(pd.DataFrame(rr).round(3).to_string())
pd.DataFrame(rr).to_csv(os.path.join(W, "neff_replay_kind_tf.csv"), index=False)

# ============================================================ (5) per strategy x tf cells (grading inputs)
cells = []
CFSd = CFS.to_dict("index")
for (k, s, tf), gg in P[P.kind.isin(["strategy", "ds200"])].groupby(["kind", "strategy", "timeframe"]):
    d = {"kind": k, "strategy": s, "timeframe": tf}
    d.update(split(gg).to_dict())
    # tilt-expected R from the exhaustive coin flip by side, run-weighted by this cell's own signals
    exp_tilt = []
    for rl, g2 in gg.groupby("run_label"):
        c = CFSd.get((rl, tf))
        if c:
            exp_tilt += list(np.where(g2.side > 0, c["cf_long"], c["cf_short"]))
    d["cf_side_expected_R"] = float(np.mean(exp_tilt)) if exp_tilt else np.nan
    for rl in ("v3b", "v4"):
        g2 = gg[gg.run_label == rl]
        d[f"n_{rl}"] = len(g2)
        d[f"excess_{rl}"] = g2["h"].mean() if len(g2) else np.nan
        d[f"chosen_R_{rl}"] = g2["R"].mean() if len(g2) else np.nan
        d[f"cf_R_{rl}"] = g2["cf"].mean() if len(g2) else np.nan
    m, lo, hi, kk = cluster_boot(gg["h"].to_numpy(float), gg["blk4"].to_numpy())
    d["excess_ci_lo"], d["excess_ci_hi"] = lo, hi
    m2, lo2, hi2, _ = cluster_boot(gg["R"].to_numpy(float), gg["blk4"].to_numpy())
    d["chosen_ci_lo"], d["chosen_ci_hi"] = lo2, hi2
    cells.append(d)
C = pd.DataFrame(cells)
# live trades and luck per cell (all runs, incl. v3a in-sample)
st = T[T.kind.isin(["strategy", "ds200"])].groupby(["kind", "strategy", "tf"]).agg(
    live_n=("R", "size"), live_mean_R=("R", "mean"), live_pnl=("pnl", "sum"),
    live_n_v3a=("run_label", lambda x: int((x == "v3a").sum())),
    live_R_v3a=("R", lambda x: np.nan), best_trade_pnl=("pnl", "max"))
for (k, s, tf), gg in T[T.kind.isin(["strategy", "ds200"])].groupby(["kind", "strategy", "tf"]):
    st.loc[(k, s, tf), "live_R_v3a"] = gg.loc[gg.run_label == "v3a", "R"].mean()
    st.loc[(k, s, tf), "live_R_v3b_v4"] = gg.loc[gg.run_label != "v3a", "R"].mean()
    pos = gg["pnl"].sum()
    st.loc[(k, s, tf), "pnl_ex_best_trade"] = pos - gg["pnl"].max()
st = st.reset_index().rename(columns={"tf": "timeframe"})
C = C.merge(st, on=["kind", "strategy", "timeframe"], how="outer")
D = pd.read_csv(os.path.join(O, "direction_luck.csv"))
flags = D[D.direction_luck_flag].groupby(["strategy", "tf"])["run"].apply(lambda x: " ".join(x.map(RUN_LABEL)))
C["direction_luck_flag_runs"] = [flags.get((s, tf), "") for s, tf in zip(C["strategy"], C["timeframe"])]
F = pd.read_csv(os.path.join(W, "flow.csv"))
C = C.merge(F[["kind", "strategy", "timeframe", "sub_per_day_pooled", "ref5y_per_day", "share_entered",
               "share_rejected", "trades"]], on=["kind", "strategy", "timeframe"], how="outer")
C.to_csv(os.path.join(W, "cells_all.csv"), index=False)
print("\ncells:", len(C))
