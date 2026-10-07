"""Per-strategy grading of the AI unit (strategy x 15m + 30m) through this lens: frequency, coin-flip-relative
direction choice (side flip, drift-neutral), run-to-run consistency (v3b vs v4), luck flags. Also 1h / 4h cells.

    python3 -I grade.py <out_real_dir> <work_dir>
Writes grades_15m30m.csv, grades_1h4h.csv.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import *  # noqa

O, W = sys.argv[1], sys.argv[2]
rng = np.random.default_rng(11)
RP = pd.read_csv(os.path.join(O, "replay_signals.csv"), low_memory=False)
RP["run_label"] = RP["run"].map(RUN_LABEL)
P = RP[(RP.status == "TRADED") & (RP.flip_status == "TRADED") & RP.kind.isin(["strategy", "ds200"])].copy()
P["h"] = 0.5 * (P["R"] - P["flip_R"])
P["cf"] = 0.5 * (P["R"] + P["flip_R"])
P["cl"] = P["run"] + "|" + (P["bar_close"] // HOUR).astype(str)       # 1h clusters (the pipeline's choice for <=1h)
# same-side random-time coin flip (exhaustive replay): mean R of a random entry on the same run x tf x side
X = pd.read_csv(os.path.join(W, "cf_exhaustive_rows.csv"), low_memory=False)
X = X[X.status == "TRADED"]
X["run_label"] = X["run"].map(RUN_LABEL)
CFS = X.groupby(["run_label", "timeframe", "side"])["R"].mean().to_dict()
P["cf_same_side"] = [CFS.get(k, np.nan) for k in zip(P["run_label"], P["timeframe"], P["side"])]
P["t_ex"] = P["R"] - P["cf_same_side"]


def boot_ci(v, cl, B=3000):
    v = np.asarray(v, float)
    u, inv = np.unique(cl, return_inverse=True)
    if len(u) < 5:
        return np.nan, np.nan
    sm, c = np.bincount(inv, weights=v), np.bincount(inv)
    d = rng.integers(0, len(u), size=(B, len(u)))
    est = sm[d].sum(1) / c[d].sum(1)
    return float(np.percentile(est, 2.5)), float(np.percentile(est, 97.5))
T = pd.read_csv(os.path.join(O, "trades_enriched.csv"), low_memory=False)
T["run_label"] = T["run"].map(RUN_LABEL)
AI = pd.read_csv(os.path.join(W, "ai_trader_15m30m.csv"))
AI = AI[AI.dedup_bars == 0].set_index(["kind", "strategy"])
L = pd.read_csv(os.path.join(O, "luck_concentration.csv"))
D = pd.read_csv(os.path.join(O, "direction_luck.csv"))
F = pd.read_csv(os.path.join(W, "flow.csv"))


def signflip_p(h, cl, B=4000):
    """one-sided p(better) of mean h with one random sign per cluster"""
    h = np.asarray(h, float)
    if len(h) < 5:
        return np.nan
    u, inv = np.unique(cl, return_inverse=True)
    s = np.bincount(inv, weights=h)
    if len(u) < 5:
        return np.nan
    obs = h.mean()
    sims = (rng.choice((-1.0, 1.0), size=(B, len(u))) * s).sum(1) / len(h)
    return (1 + (sims >= obs - 1e-12).sum()) / (B + 1)


def block(g):
    lg, sh = g[g.side > 0], g[g.side < 0]
    el = lg["h"].mean() if len(lg) else np.nan
    es = sh["h"].mean() if len(sh) else np.nan
    return {"n_pairs": len(g), "clusters_1h": g["cl"].nunique(), "long_share": (g.side > 0).mean() if len(g) else np.nan,
            "chosen_R": g["R"].mean() if len(g) else np.nan, "coinflip_R": g["cf"].mean() if len(g) else np.nan,
            "excess": g["h"].mean() if len(g) else np.nan,
            "excess_drift_neutral": np.nanmean([el, es]) if len(lg) and len(sh) else np.nan,
            "p_better": signflip_p(g["h"], g["cl"]) if len(g) else np.nan,
            "cf_same_side_R": g["cf_same_side"].mean() if len(g) else np.nan,
            "timing_excess": g["t_ex"].mean() if len(g) else np.nan,
            "timing_excess_ci": "[%.3f, %.3f]" % boot_ci(g["t_ex"], g["cl"]) if len(g) else ""}


def grade_unit(kind, strat, tfs):
    g = P[(P.kind == kind) & (P.strategy == strat) & P.timeframe.isin(tfs)]
    d = {"kind": kind, "strategy": strat, "tfs": "+".join(tfs)}
    d.update(block(g))
    for rl in ("v3b", "v4"):
        b = block(g[g.run_label == rl])
        d[f"n_{rl}"], d[f"excess_{rl}"], d[f"chosen_R_{rl}"] = b["n_pairs"], b["excess"], b["chosen_R"]
        d[f"timing_excess_{rl}"] = b["timing_excess"]
    for tf in tfs:
        b = block(g[g.timeframe == tf])
        d[f"n_{tf}"], d[f"excess_{tf}"], d[f"chosen_R_{tf}"] = b["n_pairs"], b["excess"], b["chosen_R"]
        d[f"timing_excess_{tf}"] = b["timing_excess"]
    t = T[(T.kind == kind) & (T.strategy == strat) & T.tf.isin(tfs)]
    d["live_n"] = len(t)
    d["live_R"] = t["R"].mean() if len(t) else np.nan
    d["live_R_v3a"] = t.loc[t.run_label == "v3a", "R"].mean() if len(t) else np.nan
    d["live_n_v3a"] = int((t.run_label == "v3a").sum())
    d["live_R_v3b_v4"] = t.loc[t.run_label != "v3a", "R"].mean() if len(t) else np.nan
    d["live_pnl"] = t["pnl"].sum()
    d["live_pnl_ex_best_trade"] = t["pnl"].sum() - t["pnl"].max() if len(t) else np.nan
    ll = L[(L.strategy == strat) & L.tf.isin(tfs) & (L.pnl_total > 0)]
    d["profitable_account_runs"] = len(ll)
    d["of_which_gone_wo_best_trade"] = int(ll["lucky_flag"].sum())
    dd = D[(D.strategy == strat) & D.tf.isin(tfs) & D.direction_luck_flag]
    d["direction_luck_flags"] = " ".join(f"{RUN_LABEL[r]}@{tf}" for r, tf in zip(dd["run"], dd["tf"]))
    f = F[(F.kind == kind) & (F.strategy == strat) & F.timeframe.isin(tfs)]
    d["sub_per_day"] = f["sub_per_day_pooled"].sum()
    d["ref5y_per_day"] = f["ref5y_per_day"].sum()
    d["share_rejected"] = (f["out_REJECTED:sizing"].sum() / max(f["outcomes"].sum(), 1))
    if (kind, strat) in AI.index and tfs == ["15m", "30m"]:
        a = AI.loc[(kind, strat)]
        d["ai_trades_per_day"] = a["trades_per_day"]
        d["ai_trades_per_day_5y"] = a["trades_per_day_5y_analytic"]
        d["ai_busy_share"] = a["busy_share"]
        d["ai_calls_per_day_event"] = a["calls_event_driven_per_day"]
        d["ai_calls_per_day_scans"] = a["calls_with_scans_per_day"]
    return d


rows = []
for kind in ("strategy", "ds200"):
    for s in sorted(F.loc[F.kind == kind, "strategy"].unique()):
        rows.append(grade_unit(kind, s, ["15m", "30m"]))
G = pd.DataFrame(rows)
# BH over the units with a p-value
m = G["p_better"].notna()


def bh_q(p):
    p = np.asarray(p, float)
    n = len(p)
    o = np.argsort(p)
    q = p[o] * n / np.arange(1, n + 1)
    q = np.minimum.accumulate(q[::-1])[::-1]
    out = np.empty(n)
    out[o] = np.minimum(q, 1)
    return out


G.loc[m, "bh_q_better"] = bh_q(G.loc[m, "p_better"])


def letter(r):
    tpd = max(r.get("ai_trades_per_day", 0) or 0, r.get("ai_trades_per_day_5y", 0) or 0)
    if tpd < 1.0:
        return "X"
    if r["n_pairs"] < 15 or r["clusters_1h"] < 10:
        return "?"
    runs = [r[f"excess_{rl}"] for rl in ("v3b", "v4") if r[f"n_{rl}"] >= 8]
    tfv = [r[f"excess_{tf}"] for tf in ("15m", "30m") if r[f"n_{tf}"] >= 8]
    te = r["timing_excess"]
    truns = [r[f"timing_excess_{rl}"] for rl in ("v3b", "v4") if r[f"n_{rl}"] >= 8]
    ttfs = [r[f"timing_excess_{tf}"] for tf in ("15m", "30m") if r[f"n_{tf}"] >= 8]
    # B: beats BOTH coin flips (side flip at the same moments, and a random-time entry on the same side), in every
    # run and timeframe with >= 8 signals; D: loses to both, everywhere. Nothing here is significant (see bh_q).
    if r["excess"] >= 0.10 and te >= 0.10 and all(x > 0 for x in runs + tfv + truns + ttfs):
        return "B"
    if r["excess"] <= -0.10 and te <= -0.10 and all(x < 0 for x in runs + tfv + truns + ttfs):
        return "D"
    return "C"


G["grade"] = G.apply(letter, axis=1)
G.to_csv(os.path.join(W, "grades_15m30m.csv"), index=False)

rows = []
for kind in ("strategy", "ds200"):
    for s in sorted(F.loc[F.kind == kind, "strategy"].unique()):
        for tf in ("1h", "4h"):
            rows.append(grade_unit(kind, s, [tf]))
H = pd.DataFrame(rows)
m = H["p_better"].notna()
H.loc[m, "bh_q_better"] = bh_q(H.loc[m, "p_better"])
H.to_csv(os.path.join(W, "grades_1h4h.csv"), index=False)

pd.set_option("display.width", 260)
pd.set_option("display.max_rows", 200)
cols = ["kind", "strategy", "grade", "n_pairs", "clusters_1h", "long_share", "chosen_R", "coinflip_R", "excess",
        "excess_drift_neutral", "cf_same_side_R", "timing_excess", "timing_excess_ci", "timing_excess_v3b", "timing_excess_v4", "p_better", "bh_q_better", "excess_v3b", "excess_v4", "excess_15m", "excess_30m",
        "live_n", "live_R", "live_R_v3a", "live_n_v3a", "profitable_account_runs", "of_which_gone_wo_best_trade",
        "direction_luck_flags", "sub_per_day", "ai_trades_per_day", "ai_trades_per_day_5y"]
print(G[cols].round(3).to_string())
print(G.groupby(["kind", "grade"]).size())
print("min BH q 15m+30m:", G["bh_q_better"].min(), " min p:", G["p_better"].min())
print("1h/4h: min BH q", H["bh_q_better"].min(), "min p", H["p_better"].min())
print(H[H.p_better < 0.05][["kind", "strategy", "tfs", "n_pairs", "chosen_R", "coinflip_R", "excess",
                             "excess_drift_neutral", "p_better", "bh_q_better", "excess_v3b", "excess_v4"]].round(3))
