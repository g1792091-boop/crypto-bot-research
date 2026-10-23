"""참고 read, continued from vwloss6.py (no selection, every variant shown): 'VWAP 개선판' (PREREG_FWD1.md candidate A) with
one more change at a time, on the rule bot's run (to the data end), 2020-03 .. 2024-12 and 2025-01 .. 2026-09; trades per
month next to each. Changes from the 6 stops: skip a quiet market (ADX below 15 / 20), skip the owners' chase (long in the top
of the 24h / 7-day range, short in the bottom), skip a close more than 1 ATR from the day's VWAP, and ADX 20 + no chase.

    python3 -I vwfix3.py   -> research/vwap30/fix3.json"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # python3 -I leaves the script's folder out
from vwfix2 import *


def main():
    lib = sweepsig.lib()
    parts = []
    for coin in COINS:
        R = rows_tf(coin, "30m", lib)
        O = outcomes_tf(coin, R, 30)
        R["r"], R["x"] = O["base"]
        parts.append(R)
        print("built", coin, len(R), flush=True)
    R = pd.concat(parts, ignore_index=True)
    t, coin = R.t.to_numpy(), R.coin.to_numpy()
    kst = pd.to_datetime(t + KST, unit="ms")
    wd = np.asarray(kst.dayofweek < 5)
    usop = np.array([bool(us_open_pause(int(x), 30, 30)) for x in t])
    macro = np.array([bool(EV.near(int(x), 30 * MIN, 30 * MIN)) for x in t])
    A = wd & ~usop & ~macro & ~(R.j4h.to_numpy() < 0) & ~(R.atrp.to_numpy() > R.atrp_q80.to_numpy())
    adx, chase, cva = R.adx.to_numpy(), R.chase.to_numpy(bool), R.cva.to_numpy()
    lev_cap = 0.3 * np.minimum(LEVP, 0.5 / (2.0 * R.atrf.to_numpy() + COST_RT))
    V = [("A 그대로", A), ("G1 A + 횡보(ADX 15 미만) 빼기", A & ~(adx < 15)), ("G2 A + 횡보(ADX 20 미만) 빼기", A & ~(adx < 20)),
         ("G3 A + 추격 진입 빼기", A & ~chase), ("G4 A + VWAP에서 1ATR 넘게 멀면 빼기", A & ~(cva > 1.0)),
         ("G5 A + ADX 20 미만 빼기 + 추격 빼기", A & ~(adx < 20) & ~chase)]
    per = {"17일": (START, DATA_END - MIN), "2020-03~2024-12": SEL, "2025-01~2026-09": (ms("2025-01-01"), ms("2026-10-01"))}
    months = {pn: (z - a) / DAY / 30.44 for pn, (a, z) in per.items()}
    res = {}
    for name, mask in V:
        row = {}
        for pn, (a, z) in per.items():
            m = mask & (t >= a) & (t < z)
            x = account2(t, coin, R.r.to_numpy(), R.x.to_numpy(), m, lev_cap)
            x["per_month"] = round(x["n"] / months[pn], 1)
            row[pn] = x
        res[name] = row
        print(name, " | ".join(f"{pn[:4]} n{v['n']}(월{v['per_month']}) {v['wins']}승{v['losses']}패 손절평균{v['avg_loss_roe']} "
                               f"net{v['avg_net_pct']} x{v['mult']} dd{v['maxdd']}" for pn, v in row.items()), flush=True)
    json.dump(res, open(os.path.join(RES_DIR, "fix3.json"), "w"), ensure_ascii=False, indent=1, default=float)


if __name__ == "__main__":
    main()
