"""PREREG7.md: trend breakout (Donchian N on 1h / 4h, EMA200 side) with pyramiding (+1 / +2 / +3 ATR, equal units)
and a k-ATR trailing stop shared by all units; weekday entries, one position across the six coins, 30-day hold cap.

    python3 -I vwgoal.py run      -> OUT7/*.npz, research/vwap30/results7.json (select pick, then confirm once)"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # python3 -I leaves the script's folder out
from vwcommon import *
from vwacct import _take
import hashlib, numba

OUT7 = OUT + "_r7"
RES_DIR = os.path.abspath(os.path.join(HERE, ".."))
HOLD_MIN = 30 * 1440
UNIT_X = (3, 5, 10, 20)
CAP_X = 50.0
SEED7 = 20261030
CONFIGS = [(tf, n, k, p) for tf in ("1h", "4h") for n in (20, 55) for k in (2.0, 3.0) for p in (0, 3)]


@numba.njit(cache=True)
def _trade(o, h, l, c, cf, e, s, atr, k, adds, nmax, cost):
    """One position from minute e: (sum of the units' net returns, units, exit minute)."""
    p0 = o[e]
    ent = np.empty(4)
    ent[0] = p0
    u = 1
    best = p0
    stop = p0 - s * k * atr
    m = e
    end = min(e + HOLD_MIN, nmax - 1)
    px = c[end]
    xm = end
    while m <= end:
        if s > 0:
            if l[m] <= stop:
                px = min(stop, o[m])
                xm = m
                break
        else:
            if h[m] >= stop:
                px = max(stop, o[m])
                xm = m
                break
        while u <= adds:
            lvl = p0 + s * u * atr
            if (s > 0 and h[m] >= lvl) or (s < 0 and l[m] <= lvl):
                ent[u] = max(lvl, o[m]) if s > 0 else min(lvl, o[m])
                u += 1
            else:
                break
        if s > 0:
            best = max(best, h[m])
            stop = max(stop, best - k * atr)
        else:
            best = min(best, l[m])
            stop = min(stop, best + k * atr)
        m += 1
    tot = 0.0
    for i in range(u):
        tot += s * (px / ent[i] - 1) - cost - s * (cf[xm] - cf[e - 1])
    return tot, u, xm


@numba.njit(cache=True)
def _run(o, h, l, c, cf, es, ss, atrs, k, adds, nmax, cost):
    n = len(es)
    tot = np.empty(n)
    un = np.empty(n, np.int64)
    xm = np.empty(n, np.int64)
    for i in range(n):
        tot[i], un[i], xm[i] = _trade(o, h, l, c, cf, es[i], ss[i], atrs[i], k, adds, nmax, cost)
    return tot, un, xm


def breakout_signals(df, n):
    h, l, c = (df[x].to_numpy(float) for x in ("high", "low", "close"))
    hh = pd.Series(h).rolling(n).max().shift(1).to_numpy()
    ll = pd.Series(l).rolling(n).min().shift(1).to_numpy()
    e200 = ema(c, 200)
    with np.errstate(invalid="ignore"):
        up = c > hh
        dn = c < ll
        lo = up & ~np.r_[False, up[:-1]] & (c > e200)
        sh = dn & ~np.r_[False, dn[:-1]] & (c < e200)
    lo[:250] = False
    sh[:250] = False
    return lo, sh


def build():
    os.makedirs(OUT7, exist_ok=True)
    rows = {}
    for tf in ("1h", "4h"):
        for n in (20, 55):
            parts = []
            for ci, coin in enumerate(COINS):
                df = bars(coin, tf)
                g = grid(coin)
                lo, sh = breakout_signals(df, n)
                atr, _ = atr_adx(df)
                i = np.r_[np.flatnonzero(lo), np.flatnonzero(sh)]
                side = np.r_[np.ones(lo.sum(), np.int64), -np.ones(sh.sum(), np.int64)]
                t = df.ts.to_numpy()[i] + TF_MIN[tf] * MIN
                e = (t - T0) // MIN
                ok = (e < g["n"] - 2) & (e >= 1) & np.isfinite(atr[i])
                i, side, t, e = i[ok], side[ok], t[ok], e[ok]
                cf = np.cumsum(g["fund"])
                for k in (2.0, 3.0):
                    for p in (0, 3):
                        r = {}
                        for nm, sd in (("s", side), ("o", -side)):
                            tot, un, xm = _run(g["o"], g["h"], g["l"], g["c"], cf, e.astype(np.int64), sd.astype(np.int64),
                                               atr[i].astype(float), k, p, g["n"], 2 * (0.0005 + 0.0002))
                            r[nm] = (tot, un, xm)
                        parts.append((tf, n, k, p, ci, t, side, r))
            for k in (2.0, 3.0):
                for p in (0, 3):
                    sel = [x for x in parts if x[2] == k and x[3] == p]
                    t = np.concatenate([x[5] for x in sel])
                    coin = np.concatenate([np.full(len(x[5]), x[4]) for x in sel])
                    D = {"t": t, "coin": coin}
                    for nm in ("s", "o"):
                        D[f"tot_{nm}"] = np.concatenate([x[7][nm][0] for x in sel])
                        D[f"units_{nm}"] = np.concatenate([x[7][nm][1] for x in sel])
                        D[f"xt_{nm}"] = T0 + (np.concatenate([x[7][nm][2] for x in sel]) + 1) * MIN
                    o = np.lexsort((D["coin"], D["t"]))
                    D = {q: v[o] for q, v in D.items()}
                    np.savez(os.path.join(OUT7, f"{tf}_N{n}_k{k:g}_p{p}.npz"), **D)
                    print("built", tf, n, k, p, len(t), flush=True)


def load(cfg):
    tf, n, k, p = cfg
    return dict(np.load(os.path.join(OUT7, f"{tf}_N{n}_k{k:g}_p{p}.npz")))


def account(D, per, X, flip=None):
    a, z = PERIODS[per]
    kst = pd.to_datetime(D["t"] + KST, unit="ms")
    m = (np.asarray(kst.dayofweek) < 5) & (D["t"] >= a) & (D["t"] < z)
    tot, xt, un = D["tot_s"], D["xt_s"], D["units_s"]
    if flip is not None:
        tot = np.where(flip, D["tot_o"], tot)
        xt = np.where(flip, D["xt_o"], xt)
        un = np.where(flip, D["units_o"], un)
    idx = _take(D["t"], xt, m)
    units = np.minimum(un[idx], np.floor(CAP_X / X))
    per_unit = tot[idx] / np.maximum(un[idx], 1)
    r = X * per_unit * units
    return idx, r, D["t"][idx]


def stats(D, per, X, flip=None):
    idx, r, t = account(D, per, X, flip)
    lg = np.log1p(np.maximum(r, -1 + 1e-12))
    a, z = PERIODS[per]
    d0, d1 = (a + KST) // DAY, (z + KST) // DAY
    dl = np.zeros(d1 - d0 + 1)
    np.add.at(dl, (t + KST) // DAY - d0, lg)
    cs = np.r_[0, np.cumsum(dl)]
    mm = np.exp(cs[30:] - cs[:-30])
    eq = np.exp(np.cumsum(lg))
    dd = float((eq / np.maximum.accumulate(np.r_[1.0, eq])[1:] - 1).min()) if len(eq) else 0.0
    wins = r > 0
    days = (z - a) / DAY
    return {"n": int(len(idx)), "per_day": round(len(idx) / days, 3), "win": round(float(wins.mean()), 4) if len(r) else None,
            "avg_unit_net_pct": round(float((r / X).mean() * 100), 4) if len(r) else None,
            "growth": round(float(lg.sum()), 3), "ruin_trades": int((r <= -1).sum()), "maxdd": round(dd, 4),
            "m30_x5": round(float((mm >= 5).mean()), 4), "m30_x10": round(float((mm >= 10).mean()), 4),
            "m30_x20": round(float((mm >= 20).mean()), 4), "m30_lose90": round(float((mm <= 0.1).mean()), 4),
            "m30_median": round(float(np.median(mm)), 4), "m30_best": round(float(mm.max()), 2)}


def run():
    if not all(os.path.exists(os.path.join(OUT7, f"{tf}_N{n}_k{k:g}_p{p}.npz")) for tf, n, k, p in CONFIGS):
        build()
    PERIODS["c2025"] = (ms("2025-01-01"), ms("2026-01-01"))
    PERIODS["c2026"] = (ms("2026-01-01"), ms("2026-10-01"))
    sel = []
    for cfg in CONFIGS:
        D = load(cfg)
        x = stats(D, "select", 5)
        sel.append({"cfg": list(cfg), **x})
        print("select", cfg, x, flush=True)
    best = max(sel, key=lambda r: r["growth"])
    fin = {"cfg": best["cfg"], "made": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()) + "Z"}
    fp = os.path.join(RES_DIR, "finalists7.json")
    json.dump(fin, open(fp, "w"), ensure_ascii=False, indent=1)
    open(fp + ".sha256", "w").write(hashlib.sha256(open(fp, "rb").read()).hexdigest() + "  finalists7.json\n")
    print("PICK", best["cfg"], flush=True)
    # confirm once (the pick is frozen above, before any confirm number is computed)
    D = load(tuple(best["cfg"]))
    out = {"pick": best["cfg"], "select_rows": sel, "by_exposure": {}}
    for X in UNIT_X:
        out["by_exposure"][str(X)] = {per: stats(D, per, X) for per in ("select", "confirm", "c2025", "c2026", "live")}
    g = stats(D, "confirm", 5)["growth"]
    rng = np.random.default_rng(SEED7)
    tw = np.array([stats(D, "confirm", 5, flip=rng.random(len(D["t"])) < 0.5)["growth"] for _ in range(1000)])
    p90 = float(np.percentile(tw, 90))
    conf5 = out["by_exposure"]["5"]["confirm"]
    out["twin"] = {"p50": round(float(np.median(tw)), 3), "p90": round(p90, 3), "share_below": round(float((tw < g).mean()), 3)}
    out["verdict"] = "통함" if (conf5["avg_unit_net_pct"] or 0) > 0 and g > p90 else "통하지 않음"
    json.dump(out, open(os.path.join(RES_DIR, "results7.json"), "w"), ensure_ascii=False, indent=1, default=float)
    for X in UNIT_X:
        for per in ("select", "confirm", "live"):
            print("X", X, per, out["by_exposure"][str(X)][per], flush=True)
    print("twin", out["twin"], out["verdict"])


if __name__ == "__main__":
    run()
