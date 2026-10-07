#!/usr/bin/env python3
"""5-year AI-call simulator for one-position AI traders (no API calls).

    python3 -P sim5y.py <signals_dir> <out_dir> [procs]

<signals_dir>: sig_{tf}_{COIN}USD.npz (ts open ns, o,h,l,c,atr, s__<STRAT> int8 side) for 6 coins x 15m/30m/1h/4h
(the Binance rebuild used by research/strategy_profiles out_binance). Period 2021-08-01 .. 2026-09-30 (UTC).

Per strategy, per entry-timeframe setup (A = 15m+30m, B = 15m/30m/1h/4h, C = 15m/30m/1h + 4h only when the
2 ATR stop is <= 3.2 % of price, i.e. inside 70 % of the 20x liquidation distance), per AI enter-probability
pe (1.0 = default action "enter", 0.5 = AI skips half): one trader, one position at a time, 6 coins.

Exit proxy (no AI exits): house rule, entry = next bar open, stop = 2 ATR(signal bar), stepped net-ROE lock
(first lock 10 % at best 12 %, +5 % steps, armed from the next bar), leverage 30x (15m/30m/1h) or 20x (4h),
round trip 0.12 % of notional; exits on the trade's own timeframe bars (bar low/high first = conservative).

Counts per KST day (UTC+9):
  entry      one call per bar-close moment with >= 1 entry-set signal while flat (coins and timeframes that
             close at the same moment are bundled in one call)
  switch     the same bundles while in a position (switch decisions; "ignore" mode makes them 0)
  p1_bar     holding checks at every bar close of the held timeframe strictly inside the hold, minus moments
             already called as switch bundles (counted separately for ignore mode: p1_bar_ign)
  p2_30m     holding checks at every 30-minute boundary inside the hold (p2_30m_ign likewise)
  ev_move    event checks: price moved >= 0.5 R (R = 2 ATR) from the price at the last event (bar high/low)
  ev_otf_ign same-coin signals of the strategy on a timeframe other than the held one during the hold
  ev_otf_sw  the same, excluding entry-set timeframes (those are already switch calls in switch mode)
  trades, pos_min (minutes in a position)
"""
from __future__ import annotations

import os
import sys
import json
import math
import numpy as np
from multiprocessing import Pool

COINS = ["BTC", "ETH", "SOL", "BCH", "LTC", "DOGE"]
TFS = ["15m", "30m", "1h", "4h"]
TF_MIN = {"15m": 15, "30m": 30, "1h": 60, "4h": 240}
LEV = {"15m": 30, "30m": 30, "1h": 30, "4h": 20}
RT = 0.0012
FIRST, STEP, GAP = 0.10, 0.05, 0.02
START = np.datetime64("2021-08-01T00:00", "ns").astype(np.int64)
END = np.datetime64("2026-09-30T00:00", "ns").astype(np.int64)
KST = 9 * 3600 * 10**9
DAY = 86400 * 10**9
NDAYS = int((END - START) // DAY) + 2
SETUPS = {"A": ("15m", "30m"), "B": ("15m", "30m", "1h", "4h"), "C": ("15m", "30m", "1h", "4h")}
PES = [1.0, 0.5]
STOP_CAP_4H_C = 0.032
MIN30 = 30 * 60 * 10**9

SIG_DIR = None
DATA = {}


def load(sig_dir):
    d = {}
    for tf in TFS:
        for c in COINS:
            z = np.load(os.path.join(sig_dir, f"sig_{tf}_{c}USD.npz"), allow_pickle=False)
            d[(tf, c)] = {k: z[k] for k in z.files}
    return d


def kday(t_ns):
    return ((np.asarray(t_ns, dtype=np.int64) + KST - START) // DAY).astype(np.int64)


def exit_sim(tf, coin, i, side):
    """House-exit proxy for a signal on bar i (closed). Returns dict or None if no next bar."""
    b = DATA[(tf, coin)]
    ts, o, h, l, c, atr = b["ts"], b["o"], b["h"], b["l"], b["c"], b["atr"]
    n = len(ts)
    if i + 1 >= n or not np.isfinite(atr[i]) or atr[i] <= 0:
        return None
    lev = LEV[tf]
    e = o[i + 1]
    rdist = 2.0 * atr[i]
    stop0 = e - side * rdist
    j0 = i + 1
    W = 512
    best = -1e18
    lock_stop = None  # armed lock price (applies from next bar)
    while True:
        j1 = min(n, j0 + W)
        hh, ll = h[j0:j1], l[j0:j1]
        for k in range(j1 - j0):
            stop = stop0 if lock_stop is None else (max(stop0, lock_stop) if side == 1 else min(stop0, lock_stop))
            if (side == 1 and ll[k] <= stop) or (side == -1 and hh[k] >= stop):
                jx = j0 + k
                return {"t_in": int(ts[i + 1]), "t_out": int(ts[jx] + TF_MIN[tf] * 60 * 10**9 // 2),
                        "j_in": i + 1, "j_out": jx, "e": float(e), "rdist": float(rdist)}
            fav = hh[k] if side == 1 else ll[k]
            roe = lev * (side * (fav / e - 1.0) - RT)
            if roe > best:
                best = roe
                if best >= FIRST + GAP - 1e-12:
                    m = math.floor((best - FIRST - GAP) / STEP + 1e-9)
                    lk = FIRST + STEP * m
                    lock_stop = e * (1.0 + side * (lk / lev + RT))
        if j1 >= n:
            return {"t_in": int(ts[i + 1]), "t_out": int(ts[n - 1]), "j_in": i + 1, "j_out": n - 1,
                    "e": float(e), "rdist": float(rdist), "open_end": True}
        j0 = j1


def move_events(tf, coin, j_in, j_out, e, rdist):
    """Times (ns) of >= 0.5 R moves from the last event price, on the trade's bars (j_in..j_out)."""
    b = DATA[(tf, coin)]
    ts, h, l = b["ts"], b["h"], b["l"]
    step = 0.5 * rdist
    ref = e
    out = []
    for j in range(j_in, j_out + 1):
        up = h[j] - ref
        if up >= step:
            k = int(up // step)
            out.extend([int(ts[j])] * k)
            ref += k * step
        dn = ref - l[j]
        if dn >= step:
            k = int(dn // step)
            out.extend([int(ts[j])] * k)
            ref -= k * step
    return out


def strat_signals(strat):
    """All signals of a strategy: arrays sorted by close time."""
    rows = []
    for tf in TFS:
        for ci, c in enumerate(COINS):
            b = DATA[(tf, c)]
            key = "s__" + strat
            if key not in b:
                continue
            s = b[key]
            idx = np.nonzero(s)[0]
            tclose = b["ts"][idx] + TF_MIN[tf] * 60 * 10**9
            keep = (tclose >= START) & (tclose < END)
            idx = idx[keep]
            tclose = tclose[keep]
            stopfrac = 2 * b["atr"][idx] / b["c"][idx]
            for a, t, sd, sf in zip(idx, tclose, s[idx], stopfrac):
                rows.append((int(t), TFS.index(tf), ci, int(a), int(sd), float(sf)))
    rows.sort()
    return rows


def run_strategy(strat):
    import zlib; rng_master = np.random.default_rng(zlib.crc32(strat.encode()))
    sigs = strat_signals(strat)
    if not sigs:
        return strat, None
    T = np.array([r[0] for r in sigs], dtype=np.int64)
    TFI = np.array([r[1] for r in sigs])
    CI = np.array([r[2] for r in sigs])
    SF = np.array([r[5] for r in sigs])
    # per coin x tf sorted signal times (for other-timeframe wakes)
    by_ct = {}
    for ci in range(6):
        for ti in range(4):
            m = (CI == ci) & (TFI == ti)
            by_ct[(ci, ti)] = np.unique(T[m])
    exit_cache = {}
    res = {}
    for setup, tfs in SETUPS.items():
        tset = {TFS.index(x) for x in tfs}
        elig = np.array([(ti in tset) and not (setup == "C" and ti == 3 and sf > STOP_CAP_4H_C)
                         for ti, sf in zip(TFI, SF)])
        idx_e = np.nonzero(elig)[0]
        # bundles: unique close times among eligible signals
        if len(idx_e) == 0:
            continue
        bt, first = np.unique(T[idx_e], return_index=True)
        bounds = list(first) + [len(idx_e)]
        bundles = [(int(bt[k]), idx_e[bounds[k]:bounds[k + 1]]) for k in range(len(bt))]
        for pe in PES:
            rng = np.random.default_rng(rng_master.integers(1 << 31))
            cnt = {k: np.zeros(NDAYS, dtype=np.int64) for k in
                   ["entry", "switch", "p1_bar", "p1_bar_ign", "p2_30m", "p2_30m_ign", "ev_move",
                    "ev_otf_ign", "ev_otf_sw", "trades"]}
            pos_min = np.zeros(NDAYS, dtype=np.float64)
            holds = []
            t_out = -1
            cur = None
            sw_times = []
            for tb, members in bundles:
                if tb < t_out:
                    cnt["switch"][kday(tb)] += 1
                    sw_times.append(tb)
                    continue
                if cur is not None:
                    _close_trade(cur, sw_times, cnt, pos_min, by_ct, tset)
                    cur = None
                    sw_times = []
                cnt["entry"][kday(tb)] += 1
                if pe < 1.0 and rng.random() >= pe:
                    continue
                # pick: shortest timeframe, then random coin
                mt = TFI[members]
                cand = members[mt == mt.min()]
                k = int(cand[rng.integers(len(cand))])
                tf = TFS[TFI[k]]
                coin = COINS[CI[k]]
                key = (tf, coin, sigs[k][3])
                if key not in exit_cache:
                    ex = exit_sim(tf, coin, sigs[k][3], sigs[k][4])
                    if ex is not None:
                        ex["moves"] = move_events(tf, coin, ex["j_in"], ex["j_out"], ex["e"], ex["rdist"])
                    exit_cache[key] = ex
                ex = exit_cache[key]
                if ex is None:
                    continue
                cnt["trades"][kday(tb)] += 1
                t_out = ex["t_out"]
                cur = dict(ex, tf=tf, ti=TFI[k], ci=int(CI[k]), tb=tb)
                holds.append((ex["t_out"] - tb) / 60e9)
            if cur is not None:
                _close_trade(cur, sw_times, cnt, pos_min, by_ct, tset)
            res[(setup, pe)] = {"cnt": {k: v.tolist() for k, v in cnt.items()}, "pos_min": pos_min.tolist(),
                                "hold_med_min": float(np.median(holds)) if holds else None,
                                "hold_mean_min": float(np.mean(holds)) if holds else None,
                                "n_trades": len(holds)}
    return strat, res


def _close_trade(cur, sw_times, cnt, pos_min, by_ct, tset):
    tb, t_out = cur["tb"], cur["t_out"]
    tfm = TF_MIN[cur["tf"]] * 60 * 10**9
    sw = set(sw_times)
    # bar closes of the held timeframe strictly inside (tb, t_out)
    p1 = np.arange(tb + tfm, t_out, tfm, dtype=np.int64)
    if len(p1):
        np.add.at(cnt["p1_bar_ign"], kday(p1), 1)
        p1s = np.array([t for t in p1 if t not in sw], dtype=np.int64)
        if len(p1s):
            np.add.at(cnt["p1_bar"], kday(p1s), 1)
    first30 = (tb // MIN30 + 1) * MIN30
    p2 = np.arange(first30, t_out, MIN30, dtype=np.int64)
    if len(p2):
        np.add.at(cnt["p2_30m_ign"], kday(p2), 1)
        p2s = np.array([t for t in p2 if t not in sw], dtype=np.int64)
        if len(p2s):
            np.add.at(cnt["p2_30m"], kday(p2s), 1)
    if cur["moves"]:
        np.add.at(cnt["ev_move"], kday(np.array(cur["moves"], dtype=np.int64)), 1)
    for ti in range(4):
        if ti == cur["ti"]:
            continue
        arr = by_ct[(cur["ci"], ti)]
        a, b = np.searchsorted(arr, tb, "right"), np.searchsorted(arr, t_out, "left")
        if b > a:
            np.add.at(cnt["ev_otf_ign"], kday(arr[a:b]), 1)
            if ti not in tset:
                np.add.at(cnt["ev_otf_sw"], kday(arr[a:b]), 1)
    # minutes in position per day
    t = tb
    while t < t_out:
        d = int(kday(t))
        dend = START + (d + 1) * DAY - KST
        seg = min(t_out, dend) - t
        if 0 <= d < len(pos_min):
            pos_min[d] += seg / 60e9
        t = min(t_out, dend)


def init(sig_dir):
    global DATA
    DATA = load(sig_dir)


def main():
    sig_dir, out = sys.argv[1], sys.argv[2]
    procs = int(sys.argv[3]) if len(sys.argv) > 3 else 4
    os.makedirs(out, exist_ok=True)
    z = np.load(os.path.join(sig_dir, "sig_15m_BTCUSD.npz"))
    strats = [k[3:] for k in z.files if k.startswith("s__")]
    only = os.environ.get("ONLY")
    if only:
        strats = [s for s in strats if s in only.split(",")]
    with Pool(procs, initializer=init, initargs=(sig_dir,)) as p:
        for strat, res in p.imap_unordered(run_strategy, strats):
            if res is None:
                print("no signals", strat, flush=True)
                continue
            with open(os.path.join(out, f"sim5y_{strat}.json"), "w") as fh:
                json.dump({f"{k[0]}|{k[1]}": v for k, v in res.items()}, fh)
            r = res.get(("A", 1.0))
            print(strat, "A pe1 trades", r and r["n_trades"], "hold_med", r and r["hold_med_min"], flush=True)


if __name__ == "__main__":
    main()
