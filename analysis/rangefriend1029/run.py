#!/usr/bin/env python3
"""The range bot with the friend's trend indicator (PLAN.md): the four arms through analysis/f7tp10_1026/hunt.run (one signal at
a time, as the live bot), KST months, the random-trend twins, the verdict.

    python3 -E -P analysis/rangefriend1029/run.py --bars BARS --work WORK --out OUT [--procs 4]

WORK: build.py's arrays. First hunt.parity (the study's own check against timing.run on the two live windows and two months)
so the rebuilt arrays are known to match the study's. Outputs in OUT: result.json, months.csv, trades_<arm>.csv.
Research code: nothing here trades.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from multiprocessing import Pool

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path[:0] = [HERE, os.path.join(REPO, "analysis", "f7tp10_1026"), REPO]
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import hunt as H  # noqa: E402

FRAME = {"1h": 3_600_000, "30m": 1_800_000}
F1 = dict(H.BASE, commit=True, btc=True, k=0.20, wait_h=1)          # FINAL_KO: the range bot as it runs
ARMS = {"R0": F1,
        "A": dict(F1, st1h=False, btc=False, friend="1h"),
        "B": dict(F1, st1h=False, btc=False, friend="1h", sources=("30m_x",)),
        "C": dict(F1, st1h=False, btc=False, friend="30m")}
ARM_KO = {"R0": "지금 (코인 · BTC 슈퍼트렌드)", "A": "친구 지표 1시간봉", "B": "30분봉 진입 + 친구 지표 1시간봉",
          "C": "친구 지표 30분봉"}
PERIODS = {"y2020": ("2020-01", "2020-12"), "pick": ("2021-01", "2023-12"), "check": ("2024-01", "2026-09"),
           "oct": ("2026-10", "2026-10")}
TWINS, SEED0 = 200, 501
W = FR = None


def log(*a):
    print(*a, flush=True)


def kst_months(m0: str, m1: str) -> list:
    return [(str(p), *H.kst_month(str(p))) for p in pd.period_range(m0, m1, freq="M")]


class Friend:
    def __init__(self, work: str):
        self.a = {}
        for tf in FRAME:
            for c in H.ST.COINS:
                z = np.load(os.path.join(work, "friend", f"{c}_{tf}.npz"))
                self.a[(c, tf)] = (z["ts"] + FRAME[tf], z["trend"])

    def at(self, coin: str, tf: str, t: int) -> int:
        """The trend on the last bar of ``tf`` closed at or before t."""
        close, tr = self.a[(coin, tf)]
        i = int(np.searchsorted(close, t, side="right")) - 1
        return int(tr[i]) if i >= 0 else 0


def unit(seed: int, t: int, coin: str) -> float:
    d = hashlib.blake2b(f"{seed}|{t}|{coin}".encode(), digest_size=8).digest()
    return int.from_bytes(d, "big") / 2 ** 64


def patch(fr: Friend) -> None:
    orig = H.checks_ok

    def checks_ok(Wx, cfg, coin, side, t):
        if not orig(Wx, cfg, coin, side, t):
            return False
        if cfg.get("friend") and fr.at(coin, cfg["friend"], t) != side:
            return False
        if cfg.get("twin") is not None:
            seed, share = cfg["twin"]
            if unit(seed, t, coin) >= share:
                return False
        return True

    H.checks_ok = checks_ok


def month_x(T: pd.DataFrame, months: list) -> np.ndarray:
    xs = []
    for _, a, b in months:
        r = T.roe.to_numpy()[(T.t >= a).to_numpy() & (T.t < b).to_numpy()] if len(T) else np.array([])
        xs.append(float(np.prod(1 + 0.40 * np.maximum(r, -1.0))) if len(r) else 1.0)
    return np.array(xs)


def read(T: pd.DataFrame, s: dict, months: list) -> dict:
    xs = month_x(T, months)
    return {"months": len(months), "x6": int((xs >= 6).sum()), "x2": int((xs >= 2).sum()), "up": int((xs > 1).sum()),
            "half": int((xs <= 0.5).sum()), "median": round(float(np.median(xs)), 3),
            "geo": round(float(math.exp(np.log(np.maximum(xs, 1e-6)).mean())), 3), "best": round(float(xs.max()), 3),
            "trades": int(s["n"]), "win": round(s["w"] / max(s["n"], 1), 3),
            "mean_roe": round(float(T.roe.mean()), 4) if len(T) else None,
            "per_month": round(s["n"] / len(months), 1), "whole_x": round(float(s["x"]), 6)}


def one(args):
    cfg, a, b = args
    T, s = H.run(W, cfg, a, b)
    return T, s


def main(argv=None) -> int:
    global W, FR
    ap = argparse.ArgumentParser()
    for k in ("bars", "work", "out"):
        ap.add_argument("--" + k, required=True)
    ap.add_argument("--procs", type=int, default=4)
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    W = H.World(a.bars, a.work)
    H.parity(W)                                          # raises SystemExit on a difference
    FR = Friend(a.work)
    patch(FR)
    res, mrows, per = {}, [], {}
    for p, (m0, m1) in PERIODS.items():
        months = kst_months(m0, m1)
        lo, hi = months[0][1], months[-1][2]
        d = {}
        for arm, cfg in ARMS.items():
            T, s = H.run(W, cfg, lo, hi)
            d[arm] = read(T, s, months)
            for (lab, _, _), x in zip(months, month_x(T, months)):
                mrows.append({"arm": arm, "period": p, "month": lab, "x": round(float(x), 4)})
            if len(T):
                T.assign(when_kst=pd.to_datetime(T.t + H.KST, unit="ms")).to_csv(
                    os.path.join(a.out, f"trades_{arm}_{p}.csv"), index=False)
            log(p, arm, json.dumps(d[arm], ensure_ascii=False))
        if p in ("pick", "check"):
            ev = [e for e in H.arming_events(W, dict(F1), lo, hi) if lo <= e[0] < hi and e[6] == "signal"]
            share = float(np.mean([FR.at(e[2], "1h", e[0]) == e[3] for e in ev])) if ev else 0.0
            twin_cfg = [(dict(F1, st1h=False, btc=False, twin=(SEED0 + i, share)), lo, hi) for i in range(TWINS)]
            with Pool(a.procs) as pool:
                outs = pool.map(one, twin_cfg, chunksize=4)
            tw_roe = np.array([float(T.roe.mean()) if len(T) else np.nan for T, _ in outs])
            tw_half = np.array([int((month_x(T, months) <= 0.5).sum()) for T, _ in outs])
            d["twins"] = {"pass_share": round(share, 3), "signals": len(ev),
                          "mean_roe_p5_p50_p95": [round(float(np.nanpercentile(tw_roe, q)), 4) for q in (5, 50, 95)],
                          "half_p5_p50_p95": [float(np.percentile(tw_half, q)) for q in (5, 50, 95)],
                          "A_roe_beats_share": round(float(np.nanmean(d["A"]["mean_roe"] > tw_roe)), 3)}
            log(p, "twins", d["twins"])
            per[p] = d
        res[p] = d
    tests = {p: {"roe_above_R0": per[p]["A"]["mean_roe"] > per[p]["R0"]["mean_roe"],
                 "median_above_R0": per[p]["A"]["median"] > per[p]["R0"]["median"],
                 "roe_beats_95pct_twins": per[p]["twins"]["A_roe_beats_share"] >= 0.95,
                 "half_not_more": per[p]["A"]["half"] <= per[p]["R0"]["half"]} for p in per}
    better = all(t["roe_above_R0"] and t["median_above_R0"] and t["roe_beats_95pct_twins"] for t in tests.values())
    res["verdict"] = {"tests": tests, "better": better,
                      "recommend": better and all(t["half_not_more"] for t in tests.values())}
    log("verdict", json.dumps(res["verdict"], ensure_ascii=False))
    pd.DataFrame(mrows).to_csv(os.path.join(a.out, "months.csv"), index=False)
    json.dump(res, open(os.path.join(a.out, "result.json"), "w"), ensure_ascii=False, indent=1, default=float)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
