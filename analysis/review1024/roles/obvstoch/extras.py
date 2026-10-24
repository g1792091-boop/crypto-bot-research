"""Extra descriptive tables for the report: (1) per calendar year for L1 / L2 / the friend family A (w35 and a2) with the
coin-flip twin and trend-only; (2) the last 19 days split by side (long / short) for family A and all cells; (3) gross
(before costs) per-trade mean of family A; (4) weekend/macro block (blk == 0) effect on the account rows.
Writes extras_year.csv, extras_side_fwd.csv, extras.json."""
import json
import oscore as O
from oscore import *

D = O.load_all()
yrs = [(str(y), (ms(f"{y}-01-01") if y > 2020 else ms("2020-03-01"), ms(f"{y + 1}-01-01") if y < 2026 else GRID_END))
       for y in range(2020, 2027)] + [("FWD", O.P["FWD"])]
lit = {"L1": ("30m", "1h", "OBV30", "SRSI_KD"), "L2": ("1h", "4h", "OBV30", "SRSI_KD")}
recs = []
for lab, (tf, htf, T, Ot) in lit.items():
    for X in ("w35", "a2"):
        for y, per in yrs:
            R = O.rows(D, tf, htf, T, Ot, X, per)
            s = O.summarize(R)
            Rt = O.rows(D, tf, htf, T, None, X, per, trend_only=True)
            recs.append({"what": lab, "exit": X, "year": y, "n": s["n"], "mean_roe": s["mean_roe"], "t_abs": s["t_abs"],
                         "mean_opp": s["mean_opp"], "trend_only": float(Rt["roe"].mean()), "long_share": s["long_share"],
                         "win": s["win"]})
# family A average per year (w35, a2)
famA = [(tf, htf, T, Ot) for (tf, htf) in O.MAPS for T in O.OBV_TRENDS for Ot in O.SRSI]
for X in ("w35", "a2"):
    for y, per in yrs:
        ms_, mo, n_, pos = [], [], [], 0
        for c in famA:
            R = O.rows(D, *c, X, per)
            if len(R["roe"]):
                ms_.append(R["roe"].mean()); mo.append(R["opp"].mean()); n_.append(len(R["roe"]))
                pos += R["roe"].mean() > 0
        recs.append({"what": "A_avg_160/4exits", "exit": X, "year": y, "n": float(np.mean(n_)), "mean_roe": float(np.mean(ms_)),
                     "mean_opp": float(np.mean(mo)), "cells_pos": pos, "cells": len(ms_)})
Y = pd.DataFrame(recs)
Y.to_csv("extras_year.csv", index=False, float_format="%.5g")
# (2) last 19 days by side
side = []
for (tf, htf, T, Ot, X) in O.cells():
    R = O.rows(D, tf, htf, T, Ot, X, "FWD")
    for sd, nm in ((1, "long"), (-1, "short")):
        m = R["side"] == sd
        side.append({"cell": O.cell_id(tf, htf, T, Ot, X), "famA": T in O.OBV_TRENDS and Ot in O.SRSI, "side": nm,
                     "n": int(m.sum()), "mean_roe": float(R["roe"][m].mean()) if m.any() else np.nan})
SD = pd.DataFrame(side)
SD.to_csv("extras_side_fwd.csv", index=False, float_format="%.5g")
out = {}
for fam in (True, False):
    q = SD[SD.famA == fam] if fam else SD
    for nm in ("long", "short"):
        z = q[(q.side == nm) & (q.n > 0)]
        out[f"fwd_{'A' if fam else 'all'}_{nm}_mean_of_cells"] = float(z.mean_roe.mean())
        out[f"fwd_{'A' if fam else 'all'}_{nm}_pooled"] = float((z.mean_roe * z.n).sum() / z.n.sum())
        out[f"fwd_{'A' if fam else 'all'}_{nm}_signals"] = int(z.n.sum())
# (3) gross per-trade of family A over five years (cost added back: COST x leverage); approximate (the net-ROE stop
#     itself sits on net ROE)
for X in O.EXITS:
    g = []
    for c in famA:
        R = O.rows(D, *c, X, "FIVE")
        g.append(R["roe"].mean() + COST * O.LEVX[X])
    out[f"A_five_gross_{X}"] = float(np.mean(g))
# (4) block effect in the account rows
A = pd.read_csv("accounts.csv")
v = A[(A.margin == 0.4) & (A.side == "signal") & (~A.payback) & (A.period == "CONF")]
out["blk0_effect_conf"] = v.pivot_table(index="cell", columns="blk0", values="mean_roe").round(4).to_dict()
json.dump(out, open("extras.json", "w"), indent=1, default=float)
pd.set_option("display.width", 220)
print(Y.round(4).to_string())
print(json.dumps(out, indent=1, default=float))
