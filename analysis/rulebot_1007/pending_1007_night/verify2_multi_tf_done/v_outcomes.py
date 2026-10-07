"""Independent re-implementation (verifier): every signal of a strategy subset run ALONE under the house exits,
own ATR (Wilder 14 on native tf bars), own liquidation / sizing math, own bar loop on 15m bars.
python3 -I -B v_outcomes.py <sig_dir> <ds_dir> <out_npz>
"""
import os, sys
sys.path[:0] = ['/root/.local/lib/python3.11/site-packages']
import numpy as np, pandas as pd
from multiprocessing import Pool

COINS = ("BTCUSD", "ETHUSD", "SOLUSD", "DOGEUSD", "LTCUSD", "BCHUSD")
TFS = ("15m", "30m", "1h", "4h"); TFMIN = (15, 30, 60, 240)
CORE = ("N01_ST_EMA", "N02_ST_KST", "DOGE", "S2_ST_ROC", "N20_EMA9_CHOP", "OBV_S")
DS = ("F5_BOX", "F11_RAID")
START, END = pd.Timestamp("2023-10-01").value, pd.Timestamp("2026-09-29").value
FEE, SLIP, RT = 0.0005, 0.0002, 0.0014
FB = 0.0001 * 15 / 480
EQ = 5000.0
# (notional cap, max lev, mmr, cum) - live-inferred brackets (same input as the study; not re-derived)
BRK = {"BTCUSD": [(1e12, 50, 0.004, 0.0)], "ETHUSD": [(1e12, 50, 0.004, 0.0)],
       "SOLUSD": [(50_000, 50, 0.005, 0.0), (1e12, 50, 0.0065, 75.0)],
       "DOGEUSD": [(80_000, 50, 0.0065, 0.0), (1e12, 50, 0.01, 280.0)],
       "BCHUSD": [(10_000, 50, 0.005, 0.0), (100_000, 50, 0.01, 50.0), (1e12, 40, 0.0125, 300.0)],
       "LTCUSD": [(10_000, 50, 0.005, 0.0), (50_000, 50, 0.01, 50.0), (1e12, 40, 0.015, 300.0)]}


def bracket(coin, notional):
    for cap, ml, mmr, cum in BRK[coin]:
        if notional <= cap:
            return ml, mmr, cum
    return BRK[coin][-1][1:]


def size(coin, side, raw, atr, levs=(30, 20), buf_atr=1.0):
    """Own implementation of: margin = L% of equity, bracket, stop inside liq by max(buf ATR, 0.2%), loss<=15%."""
    fill = raw * (1 + side * SLIP)
    stop = raw - side * 2 * atr
    for L in levs:
        margin = EQ * L / 100.0
        notional = margin * L
        q = notional / fill
        ml, mmr, cum = bracket(coin, notional)
        if L > ml:
            continue
        # isolated: equity at liq = maintenance -> margin + side*q*(p-fill) = q*p*mmr - cum
        liq = (margin + cum - side * q * fill) / (q * mmr - side * q)
        room = side * (stop - liq)
        if room < max(buf_atr * atr, 0.002 * fill):
            continue
        ex = stop * (1 - side * SLIP)
        loss = q * abs(fill - ex) + FEE * q * (fill + ex)
        if loss > 0.15 * EQ:
            continue
        return L, liq
    return 0, np.nan


def wilder_atr(h, l, c, n=14):
    pc = np.concatenate([[np.nan], c[:-1]])
    tr = np.nanmax(np.vstack([h - l, np.abs(h - pc), np.abs(l - pc)]), axis=0)
    a = np.full(len(tr), np.nan)
    a[n - 1] = tr[:n].mean()
    for i in range(n, len(tr)):
        a[i] = (a[i - 1] * (n - 1) + tr[i]) / n
    return a


def run_one(o, h, l, c, e, side, atr, lev, liq):
    raw = o[e]; fill = raw * (1 + side * SLIP); stop0 = raw - side * 2 * atr
    risk = abs(fill - stop0)
    st = stop0; best = fill; n = len(o); k = e
    while True:
        if k >= n:
            k = n - 1; exr = c[k]; reason = 3; break
        adv = l[k] if side == 1 else h[k]
        if side * (adv - st) <= 0:
            if side * (o[k] - st) <= 0:  # gap through the stop at the open
                if side * (o[k] - liq) <= 0:
                    held = k - e + 1
                    return -1.0 * fill / (lev * risk) * 1.0, side * (o[k] - raw) / risk, k, 2
                exr = o[k]
            else:
                exr = st
            reason = 1 if side * (st - stop0) > 1e-12 else 0
            break
        fav = h[k] if side == 1 else l[k]
        if side * (fav - best) > 0:
            best = fav
        fund = FB * (k - e + 1)
        roe_b = lev * (side * (best / fill - 1) - RT - fund)
        if roe_b >= 0.12 - 1e-12:
            lk = 0.10 + 0.05 * np.floor((roe_b - 0.12) / 0.05 + 1e-9)
            px = fill * (1 + side * (lk / lev + RT + fund))
            if side * (px - st) > 0:
                st = px
        k += 1
    held = k - e + 1
    ex = exr * (1 - side * SLIP)
    roe = lev * (side * (ex / fill - 1) - FEE * (1 + ex / fill) - FB * held)
    roe = max(roe, -1.0)
    return roe * fill / (lev * risk), side * (exr - raw) / risk, k, reason


def job(args):
    sig_dir, ds_dir, tfi, coin = args
    tf = TFS[tfi]
    z15 = np.load(os.path.join(sig_dir, f"sig_15m_{coin}.npz"))
    ts15, o, h, l, c = (z15[k] for k in ("ts", "o", "h", "l", "c"))
    z = np.load(os.path.join(sig_dir, f"sig_{tf}_{coin}.npz"))
    zd = np.load(os.path.join(ds_dir, f"ds_{tf}_{coin}.npz"))
    ts = z["ts"]
    atr = wilder_atr(z["h"], z["l"], z["c"])
    their = z["atr"]
    mm = np.isfinite(atr) & np.isfinite(their) & (np.arange(len(ts)) > 200)
    atr_dev = float(np.nanmax(np.abs(atr[mm] / their[mm] - 1)))
    step = TFMIN[tfi] * 60 * 10**9
    win = (ts >= START) & (ts < END)
    rows = []
    for nm in CORE + DS:
        src = z if nm in CORE else zd
        key = "s__" + nm
        if key not in src.files:
            continue
        s = src[key]
        idx = np.nonzero((s != 0) & win)[0]
        for i in idx:
            side = int(np.sign(s[i]))
            e = int(np.searchsorted(ts15, ts[i] + step))
            if e >= len(ts15) or ts15[e] != ts[i] + step or not np.isfinite(atr[i]):
                continue
            raw = o[e]
            lev, liq = size(coin, side, raw, atr[i])
            feas = lev > 0
            if not feas:  # sensitivity only: 20x ladder, liquidation ignored
                levu, liqu = 20, -side * 1e18
            else:
                levu, liqu = lev, liq
            R, g, x, rs = run_one(o, h, l, c, e, side, atr[i], levu, liqu)
            rows.append((nm, tfi, COINS.index(coin), e, side, R, g, x, rs, lev, atr[i] / raw))
    return rows, (tf, coin, atr_dev)


if __name__ == "__main__":
    sig_dir, ds_dir, out = sys.argv[1:4]
    jobs = [(sig_dir, ds_dir, t, c) for t in range(4) for c in COINS]
    allr = []
    with Pool(4) as p:
        for rows, info in p.imap_unordered(job, jobs):
            allr += rows
            print(info, len(rows), flush=True)
    d = pd.DataFrame(allr, columns=["strat", "tf", "coin", "e", "side", "R", "gross", "x", "reason", "lev", "atr_frac"])
    d.to_parquet(out) if out.endswith(".parquet") else d.to_csv(out, index=False)
