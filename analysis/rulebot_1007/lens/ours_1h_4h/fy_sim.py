"""5-year every-signal simulation of our 36 strategies at 15m/30m/1h/4h under the CURRENT live rules (paper v4):
quality_v1 "normal" group (30x, else 20x; reject when the stop sits too close to liquidation), 2 ATR stop, ROE ladder
(first lock 10%, step 5%, gap 2%), taker 0.05% + slippage 0.02% per side, funding 0.01%/8h paid by both sides
(as research/strategy_profiles), $5,000 equity, brackets inferred from the live trades (rb_analyze INFERRED_BRACKETS).

    python3 -I fy_sim.py <signals_dir> <rb_analyze_dir> <repo> <out_pickle> [procs]

The exit scan is a copy of research/strategy_profiles/profiles.py::_scan (vectorised ladder exit), unchanged except
for taking the ladder / costs from paperbot.config.v3_settings(). Writes one row per signal (sized or not):
strategy, tf, coin, close_ms (signal bar close), side, atr_frac, lev (0 = sizing rejected), R, roe, reason
(0 stop, 1 lock, 2 liquidation, 3 open at the end), held (bars), entry_ms, exit_ms (close of the exit bar), win (0 IS
2021-08-01..2024-07-01, 1 CF 2024-07-01..2026-09-30).
R = net pnl / (qty x |fill - stop|) = roe x fill / (lev x |fill - stop|), the live pipeline's R.
"""
import os
import site
import sys

sys.dont_write_bytecode = True
sys.path.append(site.getusersitepackages())

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

SIG_DIR, AZ_DIR, REPO, OUT = sys.argv[1:5]
PROCS = int(sys.argv[5]) if len(sys.argv) > 5 else 4
sys.path.insert(0, REPO)
sys.path.insert(0, AZ_DIR)

from paperbot.config import v3_settings  # noqa: E402
from paperbot.ladder import LadderSpec  # noqa: E402
from paperbot.sizing import size_position  # noqa: E402
import analyze as AZ  # noqa: E402  (only make_brackets / INFERRED_BRACKETS)

TFS = ("15m", "30m", "1h", "4h")
TF_MIN = {"15m": 15, "30m": 30, "1h": 60, "4h": 240}
COINS = ("BTCUSD", "ETHUSD", "SOLUSD", "DOGEUSD", "LTCUSD", "BCHUSD")
START, CF_START, END = pd.Timestamp("2021-08-01").value, pd.Timestamp("2024-07-01").value, pd.Timestamp("2026-09-30").value
S = v3_settings()
LAD = LadderSpec(S.ladder_first_lock, S.ladder_step, S.ladder_trigger_gap)
FUNDING_8H = 0.0001
EQUITY = 5000.0
K_STOP = 2.0
BRK = None


def sizer(coin):
    sym = coin + "T"
    cache = {}

    def f(side, atr_frac):
        key = (side, float(f"{atr_frac:.4g}"))
        if key not in cache:
            raw = 100.0
            a = key[1] * raw
            fill = raw * (1 + side * S.slippage_frac)
            d = size_position(S, EQUITY, side, fill, raw - side * K_STOP * a, "normal", BRK[sym], atr=a,
                              min_notional=5.0)
            cache[key] = (d.leverage, side * (fill - d.liq_price) / fill) if d.ok else (0, np.nan)
        return cache[key]
    return f


def _scan(b, idx, side, lev, liq_frac, H, n, f_bar):
    """research/strategy_profiles/profiles.py::_scan (copy)."""
    lad = LAD
    rt, fee, slip = S.round_trip_cost, S.taker_fee, S.slippage_frac
    m = len(idx)
    off = np.arange(1, H + 1)
    J = idx[:, None] + off[None, :]
    valid = J < n
    Jc = np.minimum(J, n - 1)
    o, h, lo, c = b["o"][Jc], b["h"][Jc], b["l"][Jc], b["c"][Jc]
    raw = b["o"][idx + 1]
    a = b["atr"][idx]
    fill = raw * (1 + side * slip)
    stop0 = raw - side * K_STOP * a
    liq = fill * (1 - side * liq_frac)
    s = side[:, None]
    fund = f_bar * off[None, :]
    fav = np.where(s == 1, h, -lo)
    best_px = s * np.maximum.accumulate(np.concatenate([(side * fill)[:, None], fav], axis=1), axis=1)[:, 1:]
    roe_best = lev[:, None] * (s * (best_px / fill[:, None] - 1) - rt - fund)
    first = lad.first_lock + lad.trigger_gap
    nstep = np.floor((roe_best - first) / lad.step + 1e-9)
    lock_roe = np.where(roe_best >= first - 1e-12, lad.first_lock + lad.step * nstep, np.nan)
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
    return dict(done=done, held=held, roe=roe, reason=reason, fill=fill, stop0=stop0)


def job(args):
    tf, coin = args
    z = np.load(os.path.join(SIG_DIR, f"sig_{tf}_{coin}.npz"))
    b = {k: z[k] for k in ("ts", "o", "h", "l", "c", "atr")}
    n = len(b["ts"])
    tfms = TF_MIN[tf] * 60_000
    f_bar = FUNDING_8H * TF_MIN[tf] / 480.0
    lo_all = int(np.searchsorted(b["ts"], START, "left"))
    n_end = int(np.searchsorted(b["ts"], END, "left"))
    sz = sizer(coin)
    frames = []
    for key in (k for k in z.files if k.startswith("s__")):
        name = key[3:]
        sg = z[key]
        idx = np.nonzero(sg[lo_all:n_end - 1])[0] + lo_all
        a = b["atr"][idx]
        ok = np.isfinite(a) & (a > 0) & np.isfinite(b["o"][np.minimum(idx + 1, n - 1)])
        idx = idx[ok]
        if not len(idx):
            continue
        side = sg[idx].astype(int)
        raw = b["o"][idx + 1]
        afr = b["atr"][idx] / raw
        ll = np.array([sz(int(s_), float(x)) for s_, x in zip(side, afr)]).reshape(-1, 2)
        lev, liq_frac = ll[:, 0].astype(float), ll[:, 1]
        sized = lev > 0
        res = {k: np.full(len(idx), np.nan) for k in ("held", "roe", "reason", "fill", "stop0")}
        todo = np.nonzero(sized)[0]
        for H in (64, 512, 4096):
            if not len(todo):
                break
            nxt = []
            step = max(32, 256_000 // H)
            for c0 in range(0, len(todo), step):
                sel = todo[c0:c0 + step]
                r = _scan(b, idx[sel], side[sel], lev[sel], liq_frac[sel], H, n, f_bar)
                last = H == 4096
                keep = r["done"] | last | (idx[sel] + H >= n - 1)
                for k in res:
                    res[k][sel[keep]] = r[k][keep]
                nxt.append(sel[~keep])
            todo = np.concatenate(nxt) if nxt else np.zeros(0, int)
        dist = np.abs(res["fill"] - res["stop0"])
        R = res["roe"] * res["fill"] / (lev * dist)
        R[~sized] = np.nan
        held = res["held"]
        exit_j = np.where(sized, idx + np.nan_to_num(held, nan=0).astype(int), idx)
        exit_j = np.minimum(exit_j, n - 1)
        close_ms = (b["ts"][idx] // 1_000_000) + tfms
        frames.append(pd.DataFrame({
            "strategy": name, "tf": tf, "coin": coin, "idx": idx.astype(np.int32), "close_ms": close_ms,
            "side": side.astype(np.int8), "atr_frac": afr.astype(np.float32), "lev": lev.astype(np.int16),
            "R": R.astype(np.float32), "roe": res["roe"].astype(np.float32),
            "reason": np.nan_to_num(res["reason"], nan=-1).astype(np.int8),
            "held": np.nan_to_num(held, nan=0).astype(np.int32),
            "entry_ms": close_ms, "exit_ms": np.where(sized, (b["ts"][exit_j] // 1_000_000) + tfms, close_ms),
            "win": (b["ts"][idx] >= CF_START).astype(np.int8)}))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def main():
    global BRK
    BRK, _ = AZ.make_brackets(None)
    from multiprocessing import Pool
    jobs = [(tf, c) for tf in TFS for c in COINS]
    with Pool(PROCS) as p:
        parts = p.map(job, jobs)
    D = pd.concat(parts, ignore_index=True)
    for c in ("strategy", "tf", "coin"):
        D[c] = D[c].astype("category")
    D.to_pickle(OUT)
    print(D.groupby(["tf"], observed=True).agg(n=("R", "size"), sized=("lev", lambda x: (x > 0).mean()),
                                               meanR=("R", "mean")))


if __name__ == "__main__":
    BRK, _ = AZ.make_brackets(None)
    main()
