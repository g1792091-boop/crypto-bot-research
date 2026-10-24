"""Verifier (lens: costs, executability, overlap) of the obvstoch claim about the friend-family 19-day winner
OBV30@4h > SRSI_X@1h | a2 (OBV30 trend on the last closed 4h bar, Stoch RSI(14,14,3,3) K crossing up 20 / down 80 on 1h,
2 x ATR14(1h) stop + ladder 12->10 then 5 %, 30x).

Independent of the study's cache (which is gone): OBV, SMA, RSI, Stoch RSI re-implemented here; the a2 exits are
re-walked here with frloss.walk2 at the cell's entries only, under several cost / funding / delay / liquidation
assumptions. Outcomes of the shared grid are used only as a cross-check of my cost-x1 walk.
Writes vcx_rows.csv.gz (one row per signal, all variants) and vcx_summary.json in this folder.

    python3 vcx.py
"""
import os
import sys
import json

sys.path.insert(0, "/home/user/crypto-bot-research/analysis/review1024/roles/data")
import rolesdata as RD                      # noqa: E402
from common import *                        # noqa: E402,F401,F403
from frloss import walk2                    # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
LEV = 30.0
WARM = 300
PER = {"PRE": (ms("2020-03-01"), ms("2021-01-01")), "SEL": (ms("2021-01-01"), ms("2024-01-01")),
       "CONF": (ms("2024-01-01"), GRID_END), "FWD": (ms("2026-10-05 15:00"), ms("2026-10-24 15:00")),
       "FIVE": (ms("2020-03-01"), GRID_END)}


# ------------------------------------------------------------------ my own indicators
def sma(x, n):
    x = np.asarray(x, float)
    out = np.full(len(x), np.nan)
    if len(x) < n:
        return out
    c = np.cumsum(np.r_[0.0, np.nan_to_num(x)])
    fin = np.cumsum(np.r_[0, np.isfinite(x).astype(int)])
    s = (c[n:] - c[:-n]) / n
    ok = (fin[n:] - fin[:-n]) == n
    out[n - 1:] = np.where(ok, s, np.nan)
    return out


def rma(x, n):
    x = np.asarray(x, float)
    out = np.full(len(x), np.nan)
    fin = np.isfinite(x)
    run = 0
    s = -1
    for i in range(len(x)):
        run = run + 1 if fin[i] else 0
        if run >= n:
            s = i
            break
    if s < 0:
        return out
    out[s] = x[s - n + 1:s + 1].mean()
    a = 1.0 / n
    for i in range(s + 1, len(x)):
        out[i] = a * x[i] + (1 - a) * out[i - 1] if np.isfinite(x[i]) else out[i - 1]
    return out


def rsi(c, n=14):
    d = np.r_[np.nan, np.diff(c)]
    up = np.where(d > 0, d, 0.0)
    dn = np.where(d < 0, -d, 0.0)
    up[0] = dn[0] = np.nan
    au, ad = rma(up, n), rma(dn, n)
    with np.errstate(divide="ignore", invalid="ignore"):
        r = np.where(ad == 0, 100.0, np.where(au == 0, 0.0, 100 - 100 / (1 + au / ad)))
    return np.where(np.isfinite(au) & np.isfinite(ad), r, np.nan)


def roll(x, n, f):
    s = pd.Series(x)
    return getattr(s.rolling(n, min_periods=n), f)().to_numpy()


def stochrsi_k(c):
    r = rsi(c, 14)
    lo, hi = roll(r, 14, "min"), roll(r, 14, "max")
    rng = hi - lo
    with np.errstate(divide="ignore", invalid="ignore"):
        raw = np.where(rng != 0, 100 * (r - lo) / rng, 0.0)
    raw = np.where(np.isfinite(rng), raw, np.nan)
    k = sma(raw, 3)
    return k


def obv(c, v):
    ch = np.r_[0.0, np.diff(c)]
    return np.cumsum(np.sign(ch) * np.nan_to_num(v))


# ------------------------------------------------------------------ signals of the cell
def cell_signals(coin):
    b1, b4 = bars(coin, "1h"), bars(coin, "4h")
    c1 = b1.close.to_numpy(float)
    k = stochrsi_k(c1)
    kp = np.r_[np.nan, k[:-1]]
    with np.errstate(invalid="ignore"):
        lg = (k > 20) & (kp <= 20)
        sh = (k < 80) & (kp >= 80) & ~lg
    sig = np.where(lg, 1, np.where(sh, -1, 0)).astype(int)
    sig[:WARM] = 0
    # check vs the locked library's stoch_rsi_kd
    pi = libs()["pi"]
    kl, _ = pi.stoch_rsi_kd(c1, 14, 14, 3, 3)
    kl = np.asarray(kl, float)
    m = np.isfinite(k) & np.isfinite(kl)
    chk_k = float(np.max(np.abs(k[m] - kl[m]))) if m.any() else np.nan
    chk_k_nan = bool((np.isfinite(k) == np.isfinite(kl)).all())
    c4 = b4.close.to_numpy(float)
    ob = obv(c4, b4.volume.to_numpy(float))
    st = np.sign(ob - sma(ob, 30))
    st = np.where(np.isfinite(st), st, 0).astype(int)
    st[:WARM] = 0
    # compare with the shared state file (c_OBV_S) like the study did
    Z = np.load(os.path.join(OUT, "states", f"{coin}_4h.npz"))
    zs = Z["c_OBV_S"].astype(int)
    zs = np.where(Z["nb"] < WARM, 0, zs)
    chk_st = float((zs == st).mean()) if len(zs) == len(st) else np.nan
    cl4 = b4.ts.to_numpy(np.int64) + 240 * MIN
    t1 = b1.ts.to_numpy(np.int64) + 60 * MIN
    idx = np.searchsorted(cl4, t1, side="right") - 1
    trend = np.where(idx >= 0, st[np.clip(idx, 0, len(st) - 1)], 0)
    m = (sig != 0) & (trend == sig)
    e = (t1[m] - T0) // MIN
    return pd.DataFrame({"coin": COINS.index(coin), "t": t1[m], "e": e, "side": sig[m],
                         "j": (b1.ts.to_numpy(np.int64)[m] - T0) // (60 * MIN)}), {"k_maxabs_vs_lib": chk_k,
                         "k_nan_pattern_same": chk_k_nan, "obv30_state_eq_shared": chk_st}


def fund_stress(g, rate):
    """Funding array with a constant rate at 00/08/16 UTC from 2026-10-01 (where the grid has 0)."""
    f = g["fund"].copy()
    a = (ms("2026-10-01") - T0) // MIN
    idx = np.arange(a, len(f))
    tt = T0 + idx * MIN
    hit = (tt % (8 * HOUR)) == 0
    f[idx[hit]] = rate
    return np.cumsum(f)


def walk_all(coin, S):
    g = grid(coin)
    G = RD._grid(coin)
    n = g["n"]
    o, h, l, c = g["o"], g["h"], g["l"], g["c"]
    cumf = np.cumsum(g["fund"])
    j = S.j.to_numpy(np.int64)
    e = S.e.to_numpy(np.int64)
    assert (e == (j + 1) * 60).all()
    atr = G["atr14_1h"][j]
    out = {"atr14": atr, "atrd": 2.0 * atr / o[e]}
    for lab_, s in (("L", 1), ("S", -1)):
        out[f"grid_{lab_}_r"] = G[f"a2_1h_{lab_}_r"][j].astype(float)
        out[f"grid_{lab_}_k"] = G[f"a2_1h_{lab_}_k"][j].astype(int)
        out[f"grid_{lab_}_w"] = G[f"a2_1h_{lab_}_why"][j].astype(int)
    VAR = {"x1": (COST, cumf, 0, -1.0), "x2": (2 * COST, cumf, 0, -1.0), "x0": (0.0, cumf, 0, -1.0),
           "x1_5": (1.5 * COST, cumf, 0, -1.0),
           "bybit": (2 * (0.00055 + 0.0002), cumf, 0, -1.0),
           "fneg1": (COST, fund_stress(g, -0.0001), 0, -1.0), "fneg3": (COST, fund_stress(g, -0.0003), 0, -1.0),
           "fpos1": (COST, fund_stress(g, 0.0001), 0, -1.0),
           "d1": (COST, cumf, 1, -1.0), "d2": (COST, cumf, 2, -1.0), "d5": (COST, cumf, 5, -1.0)}
    ok = np.isfinite(out["atrd"]) & (e + 5 < n)
    for nm, (cost, cf, dl, rstop) in VAR.items():
        for lab_, s in (("L", 1), ("S", -1)):
            r = np.full(len(e), np.nan)
            k = np.full(len(e), -1)
            w = np.full(len(e), -1)
            if ok.any():
                es = np.ascontiguousarray(e[ok] + dl)
                atrd = np.ascontiguousarray(2.0 * atr[ok] / o[es])
                a = walk2(o, h, l, c, cf, es, s, LEV, cost, FL, STEP, GAP, atrd, rstop, n)
                r[ok], k[ok], w[ok] = a[0], a[1] + dl, a[2]
            out[f"{nm}_{lab_}_r"], out[f"{nm}_{lab_}_k"], out[f"{nm}_{lab_}_w"] = r, k, w
    # liquidation realism: isolated 30x, maintenance margin rate mmr -> liquidation at gross adverse move 1/lev - mmr.
    # walk with the stop at min(2 ATR, liq distance); a stop at the liquidation distance loses the whole margin (-100 %).
    for mmr in (0.005, 0.01):
        liq = 1.0 / LEV - mmr
        for lab_, s in (("L", 1), ("S", -1)):
            r = np.full(len(e), np.nan)
            k = np.full(len(e), -1)
            w = np.full(len(e), -1)
            if ok.any():
                es = np.ascontiguousarray(e[ok])
                ad = 2.0 * atr[ok] / o[es]
                atrd = np.ascontiguousarray(np.minimum(ad, liq))
                a = walk2(o, h, l, c, cumf, es, s, LEV, COST, FL, STEP, GAP, atrd, -1.0, n)
                rr = a[0].copy()
                # ATR stop beyond the liquidation distance -> every stop-out (why 0) is the liquidation
                liq_hit = (ad > liq) & (a[2] == 0)
                rr = np.where(liq_hit, -1.0 / LEV, rr)
                r[ok], k[ok], w[ok] = rr, a[1], np.where(liq_hit, 9, a[2])
            out[f"liq{int(mmr * 1000)}_{lab_}_r"], out[f"liq{int(mmr * 1000)}_{lab_}_k"] = r, k
            out[f"liq{int(mmr * 1000)}_{lab_}_w"] = w
    drop(coin)
    RD._GR.pop(coin, None)
    return out



if __name__ == "__main__":
    rows, checks = [], {}
    for coin in COINS:
        S, chk = cell_signals(coin)
        S = S[S.t >= PER["PRE"][0]].reset_index(drop=True)
        W = walk_all(coin, S)
        for kk, v in W.items():
            S[kk] = v
        checks[coin] = chk
        rows.append(S)
        log(coin, len(S), chk)
    R = pd.concat(rows, ignore_index=True).sort_values(["t", "coin"]).reset_index(drop=True)
    sd = R.side.to_numpy()
    # check my x1 walk against the grid
    for lab_ in ("L", "S"):
        m = np.isfinite(R[f"grid_{lab_}_r"]) & np.isfinite(R[f"x1_{lab_}_r"])
        checks[f"x1_vs_grid_{lab_}_r_maxabs"] = float(np.max(np.abs(R[f"grid_{lab_}_r"][m] - R[f"x1_{lab_}_r"][m])))
        checks[f"x1_vs_grid_{lab_}_k_eq"] = float((R[f"grid_{lab_}_k"][m] == R[f"x1_{lab_}_k"][m]).mean())
    R.to_csv(os.path.join(HERE, "vcx_rows.csv.gz"), index=False, float_format="%.8g")
    json.dump(checks, open(os.path.join(HERE, "vcx_checks.json"), "w"), indent=1, default=float)
    print(json.dumps(checks, indent=1, default=float))
