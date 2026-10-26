#!/usr/bin/env python3
"""VWAP 개선판 -> 딥코인 (DeepCoin): the arms of PREREG.md (addendum 1) through the bot's own 5-year simulator,
research/vwap30/code (vwmonth2.paper_trades: vwfix2.rows_tf for VWAP 복귀 실패 30m, vwadd.sig_job / rows_of for CMO·샌드위치
1h, vwadd.time_ok + gates, vwacct._take, leverage min(30, 0.5 / (2 ATR % + 0.14 %)), margin 40 %, the executor's signal
light 20 / 75 %). Only its exit, vwfix2.outcomes_tf "base", is replaced by ``outcomes_arms`` below: the same matrix walk
with the arm hooks (with no arm it equals outcomes_tf "base" on every signal: checked).

The simulator reads a 1m grid (fg1m) that is not on this machine: nlcommon.load_grid is pointed at the public 5m files
expanded to minutes (a 5m bar = one minute holding its open / high / low / close / volume / funding, then four flat
minutes at its close; mark = last; gaps flat), the method of analysis/f7tp10_1026/livepar.py. The trend-judge arrays the
gates read are rebuilt from that grid with the five-year study's own judge5y.job (as research/newlive/judge_all.py did).

    python3 -I vwap.py FIVE5M_DIR WORK OUT_DIR [--judge] [--parity]
--judge builds WORK/judge/<COIN>.npz first (one process). Writes OUT_DIR/vwap.json, vwap_trades_<arm>.csv.gz."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import otcommon as CM  # noqa: E402

VW = os.path.join(CM.REPO, "research", "vwap30", "code")
for _p in (os.path.join(CM.REPO, "research", "trendbot", "fiveyear", "code"), os.path.join(CM.REPO, "research", "newlive",
                                                                                           "code"), VW):
    sys.path.insert(0, _p)
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import nlcommon as NL  # noqa: E402
import fycommon as FY  # noqa: E402

END = CM.kst_ms("2026-10-25 09:00")            # 2026-10-25 00:00 UTC: the 5m files end at 10-24 23:55 UTC
FIVE_DIR = [None]


def grid5(coin: str, end=None, oct_mark="mark") -> dict:
    """nlcommon.load_grid's output form from the 5m files (see the module docstring)."""
    z = np.load(os.path.join(FIVE_DIR[0], f"{coin}.npz"))
    T0 = FY.T0
    n = (END - T0) // CM.MIN
    k = (z["ts"].astype(np.int64) - T0) // CM.MIN
    ok = (k >= 0) & (k + 4 < n)
    k = k[ok]
    out = {x: np.full(n, np.nan) for x in ("o", "h", "l", "c", "v", "fund")}
    for x in ("o", "h", "l", "c", "v", "fund"):
        out[x][k] = z[x][ok]
    for q in range(1, 5):
        for x in ("o", "h", "l", "c"):
            out[x][k + q] = z["c"][ok]
        out["v"][k + q] = 0.0
        out["fund"][k + q] = 0.0
    have = ~np.isnan(out["c"])
    first = int(np.argmax(have))
    filled = np.zeros(n, bool)
    miss = np.flatnonzero(~have[first:]) + first
    if len(miss):
        last_idx = np.maximum.accumulate(np.where(have, np.arange(n), -1))
        src = last_idx[miss]
        for x in ("o", "h", "l", "c"):
            out[x][miss] = out["c"][src]
        out["v"][miss] = 0.0
        out["fund"][miss] = 0.0
        filled[miss] = True
    out["fund"] = np.nan_to_num(out["fund"])
    for x, y in (("mo", "o"), ("mh", "h"), ("ml", "l"), ("mc", "c")):
        out[x] = out[y]
    out.update(filled=filled, first=first, n=n, end=END)
    return out


def patch(five: str, work: str) -> None:
    """Point the simulator's data layer at grid5 and the rebuilt judge arrays (every module that copied the names)."""
    FIVE_DIR[0] = five
    NL.load_grid = grid5
    NL.DATA_END = END
    NL.JUDGE = os.path.join(work, "judge")
    for name, mod in list(sys.modules.items()):
        if name.startswith("vw") or name in ("nlcommon", "judge5y"):
            if hasattr(mod, "DATA_END"):
                mod.DATA_END = END
            if hasattr(mod, "JUDGE_DIR"):
                mod.JUDGE_DIR = os.path.join(work, "judge")
            if hasattr(mod, "load_grid") and name == "judge5y":
                mod.load_grid = lambda coin, with_oct=True: grid5(coin)


def build_judge(five: str, work: str) -> dict:
    sys.argv = [sys.argv[0], "--sample", "20"]
    import judge5y
    os.makedirs(os.path.join(work, "judge"), exist_ok=True)
    judge5y.OUT = work
    judge5y.S1 = END
    judge5y.SAMPLE = 20
    patch(five, work)
    res = {}
    for c in NL.COINS:
        t0 = time.time()
        coin, chk = judge5y.job(c)
        res[coin] = chk
        print("judge", coin, f"{time.time() - t0:.0f}s", json.dumps(chk)[:300], flush=True)
    json.dump(res, open(os.path.join(work, "judge", "judge_agreement.json"), "w"), indent=1)
    return res


# --------------------------------------------------------------------------------------------- the exit with arms
CLOCK: dict = {}


def clock(n: int):
    """(the 09:29 New York minutes as a bool per grid minute, the 09:30-11:00 minutes, their running count)."""
    if n not in CLOCK:
        T0 = FY.T0
        mo = CM.open_moments(T0, T0 + n * CM.MIN)
        ny = np.zeros(n, bool)
        k = (mo + 4 * CM.MIN - T0) // CM.MIN
        ny[k[k < n]] = True
        win = np.zeros(n, bool)
        for d in range(5, 95):
            kk = (mo + d * CM.MIN - T0) // CM.MIN
            win[kk[kk < n]] = True
        CLOCK[n] = (ny, win, np.r_[0, np.cumsum(win.astype(np.int64))])
    return CLOCK[n]


def _first(cond):
    any_ = cond.any(axis=1)
    return np.where(any_, cond.argmax(axis=1), cond.shape[1]), any_


def outcomes_arms(coin: str, R: pd.DataFrame, k: int) -> dict:
    """vwfix2.outcomes_tf's "base" walk (2 ATR stop, lock_house ladder at 30x, 96-bar cap) for every arm at once.
    Returns arm -> DataFrame (r, x, reason, touched) and "diag" (A0's diagnostics per row)."""
    import vwfix2 as V2
    Wt = 96 * k
    g = V2.grid(coin)
    cumf = np.cumsum(g["fund"])
    ny_all, win_all, wcum = clock(g["n"])
    n = len(R)
    res = {a: {"r": np.zeros(n), "x": np.zeros(n, np.int64), "reason": np.empty(n, object),
               "touched": np.zeros(n, bool)} for a in CM.ARMS}
    dg = {x: np.zeros(n) for x in ("roe_at_M", "R_at_M", "hours_at_M", "mfe_share_at_M")}
    for x in ("open_at_M", "open_4h", "open_8h", "open_12h", "locked", "sl_in_window"):
        dg[x] = np.zeros(n, bool)
    dg["kind"] = np.empty(n, object)
    dg["held_in_window"] = np.zeros(n, np.int64)
    dg["held_bars"] = np.zeros(n, np.int64)
    trig = 0.12 / V2.LEVP + V2.COST_RT                                 # the first lock's trigger (return terms)
    for a in range(0, n, 400):
        b = min(n, a + 400)
        e = R.e.to_numpy()[a:b]
        s = R.side.to_numpy()[a:b][:, None]
        p0 = g["o"][e][:, None]
        af = (R.atrf.to_numpy()[a:b] * g["o"][e] / g["o"][e])[:, None]
        idx = np.minimum(e[:, None] + np.arange(Wt)[None, :], g["n"] - 1)
        H, L, O, C = g["h"][idx] / p0 - 1, g["l"][idx] / p0 - 1, g["o"][idx] / p0 - 1, g["c"][idx] / p0 - 1
        FC = s * (cumf[idx] - cumf[e - 1][:, None])
        UP = np.where(s > 0, H, -L)
        DN = np.where(s > 0, L, -H)
        OP, CL = s * O, s * C
        hmax = np.minimum(Wt, g["n"] - e)
        col = np.arange(Wt)[None, :]
        valid = col < hmax[:, None]
        UP = np.where(valid, UP, -np.inf)
        DN = np.where(valid, DN, np.inf)
        RMI = np.maximum.accumulate(UP, axis=1)
        RMUp = np.concatenate([np.zeros((len(e), 1)), RMI[:, :-1]], axis=1)
        lk = V2.lock_house(V2.LEVP * (RMUp - V2.COST_RT))
        level = np.maximum(np.where(np.isnan(lk), -np.inf, lk / V2.LEVP + V2.COST_RT), -2.0 * af)
        lockedby = ~np.isnan(V2.lock_house(V2.LEVP * (RMI - V2.COST_RT)))        # armed by the end of that minute
        rows = np.arange(len(e))
        tn = hmax - 1
        net = CL - V2.COST_RT - FC

        def walk(lev_):
            hit = DN <= lev_
            th = np.where(hit.any(1), hit.argmax(1), Wt + 1)
            t = np.minimum(th, tn)
            thc = np.minimum(th, Wt - 1)
            v = np.where(th <= tn, np.minimum(lev_[rows, thc], OP[rows, thc]), CL[rows, np.minimum(tn, Wt - 1)])
            tc = np.minimum(t, Wt - 1)
            return th, tc, v - V2.COST_RT - FC[rows, tc]

        th0, tc0, r0 = walk(level)
        stop_exit0 = th0 <= tn
        ny = ny_all[idx] & valid
        cM, hasM = _first(ny)
        cMc = np.minimum(cM, Wt - 1)
        openM = hasM & (th0 > cM) & (cM < tn) & ~lockedby[rows, cMc]
        netM = net[rows, cMc]
        # A0 diagnostics
        sl = slice(a, b)
        dg["open_at_M"][sl] = openM
        dg["roe_at_M"][sl] = np.where(openM, V2.LEVP * netM, 0.0)
        dg["R_at_M"][sl] = np.where(openM, CL[rows, cMc] / (2.0 * af[:, 0]), 0.0)
        dg["hours_at_M"][sl] = np.where(openM, (cMc + 1) / 60.0, 0.0)
        dg["mfe_share_at_M"][sl] = np.where(openM, RMI[rows, cMc] / trig, 0.0)
        for hh in (4, 8, 12):
            c_ = 60 * hh - 1
            dg[f"open_{hh}h"][sl] = (c_ < tn) & (th0 > c_) & ~lockedby[:, min(c_, Wt - 1)]
        locked0 = ~np.isnan(lk[rows, tc0])
        dg["locked"][sl] = locked0
        kind0 = np.where(locked0, "LOCKED", np.where(stop_exit0, "SL", "OTHER"))
        dg["kind"][sl] = kind0
        dg["sl_in_window"][sl] = (kind0 == "SL") & win_all[e + tc0]
        dg["held_in_window"][sl] = wcum[e + tc0 + 1] - wcum[e]
        dg["held_bars"][sl] = tc0 + 1
        why0 = np.where(stop_exit0, np.where(locked0, "LOCK", "SL"), "CAP")
        for arm, (kind, hours) in CM.ARMS.items():
            r, x, why, tch = r0.copy(), tc0.copy(), why0.copy(), np.zeros(len(e), bool)
            if kind in ("open_close", "open_mix"):
                cl = openM if kind == "open_close" else openM & (netM <= 0)
                r = np.where(cl, CL[rows, cMc] - V2.COST_RT - FC[rows, cMc], r)
                x = np.where(cl, cMc, x)
                why = np.where(cl, "OPENCUT", why)
                tch |= cl
            if kind in ("open_be", "open_mix"):
                if kind == "open_mix":
                    cb, hasb = cMc, openM & (netM > 0)
                else:
                    cond = ny & ~lockedby & (net > 0) & (col < tn[:, None])
                    cb, hasb = _first(cond)
                    cb = np.minimum(cb, Wt - 1)
                    hasb &= th0 > cb                                             # still open then
                be_lv = V2.COST_RT + FC[rows, cb]
                lev2 = np.where(hasb[:, None] & (col > cb[:, None]), np.maximum(level, be_lv[:, None]), level)
                th2, tc2, r2 = walk(lev2)
                lk2 = ~np.isnan(lk[rows, tc2])
                r = np.where(hasb, r2, r)
                x = np.where(hasb, tc2, x)
                why = np.where(hasb, np.where(th2 <= tn, np.where(lk2, "LOCK", np.where(lev2[rows, np.minimum(th2, Wt - 1)]
                                                                                       > level[rows, np.minimum(th2, Wt - 1)],
                                                                                       "BE", "SL")), "CAP"), why)
                tch |= hasb
            if kind == "open_deep":                                              # A7 (addendum 3)
                cond = ny & ~lockedby & (CL / (2.0 * af) <= CM.DEEP_R) & (col < tn[:, None])
                cd, hasd = _first(cond)
                cd = np.minimum(cd, Wt - 1)
                cl = hasd & (th0 > cd)
                r = np.where(cl, CL[rows, cd] - V2.COST_RT - FC[rows, cd], r)
                x = np.where(cl, cd, x)
                why = np.where(cl, "OPENCUT", why)
                tch |= cl
            if kind == "time":
                c_ = 60 * hours - 1
                cl = (c_ < tn) & (th0 > c_) & ~lockedby[:, min(c_, Wt - 1)]
                r = np.where(cl, CL[:, min(c_, Wt - 1)] - V2.COST_RT - FC[:, min(c_, Wt - 1)], r)
                x = np.where(cl, c_, x)
                why = np.where(cl, "TIME", why)
                tch |= cl
            res[arm]["r"][sl], res[arm]["x"][sl], res[arm]["reason"][sl], res[arm]["touched"][sl] = r, x, why, tch
    out = {arm: pd.DataFrame(v) for arm, v in res.items()}
    out["diag"] = pd.DataFrame(dg)
    return out


# ------------------------------------------------------------------------------------------------ the account
def signal_rows():
    """vwmonth2.paper_trades' rows before the exits: (A = VWAP 30m prio 0, X = CMO 1h prio 1) after time_ok and gates."""
    import vwadd as AD
    import vwfix2 as V2
    from multiprocessing import Pool
    from paperbot import sweepsig
    AD.PHOTO = [("S3_CMO_SANDWICH", "1h", "CMO·샌드위치 캔들 1시간")]          # as vwmonth2
    lib = sweepsig.lib()
    parts = []
    for coin in NL.COINS:
        R = V2.rows_tf(coin, "30m", lib)
        parts.append((coin, 30, R))
    with Pool(2) as pool:
        sig = dict(pool.map(AD.sig_job, NL.COINS))
    for coin in NL.COINS:
        R = AD.rows_of(coin, "1h", sig[coin][("S3_CMO_SANDWICH", "1h")])
        parts.append((coin, 60, R))
    return parts


def outcomes_all(parts, parity=False):
    import vwadd as AD
    import vwfix2 as V2
    frames, bad, checked = [], 0, 0
    for coin, k, R in parts:
        R = R[AD.time_ok(R.t.to_numpy()) & AD.gates(R)].reset_index(drop=True)
        R = R.assign(prio=0 if k == 30 else 1)
        O = outcomes_arms(coin, R, k)
        if parity:
            if k == 30:
                rb, xb = V2.outcomes_tf(coin, R, k)["base"]
            else:
                rb, xb = AD.outcomes_k(coin, R, k)
            checked += len(R)
            bad += int(((np.abs(O["A0"].r.to_numpy() - rb) > 1e-12) | (O["A0"].x.to_numpy() != xb)).sum())
        cols = {f"{arm}_{c}": O[arm][c].to_numpy() for arm in CM.ARMS for c in ("r", "x", "reason", "touched")}
        D = O["diag"].add_prefix("d_")
        frames.append(pd.concat([R, pd.DataFrame(cols), D], axis=1))
        print("outcomes", coin, k, len(R), flush=True)
    P = pd.concat(frames, ignore_index=True)
    P = P[P.t >= NL.ms("2020-03-01")].reset_index(drop=True)
    P["lev"] = np.minimum(V2.LEVP, 0.5 / (2.0 * P.atrf.to_numpy() + V2.COST_RT))
    return P, {"rows": checked, "different": bad}


def account(P: pd.DataFrame, arm: str) -> tuple:
    """One position (vwacct._take on the arm's exits), the signal light on that arm's paper sequence."""
    from vwacct import _take
    from vwmonth2 import light
    t, coin, prio = P.t.to_numpy(), P.coin.to_numpy(), P.prio.to_numpy()
    o = np.lexsort((coin, prio, t))
    ext = t[o] + (P[f"{arm}_x"].to_numpy()[o] + 1) * CM.MIN
    T = P.iloc[o[_take(t[o], ext, np.ones(len(o), bool))]].reset_index(drop=True)
    r = T[f"{arm}_r"].to_numpy(float)
    on = light(r > 0)
    D = pd.DataFrame({"t": T.t.to_numpy(np.int64), "symbol": [NL.COINS[c] for c in T.coin], "member": np.where(
        T.prio == 0, "VWAP 30m", "CMO 1h"), "side": T.side, "lev": T.lev, "r": r, "roe": T.lev * r,
        "ret": 0.4 * T.lev.to_numpy() * r, "reason": T[f"{arm}_reason"], "touched": T[f"{arm}_touched"].astype(bool),
        "copied": on, "exit_ts": T.t.to_numpy(np.int64) + T[f"{arm}_x"].to_numpy() * CM.MIN})
    for c in ("open_at_M", "roe_at_M", "R_at_M", "hours_at_M", "mfe_share_at_M", "open_4h", "open_8h", "open_12h", "locked",
              "kind", "sl_in_window", "held_in_window", "held_bars"):
        D[c] = T[f"d_{c}"].to_numpy()
    return D


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("five")
    ap.add_argument("work")
    ap.add_argument("out")
    ap.add_argument("--judge", action="store_true")
    ap.add_argument("--parity", action="store_true")
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    t0 = time.time()
    if a.judge:
        build_judge(a.five, a.work)
        return 0
    import vwmonth2  # noqa: F401  (loads the whole chain, then the names are patched)
    patch(a.five, a.work)
    parts = signal_rows()
    print(f"signal rows {sum(len(R) for _, _, R in parts)} ({time.time() - t0:.0f}s)", flush=True)
    P, par = outcomes_all(parts, parity=a.parity)
    print("parity", par, f"{time.time() - t0:.0f}s", flush=True)
    if a.parity:
        json.dump(par, open(os.path.join(a.out, "vwap_parity.json"), "w"), indent=1)
        return 0 if par["different"] == 0 else 1
    out = {"bot": "VWAP 개선판 -> DeepCoin", "live": {}, "paper": {}, "parity_A0_vs_outcomes_tf": par}
    for arm in CM.ARMS:
        D = account(P, arm)
        D.to_csv(os.path.join(a.out, f"vwap_trades_{arm}.csv.gz"), index=False)
        L = D[D.copied].reset_index(drop=True)
        out["live"][arm] = {p: CM.period_metrics(L, p) for p in CM.PERIODS}
        out["paper"][arm] = {p: CM.period_metrics(D, p) for p in CM.PERIODS}
        out["live"][arm]["copied_share_pct"] = 100 * float(D.copied.mean())
        if arm == "A0":
            out["diagnostics_A0"] = {"live": CM.by_period_diag(L), "paper": CM.by_period_diag(D)}
            out["sideways_A0"] = {"live": CM.by_period_sideways(L), "paper": CM.by_period_sideways(D)}
        print(arm, {p: (d["trades"], round(d["median_month"], 4)) for p, d in out["live"][arm].items()
                    if isinstance(d, dict)}, f"{time.time() - t0:.0f}s", flush=True)
    out["verdicts"] = CM.verdicts({k: {p: v[p] for p in CM.PERIODS} for k, v in out["live"].items()})
    out["verdicts_paper"] = CM.verdicts(out["paper"])
    json.dump(CM.jsonable(out), open(os.path.join(a.out, "vwap.json"), "w"), indent=1, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
