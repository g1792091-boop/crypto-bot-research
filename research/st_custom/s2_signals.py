"""Stage 2: per coin x timeframe x period, the signals of every grid combo of the three strategies (locked param_defs
code, Supertrend / KST / Klinger memoised per series) and their outcome totals for every variant.

Series of a period = bars [start - 500, end + SPILL) of the timeframe (PREREG: 500 bars of warm-up; signals are causal,
so bars after the end change nothing inside the period; only STFLIP uses them for exits). A signal bar counts when its
open time is in the period, it is >= 500 bars into the series and it has an outcome (next 15m bar exists, ATR > 0).

Variants (index): 0 main, 1 maker, 2 htf, 3 chop, 4 stflip, 5.. tpsl (TP R x stop ATR, common.TPSL_CFG).
Per variant and combo: n trades (closed), wins (net R > 0), sum net R, sum gross R, sum net R^2, n signals.
Per combo (main): weekly n and sum net R (Monday weeks), for bootstraps and the luck baseline.
Signal lists: code = (bar - period first bar) * 2 + (side == long), per combo, for later stages.

    python3 -B research/st_custom/s2_signals.py [procs] [--only COIN,TF,PERIOD]
"""
import os
import sys
import time
import zlib
from multiprocessing import Pool

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402
import numpy as np  # noqa: E402
import s1_outcomes as S1  # noqa: E402

VARIANTS = ["main", "maker", "htf", "chop", "stflip"] + [f"tpsl_{tp:g}R_{k:g}atr" for tp, k in C.TPSL_CFG]
NV = len(VARIANTS)
STATS = ("n", "wins", "sumR", "sumG", "sumR2", "nsig")
BIG = 2**40


def tot_path(coin, tf, per):
    return os.path.join(C.TOT_DIR, f"{coin}_{tf}_{per}.npz")


def sig_path(coin, tf, per):
    return os.path.join(C.SIG_DIR, f"{coin}_{tf}_{per}.npz")


def period_range(ts, per):
    a, b = C.PERIODS[per]
    lo = int(np.searchsorted(ts, C.ts_ns(a)))
    hi = int(np.searchsorted(ts, C.ts_ns(b)))
    return lo, hi


def load_outcomes(coin, tf):
    z = np.load(S1.path(coin, tf))
    return {k: z[k] for k in z.files}


def tf_last15(coin, tf, bt, b15):
    """15m index of the last 15m bar inside each timeframe bar."""
    if tf == "15m":
        return np.arange(len(bt["ts"]))
    j = np.searchsorted(b15["ts"], bt["ts"] + (C.TF_MIN[tf] - 15) * C.NS_MIN)
    j = np.minimum(j, len(b15["ts"]) - 1)
    assert np.all(b15["ts"][j] == bt["ts"] + (C.TF_MIN[tf] - 15) * C.NS_MIN), "incomplete tf bar"
    return j


def stflip_outcomes(d, s0, gi, side, O, b15, last15):
    """STFLIP net / gross R for signals at global tf bars gi (series offset s0, direction d of the series):
    exit at the close of the first later bar whose Supertrend direction is against the side, unless the 2 ATR stop
    (stop-only scan) is touched first (stop bar <= flip bar's last 15m bar). NaN when neither happens in the data."""
    n = len(d)
    ar = np.arange(n)
    with np.errstate(invalid="ignore"):
        neg = np.where(d < 0, ar, BIG)
        pos = np.where(d > 0, ar, BIG)
    nxt_neg = np.minimum.accumulate(neg[::-1])[::-1]
    nxt_pos = np.minimum.accumulate(pos[::-1])[::-1]
    p = gi - s0
    p1 = np.minimum(p + 1, n - 1)
    k = np.where(side > 0, nxt_neg[p1], nxt_pos[p1])
    k = np.where(p + 1 < n, k, BIG)
    has_flip = k < BIG
    xk = np.where(has_flip, last15[np.minimum(s0 + k, len(last15) - 1)], BIG)
    si = np.where(side > 0, 0, 1)
    sx = np.where(si == 0, O["sx_0"][gi], O["sx_1"][gi]).astype(np.int64)
    sre = np.where(si == 0, O["sreason_0"][gi], O["sreason_1"][gi])
    sR = np.where(si == 0, O["sR_0"][gi], O["sR_1"][gi]).astype(float)
    stop_done = (sre == 0) | (sre == 2)
    use_stop = stop_done & (sx <= xk)
    e = O["e"][gi].astype(np.int64)
    atr = O["atr"][gi]
    raw = b15["o"][e]
    fill = raw * (1 + side * C.SLIP)
    stop0 = raw - side * C.K_STOP * atr
    risk = np.abs(fill - stop0)
    xkc = np.minimum(xk, len(b15["c"]) - 1)
    exr = b15["c"][xkc]
    exp_ = exr * (1 - side * C.SLIP)
    held = xkc - e + 1
    Rf = (side * (exp_ / fill - 1) - C.TAKER * (1 + exp_ / fill) - C.F_BAR15 * held) * fill / risk
    Gf = side * (exr - raw) / risk
    # gross of a stop exit (no ladder: the stop is stop0; a bar opening beyond it fills at the open, as scan)
    sxc = np.clip(sx, 0, len(b15["o"]) - 1)
    o_s = b15["o"][sxc]
    exr_s = np.where(side * o_s <= side * stop0, o_s, stop0)
    Gs = side * (exr_s - raw) / risk
    R = np.where(use_stop, sR, np.where(has_flip, Rf, np.nan))
    G = np.where(use_stop, Gs, np.where(has_flip, Gf, np.nan))
    return R, G


def job(args):
    coin, tf, per = args
    if os.path.exists(tot_path(coin, tf, per)) and os.path.exists(sig_path(coin, tf, per)):
        return coin, tf, per, "cached", 0
    t0 = time.time()
    try:
        os.nice(5)
    except OSError:
        pass
    bt = C.load_bars(coin, tf)
    b15 = C.load_bars(coin, "15m")
    O = load_outcomes(coin, tf)
    ts = bt["ts"]
    N = len(ts)
    lo, hi = period_range(ts, per)
    if hi <= lo:
        return coin, tf, per, "no bars", 0
    s0 = max(0, lo - C.WARM)
    s1 = min(N, hi + C.SPILL)
    df = C.frame(bt, tf, s0, s1)
    last15 = tf_last15(coin, tf, bt, b15)
    week0 = int(C.week_of([C.ts_ns(C.PERIODS[per][0])])[0])
    nweek = int(C.week_of([C.ts_ns(C.PERIODS[per][1]) - 1])[0]) - week0 + 1
    # ---------------- per-bar tables for the period's bars (both sides)
    gi_all = np.arange(lo, hi)
    okbar = O["valid"][lo:hi] & (gi_all - s0 >= C.WARM)
    # main
    Rm = np.stack([O["R_0"], O["R_1"]])            # (2, N)
    Gm = np.stack([O["gross_0"], O["gross_1"]])
    done_m = np.stack([O["reason_0"], O["reason_1"]]) != 3
    Rk = np.stack([O["mR_0"], O["mR_1"]])
    Gk = np.stack([O["mG_0"], O["mG_1"]])
    done_k = np.stack([O["mfill_0"] & (O["mreason_0"] != 3), O["mfill_1"] & (O["mreason_1"] != 3)])
    htf = np.stack([O["htf_0"], O["htf_1"]])
    chop = O["chop"]
    # TPSL on every valid bar of the period, both sides (computed here, not stored)
    tp_idx = gi_all[okbar]
    TPR = np.full((len(C.TPSL_CFG), 2, N), np.nan, np.float32)
    TPG = np.full((len(C.TPSL_CFG), 2, N), np.nan, np.float32)
    for si, sd in enumerate((1, -1)):
        side = np.full(len(tp_idx), sd, np.int64)
        e = O["e"][tp_idx].astype(np.int64)
        atr = O["atr"][tp_idx]
        lev, liq, _fe = C.lev_liq(coin, side, atr / b15["o"][e])
        r, g = C.tpsl_outcomes(b15, e, side, atr, lev, liq)
        TPR[:, si, tp_idx] = r
        TPG[:, si, tp_idx] = g
    t_tab = time.time() - t0
    # ---------------- signals
    C.memo_on((coin, tf, per))
    rng = np.random.default_rng(zlib.crc32(f'{coin}{tf}{per}'.encode()))
    tot = {}
    weekly_n = {}
    weekly_s = {}
    sig_store = {}
    verify = []
    for strat in C.STRATS:
        nc = C.NCOMBO[strat]
        T = np.zeros((NV, nc, len(STATS)), np.float64)
        WN = np.zeros((nc, nweek), np.int32)
        WS = np.zeros((nc, nweek), np.float32)
        codes, offs = [], [0]
        check = {C.combo_index(strat, C.DEFAULT_IDX[strat]), int(rng.integers(nc)), int(rng.integers(nc))}
        if strat in C.FRIEND_IDX:
            check.add(C.combo_index(strat, C.FRIEND_IDX[strat]))
        for c in range(nc):
            sig = C.combo_signal(strat, c, df, tf)
            if c in check:   # memoised == plain locked call
                tok = C._TOKEN[0]
                C._TOKEN[0] = None
                ref = C.combo_signal(strat, c, df, tf)
                C._TOKEN[0] = tok
                if not np.array_equal(ref, sig):
                    raise RuntimeError(f"memo mismatch {coin} {tf} {per} {strat} {c}")
                verify.append((strat, c))
            p = np.flatnonzero(sig)
            gi = p + s0
            keep = (gi >= lo) & (gi < hi) & (p >= C.WARM)
            gi = gi[keep]
            gi = gi[O["valid"][gi]]
            sd = sig[gi - s0].astype(np.int64)
            si = np.where(sd > 0, 0, 1)
            codes.append(((gi - lo) * 2 + (sd > 0)).astype(np.int32))
            offs.append(offs[-1] + len(gi))
            wk = C.week_of(ts[gi]) - week0

            def put(v, R, G, ok, nsig):
                R = R[ok].astype(float)
                G = G[ok].astype(float)
                T[v, c] = (len(R), float((R > 0).sum()), R.sum(), G.sum(), (R * R).sum(), nsig)
                return R
            # main
            ok = done_m[si, gi]
            Rv = put(0, Rm[si, gi], Gm[si, gi], ok, len(gi))
            WN[c] = np.bincount(wk[ok], minlength=nweek)[:nweek]
            WS[c] = np.bincount(wk[ok], weights=Rv, minlength=nweek)[:nweek]
            put(1, Rk[si, gi], Gk[si, gi], done_k[si, gi], len(gi))
            put(2, Rm[si, gi], Gm[si, gi], ok & htf[si, gi], int((htf[si, gi]).sum()))
            put(3, Rm[si, gi], Gm[si, gi], ok & chop[gi], int((chop[gi]).sum()))
            t = C.combo_tuple(strat, c)
            d = C.st_direction(C.ST_ATR[t[0]], C.ST_MULT[t[1]])
            Rf, Gf = stflip_outcomes(d, s0, gi, sd, O, b15, last15)
            put(4, Rf, Gf, np.isfinite(Rf), len(gi))
            for j in range(len(C.TPSL_CFG)):
                r_, g_ = TPR[j, si, gi], TPG[j, si, gi]
                put(5 + j, r_, g_, np.isfinite(r_), len(gi))
        tot[strat] = T
        weekly_n[strat] = WN
        weekly_s[strat] = WS
        offs = np.array(offs, np.int64)
        allc = np.concatenate(codes)
        dd, ff = C.encode_codes(allc, offs)
        assert np.array_equal(C.decode_codes(dd, ff, offs), allc)
        sig_store[strat + "__d"] = dd
        sig_store[strat + "__f"] = ff
        sig_store[strat + "__offs"] = offs
    C.memo_off()
    C.save_npz(sig_path(coin, tf, per), lo=np.array([lo]), hi=np.array([hi]), s0=np.array([s0]), s1=np.array([s1]),
               **sig_store)
    C.save_npz(tot_path(coin, tf, per), lo=np.array([lo]), hi=np.array([hi]), week0=np.array([week0]),
               **{f"{s}__tot": tot[s] for s in C.STRATS}, **{f"{s}__wn": weekly_n[s] for s in C.STRATS},
               **{f"{s}__ws": weekly_s[s] for s in C.STRATS},
               verified=np.array([f"{a}:{b}" for a, b in verify]))
    return coin, tf, per, f"bars {hi - lo} tables {t_tab:.0f}s", round(time.time() - t0, 1)


if __name__ == "__main__":
    procs = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    jobs = [(c, tf, per) for tf in C.TFS for per in C.PERIOD_ORDER for c in C.COINS]
    if "--only" in sys.argv:
        a = sys.argv[sys.argv.index("--only") + 1].split(",")
        jobs = [tuple(a)]
    # biggest first
    jobs.sort(key=lambda j: (j[1] != "15m", {"SEARCH": 0, "TEST": 1, "EXTRA": 2}[j[2]]))
    with Pool(procs, maxtasksperchild=1) as p:
        for r in p.imap_unordered(job, jobs):
            C.log(*r)
