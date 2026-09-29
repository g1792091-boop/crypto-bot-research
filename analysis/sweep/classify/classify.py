"""Apply HANDOFF_AGENT_TEAM_KO.md v1.1 section 4.1 (committed 39fdb4d before results) to the sweep outputs."""
import pandas as pd, numpy as np, json
W = "/tmp/claude-0/-home-user-crypto-bot-research/e4f1f93f-891a-54cf-944d-5e95b2209f11/scratchpad/sweep"
IS = pd.read_csv(f"{W}/combine/is_table_long.csv")
OOS = pd.read_csv(f"{W}/holdout/out/gate_all_oos_applied.csv")
carried = json.load(open(f"{W}/combine/carried.json"))["carried"]
key = ["strategy", "tf", "H"]
m = IS.merge(OOS[key + ["n", "fwd"]].rename(columns={"n": "n_oos", "fwd": "fwd_oos"}), on=key, how="left")
TF_ORDER = ["5m", "15m", "30m", "1h", "4h", "1d"]
rows = []
for (s, tf), g in m.groupby(["strategy", "tf"]):
    g = g.set_index("H").reindex([4, 16, 64])
    confirmed = any(c.get("strategy") == s and c.get("tf") == tf for c in carried)  # carried is empty; confirmation would need holdout too
    a = bool((g["n"].fillna(0) < 100).all())
    b = bool((g["fwd"] <= 0).all() and (g["fwd_oos"] <= 0).all())  # NaN -> comparison False -> not excluded
    cls = "1" if confirmed else ("3" if (a or b) else "2")
    reason = "a:n<100" if a else ("b:fwd<=0 IS&OOS" if b else "")
    best = g.loc[g["fwd_minus_mu_star"].idxmax()] if g["fwd_minus_mu_star"].notna().any() else None
    rows.append(dict(strategy=s, tf=tf, cls=cls, reason=reason,
                     approx=bool(g["approx"].iloc[0]), prev=bool(g["prev_examined"].iloc[0]),
                     n_max=int(g["n"].max()) if g["n"].notna().any() else 0,
                     any_underpowered=bool(g["underpowered"].fillna(True).any()),
                     all_underpowered=bool(g["underpowered"].fillna(True).all()),
                     best_H=int(best.name) if best is not None else None,
                     best_fwd_pct=float(best["fwd"] * 100) if best is not None else np.nan,
                     best_mu_pct=float(best["mu_star"] * 100) if best is not None else np.nan,
                     best_z=float(best["z"]) if best is not None else np.nan,
                     best_fwd_oos_pct=float(best["fwd_oos"] * 100) if best is not None else np.nan))
C = pd.DataFrame(rows)
C["tf"] = pd.Categorical(C["tf"], TF_ORDER, ordered=True)
C = C.sort_values(["strategy", "tf"])
C.to_csv("classification.csv", index=False)
print(C["cls"].value_counts().to_dict())
print(pd.crosstab(C["tf"], C["cls"]))
print("\n(3) by reason:", C[C.cls == "3"].reason.value_counts().to_dict())
print("\n(3) cells:\n", C[C.cls == "3"][["strategy", "tf", "reason", "n_max"]].to_string(index=False))
# DOGE-coin descriptive view: per-coin fwd for DOGEUSD vs mu*
d = m[["strategy", "tf", "H", "n_DOGEUSD", "fwd_DOGEUSD", "mu_star", "n", "fwd"]].copy()
d.to_csv("doge_coin_view_is.csv", index=False)
dd = d[d.n_DOGEUSD >= 30]
print("\nDOGE coin, IS cells with n_DOGE>=30:", len(dd), "| fwd>0:", int((dd.fwd_DOGEUSD > 0).sum()),
      "| fwd>=mu*:", int((dd.fwd_DOGEUSD >= dd.mu_star).sum()))
print(pd.crosstab(dd.tf, dd.fwd_DOGEUSD >= dd.mu_star))
