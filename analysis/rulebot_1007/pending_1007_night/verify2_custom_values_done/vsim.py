"""Independent re-simulation (own loop engine + own filters) on a random sample of signals from the analyst's
cells files; compares outcomes, default-signal parity with the locked cache, and filter flags.
usage: python3 -I vsim.py <scratchpad>"""
import sys, os, json
sys.path.append("/root/.local/lib/python3.11/site-packages")
import numpy as np
import pandas as pd

SCR = sys.argv[1]
CELLS = os.path.join(SCR, "lens2/custom_values/work/cells")
SIG = os.path.join(SCR, "binance/signals")
COINS = ("BTCUSD", "ETHUSD", "SOLUSD", "DOGEUSD", "LTCUSD", "BCHUSD")
TAKER, SLIP = 0.0005, 0.0002
RT = 2 * (TAKER + SLIP)
STOPS, EXITS = (1.5, 2.0, 2.5), ("house", "rladder", "tp15be")
FAM = {"S2_ST_ROC": "trend", "N17_KC_RSI": "mr", "OBV_B": "trend", "F5_BOX": "mr"}
TFMIN = 15
FBAR = 0.0001 * TFMIN / 480.0


def sim(o, h, l, c, i, side, atr, k, mode):
    n = len(o)
    if i + 1 >= n:
        return None
    raw = o[i + 1]
    fill = raw * (1 + side * SLIP)
    d = k * atr
    stop0 = raw - side * d
    tp = raw + side * 1.5 * d if mode == "tp15be" else None
    lock = None  # price level (side-oriented compare)
    best = fill  # best favourable price so far (long: max high, short: min low)
    for q in range(1, 4097):
        j = i + q
        if j >= n:
            return None
        st = stop0
        if lock is not None and side * lock > side * st:
            st = lock
        adverse_hit = (l[j] <= st) if side == 1 else (h[j] >= st)
        if adverse_hit:
            ex = o[j] if side * o[j] <= side * st else st
            return finish(raw, fill, ex, side, q, d)
        if tp is not None and ((h[j] >= tp) if side == 1 else (l[j] <= tp)):
            return finish(raw, fill, tp, side, q, d)
        best = max(best, h[j]) if side == 1 else min(best, l[j])
        if mode == "house":
            roe = 20 * (side * (best / fill - 1) - RT - FBAR * q)
            if roe >= 0.12 - 1e-12:
                lr = 0.10 + 0.05 * np.floor((roe - 0.12) / 0.05 + 1e-9)
                nl = fill * (1 + side * (lr / 20 + RT + FBAR * q))
                if lock is None or side * nl > side * lock:
                    lock = nl
        else:
            mfe = side * (best - raw) / d
            if mfe >= 1 - 1e-12:
                if mode == "rladder":
                    nl = raw + side * (0.5 + 0.5 * np.floor((mfe - 1) / 0.5 + 1e-9)) * d
                else:
                    nl = fill
                if lock is None or side * nl > side * lock:
                    lock = nl
    return None


def finish(raw, fill, ex, side, held, d):
    exf = ex * (1 - side * SLIP)
    pnl = side * (exf - fill) - TAKER * (fill + exf) - FBAR * held * fill
    return pnl / abs(fill - (raw - side * d)), pnl / fill, held


def wilder(x, n):
    out = np.full(len(x), np.nan)
    x = np.asarray(x, float)
    s = np.nan
    for t in range(len(x)):
        if np.isnan(x[t]):
            continue
        if np.isnan(s):
            # seed with SMA of first n valid values
            if t >= n - 1 and not np.isnan(x[t - n + 1:t + 1]).any():
                s = x[t - n + 1:t + 1].mean()
                out[t] = s
            continue
        s = s + (x[t] - s) / n
        out[t] = s
    return out


def my_adx(h, l, c, n=14):
    up = np.r_[np.nan, h[1:] - h[:-1]]
    dn = np.r_[np.nan, l[:-1] - l[1:]]
    pdm = np.where((up > dn) & (up > 0), up, 0.0)
    mdm = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = np.r_[np.nan, np.maximum.reduce([h[1:] - l[1:], abs(h[1:] - c[:-1]), abs(l[1:] - c[:-1])])]
    pdm[0] = mdm[0] = np.nan
    atr = wilder(tr, n)
    pdi = 100 * wilder(pdm, n) / atr
    mdi = 100 * wilder(mdm, n) / atr
    dx = 100 * abs(pdi - mdi) / (pdi + mdi)
    return wilder(dx, n)


def my_filters(b, fam):
    ts = b["ts"]
    c = b["c"]
    s = pd.Series(c, index=pd.to_datetime(ts))
    hc = s.resample("1h").last().dropna()
    hema = hc.ewm(span=50, adjust=False).mean()
    hend = (hc.index + pd.Timedelta("1h")).asi8
    bclose = ts + TFMIN * 60 * 10**9
    j = np.searchsorted(hend, bclose, side="right") - 1
    hcl = np.where(j >= 0, hc.values[np.maximum(j, 0)], np.nan)
    hem = np.where(j >= 0, hema.values[np.maximum(j, 0)], np.nan)
    adx = my_adx(b["h"], b["l"], c)
    hi = pd.Series(b["h"]).rolling(48).max().shift(1).values
    lo = pd.Series(b["l"]).rolling(48).min().shift(1).values
    pos = (c - lo) / (hi - lo)
    hour = (ts // (3600 * 10**9)) % 24
    sess = (hour >= 7) & (hour <= 20)
    if fam == "trend":
        return dict(htf=(hcl > hem, hcl < hem), adx=(adx >= 20, adx >= 20), box=(pos >= .5, pos <= .5), session=(sess, sess))
    return dict(htf=(hcl > hem, hcl < hem), adx=(adx < 25, adx < 25), box=(pos <= .3, pos >= .7), session=(sess, sess))


rng = np.random.default_rng(7)
res = {}
for name, fam in FAM.items():
    z = np.load(os.path.join(CELLS, f"{name}_15m.npz"))
    a = {k: z[k] for k in z.files}
    out = {"default_parity_mismatch": 0, "default_parity_checked": 0}
    pick = rng.choice(len(a["ts"]), 500, replace=False)
    dR, dP, dnm, fagree = [], [], 0, np.zeros(4)
    fn = 0
    late_fagree = np.zeros(4); late_n = 0
    for ci, coin in enumerate(COINS):
        zb = np.load(os.path.join(SIG, f"sig_15m_{coin}.npz"))
        b = {k: zb[k] for k in ("ts", "o", "h", "l", "c", "atr")}
        m = a["coin"] == ci
        if f"s__{name}" in zb.files:
            ref = zb[f"s__{name}"].astype(int)
            start = np.searchsorted(b["ts"], np.datetime64("2021-02-01", "ns").astype(np.int64))
            ok = np.zeros(len(ref), bool); ok[start:len(ref) - 1] = True
            ok &= np.isfinite(b["atr"]) & (b["atr"] > 0)
            refi = np.flatnonzero((ref != 0) & ok)
            mine = a["idx"][m & a["pmask"][:, 0]]
            sd = a["side"][m & a["pmask"][:, 0]]
            out["default_parity_checked"] += len(refi)
            out["default_parity_mismatch"] += int(len(set(zip(refi.tolist(), ref[refi].tolist())) ^ set(zip(mine.tolist(), sd.tolist()))))
        fl = my_filters(b, fam)
        for r in pick[a["coin"][pick] == ci]:
            i, sd = int(a["idx"][r]), int(a["side"][r])
            for f_i, f in enumerate(("htf", "adx", "box", "session")):
                lg, sh = fl[f]
                mine = bool(lg[i] if sd == 1 else sh[i])
                fagree[f_i] += mine == bool(a["fmask"][r, f_i])
                if a["ts"][r] > np.datetime64("2021-06-01", "ns").astype(np.int64):
                    late_fagree[f_i] += mine == bool(a["fmask"][r, f_i])
            fn += 1
            if a["ts"][r] > np.datetime64("2021-06-01", "ns").astype(np.int64):
                late_n += 1
            for si, k in enumerate(STOPS):
                for xi, mode in enumerate(EXITS):
                    jj = si * 3 + xi
                    s = sim(b["o"], b["h"], b["l"], b["c"], i, sd, b["atr"][i], k, mode)
                    if s is None or not a["done"][r, jj]:
                        dnm += int((s is None) != (not a["done"][r, jj]))
                        continue
                    dR.append(s[0] - a["rnet"][r, jj]); dP.append(s[1] - a["npct"][r, jj])
    dR, dP = np.abs(np.array(dR)), np.abs(np.array(dP))
    out.update(sample=500, outcomes_compared=len(dR), done_mismatch=dnm, max_abs_dR=float(dR.max()),
               share_dR_gt_1e3=float((dR > 1e-3).mean()), max_abs_dnetpct=float(dP.max()),
               filter_agree_share=dict(zip(("htf", "adx", "box", "session"), (fagree / fn).round(4).tolist())),
               filter_agree_after_jun2021=dict(zip(("htf", "adx", "box", "session"), (late_fagree / max(late_n, 1)).round(4).tolist())))
    res[name] = out
    print(name, out, flush=True)
json.dump(res, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "vsim.json"), "w"), indent=1)
