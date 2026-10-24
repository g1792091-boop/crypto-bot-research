"""Goal path of the cells that looked best on the second half (H2). WARNING: choosing them after seeing H2 is a
second look at H2, so these numbers are NOT out of sample any more (they are the best of 10 / 5 picks, plus the
5-year read in fiveyear_picks.csv as the independent check). Each cell alone as a one-position bot on H2, and on the
whole 19 days, with the coin-flip twin and the goal bootstrap.  Writes bestoos_accounts.csv, bestoos_goal.csv.
Run: python3 fw_bestoos.py"""
from fw_lib import *  # noqa: F401,F403
from fw_combo import add_roe, goal, growth, MARGINS, cell_rows, bot

CELLS = [
    ("w35", {"level": "E", "key": "F4_PULL|1h", "tf": "1h", "htf": "4h", "src": "c_N09_ALLIG_AROON", "rank": 1}),
    ("w35", {"level": "E", "key": "N06_MACD_ORB|15m", "tf": "15m", "htf": "1h", "src": "l_F3_HHHL", "rank": 1}),
    ("a2", {"level": "F", "key": "timing|1h", "tf": "1h", "htf": "4h", "src": "c_N07_ICHI_CMO", "rank": 1}),
    ("a2", {"level": "F", "key": "reversal|1h", "tf": "1h", "htf": "4h", "src": "c_N07_ICHI_CMO", "rank": 1}),
    ("a2", {"level": "E", "key": "F15_ASIA_SWEEP|30m", "tf": "30m", "htf": "1h", "src": "c_N01_ST_EMA", "rank": 1}),
    ("a2", {"level": "E", "key": "V2_BB_REVERT|4h", "tf": "4h", "htf": "1d", "src": "l_N24_DMI", "rank": 1}),
]


def main():
    S = add_roe(load("sig"))
    acc, gl = [], []
    for v, c in CELLS:
        X = cell_rows(S, [c])
        name = f"{v}:{c['key']}@{c['htf']}:{c['src']}"
        for per in ("H2", "all"):
            for sc in ("", "_opp"):
                T = bot(X, v, per, sc)
                if not len(T):
                    continue
                a, b = PERIOD[per]
                A = RD.account(T, v, margin=0.4, side_col=sc, start=a, end=b)
                mopt, gopt = growth(T, v, sc)
                sgn = T.side.to_numpy() * (-1 if sc else 1)
                acc.append({"cell": name, "period": per, "side": "opp" if sc else "signal", "signals": int(
                    ((X.t >= a) & (X.t < b)).sum()), **A, "nL": int((sgn > 0).sum()), "nS": int((sgn < 0).sum()),
                    "roe_L": T[f"{v}{sc}_roe"][sgn > 0].mean(), "roe_S": T[f"{v}{sc}_roe"][sgn < 0].mean(),
                    "roe_payback": A["mean_roe"] + LEV[v] * PAYBACK, "kelly_margin": mopt,
                    "x30_at_kelly": float(np.exp(gopt * A["per_day"] * 30))})
                if sc == "":
                    for mg in MARGINS:
                        Am = RD.account(T, v, margin=mg, start=a, end=b)
                        G = goal(T, v, mg, (a, b))
                        gl.append({"cell": name, "period": per, "margin": mg, "exposure_x": LEV[v] * mg,
                                   "final_x_sample": Am["final_x"], "max_dd_sample": Am["max_dd"], **G})
        log(name)
    pd.DataFrame(acc).to_csv(os.path.join(HERE, "bestoos_accounts.csv"), index=False, float_format="%.5g")
    pd.DataFrame(gl).to_csv(os.path.join(HERE, "bestoos_goal.csv"), index=False, float_format="%.5g")


if __name__ == "__main__":
    main()
