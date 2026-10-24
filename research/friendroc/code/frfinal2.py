"""The live rule the owners chose by the last 19 days (10/24 night, a read for the bot guide's numbers, not a test): the original
friend signal (15m EMA21 vs EMA52, RSI26 vs 50, ROC9 crossing 0, and the last closed 1h OR 4h ROC9 on the side; frfamily.signals),
nothing else; 35x, net ROE -50 % stop, the ladder 12 -> 10 then 5 % steps, one position, the entry blocks, margin 40 %, the TetherMax
payback 90 % per trade.

    python3 -I frfinal2.py        -> research/friendroc/results22.json"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # python3 -I leaves the script's folder out
from frcore import *
from frloss import PER, FL
from frfamily import signals
from frbracket import detail
from frladder35 import outcomes, exits


def main():
    A = signals("15m")
    R = A[A.block == ""].reset_index(drop=True)
    O = outcomes(R, -0.50, FL)
    Oo = outcomes(R, -0.50, FL, flip=True)
    use = np.ones(len(R), bool)
    d = detail(R, O, use, Oo)
    d["exits"] = exits(R, O, use)
    d["doge"] = detail(R, O, use & (R.coin == COINS.index("DOGEUSDT")).to_numpy())
    d["signals_all"], d["signals_unblocked"] = len(A), len(R)
    print("signals", len(A), "unblocked", len(R), flush=True)
    for p in PER:
        x = d[p]
        print(f"  {p:8s} n{x['n']} {x['per_weekday']}/d w{x['win']} be{x['breakeven_win']} aw{x['avg_win_pct']} al{x['avg_loss_pct']} "
              f"roe{x['roe_pct']} (no pb {x['roe_pct_no_payback']}) x40 {x['mult40']} dd{x['maxdd40']} twin {x.get('twin')} | {d['exits'][p]}", flush=True)
    print("  months", d["months"], "goal90", d["goal90"], flush=True)
    print("  doge", {p: (d["doge"][p]["n"], d["doge"][p]["win"], d["doge"][p]["roe_pct"], d["doge"][p]["mult40"]) for p in PER}, flush=True)
    json.dump(d, open(os.path.join(RES_DIR, "results22.json"), "w"), ensure_ascii=False, indent=1, default=float)


if __name__ == "__main__":
    main()
