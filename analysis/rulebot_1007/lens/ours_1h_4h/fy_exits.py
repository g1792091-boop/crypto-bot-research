"""5-year exit / custom-value what-ifs per timeframe for our 36 strategies, on the same signals (paired):
every signal the live sizing accepts (quality_v1 normal, 30x else 20x), re-run with
  base      the live rules (ROE ladder: first lock 10%, step 5%, gap 2%) at the sized leverage
  lock20 / lock30     first lock 20% / 30% ROE (step, gap unchanged)        [as the nightly d3 variants]
  lev10     10x leverage, same ROE ladder (so the lock sits 2-3x further away in price)
  ladderR   the ladder expressed in R instead of ROE: first lock at +0.5R once +0.6R was reached, then +0.25R steps
  tp1R / tp2R  fixed take-profit at 1R / 2R, no ladder (stop first when one bar touches both)
  time64    base, but closed at the close of bar 64 if still open
R is always in units of the base stop distance (|fill - 2 ATR stop|), net of 0.05% taker + 0.02% slippage per side
and funding 0.01%/8h. Paired difference variant - base, SE clustered by UTC day, IS and CF separately.

    python3 -I fy_exits.py <signals_dir> <rb_analyze_dir> <repo> <fy_signals.pkl> <out_csv>
"""
import os
import site
import sys

sys.dont_write_bytecode = True
sys.path.append(site.getusersitepackages())
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

SIG, AZD, REPO, FY, OUT = sys.argv[1:6]
sys.path.insert(0, REPO)
from paperbot.config import v3_settings  # noqa: E402

S = v3_settings()
RT, FEE, SLIP = S.round_trip_cost, S.taker_fee, S.slippage_frac
TF_MIN = {"15m": 15, "30m": 30, "1h": 60, "4h": 240}
DAY = 86_400_000
CF_START = pd.Timestamp("2024-07-01").value // 1_000_000


def scan(b, idx, side, lev, liq_frac, H, n, f_bar, first, step, gap, mode="roe", tpR=None, tmax=None):
    m = len(idx)
    off = np.arange(1, H + 1)
    J = idx[:, None] + off[None, :]
    valid = J < n
    Jc = np.minimum(J, n - 1)
    o, h, lo, c = b["o"][Jc], b["h"][Jc], b["l"][Jc], b["c"][Jc]
    raw = b["o"][idx + 1]
    a = b["atr"][idx]
    fill = raw * (1 + side * SLIP)
    stop0 = raw - side * 2.0 * a
    dist = np.abs(fill - stop0)
    liq = fill * (1 - side * liq_frac)
    s = side[:, None]
    fund = f_bar * off[None, :]
    fav = np.where(s == 1, h, -lo)
    best_px = s * np.maximum.accumulate(np.concatenate([(side * fill)[:, None], fav], axis=1), axis=1)[:, 1:]
    if tpR is None:
        if mode == "roe":
            roe_best = lev[:, None] * (s * (best_px / fill[:, None] - 1) - RT - fund)
            nst = np.floor((roe_best - (first + gap)) / step + 1e-9)
            lock_roe = np.where(roe_best >= first + gap - 1e-12, first + step * nst, np.nan)
            lock_px = fill[:, None] * (1 + s * (lock_roe / lev[:, None] + RT + fund))
        else:   # ladder in R units (net of the round trip, like the ROE ladder)
            r_best = (s * (best_px - fill[:, None]) - (RT + fund) * fill[:, None]) / dist[:, None]
            nst = np.floor((r_best - (first + gap)) / step + 1e-9)
            lock_r = np.where(r_best >= first + gap - 1e-12, first + step * nst, np.nan)
            lock_px = fill[:, None] + s * (lock_r * dist[:, None] + (RT + fund) * fill[:, None])
        lp = np.where(np.isnan(lock_px), -np.inf, s * lock_px)
        lock_cum = np.maximum.accumulate(np.concatenate([np.full((m, 1), -np.inf), lp], axis=1), axis=1)[:, :-1]
        stop_eff = np.maximum((side * stop0)[:, None], lock_cum)
    else:
        stop_eff = np.repeat((side * stop0)[:, None], H, axis=1)
    adverse = np.where(s == 1, lo, -h)
    hit = (adverse <= stop_eff) & valid
    if tpR is not None:
        tp_px = fill + side * tpR * dist
        tph = (fav >= (side * tp_px)[:, None]) & valid & ~hit
    else:
        tph = np.zeros_like(hit)
    if tmax is not None:
        tcut = (off[None, :] >= tmax) & valid
    else:
        tcut = np.zeros_like(hit)
    any_ev = hit | tph | tcut
    done = any_ev.any(axis=1)
    q = np.where(done, any_ev.argmax(axis=1), np.minimum(H, np.maximum(valid.sum(axis=1), 1)) - 1)
    r = np.arange(m)
    is_hit = hit[r, q] & done
    is_tp = tph[r, q] & done & ~is_hit
    st = side * stop_eff[r, q]
    oq = o[r, q]
    gapx = (side * oq) <= (side * st)
    liq_gap = is_hit & gapx & ((side * oq) <= (side * liq))
    exit_raw = np.where(is_hit, np.where(gapx, oq, st), np.where(is_tp, np.where((side * oq) >= (side * tp_px if tpR is not None else 0), oq, tp_px if tpR is not None else 0), c[r, q]))
    exit_px = np.where(liq_gap, liq, exit_raw * (1 - side * SLIP))
    held = q + 1
    roe = lev * (side * (exit_px / fill - 1) - FEE * (1 + exit_px / fill) - f_bar * held)
    roe = np.where(liq_gap, -1.0, np.maximum(roe, -1.0))
    R = roe * fill / (lev * dist)
    return done, R


def run_variant(b, idx, side, lev, liq_frac, n, f_bar, var):
    first, step, gap, mode, tpR, tmax = 0.10, 0.05, 0.02, "roe", None, None
    lv = lev.copy()
    lf = liq_frac.copy()
    if var == "lock20":
        first = 0.20
    elif var == "lock30":
        first = 0.30
    elif var == "lev10":
        lv = np.full(len(idx), 10.0)
        lf = np.full(len(idx), 0.09)
    elif var == "ladderR":
        first, step, gap, mode = 0.5, 0.25, 0.1, "r"
    elif var == "tp1R":
        tpR = 1.0
    elif var == "tp2R":
        tpR = 2.0
    elif var == "time64":
        tmax = 64
    out = np.full(len(idx), np.nan)
    todo = np.arange(len(idx))
    for H in (64, 512, 4096):
        if not len(todo):
            break
        nxt = []
        stp = max(32, 256_000 // H)
        for c0 in range(0, len(todo), stp):
            sel = todo[c0:c0 + stp]
            d, R = scan(b, idx[sel], side[sel], lv[sel], lf[sel], H, n, f_bar, first, step, gap, mode, tpR, tmax)
            keep = d | (H == 4096) | (idx[sel] + H >= n - 1)
            out[sel[keep]] = R[keep]
            nxt.append(sel[~keep])
        todo = np.concatenate(nxt) if nxt else np.zeros(0, int)
    return out


VARS = ("base", "lock20", "lock30", "lev10", "ladderR", "tp1R", "tp2R", "time64")


def main():
    D = pd.read_pickle(FY)
    for c in ("strategy", "tf", "coin"):
        D[c] = D[c].astype(str)
    D = D[D["lev"] > 0]
    rows = []
    for tf in ("15m", "30m", "1h", "4h"):
        parts = []
        for coin in ("BTCUSD", "ETHUSD", "SOLUSD", "DOGEUSD", "LTCUSD", "BCHUSD"):
            g = D[(D["tf"] == tf) & (D["coin"] == coin)]
            if not len(g):
                continue
            if tf in ("15m", "30m"):          # subsample the big ones (fixed seed) to keep memory and time small
                g = g.sample(n=min(len(g), 60_000), random_state=7)
            z = np.load(os.path.join(SIG, f"sig_{tf}_{coin}.npz"))
            b = {k: z[k] for k in ("ts", "o", "h", "l", "c", "atr")}
            n = len(b["ts"])
            f_bar = 0.0001 * TF_MIN[tf] / 480.0
            idx = g["idx"].to_numpy().astype(int)
            side = g["side"].to_numpy().astype(int)
            lev = g["lev"].to_numpy().astype(float)
            liq_frac = np.full(len(idx), np.nan)
            liq_frac[:] = 1.0 / lev - 0.01        # approx; the stop is always >= 1 ATR inside it at the sized lev
            res = {v: run_variant(b, idx, side, lev, liq_frac, n, f_bar, v) for v in VARS}
            P = pd.DataFrame(res)
            P["day"] = g["close_ms"].to_numpy() // DAY
            P["cf"] = (g["close_ms"].to_numpy() >= CF_START).astype(int)
            P["R_sim"] = g["R"].to_numpy()
            parts.append(P)
        P = pd.concat(parts, ignore_index=True)
        chk = float((np.abs(P["base"] - P["R_sim"]) < 1e-4).mean())
        for v in VARS:
            for w, wl in ((None, "all"), (0, "is"), (1, "cf")):
                Q = P if w is None else P[P["cf"] == w]
                d = (Q[v] - Q["base"]).to_numpy(float)
                ok = np.isfinite(d)
                d, day = d[ok], Q["day"].to_numpy()[ok]
                m = d.mean()
                sc = pd.Series(d - m).groupby(day).sum().to_numpy()
                G = len(sc)
                se = np.sqrt(G / (G - 1) * (sc ** 2).sum()) / len(d)
                rows.append({"tf": tf, "variant": v, "window": wl, "n": len(d), "mean_R_variant": Q[v].mean(),
                             "mean_R_base": Q["base"].mean(), "diff_R": m, "se": se, "t": m / se if se > 0 else np.nan,
                             "share_better": float((d > 1e-12).mean()), "base_match_share": chk})
    out = pd.DataFrame(rows)
    out.to_csv(OUT, index=False)
    pd.set_option("display.width", 220)
    print(out[out["window"] != "all"].pivot_table(index=["tf", "variant"], columns="window",
                                                  values=["mean_R_variant", "diff_R", "t"]).round(3).to_string())
    print("base reproduces fy_sim R (share within 1e-4):", out.groupby("tf")["base_match_share"].first().to_dict())


if __name__ == "__main__":
    main()
