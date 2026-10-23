"""참고 read: 'VWAP 개선판' (PREREG_FWD1.md candidate A) entries over the rule bot's run (2026-10-05 19:30 UTC .. the data
end) under the live bot's exit and size rules (deploy/combo.trend.json: margin 40 %, BTC 40x / others 30x, net ROE -50 %
stop, the owners' ladder, early exit on the same strategy's opposite signal before the first lock, no time exit), next to
A under the paper rules. One position.

    python3 -I vwliveA.py   -> research/vwap30/liveA.json"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # python3 -I leaves the script's folder out
from vwfix2 import *
import vwlive19 as LV


def main():
    lib = sweepsig.lib()
    parts = []
    for coin in COINS:
        R = rows_tf(coin, "30m", lib)
        parts.append(R[(R.t >= START) & (R.t < DATA_END - MIN)])
    R = pd.concat(parts, ignore_index=True).sort_values(["t", "coin"]).reset_index(drop=True)
    t = R.t.to_numpy()
    kst = pd.to_datetime(t + KST, unit="ms")
    wd = np.asarray(kst.dayofweek < 5)
    usop = np.array([bool(us_open_pause(int(x), 30, 30)) for x in t])
    macro = np.array([bool(EV.near(int(x), 30 * MIN, 30 * MIN)) for x in t])
    A = wd & ~usop & ~macro & ~(R.j4h.to_numpy() < 0) & ~(R.atrp.to_numpy() > R.atrp_q80.to_numpy())
    trades, free = [], -1
    for q in np.flatnonzero(A):
        r = R.iloc[q]
        if r.t < free:
            continue
        cn = COINS[int(r.coin)]
        opp = R[(R.coin == r.coin) & (R.side == -r.side) & (R.t > r.t)].t.to_numpy()
        k, ret, why, best = LV.trade(cn, int(r.e), int(r.side), (opp - T0) // MIN - int(r.e))
        L = LV.LEV.get(cn, 30)
        trades.append({"coin": cn[:-4], "side": "롱" if r.side > 0 else "숏", "entry_kst": str(pd.Timestamp(int(r.t) + KST, unit="ms"))[:16],
                       "lev": L, "roe": float(L * ret), "why": why})
        free = int(r.t) + (k + 1) * MIN
    LV.MARGIN = 0.40
    sm = LV.summary(trades)
    out = {"live_rules": sm, "trades": trades}
    print(json.dumps(sm, ensure_ascii=False))
    json.dump(out, open(os.path.join(RES_DIR, "liveA.json"), "w"), ensure_ascii=False, indent=1, default=float)


if __name__ == "__main__":
    main()
