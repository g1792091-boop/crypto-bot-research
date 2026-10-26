#!/usr/bin/env python3
"""레인지 봇 -> WOO X Pro, 2021-01 .. 2026-10 on the public 5m bars, with the arms of PREREG.md.

The machinery is analysis/f7tp10_1026/hunt.py ``run`` with F1 (FINAL_KO.md's structure): every entry rule, block and the
one-position walk are the study's own. Only the position function hunt calls (sim.run_position) is replaced by
``run_position_arm`` below: a copy of it with the arm hooks at the end of a 5m bar and the diagnostics of PREREG.md
(with no arm it equals sim.run_position: checked on every trade). The entry blocks are recomputed over the whole range
with hunt_prep.blocks' own functions (its blocks.npz started 2024-12).

    python3 -I rangebot.py FIVE5M_PARENT WORK OUT_DIR [--build] [--parity]
FIVE5M_PARENT: the folder holding 5m/<SYM>.npz. WORK: the work folder (hunt/<COIN>.npz, prep/<COIN>_trend.npz,
hunt/blocks.npz); --build makes it from the 5m files with the study's own scripts (hunt_prep.job, trendcols.py)."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import otcommon as CM  # noqa: E402  (puts the repository on sys.path)

F7 = os.path.join(CM.REPO, "analysis", "f7tp10_1026")
sys.path.insert(0, F7)
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import hunt as H  # noqa: E402
import hunt_prep as HP  # noqa: E402
import pick as PK  # noqa: E402
import prep as P  # noqa: E402
import sim as S  # noqa: E402

F1 = dict(H.BASE, commit=True, btc=True, k=0.20, wait_h=1)      # livepar.F1 = FINAL_KO.md's structure
ORIG_RUN_POSITION = S.run_position
ARM = ["A0"]
REC: dict = {}                                                  # (coin, entry index) -> diagnostics of that position
LAST_END: list = []


def run_position_arm(m: dict, i0: int, side: int, lev: float, ref: float, exit_kind: str, stop_dist: float = 0.0,
                     sup_at: int | None = None, tp_roe: float = 0.10, lad: tuple | None = None,
                     stop_roe: float | None = None, time_bars: int | None = None) -> dict:
    """sim.run_position, the same order of checks inside a bar, plus at the END of each bar (the position still open):
    the diagnostics and the arm (PREREG.md). Exit reasons added: OPENCUT (A1 / A6 close), TIME (A3-5), BE (the stop
    raised to break-even was hit)."""
    o, h, l, c, fund = m["o"], m["h"], m["l"], m["c"], m["fund"]
    ny, win = m["ny"], m["win"]
    kind, hours = CM.ARMS[ARM[0]]
    tbars = int(hours * 12)
    n = len(o)
    fill = o[i0] * (1 + side * S.SLIP)
    fee_in = S.TAKER
    f_paid = 0.0
    if exit_kind == "tp10":
        stop = ref - side * stop_dist
        tp = fill * (1 + side * (tp_roe / lev + S.RT))
    elif exit_kind in ("lad", "trendlad"):
        stop = ref - side * stop_dist
        tp = None
    else:
        stop = fill * (1 + side * (-0.50 / lev + S.RT))
        tp = None
    if stop_roe is not None and exit_kind in ("tp10", "lad", "trendlad"):
        stop = fill * (1 + side * (-stop_roe / lev + S.RT))
    lock = None
    best = -9.0
    stop0, best_px = stop, fill
    tgt = tp if tp is not None else fill * (1 + side * (0.10 / lev + S.RT))
    d = {"R_at_M": 0.0, "hours_at_M": 0.0, "mfe_share_at_M": 0.0, "first_m": -1, "roe_at_M": 0.0, "open_4h": False, "open_8h": False, "open_12h": False, "touched": False,
         "be": False, "inwin": 0}

    def roe_at(px: float, fee_out: float, slip: bool):
        xp = px * (1 - side * S.SLIP) if slip else px
        return lev * (side * (xp / fill - 1) - fee_in - fee_out * xp / fill - f_paid), xp

    def done(res: dict) -> dict:
        d["bars"] = int(res["exit_i"] - i0 + 1)
        REC[(m["coin"], int(i0))] = dict(d, reason=res["reason"], exit_i=int(res["exit_i"]))
        if res["reason"] == "END":
            LAST_END.append((m["coin"], int(i0), side, res))
        return res

    i = i0
    while i < n:
        if win[i]:
            d["inwin"] += 1
        if i > i0 and fund[i] != 0.0:
            f_paid += side * fund[i] * o[i] / fill
            if exit_kind == "trend" and lock is None:
                stop = fill * (1 + side * (-0.50 / lev + S.RT + f_paid))
        if time_bars is not None and i >= i0 + time_bars:
            r, xp = roe_at(o[i], S.TAKER, True)
            return done({"exit_i": i, "reason": "TIME", "roe": r, "mfe": best, "fill": fill, "exit_px": xp})
        if exit_kind == "trend" and sup_at is not None and i >= sup_at and lock is None and i > i0:
            r, xp = roe_at(o[i], S.TAKER, True)
            return done({"exit_i": i, "reason": "SUP", "roe": r, "mfe": best, "fill": fill, "exit_px": xp})
        why = "LOCK" if lock is not None else ("BE" if d["be"] else "SL")
        if (o[i] - stop) * side <= 0:
            r, xp = roe_at(o[i], S.TAKER, True)
            return done({"exit_i": i, "reason": why, "roe": r, "mfe": max(best, r), "fill": fill, "exit_px": xp})
        worst, top = (l[i], h[i]) if side > 0 else (h[i], l[i])
        if (worst - stop) * side <= 0:
            r, xp = roe_at(stop, S.TAKER, True)
            return done({"exit_i": i, "reason": why, "roe": r, "mfe": best, "fill": fill, "exit_px": xp})
        b = lev * (side * (top / fill - 1) - S.RT - f_paid)
        best = max(best, b)
        best_px = max(best_px, top) if side > 0 else min(best_px, top)
        if tp is not None and (top - tp) * side >= 0:
            px = max(tp, o[i]) if side > 0 else min(tp, o[i])
            r, xp = roe_at(px, S.MAKER, False)
            return done({"exit_i": i, "reason": "TP", "roe": r, "mfe": best, "fill": fill, "exit_px": xp})
        if exit_kind in ("trend", "trendlad", "lad") and i > i0:
            k = S.lad_lock(best, lad) if exit_kind == "lad" else S.ladder_lock(best)
            if k is not None and (lock is None or k > lock + 1e-12):
                cand = fill * (1 + side * (k / lev + S.RT + f_paid))
                stop = max(stop, cand) if side > 0 else min(stop, cand)
                lock = k
        # ---- the end of bar i, the position still open (PREREG.md)
        if lock is None:
            nr = lev * (side * (c[i] / fill - 1) - S.RT - f_paid)
            if ny[i] and d["first_m"] < 0:
                d["first_m"], d["roe_at_M"] = int(i), float(nr)
                d["R_at_M"] = float(side * (c[i] - fill) / abs(fill - stop0))
                d["hours_at_M"] = (i - i0 + 1) * 5.0 / 60.0
                d["mfe_share_at_M"] = float(side * (best_px - fill) / (side * (tgt - fill)))
            for hh in (4, 8, 12):
                if i == i0 + 12 * hh - 1:
                    d[f"open_{hh}h"] = True
            close_why, be = None, False
            if ny[i]:
                if kind == "open_close" or (kind == "open_mix" and nr <= 0):
                    close_why = "OPENCUT"
                elif kind in ("open_be", "open_mix") and nr > 0:
                    be = True
            if kind == "time" and i == i0 + tbars - 1:
                close_why = "TIME"
            if close_why is not None:
                d["touched"] = True
                r, xp = roe_at(c[i], S.TAKER, True)
                return done({"exit_i": i, "reason": close_why, "roe": r, "mfe": best, "fill": fill, "exit_px": xp})
            if be:
                cand = fill * (1 + side * (S.RT + f_paid))
                if (cand - stop) * side > 0:
                    stop = cand
                    d["be"] = d["touched"] = True
        i += 1
    r, xp = roe_at(c[n - 1], S.TAKER, True)
    return done({"exit_i": n - 1, "reason": "END", "roe": r, "mfe": best, "fill": fill, "exit_px": xp})


# ------------------------------------------------------------------------------------------------ the work arrays
def build(bars: str, work: str) -> None:
    """hunt_prep.job per coin (one process), the 1h bars trendcols.py reads, trendcols.py, and the blocks over the whole
    range (hunt_prep.blocks with its start moved to 2020-03-01)."""
    import trendcols
    os.makedirs(os.path.join(work, "hunt"), exist_ok=True)
    os.makedirs(os.path.join(work, "prep"), exist_ok=True)
    for c in P.COINS:
        print("hunt_prep", HP.job((c, bars, work)), flush=True)
        z = np.load(os.path.join(bars, "5m", f"{c}.npz"))
        h1 = P.bars(z["ts"], z["o"], z["h"], z["l"], z["c"], z["v"], P.HOUR)
        np.savez(os.path.join(work, "prep", f"{c}.npz"), **{f"h1_{k}": a for k, a in h1.items()})
    trendcols.main(["--work", work])
    HP.GRID_FROM = "2020-03-01"
    end = int(np.load(os.path.join(bars, "5m", "BTCUSDT.npz"))["ts"][-1]) + 300_000
    t0 = time.time()
    HP.blocks(work, end)
    print(f"blocks {time.time() - t0:.0f}s", flush=True)


def world(bars: str, work: str) -> H.World:
    W = H.World(bars, work)
    for c in P.COINS:
        ts = W.m5[c]["ts"].astype(np.int64)
        W.m5[c]["ny"] = CM.open_flags(ts)
        W.m5[c]["win"] = CM.window_flags(ts)
        W.m5[c]["coin"] = c
    return W


def parity(W: H.World) -> dict:
    """F1 with the study's own position function on the published windows, and the copy (no arm) on every trade."""
    want = {"rulebot": (38, 38, 0, 6.239411160748707), "league": (23, 23, 0, 3.0458624528946228),
            "oct": (41, 40, 1, 5.533054664599554)}
    S.run_position = ORIG_RUN_POSITION
    H.S.run_position = ORIG_RUN_POSITION
    ev = H.evaluate(W, F1)
    got = {k: (ev[k]["n"], ev[k]["w"], ev[k]["l"], ev[k]["x"]) for k in want}
    mo = ev["months"]
    out = {"windows": got, "want": want, "months_2025_2026": {k: mo[k] for k in ("up", "median", "worst", "win")},
           "months_want": {"up": 4, "median": 0.6652886979312416, "worst": 0.1894871470900655, "win": 0.7740046838407494}}
    ok = all(got[k][:3] == want[k][:3] and abs(got[k][3] - want[k][3]) < 1e-9 for k in want)
    ok &= mo["up"] == 4 and abs(mo["median"] - 0.6652886979312416) < 1e-9 and abs(mo["win"] - 0.7740046838407494) < 1e-9
    out["published_numbers_equal"] = bool(ok)
    # the copy with no arm, on every trade of a continuous run
    T, _ = H.run(W, F1, CM.RUN_START, PK.END + 30 * CM.DAY)
    bad = 0
    ARM[0] = "A0"
    for r in T.itertuples():
        m = W.m5[r.coin]
        j = int(np.searchsorted(m["ts"], r.t))
        lev = 40.0 if r.coin == "BTCUSDT" else 30.0
        fill = m["o"][j] * (1 + r.side * S.SLIP)
        a = ORIG_RUN_POSITION(m, j, r.side, lev, fill, "tp10", 0.0, None, tp_roe=0.10, stop_roe=0.50)
        b = run_position_arm(m, j, r.side, lev, fill, "tp10", 0.0, None, tp_roe=0.10, stop_roe=0.50)
        if a["exit_i"] != b["exit_i"] or a["reason"] != b["reason"] or abs(a["roe"] - b["roe"]) > 1e-12:
            bad += 1
    out["copy_vs_original"] = {"trades": int(len(T)), "different": bad}
    return out


def run_arm(W: H.World, arm: str, end: int) -> pd.DataFrame:
    ARM[0] = arm
    REC.clear()
    LAST_END.clear()
    S.run_position = run_position_arm
    H.S.run_position = run_position_arm
    T, _s = H.run(W, F1, CM.RUN_START, end)
    S.run_position = ORIG_RUN_POSITION
    H.S.run_position = ORIG_RUN_POSITION
    rows = []
    recs = [(int(r.t), r.coin, int(r.side), float(r.roe), r.reason) for r in T.itertuples()]
    for c, i0, side, res in LAST_END:                     # hunt.run drops a position open at the data end: marked here
        recs.append((int(W.m5[c]["ts"][i0]), c, side, float(res["roe"]), "END"))
    for t, c, side, roe, reason in recs:
        m = W.m5[c]
        i0 = int(np.searchsorted(m["ts"], t))
        d = REC[(c, i0)]
        ret = 0.40 * max(roe, -1.0)
        rows.append({"t": t, "symbol": c, "side": side, "roe": roe, "reason": reason, "ret": ret,
                     "exit_ts": int(m["ts"][d["exit_i"]]), "touched": bool(d["touched"]),
                     "locked": reason == "TP", "kind": "LOCKED" if reason == "TP" else ("SL" if reason == "SL" else "OTHER"),
                     "open_at_M": d["first_m"] >= 0, "roe_at_M": d["roe_at_M"],
                     "R_at_M": d["R_at_M"], "hours_at_M": d["hours_at_M"], "mfe_share_at_M": d["mfe_share_at_M"], "open_4h": d["open_4h"],
                     "open_8h": d["open_8h"], "open_12h": d["open_12h"],
                     "sl_in_window": bool(reason == "SL" and m["win"][d["exit_i"]]),
                     "held_in_window": int(d["inwin"]), "held_bars": int(d["bars"])})
    return pd.DataFrame(rows).sort_values("t").reset_index(drop=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("bars")
    ap.add_argument("work")
    ap.add_argument("out")
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--parity", action="store_true")
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    t0 = time.time()
    if a.build:
        build(a.bars, a.work)
        return 0
    W = world(a.bars, a.work)
    if a.parity:
        p = parity(W)
        print(json.dumps(p, indent=1, default=str), flush=True)
        json.dump(CM.jsonable(p), open(os.path.join(a.out, "range_parity.json"), "w"), indent=1)
        return 0 if p["published_numbers_equal"] and p["copy_vs_original"]["different"] == 0 else 1
    end = int(W.m5["BTCUSDT"]["ts"][-1]) + CM.FIVE
    res, diag = {}, None
    for arm in CM.ARMS:
        T = run_arm(W, arm, end)
        T.to_csv(os.path.join(a.out, f"range_trades_{arm}.csv.gz"), index=False)
        res[arm] = {p: CM.period_metrics(T, p) for p in CM.PERIODS}
        if arm == "A0":
            diag = CM.by_period_diag(T)
            diag_d = CM.by_period_sideways(T)
        print(arm, {p: (d["trades"], round(d["median_month"], 4)) for p, d in res[arm].items()},
              f"{time.time() - t0:.0f}s", flush=True)
    out = {"bot": "레인지 봇 -> WOO X Pro", "arms": res, "verdicts": CM.verdicts(res), "diagnostics_A0": diag, "sideways_A0": diag_d}
    json.dump(CM.jsonable(out), open(os.path.join(a.out, "range.json"), "w"), indent=1, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
