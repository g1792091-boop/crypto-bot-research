"""After PREREG11 (a read the owners asked for on 10/24 night, not a new test: "이걸로 해서 손절은 50%로 해서 해봐"): PREREG11's B (the
manual style's 15m friend signal with the 1h OR 4h ROC9, PREREG10's four bigger-trend conditions, 35x, the ladder 12 -> 10 then 5 %
steps, one position, the entry blocks, margin 40 %, the TetherMax payback 90 %) with the stop at -50 %: on the screen's ROE before
fees (PREREG11's reference row, here with the coin-flip twin) and on the net ROE (the bots' usual -50 % stop). B with the screen's
-20 % stop beside them.

    python3 -I frladder50.py      -> research/friendroc/results16.json"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # python3 -I leaves the script's folder out
from frcore import *
from frloss import PER, FL
from frfamily import signals
from frbracket import detail
from frtrend4 import trend_columns, conditions
from frladder35 import outcomes, exits, FEE_ROE


def main():
    A = signals("15m")
    R = trend_columns(A[A.block == ""].reset_index(drop=True))
    t4 = np.logical_and.reduce(list(conditions(R).values()))
    doge = (R.coin == COINS.index("DOGEUSDT")).to_numpy()
    res = {}
    for nm, net_stop in (("손절 화면 −20", -0.20 - FEE_ROE), ("손절 화면 −50", -0.50 - FEE_ROE), ("손절 순ROE −50", -0.50)):
        O = outcomes(R, net_stop, FL)
        Oo = outcomes(R, net_stop, FL, flip=True)
        d = detail(R, O, t4, Oo)
        d["exits"] = exits(R, O, t4)
        d["doge"] = detail(R, O, t4 & doge)
        res[nm] = d
        print(f"== B + 네 조건 · 계단 · {nm} (net stop {net_stop * 100:.2f}%)", flush=True)
        for p in PER:
            x = d[p]
            print(f"  {p:8s} n{x['n']} {x['per_weekday']}/d w{x['win']} be{x['breakeven_win']} aw{x['avg_win_pct']} al{x['avg_loss_pct']} "
                  f"roe{x['roe_pct']} (no pb {x['roe_pct_no_payback']}) x40 {x['mult40']} dd{x['maxdd40']} twin {x.get('twin')} | {d['exits'][p]}", flush=True)
        print("  months", d["months"], "goal90", d["goal90"], flush=True)
        print("  doge", {p: (d["doge"][p]["n"], d["doge"][p]["win"], d["doge"][p]["roe_pct"], d["doge"][p]["mult40"]) for p in PER}, flush=True)
    json.dump(res, open(os.path.join(RES_DIR, "results16.json"), "w"), ensure_ascii=False, indent=1, default=float)


if __name__ == "__main__":
    main()
