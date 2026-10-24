"""PLAN.md: the signal rows of the 48 families on the extended 1m grid and their outcomes under the 8 exits (own side and
the opposite side for the coin-flip twin), the forward moves for the direction shares, the entry blocks.

    python3 -I f2build.py [--procs 3]      -> SCR/rows_<coin>.pkl, SCR/build_info.json"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # python3 -I leaves the script's folder out
from f2common import *
import hashlib
from multiprocessing import Pool

HORIZONS = (60, 240, 1440)


def coin_rows(coin):
    t0 = time.time()
    info = extend_grid(coin)
    frames = {tf: tf_frame(coin, tf) for tf in ALL_TF}
    g = grid(coin)
    n = g["n"]
    parts = []
    for tf in TFS:
        E = frames[tf]
        H = align(frames[HTF[tf]], E["tclose"])
        e = (E["tclose"] - T0) // MIN
        valid = e < n
        fams = [f for f in FAMS if FAMS[f]["tf"] == tf]
        S = {f: family_sides(FAMS[f], E, H) for f in fams}
        for s in (1, -1):
            hit = np.logical_or.reduce([S[f] == s for f in fams]) & valid
            i = np.flatnonzero(hit)
            d = pd.DataFrame({"e": e[i], "side": np.int8(s)})
            for f in FAMS:
                d[f] = (S[f][i] == s) if f in S else False
            parts.append(d)
    R = pd.concat(parts, ignore_index=True)
    R = R.groupby(["e", "side"], as_index=False, sort=True).max()          # one row per entry minute and side
    R["coin"] = np.int8(COINS.index(coin))
    R["t"] = T0 + R.e.to_numpy(np.int64) * MIN
    R["block"] = [blocked(int(x)) for x in R.t.to_numpy()]
    cumf = np.cumsum(g["fund"])
    o, h, l, c = (np.ascontiguousarray(g[x], dtype=np.float64) for x in ("o", "h", "l", "c"))
    es = R.e.to_numpy(np.int64)
    side = R.side.to_numpy()
    for hz in HORIZONS:
        j = np.minimum(es + hz - 1, n - 1)
        R[f"fwd{hz}"] = (side * (c[j] / o[es] - 1)).astype(np.float32)
        R.loc[es + hz - 1 >= n, f"fwd{hz}"] = np.nan                     # not yet known at the data end
    for (lev, sl), xn in zip(EXITS, XN):
        for sn, sg in (("own", 1), ("opp", -1)):
            r = np.zeros(len(R)); k = np.zeros(len(R), np.int64); w = np.zeros(len(R), np.int8); ma = np.zeros(len(R))
            for sd in (1, -1):
                m = side * sg == sd
                if m.any():
                    r[m], k[m], w[m], ma[m] = walk4(o, h, l, c, cumf, es[m], sd, lev, COST, FL, STEP, GAP, sl, n)
            R[f"{xn}_{sn}_r"] = r
            R[f"{xn}_{sn}_k"] = k.astype(np.int32)
            if sn == "own":
                R[f"{xn}_own_why"] = w
                R[f"{xn}_own_mae"] = ma.astype(np.float32)
    # parity: walk4 == frdeep.walk3 (no fixes) on the first 3,000 rows of each side, two exits
    par = {}
    for lev, sl in ((35.0, -0.20), (20.0, -0.50)):
        same = tot = 0
        dmax = 0.0
        for sd in (1, -1):
            ee = es[side == sd][:3000]
            a = walk4(o, h, l, c, cumf, ee, sd, lev, COST, FL, STEP, GAP, sl, n)
            b = walk3(o, h, l, c, cumf, ee, sd, lev, COST, FL, STEP, GAP, sl, 9.0, 0.0, 0, np.zeros(1, bool), False,
                      c, o, 0.0, n)
            same += int(((a[1] == b[1]) & (a[2] == b[2])).sum())
            tot += len(ee)
            dmax = max(dmax, float(np.abs(a[0] - b[0]).max()))
        par[xname(lev, sl)] = {"rows": tot, "same_exit_and_reason": same, "max_abs_diff_r": dmax}
    R.to_pickle(os.path.join(SCR, f"rows_{coin}.pkl"))
    print("built", coin, len(R), {f: int(R[f].sum()) for f in list(FAMS)[:6]}, f"{time.time() - t0:.0f}s", flush=True)
    return coin, info, par, int(len(R)), int(n)


def main():
    procs = int(sys.argv[sys.argv.index("--procs") + 1]) if "--procs" in sys.argv else 3
    with Pool(procs) as pool:
        out = pool.map(coin_rows, COINS)
    res = {"made": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()) + "Z",
           "plan_sha256": hashlib.sha256(open(os.path.join(F2_DIR, "PLAN.md"), "rb").read()).hexdigest(),
           "live_csv_sha256": hashlib.sha256(open(LIVE_CSV, "rb").read()).hexdigest(),
           "grid_end_before_utc": str(pd.Timestamp(DATA_END, unit="ms")),
           "extension": {c: i for c, i, _, _, _ in out}, "walk_parity": {c: p for c, _, p, _, _ in out},
           "rows": {c: r for c, _, _, r, _ in out},
           "data_end_utc": {c: str(pd.Timestamp(T0 + n * MIN, unit="ms")) for c, _, _, _, n in out}}
    json.dump(res, open(os.path.join(SCR, "build_info.json"), "w"), indent=1)
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    want = open(os.path.join(F2_DIR, "PLAN.md.sha256")).read().split()[0]
    assert hashlib.sha256(open(os.path.join(F2_DIR, "PLAN.md"), "rb").read()).hexdigest() == want, "PLAN.md changed"
    main()
