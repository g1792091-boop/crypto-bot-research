"""Own day-block bootstrap (different seed, own code) of the 30-day goal path for OBV30@4h > SRSI_X@1h | a2 from the
independent rows (vrebuild.py): one position at a time, UTC-day blocks (days without trades kept), 30 days, x6 target,
P(-50 % / -90 % first). Also the forward window shifted by one 4h bar (the 'late' rows) for fragility.
Writes vgoal.json.

    python3 vgoal.py
"""
import os
import sys
import json

sys.path.insert(0, "/home/user/crypto-bot-research/analysis/review1024/roles/data")
from common import ms, DAY, COINS, PAYBACK, GRID_END, ext_end  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from vsummary import one_pos  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
LEV = 30.0


def boot(T, a, b, margin, n=20000, seed=7):
    roe = np.maximum(T.roe.to_numpy() + LEV * PAYBACK, -1.0)
    d = T.t.to_numpy() // DAY
    lo, hi = a // DAY, (b - 1) // DAY
    nd = int(hi - lo + 1)
    by = [roe[d == lo + i] for i in range(nd)]
    rng = np.random.default_rng(seed)
    hit = l50 = l90 = 0
    fin = np.empty(n)
    for i in range(n):
        eq, h50, done = 1.0, False, False
        for di in rng.integers(0, nd, 30):
            for x in by[di]:
                eq *= 1 + margin * x
                if not done:
                    if eq >= 6:
                        hit += 1
                        done = True
                    else:
                        if eq <= 0.5 and not h50:
                            l50 += 1
                            h50 = True
                        if eq <= 0.1:
                            l90 += 1
                            done = True
        fin[i] = eq
    return {"p_x6": hit / n, "p_lose50_first": l50 / n, "p_lose90_first": l90 / n, "median_x": float(np.median(fin)),
            "days": nd, "trades": len(roe)}


def main():
    out = {}
    for v in ("ok", "late"):
        R = pd.read_csv(os.path.join(HERE, f"rows_{v}.csv.gz"))
        R["coin_i"] = R.coin.map({c: i for i, c in enumerate(COINS)})
        R = R[(R.why != 3) & (R.why_opp != 3)]
        for per, (a, b) in (("FWD", (ms("2026-10-05 15:00"), ext_end())), ("CONF", (ms("2024-01-01"), GRID_END))):
            if v == "late" and per == "CONF":
                continue
            T = one_pos(R[(R.t >= a) & (R.t < b)]).sort_values("t")
            for m in ((0.58, 0.4) if per == "FWD" else (0.4,)):
                out[f"{v}_{per}_pb_m{int(m * 100)}"] = boot(T, a, b, m)
                print(v, per, m, out[f"{v}_{per}_pb_m{int(m * 100)}"], flush=True)
    json.dump(out, open(os.path.join(HERE, "vgoal.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
