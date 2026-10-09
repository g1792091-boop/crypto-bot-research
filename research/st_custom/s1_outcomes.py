"""Stage 1: per coin x timeframe, the outcome of an entry after EVERY signal-timeframe bar, both sides (house exits do
not depend on strategy parameters, only on the entry bar, side, signal-bar ATR and timeframe):

  main   : entry at the next bar's open (15m bar e), stop 2 x ATR14 of the signal bar, paperbot ladder at the sizer's
           leverage (30x, else 20x; neither = 'infeasible', scanned at 20x without liquidation, as precompute.py's
           all-signal sensitivity), checked on 15m bars, taker + slippage both sides, funding per 15m bar.
  maker  : limit at the signal bar's close, valid for one signal-timeframe bar (1 or 2 15m bars), filled when a 15m
           bar trades at/through it; entry fee 0.02%, no entry slippage; same stop / ladder / exit costs.
  stop   : the 2 ATR stop alone (no ladder): first touch (STFLIP combines it with each Supertrend's flip).
  masks  : HTF (last closed 4h close vs 4h EMA50, trade side), CHOP (ADX14 of the signal timeframe >= 20).

Output WORK/outcomes/<coin>_<tf>.npz; one job per coin x tf, skipped when its file exists (resume).
    python3 -B research/st_custom/s1_outcomes.py [procs]
"""
import os
import sys
import time
from multiprocessing import Pool

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402
import numpy as np  # noqa: E402


def path(coin, tf):
    return os.path.join(C.OUTC_DIR, f"{coin}_{tf}.npz")


def job(args):
    coin, tf = args
    if os.path.exists(path(coin, tf)):
        return coin, tf, "cached", 0.0
    t0 = time.time()
    os.nice(5)
    b15 = C.load_bars(coin, "15m")
    bt = C.load_bars(coin, tf)
    n = len(bt["ts"])
    n15 = len(b15["ts"])
    step = C.TF_MIN[tf] * C.NS_MIN
    df = C.frame(bt, tf)
    atr = C.fg.atr(df, 14).to_numpy(float)
    adx = C.fg.dmi_adx(df, 14, 14)[2].to_numpy(float)
    e = np.searchsorted(b15["ts"], bt["ts"] + step)
    ok = (e < n15) & np.isfinite(atr) & (atr > 0)
    ok[ok] &= b15["ts"][e[ok]] == bt["ts"][ok] + step
    idx = np.flatnonzero(ok)
    e_ok = e[idx]
    a_ok = atr[idx]
    out = dict(e=np.where(ok, e, -1).astype(np.int32), atr=atr, valid=ok)
    # ---------------- main + stop-only, both sides
    for si, sd in enumerate((1, -1)):
        side = np.full(len(idx), sd, np.int64)
        raw = b15["o"][e_ok]
        lev, liq, feas = C.lev_liq(coin, side, a_ok / raw)
        r = C.run_scan(b15, e_ok, side, lev, liq, C.K_STOP * a_ok)
        for k, dt in (("R", np.float32), ("gross", np.float32), ("x", np.int32), ("reason", np.int8)):
            arr = np.full(n, np.nan if dt == np.float32 else -1, dt)
            arr[idx] = r[k]
            out[f"{k}_{si}"] = arr
        lv = np.zeros(n, np.int8)
        lv[idx] = lev
        fe = np.zeros(n, bool)
        fe[idx] = feas
        out[f"lev_{si}"] = lv
        out[f"feas_{si}"] = fe
        rs = C.run_scan(b15, e_ok, side, lev, liq, C.K_STOP * a_ok, ladder=False)
        for k, dt in (("R", np.float32), ("x", np.int32), ("reason", np.int8)):
            arr = np.full(n, np.nan if dt == np.float32 else -1, dt)
            arr[idx] = rs[k]
            out[f"s{k}_{si}"] = arr
        # ---------------- maker
        P = bt["c"][idx]
        nb = C.TF_MIN[tf] // 15
        fillbar = np.full(len(idx), -1, np.int64)
        for j in range(nb - 1, -1, -1):        # the earliest bar wins: iterate backwards, overwrite
            ej = e_ok + j
            inb = ej < n15
            ejc = np.minimum(ej, n15 - 1)
            inb &= b15["ts"][ejc] == bt["ts"][idx] + step + j * 15 * C.NS_MIN
            touch = (b15["l"][ejc] <= P) if sd == 1 else (b15["h"][ejc] >= P)
            fillbar = np.where(inb & touch, ej, fillbar)
        f = fillbar >= 0
        mR = np.full(n, np.nan, np.float32)
        mG = np.full(n, np.nan, np.float32)
        mx = np.full(n, -1, np.int32)
        mreason = np.full(n, -1, np.int8)
        mfill = np.zeros(n, bool)
        if f.any():
            ii = np.flatnonzero(f)
            sidef = side[ii]
            Pf = P[ii]
            levm, liqm, _fe = C.lev_liq(coin, sidef, a_ok[ii] / Pf)
            rm = C.run_scan(b15, fillbar[ii], sidef, levm, liqm, C.K_STOP * a_ok[ii], fill=Pf.copy(),
                            raw=Pf.copy(), fill_bar=True, entry_fee=C.MAKER)
            tgt = idx[ii]
            mR[tgt] = rm["R"]
            mG[tgt] = rm["gross"]
            mx[tgt] = rm["x"]
            mreason[tgt] = rm["reason"]
            mfill[tgt] = True
        out[f"mR_{si}"], out[f"mG_{si}"], out[f"mx_{si}"] = mR, mG, mx
        out[f"mreason_{si}"], out[f"mfill_{si}"] = mreason, mfill
    # ---------------- masks
    b4 = C.load_bars(coin, "4h")
    ema = C.pi.pine_ema(b4["c"], 50)
    close_t = bt["ts"] + step
    j = np.searchsorted(b4["ts"] + 240 * C.NS_MIN, close_t, side="right") - 1
    jj = np.maximum(j, 0)
    c4 = np.where(j >= 0, b4["c"][jj], np.nan)
    e4 = np.where(j >= 0, ema[jj], np.nan)
    with np.errstate(invalid="ignore"):
        out["htf_0"] = c4 > e4
        out["htf_1"] = c4 < e4
        out["chop"] = adx >= 20
    out["adx"] = adx.astype(np.float32)
    C.save_npz(path(coin, tf), **out)
    return coin, tf, f"{len(idx)} bars", round(time.time() - t0, 1)


if __name__ == "__main__":
    procs = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    jobs = [(c, tf) for tf in C.TFS for c in C.COINS]
    with Pool(procs) as p:
        for r in p.imap_unordered(job, jobs):
            C.log(*r)
