#!/usr/bin/env python3
"""레인지 봇에 코인 더하기 (PREREG.md): F1 with the six coins vs the six + new coins, 2021-01 .. 2026-10 on the public 5m bars.

    python3 run.py fetch BARS [--first 2020-01] [--last-day 2026-10-24] [--procs 8]   the new coins' 5m bars -> BARS/5m
    python3 run.py build BARS WORK                                                    their hunt / prep arrays -> WORK
    python3 run.py run BARS WORK OUT                                                  the arms -> OUT/rangecoins.json
BARS/5m and WORK (hunt/, prep/, hunt/blocks.npz) hold every coin: the six from research/range4h's folders, the new ones built
here with the study's own code (hunt_prep.job, trendcols.py)."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "opentime"))
import otcommon as CM  # noqa: E402  (puts the repository on sys.path)
import rangebot as RB  # noqa: E402

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

H, PK, S, P, HP = RB.H, RB.PK, RB.S, RB.P, RB.HP
ST = H.ST

SIX = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT")
NEW = ("XRPUSDT", "BNBUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT")
assert tuple(ST.COINS) == SIX == tuple(P.COINS)


# ------------------------------------------------------------------------------------------------ data
def fetch(cache: str, first: str, last_day: str, procs: int) -> None:
    """analysis/v39_1h/fetch_bars.py ``five`` for the new coins, with the volume column hunt_prep reads."""
    sys.path.insert(0, os.path.join(CM.REPO, "analysis", "v39_1h"))
    import fetch_bars as FB
    os.makedirs(os.path.join(cache, "5m"), exist_ok=True)
    last_month = last_day[:7]
    full = [m for m in FB.months(first, last_month) if m < last_month]
    for sym in NEW:
        path = os.path.join(cache, "5m", f"{sym}.npz")
        if os.path.exists(path):
            print(f"{sym}: kept {path}")
            continue
        t0 = time.time()
        rels = [f"monthly/klines/{sym}/5m/{sym}-5m-{m}.zip" for m in full]
        rels += [f"daily/klines/{sym}/5m/{sym}-5m-{d}.zip" for d in FB.days(last_month + "-01", last_day)]
        parts, miss = FB._many(rels, procs, FB.read_klines)
        k = pd.concat(parts, ignore_index=True).drop_duplicates("t", keep="last").sort_values("t")
        k = k[k["volume"] > 0]
        fr, fmiss = FB._many([f"monthly/fundingRate/{sym}/{sym}-fundingRate-{m}.zip" for m in full], procs, FB.read_funding)
        f = pd.concat(fr, ignore_index=True).drop_duplicates("calc_time").sort_values("calc_time")
        ts = k["t"].to_numpy(np.int64)
        fund = np.zeros(len(ts))
        ft = f["calc_time"].to_numpy(np.int64) // 60_000 * 60_000
        j = np.searchsorted(ts, ft, side="left")
        ok = j < len(ts)
        np.add.at(fund, j[ok], f["rate"].to_numpy(float)[ok])
        np.savez(path, ts=ts, o=k["open"].to_numpy(float), h=k["high"].to_numpy(float), l=k["low"].to_numpy(float),
                 c=k["close"].to_numpy(float), v=k["volume"].to_numpy(float), fund=fund)
        print(f"{sym}: {len(ts):,} 5m bars {pd.Timestamp(ts[0], unit='ms')} .. {pd.Timestamp(ts[-1], unit='ms')}, "
              f"funding {int(ok.sum())}, missing files {len(miss) + len(fmiss)} {sorted(miss + fmiss)[:3]} "
              f"({time.time() - t0:.0f}s)", flush=True)


def build(bars: str, work: str) -> None:
    """rangebot.build for the new coins only (the six and the blocks are already in WORK)."""
    import trendcols
    os.makedirs(os.path.join(work, "hunt"), exist_ok=True)
    os.makedirs(os.path.join(work, "prep"), exist_ok=True)
    for c in NEW:
        print("hunt_prep", HP.job((c, bars, work)), flush=True)
        z = np.load(os.path.join(bars, "5m", f"{c}.npz"))
        h1 = P.bars(z["ts"], z["o"], z["h"], z["l"], z["c"], z["v"], P.HOUR)
        np.savez(os.path.join(work, "prep", f"{c}.npz"), **{f"h1_{k}": a for k, a in h1.items()})
    trendcols.COINS = NEW
    trendcols.main(["--work", work])


# ------------------------------------------------------------------------------------------------ the arms
def trades(W: H.World, coins: tuple, a: int, b: int) -> pd.DataFrame:
    """hunt.run with F1 over ``coins`` (their order is the tie-break)."""
    ST.COINS = coins
    try:
        T, _s = H.run(W, RB.F1, a, b)
    finally:
        ST.COINS = SIX + NEW
    if not len(T):
        return pd.DataFrame(columns=["t", "coin", "side", "roe", "reason", "ret"])
    T = T.copy()
    T["ret"] = 0.40 * np.maximum(T["roe"].to_numpy(float), -1.0)
    return T


def window(T: pd.DataFrame) -> dict:
    r = T["ret"].to_numpy(float)
    return {"n": int(len(r)), "w": int((r > 0).sum()), "l": int((r <= 0).sum()), "x": float(np.prod(1 + r))}


def weekdays(period: str) -> int:
    a, b = CM.PERIODS[period]
    d = pd.date_range(f"{a}-01", pd.Period(b, "M").end_time.normalize(), freq="D")
    if period == "recent":
        d = d[d <= pd.Timestamp("2026-10-24")]
    return int((d.dayofweek < 5).sum())


def describe(T: pd.DataFrame, base: pd.DataFrame | None) -> dict:
    """Per period: entries per weekday, trades / mean return by coin, six-coin trades lost or gained against C0."""
    out = {}
    mo = CM.kst_month(T["t"].to_numpy(np.int64)) if len(T) else np.array([], object)
    bmo = CM.kst_month(base["t"].to_numpy(np.int64)) if base is not None and len(base) else np.array([], object)
    for p in CM.PERIODS:
        ms_ = CM.months_of(p)
        X = T[np.isin(mo, ms_)]
        d = {"per_weekday": len(X) / max(weekdays(p), 1),
             "by_coin": {c: {"n": int(len(g)), "win_pct": 100 * float((g["ret"] > 0).mean()),
                             "mean_ret_pct": 100 * float(g["ret"].mean())} for c, g in X.groupby("coin")}}
        if base is not None:
            B = base[np.isin(bmo, ms_)]
            a6 = set(zip(X.loc[X["coin"].isin(SIX), "t"], X.loc[X["coin"].isin(SIX), "coin"]))
            b6 = set(zip(B["t"], B["coin"]))
            lost = B[[(t, c) in (b6 - a6) for t, c in zip(B["t"], B["coin"])]]
            d["six_lost"] = {"n": int(len(lost)), "wins": int((lost["ret"] > 0).sum()), "sum_ret_pct": 100 * float(lost["ret"].sum())}
            d["six_gained"] = int(len(a6 - b6))
        out[p] = d
    return out


def liq_fail_share(W: H.World) -> dict:
    """Share of 1h bars (2021-01 .. 2026-09) where hunt.run's liquidation room check would refuse an entry at the close."""
    out = {}
    for c in SIX + NEW:
        h = W.h[c]
        lev = 40.0 if c == "BTCUSDT" else 30.0
        sel = (h["1h_ts"] >= CM.RUN_START) & (h["1h_ts"] < CM.kst_ms("2026-10-01 00:00"))
        atr, px = h["1h_atr"][sel], h["1h_c"][sel]
        dist = 0.50 / lev - S.RT
        fail = (dist + atr / px) > (1.0 / lev - 0.005)
        out[c] = float(np.nanmean(fail))
    return out


def arm(W: H.World, name: str, coins: tuple, end: int, out: str, base: pd.DataFrame | None, t0: float) -> tuple:
    T = trades(W, coins, CM.RUN_START, end)
    T.to_csv(os.path.join(out, f"rangecoins_trades_{name}.csv.gz"), index=False)
    per = {p: CM.period_metrics(T, p) for p in CM.PERIODS}
    live = {k: window(trades(W, coins, a, b)) for k, (a, b) in PK.LIVE.items()}
    live["oct"] = window(trades(W, coins, *H.OCT))
    r = {"coins": list(coins), "periods": per, "live": live, "describe": describe(T, base)}
    print(name, len(coins), {p: (d["trades"], round(d["median_month"], 4), d["months_up"]) for p, d in per.items()},
          {k: (v["w"], v["l"], round(v["x"], 3)) for k, v in live.items()},
          {p: round(d["per_weekday"], 2) for p, d in r["describe"].items()}, f"{time.time() - t0:.0f}s", flush=True)
    return r, T


def run(bars: str, work: str, out: str) -> int:
    os.makedirs(out, exist_ok=True)
    t0 = time.time()
    ST.COINS = SIX + NEW
    W = H.World(bars, work)
    S.run_position = RB.ORIG_RUN_POSITION
    H.S.run_position = RB.ORIG_RUN_POSITION
    end = int(W.m5["BTCUSDT"]["ts"][-1]) + CM.FIVE
    res = {}
    res["C0"], T0 = arm(W, "C0", SIX, end, out, None, t0)
    res["C5"], _ = arm(W, "C5", SIX + NEW, end, out, T0, t0)
    for c in NEW:
        res[f"C1_{c}"], _ = arm(W, f"C1_{c}", SIX + (c,), end, out, T0, t0)
    chosen = tuple(c for c in NEW if CM.beats(res[f"C1_{c}"]["periods"]["choose"], res["C0"]["periods"]["choose"]))
    if chosen:
        res["CS"], _ = arm(W, "CS", SIX + chosen, end, out, T0, t0)
    v = {"C5": {"beats_C0_choose": CM.beats(res["C5"]["periods"]["choose"], res["C0"]["periods"]["choose"]),
                "beats_C0_check": CM.beats(res["C5"]["periods"]["check"], res["C0"]["periods"]["check"])}}
    v["C5"]["helps"] = bool(v["C5"]["beats_C0_choose"] and v["C5"]["beats_C0_check"])
    v["CS"] = {"chosen": list(chosen)}
    if chosen:
        v["CS"]["helps"] = CM.beats(res["CS"]["periods"]["check"], res["C0"]["periods"]["check"])
    v["recommend"] = list(NEW) if v["C5"]["helps"] else (list(chosen) if chosen and v["CS"]["helps"] else [])
    o = {"arms": res, "verdicts": v, "liq_fail_share": liq_fail_share(W),
         "weekdays": {p: weekdays(p) for p in CM.PERIODS}}
    json.dump(CM.jsonable(o), open(os.path.join(out, "rangecoins.json"), "w"), indent=1, ensure_ascii=False)
    print(json.dumps(CM.jsonable({"verdicts": v, "liq_fail_share": o["liq_fail_share"]}), indent=1), flush=True)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("bars")
    f.add_argument("--first", default="2020-01")
    f.add_argument("--last-day", default="2026-10-24")
    f.add_argument("--procs", type=int, default=8)
    b = sub.add_parser("build")
    b.add_argument("bars")
    b.add_argument("work")
    r = sub.add_parser("run")
    r.add_argument("bars")
    r.add_argument("work")
    r.add_argument("out")
    a = ap.parse_args(argv)
    if a.cmd == "fetch":
        fetch(a.bars, a.first, a.last_day, a.procs)
        return 0
    if a.cmd == "build":
        build(a.bars, a.work)
        return 0
    return run(a.bars, a.work, a.out)


if __name__ == "__main__":
    raise SystemExit(main())
