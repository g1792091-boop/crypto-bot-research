"""Goal path (+500 % in 30 days = x6) for the trend bot's variants: day-block bootstrap of 30-day paths from the taken
trades (RD.goal_bootstrap: P(x6), P(-50 % first), P(-90 % first), median end), margins 0.2 .. 1.0, without / with the
TetherMax payback; the per-trade mean ROE a x6 month would need at each variant's trade rate; and the forward trend
luck check (the same entries' short side and long side). Run: python3 lb_goal.py"""
import lb_core as L
from lb_core import *  # noqa: F401,F403

VARS = ["B0", "B3", "B4", "B5", "B6", "B7", "B9", "W3"]
POOL = {"confirm+late": (L.P_CON[0], L.P_LATE[1]), "fwd": L.P_FWD, "select": L.P_SEL}


def load(v):
    return pd.read_csv(os.path.join(L.LB, "trades", f"trades_{v}.csv.gz"))


def main():
    rows, need, luck = [], [], []
    for v in VARS:
        T = load(v)
        lev = lev_of(T.coin.to_numpy())
        for pn, (a, b) in POOL.items():
            P = T[(T.t >= a) & (T.t < b)].copy()
            if len(P) < 5:
                continue
            days = (b - a) / DAY
            n30 = len(P) / days * 30
            for pb in (False, True):
                Q = P.copy()
                if pb:
                    Q["tb_roe"] = Q.tb_roe + lev_of(Q.coin.to_numpy()) * PAYBACK
                for m in (0.2, 0.4, 0.6, 1.0):
                    g = RD.goal_bootstrap(Q, "tb", margin=m, days=(a, b), n_boot=4000 if pn != "fwd" else 20000)
                    rows.append({"variant": v, "pool": pn, "payback": pb, "margin": m, "trades": len(Q),
                                 "trades_30d": n30, "mean_roe": Q.tb_roe.mean(), **g})
            # needed mean ROE per trade for x6 in 30 days at this rate, no variance (a floor; variance needs more)
            for m in (0.4, 1.0):
                need.append({"variant": v, "pool": pn, "margin": m, "trades_30d": n30,
                             "need_roe_floor": (6 ** (1 / max(n30, 1)) - 1) / m, "have_roe": P.tb_roe.mean(),
                             "have_roe_payback": (P.tb_roe + lev_of(P.coin.to_numpy()) * PAYBACK).mean()})
            if pn == "fwd":
                short = np.where(P.side < 0, P.tb_roe, P.tb_opp_roe)
                long_ = np.where(P.side > 0, P.tb_roe, P.tb_opp_roe)
                luck.append({"variant": v, "n": len(P), "short_share": (P.side < 0).mean(), "own": P.tb_roe.mean(),
                             "opp": P.tb_opp_roe.mean(), "always_short": short.mean(), "always_long": long_.mean(),
                             "own_long": P.tb_roe[P.side > 0].mean(), "own_short": P.tb_roe[P.side < 0].mean(),
                             "n_long": int((P.side > 0).sum())})
    G = pd.DataFrame(rows)
    G.to_csv(os.path.join(L.LB, "goal_paths.csv"), index=False, float_format="%.4g")
    N = pd.DataFrame(need)
    N.to_csv(os.path.join(L.LB, "goal_need.csv"), index=False, float_format="%.4g")
    K = pd.DataFrame(luck)
    K.to_csv(os.path.join(L.LB, "fwd_trend_luck.csv"), index=False, float_format="%.4g")
    pd.set_option("display.width", 220)
    print(G[(G.margin == 0.4)].round(4).to_string(index=False))
    print(N.round(4).to_string(index=False))
    print(K.round(4).to_string(index=False))
    # the market over the forward days
    for c in COINS:
        g = grid(c)
        a, b = (FWD[0] - T0) // MIN, min((FWD[1] - T0) // MIN, g["n"] - 1)
        print(c, "forward change %.1f%%" % (100 * (g["c"][b] / g["o"][a] - 1)))
        drop(c)


if __name__ == "__main__":
    main()
