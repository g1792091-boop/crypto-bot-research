"""One-position bots for sets fixed WITHOUT looking at the forward data (so the whole 19 days are out of sample for the
selection; only the friend's rule and the live design decide what is taken):
  P1 every non-trend entry (77 strategies, 15m-4h) taking only signals WITH the live judge (Jdir, auto mapping)
  P2 the same, only signals AGAINST it (what the friend says not to do)
  P3 the same, all signals (no trend filter: how the rule bot runs each strategy)
  P4 the trend bot's 18 members (default numbers) + the bot's full checks (10-22 design: tj_why_1022 == '')
  P5 the friend's own example: O4_STOCHRSI_ZONE 1h + OBV_S state of the last closed 4h bar
  P6 every non-trend entry WITH the 4-of-4 vote (stricter judge)
  P7 the friend's own words: 횡보 자리 (range) + 눌림 (pullback) + 돌파 (breakout) entries WITH the live judge (auto)
  P8 the same, only 30m entries with the 1h judge ("30분봉 진입이면 1시간봉 추세")
Each under w35 and a2, signal side and coin-flip twin, all / H1 / H2, with and without the live entry blocks.
Goal path at margins 0.05 .. 1.0 (w35 = 35x, a2 = 30x). Writes prespec_bots.csv, prespec_goal.csv.
Run: python3 fw_prespec_bots.py"""
import json
from fw_lib import *  # noqa: F401,F403
from fw_combo import add_roe, goal, growth, MARGINS


def auto_state(S, src):
    a = np.zeros(len(S), np.int8)
    for t_, h_ in AUTO.items():
        m = S.tf.to_numpy() == t_
        a[m] = state(S, src, h_)[m]
    return a


def main():
    S = add_roe(load("sig"))
    side = S.side.to_numpy()
    nt = S.role.to_numpy() != "trend"
    jd = auto_state(S, "Jdir") * side
    j4 = auto_state(S, "J4of4") * side
    mem = json.load(open(os.path.join(REPO, "deploy", "combo.trend.json")))["members"]
    mm = np.zeros(len(S), bool)
    for it in mem:
        mm |= (S.name.to_numpy() == it["strategy"]) & (S.tf.to_numpy() == it["tf"])
    fr = (S.name.to_numpy() == "O4_STOCHRSI_ZONE") & (S.tf.to_numpy() == "1h") & \
         ((state(S, "c_OBV_S", "4h") * side) == 1)
    fam = np.isin(S.role.to_numpy(), ["pullback", "range", "breakout"])
    sets = {"P1_entry_with_Jdir": nt & (jd == 1), "P2_entry_against_Jdir": nt & (jd == -1), "P3_entry_all": nt,
            "P4_trendbot18_checks": mm & (S.tj_why_1022.to_numpy() == ""), "P5_friend_OBV4h_StochRSI1h": fr,
            "P6_entry_with_J4of4": nt & (j4 == 1),
            "P7_friend_pull_range_brk_Jdir": fam & (jd == 1),
            "P8_friend_30m_on_1h_Jdir": fam & (S.tf.to_numpy() == "30m") & (jd == 1)}
    rows, gl = [], []
    for name, m in sets.items():
        X = S[m].copy()
        X["prio"] = X.coin.astype(int) * 10 + X.tf.map({t: i for i, t in enumerate(TFS)}).astype(int)
        for v in ("w35", "a2"):
            for per in ("all", "H1", "H2"):
                for blocks in (False, True):
                    for sc in ("", "_opp"):
                        a, b = PERIOD[per]
                        Y = X[(X.t >= a) & (X.t < b) & (X[f"{v}{sc}_why"] != 3)]
                        if blocks:
                            Y = Y[Y.blk == 0]
                        Y = Y.reset_index(drop=True)
                        if not len(Y):
                            continue
                        T = Y[RD.one_position(Y, v, side_col=sc, priority="prio")]
                        A = RD.account(T, v, margin=0.4, side_col=sc, start=a, end=b)
                        mopt, gopt = growth(T, v, sc)
                        sgn = T.side.to_numpy() * (-1 if sc else 1)
                        rows.append({"set": name, "exit": v, "period": per, "blocks": blocks,
                                     "side": "opp" if sc else "signal", "signals": len(Y), **A,
                                     "nL": int((sgn > 0).sum()), "nS": int((sgn < 0).sum()),
                                     "roe_L": T[f"{v}{sc}_roe"][sgn > 0].mean(), "roe_S": T[f"{v}{sc}_roe"][sgn < 0].mean(),
                                     "roe_payback": A["mean_roe"] + LEV[v] * PAYBACK, "kelly_margin": mopt,
                                     "x30_at_kelly": float(np.exp(gopt * A["per_day"] * 30))})
                        if sc == "" and not blocks and per in ("all", "H2"):
                            for mg in MARGINS:
                                Am = RD.account(T, v, margin=mg, start=a, end=b)
                                G = goal(T, v, mg, (a, b))
                                gl.append({"set": name, "exit": v, "period": per, "margin": mg, "exposure_x": LEV[v] * mg,
                                           "final_x_sample": Am["final_x"], "max_dd_sample": Am["max_dd"], **G})
        log(name, int(m.sum()))
    pd.DataFrame(rows).to_csv(os.path.join(HERE, "prespec_bots.csv"), index=False, float_format="%.5g")
    pd.DataFrame(gl).to_csv(os.path.join(HERE, "prespec_goal.csv"), index=False, float_format="%.5g")


if __name__ == "__main__":
    main()
