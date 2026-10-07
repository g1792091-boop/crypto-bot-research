"""Signal flow per strategy x tf (SUBMITTED / day, outcome shares, zero-trade causes) -> flow.csv, flow_runs.csv,
zero_trade_accounts.csv.

    python3 -I flow.py <export_dir> <out_real_dir> <work_dir>
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import *  # noqa

E, O, W = sys.argv[1], sys.argv[2], sys.argv[3]
meta = pd.read_csv(os.path.join(O, "runs_meta.csv"))
DAYS = dict(zip(meta["run"], meta["days"]))
sf = pd.read_csv(os.path.join(O, "signal_flow.csv"))
sf["run_label"] = sf["run"].map(RUN_LABEL)
sf["days"] = sf["run"].map(DAYS)
for c in ["sig_SUBMITTED", "sig_RECORD", "outcomes", "out_ENTERED:ok", "out_REJECTED:sizing", "out_SKIPPED:in position",
          "out_SKIPPED:lower score", "out_SKIPPED:reel", "trades", "entered", "open_at_end"]:
    sf[c] = sf[c].fillna(0)

# distinct signal moments (bar closes with >= 1 SUBMITTED signal) and distinct coins per account and run
mom = []
for r in RUNS:
    s = pd.read_csv(os.path.join(E, r, "signal_log.csv"))
    s = s[s["status"] == "SUBMITTED"].copy()
    s["account_id"] = s["strategy"] + "@" + s["timeframe"]
    g = s.groupby("account_id").agg(moments=("bar_close", "nunique"), coins=("symbol", "nunique"),
                                    long_share_sig=("side", lambda x: float((x > 0).mean())))
    g["run"] = r
    mom.append(g.reset_index())
mom = pd.concat(mom)
sf = sf.merge(mom, on=["run", "account_id"], how="left")
sf["moments"] = sf["moments"].fillna(0)
sf["sub_per_day"] = sf["sig_SUBMITTED"] / sf["days"]
sf["moments_per_day"] = sf["moments"] / sf["days"]
sf["trades_per_day"] = sf["trades"] / sf["days"]
sf["share_entered"] = sf["out_ENTERED:ok"] / sf["outcomes"].replace(0, np.nan)
sf["share_skip_inpos"] = sf["out_SKIPPED:in position"] / sf["outcomes"].replace(0, np.nan)
sf["share_skip_lower"] = sf["out_SKIPPED:lower score"] / sf["outcomes"].replace(0, np.nan)
sf["share_rejected"] = sf["out_REJECTED:sizing"] / sf["outcomes"].replace(0, np.nan)
keep = ["run", "run_label", "account_id", "kind", "strategy", "timeframe", "days", "sig_SUBMITTED", "sig_RECORD",
        "moments", "coins", "sub_per_day", "moments_per_day", "outcomes", "out_ENTERED:ok", "out_SKIPPED:in position",
        "out_SKIPPED:lower score", "out_REJECTED:sizing", "out_SKIPPED:reel", "share_entered", "share_skip_inpos",
        "share_skip_lower", "share_rejected", "trades", "open_at_end", "trades_per_day", "long_share_sig",
        "zero_trade_cause"]
sf[keep].to_csv(os.path.join(W, "flow_runs.csv"), index=False)

# sizing rejection detail per account (all runs)
rej = pd.read_csv(os.path.join(O, "sizing_rejections.csv"))
print("sizing_rejections columns:", rej.columns.tolist())

# pooled per kind x strategy x tf
ref = pd.read_csv(os.path.join(O, "fiveyear_ref.csv"))
r36 = ref[ref["source"] == "profiles_binance"].set_index(["strategy", "timeframe"])
rds = ref[(ref["source"] == "deepseek200") & (ref["variant"] == "X5_TRAIL2")].set_index(["strategy", "timeframe"])
rows = []
for (k, s, tf), g in sf.groupby(["kind", "strategy", "timeframe"]):
    d = {"kind": k, "strategy": s, "timeframe": tf, "runs_present": " ".join(g["run_label"]),
         "days": g["days"].sum()}
    for lab in ("v3a", "v3b", "v4"):
        x = g[g["run_label"] == lab]
        d[f"sub_{lab}"] = int(x["sig_SUBMITTED"].sum()) if len(x) else np.nan
        d[f"sub_per_day_{lab}"] = float(x["sub_per_day"].sum()) if len(x) else np.nan
        d[f"trades_{lab}"] = int(x["trades"].sum()) if len(x) else np.nan
        d[f"zero_cause_{lab}"] = (x["zero_trade_cause"].fillna("").iloc[0] if len(x) else "absent")
    for c in ["sig_SUBMITTED", "sig_RECORD", "moments", "outcomes", "out_ENTERED:ok", "out_SKIPPED:in position",
              "out_SKIPPED:lower score", "out_REJECTED:sizing", "trades", "open_at_end"]:
        d[c] = int(g[c].sum())
    d["sub_per_day_pooled"] = d["sig_SUBMITTED"] / d["days"]
    d["moments_per_day_pooled"] = d["moments"] / d["days"]
    d["trades_per_day_pooled"] = d["trades"] / d["days"]
    oc = max(d["outcomes"], 1)
    d["share_entered"] = d["out_ENTERED:ok"] / oc if d["outcomes"] else np.nan
    d["share_skip_inpos"] = d["out_SKIPPED:in position"] / oc if d["outcomes"] else np.nan
    d["share_skip_lower"] = d["out_SKIPPED:lower score"] / oc if d["outcomes"] else np.nan
    d["share_rejected"] = d["out_REJECTED:sizing"] / oc if d["outcomes"] else np.nan
    d["zero_trade_all_runs"] = bool((g["trades"] == 0).all())
    d["zero_signal_all_runs"] = bool((g["sig_SUBMITTED"] == 0).all())
    key = (s, tf)
    if k == "strategy" and key in r36.index:
        d["ref5y_per_day"] = float(r36.loc[key, "per_day"])
        d["ref5y_median_hold_h"] = float(r36.loc[key, "median_hold_hours"])
        d["ref5y_long_share"] = float(r36.loc[key, "long_share"])
    elif k == "ds200" and key in rds.index:
        d["ref5y_per_day"] = float(rds.loc[key, "per_day"])
        d["ref5y_median_hold_h"] = np.nan
        d["ref5y_long_share"] = np.nan
    if d.get("ref5y_per_day") and d["ref5y_per_day"] > 0:
        d["live_vs_5y_rate"] = d["sub_per_day_pooled"] / d["ref5y_per_day"]
        # Poisson probability of the observed count or fewer under the 5-year rate (is the live drought unusual?)
        from scipy.stats import poisson
        lam = d["ref5y_per_day"] * d["days"]
        d["p_le_obs_under_5y_rate"] = float(poisson.cdf(d["sig_SUBMITTED"], lam))
        d["p_ge_obs_under_5y_rate"] = float(poisson.sf(d["sig_SUBMITTED"] - 1, lam))
    rows.append(d)
F = pd.DataFrame(rows)
F.to_csv(os.path.join(W, "flow.csv"), index=False)

# every zero-trade account with its cause
Z = sf[sf["trades"] == 0][["run_label", "account_id", "kind", "strategy", "timeframe", "sig_SUBMITTED", "sig_RECORD",
                           "out_ENTERED:ok", "out_REJECTED:sizing", "open_at_end", "zero_trade_cause"]]
Z.to_csv(os.path.join(W, "zero_trade_accounts.csv"), index=False)

pd.set_option("display.width", 250)
pd.set_option("display.max_rows", 500)
print("\n== zero-trade accounts by run/kind/cause")
print(Z.groupby(["run_label", "kind", "zero_trade_cause"]).size())
print("\n== strategy x tf with zero trades in EVERY run (non-random)")
zz = F[(F["zero_trade_all_runs"]) & (F["kind"].isin(["strategy", "ds200"]))]
print(zz[["kind", "strategy", "timeframe", "runs_present", "sig_SUBMITTED", "out_REJECTED:sizing", "open_at_end",
          "zero_cause_v3a", "zero_cause_v3b", "zero_cause_v4", "ref5y_per_day", "p_le_obs_under_5y_rate"]].to_string())
print("\n== kind x tf totals")
kt = sf.groupby(["run_label", "kind", "timeframe"]).agg(acc=("account_id", "size"), sub=("sig_SUBMITTED", "sum"),
                                                       ent=("out_ENTERED:ok", "sum"),
                                                       inpos=("out_SKIPPED:in position", "sum"),
                                                       lower=("out_SKIPPED:lower score", "sum"),
                                                       rej=("out_REJECTED:sizing", "sum"), days=("days", "first"))
kt["sub_per_acct_day"] = kt["sub"] / kt["acc"] / kt["days"]
for c in ["ent", "inpos", "lower", "rej"]:
    kt["sh_" + c] = kt[c] / kt["sub"]
print(kt.round(3).to_string())
kt.reset_index().to_csv(os.path.join(W, "flow_kind_tf.csv"), index=False)
