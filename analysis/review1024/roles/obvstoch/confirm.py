"""Step 2 (PLAN.md section 4): the ONE read of the picked cells on CONF (2024-01-01 .. 2026-10-23), with Holm across the
picks of each track (S1 = picks.csv, S2 = picks_payback.csv), then the descriptive reads PRE / YTD / FWD / FIVE of the
same cells and the controls. Writes conf_picks.csv.

    python3 confirm.py
"""
import oscore as O
from oscore import *
from scipy.stats import norm


parse, holm = O.parse, O.holm


D = O.load_all()
out = []
for track, f, pb in (("S1", "picks.csv", False), ("S2", "picks_payback.csv", True)):
    K = pd.read_csv(f)
    recs = []
    for r in K.itertuples():
        tf, htf, T, Ot, X = parse(r.cell)
        add = PAYBACK * O.LEVX[X] if pb else 0.0
        row = {"track": track, "cell": r.cell, "pick_kind": r.pick_kind, "sel_n": r.n, "sel_mean_roe": r.mean_roe + add,
               "sel_mean_d": r.mean_d}
        for per in ("CONF", "PRE", "YTD", "FWD", "FIVE"):
            R = O.rows(D, tf, htf, T, Ot, X, per)
            R["roe"] = R["roe"] + add
            R["opp"] = R["opp"] + add
            s = O.summarize(R)
            Rt = O.rows(D, tf, htf, T, None, X, per, trend_only=True)
            for k in ("n", "mean_roe", "t_abs", "p_abs", "mean_opp", "mean_d", "t_d", "win", "long_share"):
                row[f"{per}_{k}"] = s[k]
            row[f"{per}_per_day"] = s["n"] / max((min(O.P[per][1], ext_end()) - O.P[per][0]) / DAY, 1e-9)
            row[f"{per}_trend_only"] = float(Rt["roe"].mean() + add) if len(Rt["roe"]) else np.nan
        recs.append(row)
    Rf = pd.DataFrame(recs)
    Rf["CONF_p_holm"] = holm(Rf.CONF_p_abs.fillna(1.0).to_numpy())
    Rf["confirmed"] = (Rf.CONF_mean_roe > 0) & (Rf.CONF_p_holm < 0.05) & (Rf.CONF_mean_d > 0)
    out.append(Rf)
R = pd.concat(out, ignore_index=True)
R.to_csv("conf_picks.csv", index=False)
pd.set_option("display.width", 250)
cols = ["track", "cell", "sel_mean_roe", "CONF_n", "CONF_mean_roe", "CONF_t_abs", "CONF_p_holm", "CONF_mean_opp",
        "CONF_mean_d", "CONF_trend_only", "confirmed"]
print(R[cols].round(4).to_string())
cols2 = ["track", "cell", "PRE_n", "PRE_mean_roe", "YTD_n", "YTD_mean_roe", "FWD_n", "FWD_mean_roe", "FWD_mean_opp",
         "FWD_trend_only", "FWD_long_share", "FIVE_mean_roe"]
print(R[cols2].round(4).to_string())
