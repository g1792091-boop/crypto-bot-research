"""The dense outcome grid: for EVERY 15m bar close of every coin (2020-01 .. the extended grid end) and BOTH sides, the
trade outcome of an entry at the open of the minute that starts at that close, under

  w35     the owners' live exits: 35x, net ROE -50 % stop, ladder +12 % -> +10 % then every 5 % (frdeep.walk3, no
          time stop / cancel / BTC exit / break-even)
  w30     the same at 30x
  w35s20  35x with a net ROE -20 % stop
  a2      per timeframe (15m / 30m / 1h / 4h bar closes): stop 2 x ATR14 of that timeframe's signal bar from the entry
          (gross price distance), the same ladder at 30x, no net-ROE cap (floor = -100 % net, the margin), no leverage
          downgrade (the house engine's 15 %-of-equity rule is not applied) -- frloss.walk2

Cost 0.124 % round trip (taker 0.042 % + slippage 0.02 %, each side); TetherMax payback NOT included (add
common.PAYBACK = 0.0756 % to r for it). Funding: the grid's (0 in October 2026 and in the extension).

A trade depends only on (coin, entry minute, side) for the walk3 variants, so every strategy's signal at a bar close
is a lookup here; the opposite side is the coin-flip twin on the same entry.

Output OUT/grid/<coin>.npz:
  j15 index = 15m bar number from T0 (bar open = T0 + j * 15 min; entry minute e = (j + 1) * 15)
  valid15 bool    the bar is whole and the entry minute exists
  <v>_<L|S>_r     float32 net price return (ROE = leverage x r; NaN where not valid)
  <v>_<L|S>_k     int32 minutes from the entry minute to the exit minute (the exit happens inside minute e + k)
  <v>_<L|S>_why   int8 0 stop, 1 lock (ladder), 3 open at the data end
  a2_<tf>_<L|S>_r / _k / _why on that timeframe's bar index (bar open = T0 + j * tf), atr14_<tf> float64
  blk15 int8      frcore.blocked code of the entry minute (0 none, 1 KST weekend, 2 US macro +-30 min, 3 NYSE open +-30)

    python3 build_grid.py [coin ...]"""
from common import *
import numba
from frdeep import walk3
from frloss import walk2


def entry_minutes(g, tf):
    """(j, e, valid): bar number from T0, entry minute index, whether the bar is whole and e < n."""
    k = TF_MIN[tf]
    nb = g["n"] // k
    j = np.arange(nb, dtype=np.int64)
    e = (j + 1) * k
    valid = (j * k >= g["first"]) & (e < g["n"])
    return j, e, valid


def blocked_codes(t):
    from frcore import blocked
    code = {s: i for i, s in enumerate(BLOCK)}
    return np.array([code[blocked(int(x))] for x in t], np.int8)


def run_coin(coin):
    t0 = time.time()
    g = grid(coin)
    n = g["n"]
    o, h, l, c = g["o"], g["h"], g["l"], g["c"]
    cumf = np.cumsum(g["fund"])
    j, e, valid = entry_minutes(g, "15m")
    ev = e[valid]
    assert not np.isnan(o[ev]).any() and not np.isnan(c[g["first"]:]).any(), "NaN inside the grid"
    out = {"valid15": valid, "n_minutes": np.int64(n), "n_grid": np.int64(g["n_grid"]), "first": np.int64(g["first"])}
    dummy_flag = np.zeros(1, bool)
    for vn, (kind, lev, stop) in VARIANTS.items():
        if kind != "walk3":
            continue
        for sn, s in (("L", 1), ("S", -1)):
            r = np.full(len(e), np.nan, np.float32)
            k = np.full(len(e), -1, np.int32)
            w = np.full(len(e), -1, np.int8)
            a = walk3(o, h, l, c, cumf, ev, s, lev, COST, FL, STEP, GAP, stop, 9.0, 0.01, 0, dummy_flag, False, c, o, 0.0, n)
            r[valid], k[valid], w[valid] = a[0], a[1], a[2]
            out[f"{vn}_{sn}_r"], out[f"{vn}_{sn}_k"], out[f"{vn}_{sn}_why"] = r, k, w
        log(coin, vn, f"{time.time() - t0:.0f}s")
    fg = libs()["fg"]
    for tf in TFS:
        df = bars(coin, tf)
        atr = fg.atr(df, 14).to_numpy(float)
        jt, et, vt = entry_minutes(g, tf)
        full_atr = np.full(len(jt), np.nan)
        jb = (df.ts.to_numpy(np.int64) - T0) // (TF_MIN[tf] * MIN)
        full_atr[jb] = atr
        ok = vt & np.isfinite(full_atr)
        es = et[ok]
        atrd = 2.0 * full_atr[ok] / o[es]
        out[f"atr14_{tf}"] = full_atr
        for sn, s in (("L", 1), ("S", -1)):
            r = np.full(len(jt), np.nan, np.float32)
            k = np.full(len(jt), -1, np.int32)
            w = np.full(len(jt), -1, np.int8)
            a = walk2(o, h, l, c, cumf, es, s, 30.0, COST, FL, STEP, GAP, np.ascontiguousarray(atrd), -1.0, n)
            r[ok], k[ok], w[ok] = a[0], a[1], a[2]
            out[f"a2_{tf}_{sn}_r"], out[f"a2_{tf}_{sn}_k"], out[f"a2_{tf}_{sn}_why"] = r, k, w
        log(coin, "a2", tf, f"{time.time() - t0:.0f}s")
    out["blk15"] = BLK15[: len(e)]
    os.makedirs(os.path.join(OUT, "grid"), exist_ok=True)
    save_npz(os.path.join(OUT, "grid", f"{coin}.npz"), **out)
    drop(coin)
    log(coin, "done", f"{time.time() - t0:.0f}s")


def blk15_all():
    """frcore.blocked of every 15m entry minute (same for all coins), cached."""
    p = os.path.join(OUT, "grid", "blk15.npy")
    if os.path.exists(p):
        return np.load(p)
    nb = (ext_end() - T0) // (15 * MIN)
    t = T0 + (np.arange(nb, dtype=np.int64) + 1) * 15 * MIN
    b = blocked_codes(t)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    np.save(p, b)
    return b


if __name__ == "__main__":
    coins = sys.argv[1:] or list(COINS)
    t0 = time.time()
    BLK15 = blk15_all()
    log("blk15", len(BLK15), np.bincount(BLK15).tolist(), f"{time.time() - t0:.0f}s")
    for coin in coins:
        run_coin(coin)
