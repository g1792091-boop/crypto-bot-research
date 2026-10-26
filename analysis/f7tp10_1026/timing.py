"""Owners 10/26: "진입타점이 결국 문제가 아닐까? 너무 빨리 진입하거나 너무 늦게 진입해서 그런거 아니야?" On the two live windows only,
the chosen structure (custom 80 / 9.0, BTC 40x / others 30x, margin 40 %, TP net +10 %, stop net ROE -50 %, no weekend, NYSE open
and macro +-30 min; with and without the V3.9 1h supertrend side check):
  (a) the path of each trade: for winners how far it went against before the take-profit (MAE), for losers how far it went
      for before the stop (MFE) and how soon it turned;
  (b) entry timing variants:
      now       the next 5-minute open after the 1h signal bar's close (what the bot does)
      pull k/N  wait up to N hours for a pullback of k x ATR(1h) from the signal's close; when a 5-minute bar touches it, enter at
                the NEXT 5-minute open at market (no limit order: owners' rule), else skip (the account waits for it)
      confirm   wait for the next 1h bar: enter at its close only if it closed further in the trade's direction
      break     wait up to N hours for price to pass the signal bar's own high (long) / low (short), enter at the next open
Run: python3 timing.py --bars FIVE5M_DIR --work WORK_DIR"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import pick as PK  # noqa: E402
import sim as S  # noqa: E402
import structure as SR  # noqa: E402
import study as ST  # noqa: E402

FIVE, HOUR = 300_000, 3_600_000


def entry_index(W, r, mode) -> int | None:
    """The 5-minute bar index of the entry (its open is the fill), or None to skip."""
    m = W.m5[r.coin]
    side = int(r.side)
    e5 = int(r.e5)
    if mode[0] == "now":
        return e5
    if mode[0] == "pull":
        k, n = mode[1], int(mode[2] * 12)
        level = r.ref - side * k * r.atr
        lo, hi = (m["l"], m["h"])
        seg = (lo[e5:e5 + n] <= level) if side > 0 else (hi[e5:e5 + n] >= level)
        j = np.flatnonzero(seg)
        return (e5 + int(j[0]) + 1) if len(j) else None
    if mode[0] == "confirm":
        p = W.p[r.coin]
        i = int(r.i1)
        if i + 1 >= len(p["h1_c"]) or side * (p["h1_c"][i + 1] - p["h1_c"][i]) <= 0:
            return None
        return int(np.searchsorted(m["ts"], int(p["h1_ts"][i + 1]) + HOUR))
    if mode[0] == "break":
        p = W.p[r.coin]
        i = int(r.i1)
        n = int(mode[1] * 12)
        level = p["h1_h"][i] if side > 0 else p["h1_l"][i]
        seg = (m["h"][e5:e5 + n] > level) if side > 0 else (m["l"][e5:e5 + n] < level)
        j = np.flatnonzero(seg)
        return (e5 + int(j[0]) + 1) if len(j) else None
    raise ValueError(mode)


def run(W, cand, trend, mode, a, b, keep_paths=False, exit_kind="tp10", tp_roe=0.10, lad=None, weekend_off=True):
    c = cand[(cand.t >= a) & (cand.t < b) & ~cand.us_open & ~cand.macro]
    if weekend_off:
        c = c[~c.weekend]
    if trend:
        c = c[c[trend] == c.side]
    eq, busy = 1.0, -1
    out = []
    for t, g in c.groupby("t", sort=True):
        if t < busy:
            continue
        for r in g.itertuples():
            lev = 40.0 if r.coin == "BTCUSDT" else 30.0
            m = W.m5[r.coin]
            j = entry_index(W, r, mode)
            wait_end = int(r.t) + int((mode[2] if mode[0] == "pull" else mode[1] if mode[0] == "break" else 1) * HOUR) \
                if mode[0] != "now" else int(r.t)
            if j is None or j >= len(m["o"]):
                busy = max(busy, wait_end)                 # the account waited for this signal
                break
            fill = m["o"][j] * (1 + r.side * S.SLIP)
            if (0.50 / lev - S.RT) * fill + r.atr > (1.0 / lev - 0.005) * fill:
                continue                                   # the liquidation check (as pick.py)
            res = S.run_position(m, j, int(r.side), lev, float(r.ref), exit_kind, 0.0, None, tp_roe=tp_roe, lad=lad,
                                 stop_roe=0.50)
            busy = int(m["ts"][res["exit_i"]]) + FIVE
            if res["reason"] == "END":
                break
            eq *= 1 + 0.40 * max(res["roe"], -1.0)
            row = dict(t=int(r.t), coin=r.coin, side=int(r.side), roe=res["roe"], reason=res["reason"],
                       wait_h=(int(m["ts"][j]) - int(r.t)) / HOUR, hold_h=(int(m["ts"][res["exit_i"]]) - int(m["ts"][j])) / HOUR)
            if keep_paths:                                # worst / best net ROE before the exit
                adv = (m["l"] if r.side > 0 else m["h"])[j:res["exit_i"] + 1]
                fav = (m["h"] if r.side > 0 else m["l"])[j:res["exit_i"] + 1]
                ra = lev * (r.side * (adv / res["fill"] - 1) - S.RT)
                rf = lev * (r.side * (fav / res["fill"] - 1) - S.RT)
                row["mae"] = float(ra.min())
                row["mfe"] = float(rf.max())
                first_against = np.flatnonzero(ra <= -0.25)
                row["h_to_minus25"] = (first_against[0] * 5 / 60) if len(first_against) else None
            out.append(row)
            break
    T = pd.DataFrame(out)
    w = int((T.roe > 0).sum()) if len(T) else 0
    return T, {"n": int(len(T)), "w": w, "l": int(len(T) - w), "x": float(eq)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", required=True)
    ap.add_argument("--work", required=True)
    a = ap.parse_args(argv)
    W = ST.World(a.bars, a.work)
    cand = SR.add_trend(W, pd.read_pickle(os.path.join(a.work, "cand.pkl")), a.work)
    res = {"paths": {}, "modes": []}
    modes = [("now",), ("confirm",)] + [("break", n) for n in (1, 2, 4)] + \
            [("pull", k, n) for k in (0.1, 0.25, 0.5, 0.75, 1.0) for n in (2, 4, 8)]
    for tn, tc in (("추세 없음", None), ("슈퍼트렌드 1시간", "st1h")):
        for wn, (wa, wb) in PK.LIVE.items():
            T, s = run(W, cand, tc, ("now",), wa, wb, keep_paths=True)
            win, los = T[T.roe > 0], T[T.roe <= 0]
            res["paths"][f"{tn}|{wn}"] = {
                "winners": int(len(win)), "winner_mae_median": float(win.mae.median()),
                "winner_mae_share_below_-10": float((win.mae <= -0.10).mean()),
                "winner_mae_share_below_-25": float((win.mae <= -0.25).mean()),
                "winner_hold_h_median": float(win.hold_h.median()),
                "losers": [{"t": int(x.t), "coin": x.coin, "side": x.side, "mfe": round(x.mfe, 3), "hold_h": round(x.hold_h, 1),
                            "h_to_-25": x.h_to_minus25} for x in los.itertuples()]}
            print("paths", tn, wn, json.dumps(res["paths"][f"{tn}|{wn}"], ensure_ascii=False), flush=True)
        for mo in modes:
            r = {"trend": tn, "mode": list(mo)}
            for wn, (wa, wb) in PK.LIVE.items():
                r[wn] = run(W, cand, tc, mo, wa, wb)[1]
            r["score"] = min(r["rulebot"]["x"], r["league"]["x"])
            res["modes"].append(r)
            print(json.dumps(r, ensure_ascii=False), flush=True)
    # the leading entries with the other exits and the weekend (owners: "최선을 다해줘")
    exits = {"고정 +10%": ("tp10", 0.10, None), "고정 +15%": ("tp10", 0.15, None), "고정 +20%": ("tp10", 0.20, None),
             "계단 12→10": ("lad", 0.10, (0.12, 0.10, 0.05, 0.02)), "계단 22→20": ("lad", 0.10, (0.22, 0.20, 0.05, 0.02))}
    res["combos"] = []
    for tn, tc in (("추세 없음", None), ("슈퍼트렌드 1시간", "st1h")):
        for mo in (("now",), ("pull", 0.1, 2), ("pull", 0.25, 2), ("pull", 0.25, 4), ("pull", 0.5, 2)):
            for en, (ek, tp, lad) in exits.items():
                for wk in (True, False):
                    r = {"trend": tn, "mode": list(mo), "exit": en, "weekend_off": wk}
                    for wn, (wa, wb) in PK.LIVE.items():
                        r[wn] = run(W, cand, tc, mo, wa, wb, exit_kind=ek, tp_roe=tp, lad=lad, weekend_off=wk)[1]
                    r["score"] = min(r["rulebot"]["x"], r["league"]["x"])
                    res["combos"].append(r)
                    print(json.dumps(r, ensure_ascii=False), flush=True)
    json.dump(res, open(os.path.join(a.work, "timing.json"), "w"), indent=1, ensure_ascii=False, default=float)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
