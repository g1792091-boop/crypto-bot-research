"""Independent 5-year every-signal simulation (verifier's own code; a per-signal bar loop, not the vectorised scan).

    python3 -I vsim.py <sig_dir> <repo> <out_pkl> <res: tf|5m> <tfs comma> <variants 0|1> [procs]

Rules (paperbot.config.v3_settings(), paper v4): sizing paperbot.sizing.size_position group "normal" (30x/30%,
else 20x/20%), equity $5,000, brackets = rb_analyze INFERRED_BRACKETS (copied below), min notional 5.
Entry at the next bar's open + slippage; stop 2 x ATR14 (signal bar) from the raw open; ROE ladder
(paperbot.ladder.LadderSpec semantics: lock applies from the next bar; stop checked before the bar's favourable move);
gap through the stop fills at the open; gap through the liquidation price = ROE -1. Costs: taker 0.05% per side,
slippage 0.02% per side, funding 0.01% per 8 h paid by both sides (research convention).
res = tf: exits on the signal timeframe's own bars (the repo's 5-year method).
res = 5m: exits on 5-minute bars (closer to the live 1-minute engine) for the same signals.
Variants (only when asked): lev10 (10x, same ROE ladder), lock30 (first lock 30%), tp1R / tp2R (fixed TP at 1R / 2R,
no ladder, stop first on a two-sided bar), all in R units of the base stop distance.
R = roe * fill / (lev * |fill - stop0|). gross_R = side * (exit_raw - raw) / |fill - stop0| (fees, slippage and
funding added back; the exit price itself is unchanged).
"""
import math
import os
import site
import sys

sys.dont_write_bytecode = True
sys.path.append(site.getusersitepackages())
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

SIG, REPO, OUT, RES, TFS, VAR = sys.argv[1:7]
TFS = TFS.split(",")
VAR = VAR == "1"
PROCS = int(sys.argv[7]) if len(sys.argv) > 7 else 4
sys.path.insert(0, REPO)
from paperbot.config import v3_settings  # noqa: E402
from paperbot.margin import BracketTier, Brackets, liquidation_price  # noqa: E402
from paperbot.sizing import size_position  # noqa: E402

INFERRED_BRACKETS = {
    "BTCUSDT": [(1e12, 50, 0.004, 0.0)],
    "ETHUSDT": [(1e12, 50, 0.004, 0.0)],
    "SOLUSDT": [(50_000, 50, 0.005, 0.0), (1e12, 50, 0.0065, 75.0)],
    "DOGEUSDT": [(80_000, 50, 0.0065, 0.0), (1e12, 50, 0.01, 280.0)],
    "BCHUSDT": [(10_000, 50, 0.005, 0.0), (100_000, 50, 0.01, 50.0), (1e12, 40, 0.0125, 300.0)],
    "LTCUSDT": [(10_000, 50, 0.005, 0.0), (50_000, 50, 0.01, 50.0), (1e12, 40, 0.015, 300.0)],
}
BRK = {s: Brackets([BracketTier(*t) for t in tiers]) for s, tiers in INFERRED_BRACKETS.items()}
S = v3_settings()
FEE, SLIP, RT = S.taker_fee, S.slippage_frac, S.round_trip_cost
FIRST, STEP, GAP = S.ladder_first_lock, S.ladder_step, S.ladder_trigger_gap
TFMIN = {"15m": 15, "30m": 30, "1h": 60, "4h": 240}
COINS = ("BTCUSD", "ETHUSD", "SOLUSD", "DOGEUSD", "LTCUSD", "BCHUSD")
START = pd.Timestamp("2021-08-01").value
CF = pd.Timestamp("2024-07-01").value
END = pd.Timestamp("2026-09-30").value
EQ = 5000.0


def sim(o, h, l, c, j0, nb, side, raw, a, lev, liq, fbar, first, tpR, maxb):
    """One trade. Returns (R, gross_R, roe, reason, bars_held, exit_j, mfeR). reason 0 stop 1 lock 2 liq 3 open/tp=4."""
    fill = raw * (1 + side * SLIP)
    stop0 = raw - side * 2.0 * a
    dist = abs(fill - stop0)
    stop = stop0
    best = fill
    tp = fill + side * tpR * dist if tpR else None
    k = 0
    j = j0
    reason = 3
    exit_raw = None
    liqx = False
    while True:
        if j >= nb or k >= maxb:
            j = min(j, nb) - 1
            exit_raw = c[j]
            reason = 3
            break
        k += 1
        oj, hj, lj = o[j], h[j], l[j]
        if side == 1:
            if lj <= stop:
                if oj <= stop:
                    exit_raw = oj
                    liqx = oj <= liq
                else:
                    exit_raw = stop
                reason = 2 if liqx else (1 if stop > stop0 + 1e-12 else 0)
                break
            fav = hj
        else:
            if hj >= stop:
                if oj >= stop:
                    exit_raw = oj
                    liqx = oj >= liq
                else:
                    exit_raw = stop
                reason = 2 if liqx else (1 if stop < stop0 - 1e-12 else 0)
                break
            fav = lj
        if tp is not None:
            if side * fav >= side * tp:
                exit_raw = oj if side * oj >= side * tp else tp
                reason = 4
                break
        else:
            if side * fav > side * best:
                best = fav
            rb = lev * (side * (best / fill - 1) - RT - fbar * k)
            if rb >= first + GAP - 1e-12:
                lk = first + STEP * math.floor((rb - first - GAP) / STEP + 1e-9)
                lp = fill * (1 + side * (lk / lev + RT + fbar * k))
                if side * lp > side * stop:
                    stop = lp
        if tp is not None and side * fav > side * best:
            best = fav
        j += 1
    exit_px = exit_raw * (1 - side * SLIP)
    roe = lev * (side * (exit_px / fill - 1) - FEE * (1 + exit_px / fill) - fbar * k)
    roe = -1.0 if liqx else max(roe, -1.0)
    R = roe * fill / (lev * dist)
    gR = side * (exit_raw - raw) / dist
    return R, gR, roe, reason, k, j, side * (best - fill) / dist


def job(arg):
    tf, coin = arg
    z = np.load(os.path.join(SIG, f"sig_{tf}_{coin}.npz"))
    ts = z["ts"]
    O, H, L, C, A = (z[k] for k in ("o", "h", "l", "c", "atr"))
    n = len(ts)
    tfms = TFMIN[tf] * 60_000
    if RES == "5m":
        f5 = np.load(os.path.join(SIG, f"sig_5m_{coin}.npz"))
        t5 = f5["ts"]
        o, h, l, c = (f5[k].tolist() for k in ("o", "h", "l", "c"))
        fbar = 0.0001 * 5 / 480.0
        maxb = 200_000
        nb = len(t5)
    else:
        o, h, l, c = O.tolist(), H.tolist(), L.tolist(), C.tolist()
        fbar = 0.0001 * TFMIN[tf] / 480.0
        maxb = 4096
        nb = n
    sym = coin + "T"
    lo = int(np.searchsorted(ts, START))
    hi = int(np.searchsorted(ts, END))
    rows = []
    cache = {}
    for key in [k for k in z.files if k.startswith("s__")]:
        strat = key[3:]
        sg = z[key]
        for i in np.nonzero(sg[lo:hi - 1])[0] + lo:
            i = int(i)
            if i + 1 >= n:
                continue
            a = float(A[i])
            raw = float(O[i + 1])
            if not (a > 0 and math.isfinite(a) and math.isfinite(raw)):
                continue
            side = int(sg[i])
            fill = raw * (1 + side * SLIP)
            stop0 = raw - side * 2.0 * a
            d = size_position(S, EQ, side, fill, stop0, "normal", BRK[sym], atr=a, min_notional=5.0)
            row = dict(strategy=strat, tf=tf, coin=coin, idx=i, close_ms=int(ts[i] // 1_000_000) + tfms, side=side,
                       atr_frac=a / raw, lev=d.leverage if d.ok else 0, win=int(ts[i] >= CF))
            if not d.ok:
                rows.append(row)
                continue
            lev = float(d.leverage)
            liq = d.liq_price
            if RES == "5m":
                j0 = int(np.searchsorted(t5, ts[i + 1]))
                if j0 >= nb or t5[j0] != ts[i + 1]:
                    row["lev"] = -1     # no aligned 5m bar: left out
                    rows.append(row)
                    continue
            else:
                j0 = i + 1
            R, gR, roe, rsn, k, je, mfe = sim(o, h, l, c, j0, nb, side, raw, a, lev, liq, fbar, FIRST, None, maxb)
            row.update(R=R, gross_R=gR, roe=roe, reason=rsn, held=k, mfe_R=mfe,
                       exit_ms=(int(t5[je] // 1_000_000) + 300_000) if RES == "5m" else int(ts[je] // 1_000_000) + tfms)
            if VAR:
                # lev10: 10x at the same margin fraction (20%): liquidation from the bracket formula
                qty = EQ * 0.2 * 10 / fill
                liq10 = liquidation_price(side, qty, fill, EQ * 0.2, BRK[sym].for_notional(qty * fill))
                row["R_lev10"] = sim(o, h, l, c, j0, nb, side, raw, a, 10.0, liq10, fbar, FIRST, None, maxb)[0]
                row["R_lock30"] = sim(o, h, l, c, j0, nb, side, raw, a, lev, liq, fbar, 0.30, None, maxb)[0]
                row["R_tp1R"] = sim(o, h, l, c, j0, nb, side, raw, a, lev, liq, fbar, FIRST, 1.0, maxb)[0]
                row["R_tp2R"] = sim(o, h, l, c, j0, nb, side, raw, a, lev, liq, fbar, FIRST, 2.0, maxb)[0]
            rows.append(row)
    return pd.DataFrame(rows)


def main():
    from multiprocessing import Pool
    jobs = [(tf, c) for tf in TFS for c in COINS]
    with Pool(PROCS) as p:
        parts = p.map(job, jobs, chunksize=1)
    D = pd.concat(parts, ignore_index=True)
    for k in ("strategy", "tf", "coin"):
        D[k] = D[k].astype("category")
    D.to_pickle(OUT)
    ok = D[D.lev > 0]
    print(ok.groupby("tf", observed=True).agg(n=("R", "size"), R=("R", "mean"), gR=("gross_R", "mean")))
    print("all signals", D.groupby("tf", observed=True).size().to_dict())


if __name__ == "__main__":
    main()
