"""Coin-flip baselines: (1) the exhaustive coin flip (cf_exhaustive_rows.csv), (2) the live coin-flip accounts,
(3) the timing-matched side flip of the strategies' own signals (replay_signals.csv), and the luck band of the
15m coin-flip accounts. Writes coinflip_baselines.csv, coinflip_accounts.csv, cf_exhaustive_summary.csv,
cf_side_by_run.csv.

    python3 -I coinflip.py <out_real_dir> <work_dir>
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import *  # noqa

O, W = sys.argv[1], sys.argv[2]
rng = np.random.default_rng(20261007)
B = 5000
P_BEST = {"15m": 0.2155, "30m": 0.2170, "1h": 0.2157, "4h": 0.2095}


def cluster_ci(vals: np.ndarray, cl: np.ndarray, B: int = B, w: np.ndarray | None = None):
    """Mean and 95% percentile CI from a cluster bootstrap (resample whole clusters)."""
    vals = np.asarray(vals, float)
    w = np.ones_like(vals) if w is None else np.asarray(w, float)
    m = np.isfinite(vals)
    vals, cl, w = vals[m], np.asarray(cl)[m], w[m]
    if len(vals) == 0:
        return np.nan, np.nan, np.nan, 0, 0
    u, inv = np.unique(cl, return_inverse=True)
    sv = np.bincount(inv, weights=vals * w)
    sw = np.bincount(inv, weights=w)
    k = len(u)
    if k < 3:
        return float((vals * w).sum() / w.sum()), np.nan, np.nan, len(vals), k
    draws = rng.integers(0, k, size=(B, k))
    est = sv[draws].sum(1) / sw[draws].sum(1)
    return float((vals * w).sum() / w.sum()), float(np.percentile(est, 2.5)), float(np.percentile(est, 97.5)), len(vals), k


# ------------------------------------------------------------------ (1) exhaustive coin flip
X = pd.read_csv(os.path.join(W, "cf_exhaustive_rows.csv"), low_memory=False)
X["run_label"] = X["run"].map(RUN_LABEL)
dist = (X["entry_price"] - X["stop_initial"]).abs()
X["cost_R"] = (X["fees"] + X["funding"].fillna(0)) / (X["qty"] * dist)
X["gross_R"] = X["R"] + X["cost_R"]
X["R_incl_mark"] = np.where(X["status"] == "TRADED", X["R"], X.get("mark_R"))
X["blk"] = X["run"] + "|" + (X["bar_close"] // (4 * HOUR)).astype(str)
X["w"] = np.where(X["lev_group"] == "best", X["timeframe"].map(P_BEST), 1 - X["timeframe"].map(P_BEST))
rows = []
for keys, g in X.groupby(["run_label", "timeframe", "lev_group"]):
    t = g[g.status == "TRADED"]
    d = dict(zip(["run", "timeframe", "lev_group"], keys))
    d.update(n_rows=len(g), n_traded=len(t), n_unresolved=int((g.status == "UNRESOLVED").sum()),
             n_rejected=int((g.status == "REJECTED_SIZING").sum()), mean_R=t["R"].mean(), sd_R=t["R"].std(),
             win=(t["R"] > 0).mean(), mean_cost_R=t["cost_R"].mean(), mean_gross_R=t["gross_R"].mean(),
             mean_R_long=t.loc[t.side > 0, "R"].mean(), mean_R_short=t.loc[t.side < 0, "R"].mean(),
             mean_R_incl_unresolved_mark=g["R_incl_mark"].mean(), lock_share=(t["exit_reason"] == "LOCK").mean(),
             mean_hold_min=t["hold_min"].mean(), mean_mfe_R=t["mfe_R"].mean(), lev_mix=" ".join(f"{int(k)}:{v}" for k, v in t["leverage"].value_counts().items()))
    rows.append(d)
XS = pd.DataFrame(rows)
# leverage-mixed (coin-flip rule: 'best' with P_BEST) per run x tf and pooled over runs
mix_rows = []
for keys, g in list(X.groupby(["run_label", "timeframe"])) + [(("v3b+v4", tf), g) for tf, g in X.groupby("timeframe")]:
    t = g[g.status == "TRADED"]
    m, lo, hi, n, k = cluster_ci(t["R"], t["blk"], w=t["w"])
    ml, lol, hil, _, _ = cluster_ci(t.loc[t.side > 0, "R"], t.loc[t.side > 0, "blk"], w=t.loc[t.side > 0, "w"])
    ms, los, his, _, _ = cluster_ci(t.loc[t.side < 0, "R"], t.loc[t.side < 0, "blk"], w=t.loc[t.side < 0, "w"])
    mc, _, _, _, _ = cluster_ci(t["cost_R"], t["blk"], w=t["w"])
    mg, _, _, _, _ = cluster_ci(t["gross_R"], t["blk"], w=t["w"])
    mk, _, _, _, _ = cluster_ci(g["R_incl_mark"], g["blk"], w=g["w"])
    sd = float(np.sqrt(np.average((t["R"] - m) ** 2, weights=t["w"])))
    mix_rows.append({"run": keys[0], "timeframe": keys[1], "n_traded": n, "clusters_4h": k, "mean_R": m, "ci_lo": lo,
                     "ci_hi": hi, "sd_R": sd, "mean_cost_R": mc, "mean_gross_R": mg, "mean_R_long": ml,
                     "long_ci": f"[{lol:.3f}, {hil:.3f}]", "mean_R_short": ms, "short_ci": f"[{los:.3f}, {his:.3f}]",
                     "mean_R_incl_unresolved_mark": mk,
                     "n_unresolved": int((g.status == "UNRESOLVED").sum()),
                     "win": float(np.average(t["R"] > 0, weights=t["w"]))})
XM = pd.DataFrame(mix_rows)
XS.to_csv(os.path.join(W, "cf_exhaustive_by_levgroup.csv"), index=False)
XM.to_csv(os.path.join(W, "cf_exhaustive_summary.csv"), index=False)

# ------------------------------------------------------------------ (2) live coin-flip accounts
T = pd.read_csv(os.path.join(O, "trades_enriched.csv"), low_memory=False)
T["run_label"] = T["run"].map(RUN_LABEL)
T["blk"] = T["run"] + "|" + (T["entry_time"] // (4 * HOUR)).astype(str)
r = T[(T["kind"] == "random") & (T["exits"] == "house")]
crow = []
for keys, g in list(r.groupby(["run_label", "tf"])) + [(("ALL", tf), g) for tf, g in r.groupby("tf")]:
    m, lo, hi, n, k = cluster_ci(g["R"], g["blk"])
    crow.append({"run": keys[0], "timeframe": keys[1], "n": n, "clusters_4h": k, "mean_R": m, "ci_lo": lo, "ci_hi": hi,
                 "sd_R": g["R"].std(), "win": (g["R"] > 0).mean(), "long_share": (g["side"] > 0).mean(),
                 "mean_R_long": g.loc[g.side > 0, "R"].mean(), "mean_R_short": g.loc[g.side < 0, "R"].mean(),
                 "n_long": int((g.side > 0).sum()), "n_short": int((g.side < 0).sum()),
                 "mean_cost_R": g["cost_R"].mean(), "mean_mfe_R": g["mfe_R"].mean(), "mean_lev": g["leverage"].mean(),
                 "lev_mix": " ".join(f"{int(a)}:{b}" for a, b in g["leverage"].value_counts().items()),
                 "lock_share": (g["exit_reason"] == "LOCK").mean(), "mean_hold_min": g["hold_min"].mean(),
                 "max_R": g["R"].max(), "share_pnl_top2": np.sort(g["R"].to_numpy())[-2:].sum() / g["R"].sum()
                 if g["R"].sum() > 0 else np.nan})
CA = pd.DataFrame(crow)
CA.to_csv(os.path.join(W, "coinflip_accounts.csv"), index=False)

# strategy trades by tf for the same view (house exits)
srow = []
for keys, g in list(T[T.kind.isin(["strategy", "ds200"])].groupby(["kind", "run_label", "tf"])):
    srow.append({"kind": keys[0], "run": keys[1], "timeframe": keys[2], "n": len(g), "mean_R": g["R"].mean(),
                 "long_share": (g.side > 0).mean(), "mean_R_long": g.loc[g.side > 0, "R"].mean(),
                 "mean_R_short": g.loc[g.side < 0, "R"].mean(), "mean_cost_R": g["cost_R"].mean(),
                 "mean_lev": g["leverage"].mean()})
pd.DataFrame(srow).to_csv(os.path.join(W, "strategy_trades_by_side.csv"), index=False)

# ------------------------------------------------------------------ (3) timing-matched side flip (replay)
RP = pd.read_csv(os.path.join(O, "replay_signals.csv"), low_memory=False)
RP["run_label"] = RP["run"].map(RUN_LABEL)
p = RP[(RP.status == "TRADED") & (RP.flip_status == "TRADED") & RP.kind.isin(["strategy", "ds200"])].copy()
p["cf"] = 0.5 * (p["R"] + p["flip_R"])
blk = np.maximum(p["timeframe"].map(TF_MIN).to_numpy() * MIN, HOUR)
p["cl"] = p["run"] + "|" + (p["bar_close"] // blk).astype(str)
p["blk4"] = p["run"] + "|" + (p["bar_close"] // (4 * HOUR)).astype(str)
brow = []
for keys, g in list(p.groupby(["run_label", "timeframe"])) + [(("v3b+v4", tf), g) for tf, g in p.groupby("timeframe")]:
    m, lo, hi, n, k = cluster_ci(g["cf"], g["blk4"])
    mc, loc, hic, _, _ = cluster_ci(g["R"], g["blk4"])
    ex, loe, hie, _, _ = cluster_ci(0.5 * (g["R"] - g["flip_R"]), g["blk4"])
    lg = g[g.side > 0]
    sh = g[g.side < 0]
    brow.append({"run": keys[0], "timeframe": keys[1], "n_pairs": n, "clusters_4h": k,
                 "timing_matched_coinflip_R": m, "tm_ci_lo": lo, "tm_ci_hi": hi,
                 "chosen_R": mc, "chosen_ci_lo": loc, "chosen_ci_hi": hic, "excess_R": ex, "excess_ci_lo": loe,
                 "excess_ci_hi": hie, "long_share": (g.side > 0).mean(),
                 "R_long_signals": lg["R"].mean(), "R_long_signals_flipped_short": lg["flip_R"].mean(),
                 "R_short_signals": sh["R"].mean(), "R_short_signals_flipped_long": sh["flip_R"].mean()})
BL = pd.DataFrame(brow)
BL.to_csv(os.path.join(W, "cf_side_by_run.csv"), index=False)

# ------------------------------------------------------------------ (4) luck band of the 15m coin-flip accounts
# n = 50 trades (23 v3a + 10 v3b + 17 v4); draw clusters of the exhaustive 15m coin flip (v3b + v4, leverage-mixed)
x15 = X[(X.timeframe == "15m") & (X.status == "TRADED")]
# one coin-flip trade per 4h block on average? use the account's own clustering: 50 trades in 28 4h-blocks
acc15 = r[r.tf == "15m"]
k_blocks = acc15["blk"].nunique()
per_blk = len(acc15) / k_blocks
u = x15["blk"].unique()
vals_by_blk = {b: (g["R"].to_numpy(), g["w"].to_numpy()) for b, g in x15.groupby("blk")}
sims = np.empty(B)
for b in range(B):
    pick = rng.choice(u, size=k_blocks, replace=True)
    vs = []
    for bb in pick:
        v, w = vals_by_blk[bb]
        m_ = int(rng.poisson(per_blk - 1)) + 1
        vs.append(rng.choice(v, size=m_, replace=True, p=w / w.sum()))
    vs = np.concatenate(vs)
    sims[b] = vs[:len(acc15)].mean() if len(vs) >= len(acc15) else vs.mean()
obs = acc15["R"].mean()
luck = {"obs_15m_coinflip_mean_R": obs, "n": len(acc15), "blocks_4h": k_blocks,
        "exhaustive_15m_mean_R": float(np.average(x15["R"], weights=x15["w"])),
        "sim_mean": sims.mean(), "sim_p2.5": np.percentile(sims, 2.5), "sim_p97.5": np.percentile(sims, 97.5),
        "p_sim_ge_obs": float((sims >= obs).mean())}
print("luck band 15m coin-flip accounts:", {k: round(v, 3) if isinstance(v, float) else v for k, v in luck.items()})
pd.DataFrame([luck]).to_csv(os.path.join(W, "cf_luck_band_15m.csv"), index=False)

pd.set_option("display.width", 250)
print("\n== exhaustive coin flip (leverage-mixed, cluster CI 4h blocks)")
print(XM.round(3).to_string())
print("\n== exhaustive by lev group")
print(XS[["run", "timeframe", "lev_group", "n_traded", "n_unresolved", "mean_R", "win", "mean_cost_R", "mean_gross_R",
          "lock_share", "mean_hold_min", "lev_mix"]].round(3).to_string())
print("\n== live coin-flip accounts")
print(CA.round(3).to_string())
print("\n== timing-matched side flip by run")
print(BL.round(3).to_string())
# side-flip: the 'direction skill' is the excess; how big does chance make it per account? excess per strategy x tf
