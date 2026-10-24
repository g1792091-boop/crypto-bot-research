"""Summaries of the independent rows (vrebuild.py) per period and alignment variant, the one-position account and the
comparison with the study's published numbers. Writes vsummary.json.

    python3 vsummary.py
"""
import os
import sys
import json

sys.path.insert(0, "/home/user/crypto-bot-research/analysis/review1024/roles/data")
from common import ms, T0, MIN, DAY, COINS, PAYBACK, GRID_END, ext_end  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
P = {"CONF": (ms("2024-01-01"), GRID_END), "FIVE": (ms("2020-03-01"), GRID_END),
     "SEL": (ms("2021-01-01"), ms("2024-01-01")),
     "FWD": (ms("2026-10-05 15:00"), ms("2026-10-24 15:00"))}
LEV = 30.0


def one_pos(R):
    R = R.sort_values(["e", "coin_i"]).reset_index(drop=True)
    took = np.zeros(len(R), bool)
    busy = -1
    for q, (e, k) in enumerate(zip(R.e.to_numpy(), R.kk.to_numpy())):
        if e > busy:
            took[q] = True
            busy = e + k
    return R[took]


def acct(roe, m):
    roe = np.maximum(roe, -1.0)
    eq = np.cumprod(1 + m * roe)
    peak = np.maximum.accumulate(np.r_[1.0, eq])[1:]
    return float(eq[-1]), float((1 - eq / peak).max())


def main():
    out = {}
    for v in ("ok", "la", "late"):
        R = pd.read_csv(os.path.join(HERE, f"rows_{v}.csv.gz"))
        R["coin_i"] = R.coin.map({c: i for i, c in enumerate(COINS)})
        for per, (a, b) in P.items():
            q = R[(R.t >= a) & (R.t < b)]
            dropped = int(((q.why == 3) | (q.why_opp == 3)).sum())
            q = q[(q.why != 3) & (q.why_opp != 3)]
            d = {"n": len(q), "dropped_open": dropped, "mean_roe": float(q.roe.mean()),
                 "mean_opp": float(q.roe_opp.mean()), "win": float((q.roe > 0).mean()),
                 "short_share": float((q.side < 0).mean()),
                 "mean_long": float(q.roe[q.side > 0].mean()), "mean_short": float(q.roe[q.side < 0].mean()),
                 "n_long": int((q.side > 0).sum()), "n_short": int((q.side < 0).sum())}
            if per == "FWD" or (per == "CONF" and v == "ok"):
                T = one_pos(q).sort_values("t")
                for pb in (False, True):
                    roe = T.roe.to_numpy() + (LEV * PAYBACK if pb else 0)
                    ro = T.roe_opp.to_numpy() + (LEV * PAYBACK if pb else 0)
                    fx, dd = acct(roe, 0.4)
                    fo, _ = acct(ro, 0.4)
                    d[f"acct40_pb{int(pb)}"] = {"n": len(T), "mean_roe": float(roe.mean()), "final_x": fx, "max_dd": dd,
                                                "twin_final_x": fo}
            out[f"{v}_{per}"] = d
    json.dump(out, open(os.path.join(HERE, "vsummary.json"), "w"), indent=1)
    pd.set_option("display.width", 250)
    print(pd.DataFrame({k: {kk: vv for kk, vv in d.items() if not isinstance(vv, dict)} for k, d in out.items()}).T.round(4))
    for k, d in out.items():
        for kk, vv in d.items():
            if isinstance(vv, dict):
                print(k, kk, {a: round(b, 4) if isinstance(b, float) else b for a, b in vv.items()})


if __name__ == "__main__":
    main()
