#!/usr/bin/env python3
"""The friend bot with a signal light (PLAN.md): friend_trades.py's paper (the bot's own rules, month windows joined in
time order), the light on its closed trades, the live account following the lit entries (same rules, so a followed
trade's wallet return is the paper's), month accounts, one account per period, random-skip twins, the verdict.

    python3 -E -P analysis/gate1028/run_friend.py --trades OUT/friend_trades.json --out OUT2

Net ROE of a trade = its wallet return / 0.4 (margin 40 % of the wallet). Outputs in OUT2: result.json, months.csv.
Research code: nothing here trades.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import gate as GT  # noqa: E402

MARGIN = 0.40
PERIODS = {"choose": ("2021-10-01", "2024-10-01"), "check": ("2024-10-01", "2026-10-01")}


def months(a: str, b: str) -> list:
    d = pd.date_range(pd.Timestamp(a, tz="UTC"), pd.Timestamp(b, tz="UTC"), freq="MS")
    return [(int(x.value // 10**6), int(y.value // 10**6)) for x, y in zip(d[:-1], d[1:])]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trades", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    rows = [t for m in json.load(open(a.trades)) for t in m["trades"]]
    P = pd.DataFrame(rows).sort_values("t", kind="stable").reset_index(drop=True)
    fill, exit_ = P["t"].to_numpy(np.int64), P["exit_t"].to_numpy(np.int64)
    ret = P["ret"].to_numpy(float)
    roe = ret / MARGIN
    ok = np.ones(len(P), bool)
    L = {g: GT.lights(exit_, roe, fill, rule) for g, rule in GT.RULES.items()}
    res, mrows, per = {"paper_trades": int(len(P))}, [], {}
    for p, (pa, pb) in PERIODS.items():
        ml = months(pa, pb)
        lo, hi = ml[0][0], ml[-1][1]
        inp = (fill >= lo) & (fill < hi)
        d = {}
        for g in GT.RULES:
            # the paper holds one position, so a followed entry never meets an open live position: exit = fill
            xs = GT.fast_months(ml, fill, fill, ret, ok, L[g])
            k = L[g] & inp
            w = GT.START
            for r in ret[k]:
                w *= 1.0 + r
                if w < GT.BUST:
                    break
            d[g] = {**GT.month_read(xs), "paper_entries": int(inp.sum()), "followed": int(k.sum()),
                    "share": round(float(k.sum() / max(1, inp.sum())), 3), "trades": int(k.sum()),
                    "mean_roe": round(float(roe[k].mean()), 4) if k.any() else None,
                    "win": round(float((ret[k] > 0).mean()), 3) if k.any() else None,
                    "whole_x": round(w / GT.START, 6), "whole_bust": bool(w < GT.BUST)}
            for (ma, _), x in zip(ml, xs):
                mrows.append({"arm": g, "period": p, "month": pd.Timestamp(ma, unit="ms").strftime("%Y-%m"), "x": round(x, 4)})
            print(p, g, json.dumps(d[g], ensure_ascii=False), flush=True)
        for g in ("G1", "G2", "G3"):                  # G1 judged (PLAN 5); G2 · G3 shown only
            tw = GT.twins(ml, fill, fill, ret, ok, inp, d[g]["followed"])
            d[g]["twins_half"] = {"p5": float(np.percentile(tw, 5)), "p50": float(np.median(tw)),
                                  "p95": float(np.percentile(tw, 95))}
            d[g]["twins_more_share"] = float((tw > d[g]["half"]).mean())
            print(p, g, "twins", d[g]["twins_half"], "share with more half months", d[g]["twins_more_share"], flush=True)
        d["twins_more_share"] = d["G1"]["twins_more_share"]
        per[p] = d
        res[p] = d
    res["verdict"] = GT.verdict(per)
    print("verdict", json.dumps(res["verdict"], ensure_ascii=False), flush=True)
    pd.DataFrame(mrows).to_csv(os.path.join(a.out, "months.csv"), index=False)
    json.dump(res, open(os.path.join(a.out, "result.json"), "w"), ensure_ascii=False, indent=1, default=float)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
