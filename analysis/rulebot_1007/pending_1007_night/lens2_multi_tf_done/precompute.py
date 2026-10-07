"""Every signal of the 36 core strategies and the 44 DeepSeek definitions on 15m/30m/1h/4h, run ALONE under the
house exits (2 ATR14 stop of the signal bar, paperbot ladder, taker 0.05% + slippage 0.02% each side, funding
0.01%/8h), with the stop and ladder checked on 15m bars for every timeframe (closer to the live 1m engine than the
5-year studies' own-timeframe bars; for 15m it is identical).

Sizing: paperbot.sizing.size_position with config.v3_settings() (= live v4 rule set) and the "normal" group
(30x/30% then 20x/20%: the live ds200 rule and ~78% of core signals), brackets inferred from live trades
(rb_analyze INFERRED_BRACKETS). A signal neither 30x nor 20x can size is "infeasible" (house: REJECTED); it is still
scanned at 20x ladder thresholds for the "all signals" sensitivity.

    python3 -I -B precompute.py <core_sig_dir> <ds_sig_dir> <out_dir> [procs]
"""
import os
import sys
import time

sys.path[:0] = ['/root/.local/lib/python3.11/site-packages', '/home/user/crypto-bot-research']
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from multiprocessing import Pool  # noqa: E402

from paperbot import sweepsig  # noqa: E402
from paperbot.config import v3_settings  # noqa: E402
from paperbot.ladder import LadderSpec  # noqa: E402
from paperbot.margin import BracketTier, Brackets  # noqa: E402
from paperbot.sizing import size_position  # noqa: E402

COINS = ("BTCUSD", "ETHUSD", "SOLUSD", "DOGEUSD", "LTCUSD", "BCHUSD")
TFS = ("15m", "30m", "1h", "4h")
TF_MIN = {"15m": 15, "30m": 30, "1h": 60, "4h": 240}
START, END = "2021-08-01", "2026-09-30"
K_STOP = 2.0
FUNDING_8H = 0.0001
EQUITY = 5000.0
S = v3_settings()
LAD = LadderSpec(S.ladder_first_lock, S.ladder_step, S.ladder_trigger_gap)
INFERRED_BRACKETS = {   # copied from rb_analyze/analyze.py (fit to the live trades' liquidation prices)
    "BTCUSD": [(1e12, 50, 0.004, 0.0)],
    "ETHUSD": [(1e12, 50, 0.004, 0.0)],
    "SOLUSD": [(50_000, 50, 0.005, 0.0), (1e12, 50, 0.0065, 75.0)],
    "DOGEUSD": [(80_000, 50, 0.0065, 0.0), (1e12, 50, 0.01, 280.0)],
    "BCHUSD": [(10_000, 50, 0.005, 0.0), (100_000, 50, 0.01, 50.0), (1e12, 40, 0.0125, 300.0)],
    "LTCUSD": [(10_000, 50, 0.005, 0.0), (50_000, 50, 0.01, 50.0), (1e12, 40, 0.015, 300.0)],
}
BR = {c: Brackets([BracketTier(*t) for t in v]) for c, v in INFERRED_BRACKETS.items()}


def sizer(coin):
    cache = {}

    def f(side, atr_frac):
        key = (side, float(f"{atr_frac:.4g}"))
        if key not in cache:
            raw = 100.0
            a = key[1] * raw
            fill = raw * (1 + side * S.slippage_frac)
            d = size_position(S, EQUITY, side, fill, raw - side * K_STOP * a, "normal", BR[coin], atr=a, min_notional=5.0)
            cache[key] = (d.leverage, side * (fill - d.liq_price) / fill) if d.ok else (0, np.nan)
        return cache[key]
    return f


def scan(b, e, side, lev, liq_frac, atr, H, f_bar):
    """House exit on 15m bars for entries at the open of 15m bar e (vectorised; copy of
    research/strategy_profiles/profiles._scan with the entry bar given directly)."""
    rt, fee, slip = S.round_trip_cost, S.taker_fee, S.slippage_frac
    n = len(b["o"])
    m = len(e)
    off = np.arange(H)
    J = e[:, None] + off[None, :]
    valid = J < n
    Jc = np.minimum(J, n - 1)
    o, h, lo, c = b["o"][Jc], b["h"][Jc], b["l"][Jc], b["c"][Jc]
    raw = b["o"][e]
    fill = raw * (1 + side * slip)
    stop0 = raw - side * K_STOP * atr
    liq = fill * (1 - side * liq_frac)
    s = side[:, None]
    fund = f_bar * (off[None, :] + 1)
    fav = np.where(s == 1, h, -lo)
    best_px = s * np.maximum.accumulate(np.concatenate([(side * fill)[:, None], fav], axis=1), axis=1)[:, 1:]
    roe_best = lev[:, None] * (s * (best_px / fill[:, None] - 1) - rt - fund)
    first = LAD.first_lock + LAD.trigger_gap
    nstep = np.floor((roe_best - first) / LAD.step + 1e-9)
    lock_roe = np.where(roe_best >= first - 1e-12, LAD.first_lock + LAD.step * nstep, np.nan)
    lock_px = fill[:, None] * (1 + s * (lock_roe / lev[:, None] + rt + fund))
    lp = np.where(np.isnan(lock_px), -np.inf, s * lock_px)
    lock_cum = np.maximum.accumulate(np.concatenate([np.full((m, 1), -np.inf), lp], axis=1), axis=1)[:, :-1]
    stop_eff = np.maximum((side * stop0)[:, None], lock_cum)
    adverse = np.where(s == 1, lo, -h)
    hit = (adverse <= stop_eff) & valid
    done = hit.any(axis=1)
    q = np.where(done, hit.argmax(axis=1), np.minimum(H, np.maximum(valid.sum(axis=1), 1)) - 1)
    r = np.arange(m)
    st = side * stop_eff[r, q]
    oq = o[r, q]
    gap = (side * oq) <= (side * st)
    liq_gap = done & gap & ((side * oq) <= (side * liq))
    exit_raw = np.where(done, np.where(gap, oq, st), c[r, q])
    exit_px = np.where(liq_gap, liq, exit_raw * (1 - side * slip))
    held = q + 1
    roe = lev * (side * (exit_px / fill - 1) - fee * (1 + exit_px / fill) - f_bar * held)
    roe = np.where(liq_gap, -1.0, np.maximum(roe, -1.0))
    is_lock = done & ~liq_gap & (side * st > side * stop0 + 1e-12)
    reason = np.where(~done, 3, np.where(liq_gap, 2, np.where(is_lock, 1, 0)))
    risk = np.abs(fill - stop0)
    R = roe * fill / (lev * risk)
    gross = side * (exit_raw - raw) / risk
    return dict(done=done, x=e + q, R=R, gross=gross, roe=roe, reason=reason, fill=fill, risk=risk)


def job(args):
    tf, coin, core_dir, ds_dir, out_dir = args
    t0 = time.time()
    L = sweepsig.lib()
    z15 = np.load(os.path.join(core_dir, f"sig_15m_{coin}.npz"))
    b15 = {k: z15[k] for k in ("ts", "o", "h", "l", "c")}
    zc = np.load(os.path.join(core_dir, f"sig_{tf}_{coin}.npz"))
    zd = np.load(os.path.join(ds_dir, f"ds_{tf}_{coin}.npz"))
    ts = zc["ts"]
    assert np.array_equal(ts, zd["ts"]), "core and ds bars differ"
    atr = zc["atr"]
    n = len(ts)
    step_ns = TF_MIN[tf] * 60 * 10**9
    lo = max(int(np.searchsorted(ts, pd.Timestamp(START).value)), L.warmup_bars(tf))
    hi = int(np.searchsorted(ts, pd.Timestamp(END).value)) - 1
    sigs = {}
    for zz, pre in ((zc, "C:"), (zd, "D:")):
        for k in zz.files:
            if k.startswith("s__"):
                sg = zz[k]
                idx = np.nonzero(sg[lo:hi])[0] + lo
                sigs[pre + k[3:]] = (idx, sg[idx].astype(np.int8))
    allk = np.concatenate([i.astype(np.int64) * 2 + (s > 0) for i, s in sigs.values()])
    uk = np.unique(allk)
    ui, us = uk // 2, np.where(uk % 2 == 1, 1, -1)
    # entry 15m bar: the open at the signal bar's close
    e = np.searchsorted(b15["ts"], ts[ui] + step_ns)
    a = atr[ui]
    ok = (e < len(b15["ts"])) & np.isfinite(a) & (a > 0)
    ok[ok] &= b15["ts"][e[ok]] == ts[ui[ok]] + step_ns
    ui, us, e, a = ui[ok], us[ok], e[ok], a[ok]
    raw = b15["o"][e]
    sz = sizer(coin)
    ll = np.array([sz(int(s_), float(x)) for s_, x in zip(us, a / raw)]).reshape(-1, 2)
    lev = ll[:, 0].astype(float)
    liq_frac = ll[:, 1]
    feasible = lev > 0
    # infeasible: ladder at 20x, liquidation ignored (sensitivity only)
    lev_s = np.where(feasible, lev, 20.0)
    liq_s = np.where(feasible, liq_frac, 10.0)
    f_bar = FUNDING_8H * 15 / 480.0
    res = {k: np.full(len(e), np.nan) for k in ("x", "R", "gross", "roe", "reason", "fill", "risk")}
    todo = np.arange(len(e))
    for H in (96, 768, 6144, 49152):
        if not len(todo):
            break
        nxt = []
        step = max(16, 400_000 // H)
        for c0 in range(0, len(todo), step):
            sel = todo[c0:c0 + step]
            r = scan(b15, e[sel], us[sel], lev_s[sel], liq_s[sel], a[sel], H, f_bar)
            keep = r["done"] | (H == 49152) | (e[sel] + H >= len(b15["ts"]))
            for k in res:
                res[k][sel[keep]] = r[k][keep]
            nxt.append(sel[~keep])
        todo = np.concatenate(nxt) if nxt else np.zeros(0, int)
    key_u = ui.astype(np.int64) * 2 + (us > 0)
    out = dict(i=ui.astype(np.int32), side=us.astype(np.int8), e=e.astype(np.int32), lev=lev.astype(np.int8),
               feasible=feasible, atr_frac=(a / raw).astype(np.float32),
               x=res["x"].astype(np.int32), R=res["R"].astype(np.float32), gross=res["gross"].astype(np.float32),
               roe=res["roe"].astype(np.float32), reason=res["reason"].astype(np.int8),
               fill=res["fill"], risk=res["risk"], key=key_u)
    # per strategy: positions of its signals in the outcome table
    for nm, (idx, sd) in sigs.items():
        kk = idx.astype(np.int64) * 2 + (sd > 0)
        pos = np.searchsorted(key_u, kk)
        good = (pos < len(key_u))
        good[good] &= key_u[pos[good]] == kk[good]
        out["m__" + nm] = pos[good].astype(np.int32)
    np.savez_compressed(os.path.join(out_dir, f"out_{tf}_{coin}.npz"), **out)
    return tf, coin, len(e), int(feasible.sum()), time.time() - t0


if __name__ == "__main__":
    core_dir, ds_dir, out_dir = sys.argv[1:4]
    procs = int(sys.argv[4]) if len(sys.argv) > 4 else 4
    os.makedirs(out_dir, exist_ok=True)
    jobs = [(tf, c, core_dir, ds_dir, out_dir) for tf in ("15m", "30m", "1h", "4h") for c in COINS]
    with Pool(procs) as p:
        for r in p.imap_unordered(job, jobs):
            print(r, flush=True)
