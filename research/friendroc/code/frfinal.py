"""The live rule the owners chose on 10/24 night for the friend's WOO X Pro account (a read for the bot guide's numbers, not a test):
15m EMA21 > EMA52, RSI26 > 50, ROC9 crossing 0 upward, and on the last closed 1h bar RSI26 > 50 and ROC9 > 0 (no 1h EMA, no 4h;
shorts mirrored); 35x, the screen's -20 % stop, the ladder 12 -> 10 then 5 % steps, one position, the entry blocks, margin 40 %,
the TetherMax payback 90 % per trade.

    python3 -I frfinal.py         -> research/friendroc/results20.json"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # python3 -I leaves the script's folder out
from frcore import *
from frloss import PER, FL
from frbracket import detail
from frladder35 import outcomes, exits, FEE_ROE
from frhtrend import raw15
from frhtrend2 import add_rsi


def main():
    A = add_rsi(pd.concat([raw15(c) for c in COINS], ignore_index=True))
    A = A.iloc[np.lexsort((A.coin.to_numpy(), A.t.to_numpy()))].reset_index(drop=True)
    with np.errstate(invalid="ignore"):
        A = A[(A.roc_1h.to_numpy() > 0) & (A.rsi_1h.to_numpy() > 0)].reset_index(drop=True)
    A["block"] = [blocked(int(x)) for x in A.t.to_numpy()]
    R = A[A.block == ""].reset_index(drop=True)
    O = outcomes(R, -0.20 - FEE_ROE, FL)
    Oo = outcomes(R, -0.20 - FEE_ROE, FL, flip=True)
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
    json.dump(d, open(os.path.join(RES_DIR, "results20.json"), "w"), ensure_ascii=False, indent=1, default=float)


if __name__ == "__main__":
    main()
