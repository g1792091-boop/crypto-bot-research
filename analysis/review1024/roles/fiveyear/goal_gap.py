"""How far from the goal: for chosen bots, on their CONFIRM trades (one position, w35), the per-trade ROE shift delta
(ROE points at 35x, added to every trade) that makes the growth-optimal 30-day median multiple reach x6 at the bot's
CONFIRM trade rate, and the margin that needs. Also the same with the TetherMax payback already added.
    python3 goal_gap.py  ->  goal_gap_delta.csv"""
from fy_analyze import bh, pval, ENTRY_ROLES
from goalpath import *


def need(roe, per_day):
    for d in np.arange(0.0, 0.40, 0.0025):
        m, x = growth_opt(roe + d, per_day)
        if x >= 6.0:
            return d, m
    return np.nan, np.nan


def main():
    fam = pd.read_pickle(os.path.join(SHM, "cells.pkl"))
    sel = pd.read_csv(os.path.join(HERE, "shortlist.csv"))
    import json
    cfg = json.load(open(os.path.join(REPO, "deploy", "combo.trend.json")))
    hmap = {"30m": "1h", "1h": "4h", "4h": "1d"}
    N = RD.names()
    bots = {
        "B_sel_with20": [(r["name"], r.etf, r.htf, r.source.split(":")[0], r.source.split(":")[1], "W")
                         for _, r in sel[sel.cond == "W"].iterrows()],
        "C_friend_30m": [("O4_STOCHRSI_ZONE", "30m", "1h", "c", "OBV_S", "W")],
        "D_trendbot18": [(m["strategy"], m["tf"], hmap[m["tf"]], "j", "TB22", "P") for m in cfg["members"]],
        "E_timing_v4of4": [(nm, tf, "1h", "j", "V4OF4", "W") for tf in ("15m", "30m")
                           for nm in N.name[N.role == "timing"]],
    }
    rows = []
    for b, specs in bots.items():
        S = bot_rows(specs)
        o, T = read(S, "CONF")
        roe = np.maximum(T.w35_roe.to_numpy(), -1.0)
        d0, m0 = need(roe, o["per_day"])
        d1, m1 = need(roe + 35 * PAYBACK, o["per_day"])
        rows.append({"bot": b, "per_day": o["per_day"], "mean_roe": roe.mean(), "sd_roe": roe.std(),
                     "need_shift_roe_pts": d0 * 100, "need_mean_roe": (roe.mean() + d0) * 100, "margin_at_need": m0,
                     "need_shift_with_payback_pts": d1 * 100, "margin_at_need_pb": m1})
        log(b, rows[-1])
    D = pd.DataFrame(rows)
    D.to_csv(os.path.join(HERE, "goal_gap_delta.csv"), index=False, float_format="%.4g")
    print(D.round(3).to_string())


if __name__ == "__main__":
    main()
