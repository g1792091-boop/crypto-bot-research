"""Verifier (costs / overlap lens): (1) rebuild the study cache with its own oscore.build_coin into a private /dev/shm
folder; (2) re-walk the exits per coin at every valid 15m entry minute (w35) and every 15m/30m/1h bar (a2) with
  cost x1 (check = the grid), cost x2 (0.248 % round trip), cost 0 (gross), and funding off (cost x1),
and save r, k (minutes to exit), why. Nothing is written in the repository except this script and its logs."""
import os, sys, json, time
sys.path.insert(0, "/home/user/crypto-bot-research/analysis/review1024/roles/obvstoch")
import oscore as O
from oscore import *
from frdeep import walk3
from frloss import walk2
O.CACHE = "/dev/shm/claude_verify_cost"
VC = O.CACHE


def walks(coin):
    t0 = time.time()
    G = RD._grid(coin)
    g = grid(coin)
    n = g["n"]
    o, h, l, c = g["o"], g["h"], g["l"], g["c"]
    cumf = np.cumsum(g["fund"])
    zf = np.zeros_like(cumf)
    valid = G["valid15"]
    e = (np.arange(len(valid), dtype=np.int64) + 1) * 15
    ev = e[valid]
    flag = np.zeros(1, bool)
    out = {"valid15": valid}
    chk = {}
    for nm, cost, cf in (("x1", COST, cumf), ("x2", 2 * COST, cumf), ("x0", 0.0, cumf), ("nf", COST, zf)):
        for lab, s in (("L", 1), ("S", -1)):
            a = walk3(o, h, l, c, cf, ev, s, 35.0, cost, FL, STEP, GAP, -0.50, 9.0, 0.01, 0, flag, False, c, o, 0.0, n)
            r = np.full(len(valid), np.nan, np.float32); k = np.full(len(valid), -1, np.int32); w = np.full(len(valid), -1, np.int8)
            r[valid], k[valid], w[valid] = a[0], a[1], a[2]
            out[f"w35{nm}_{lab}_r"], out[f"w35{nm}_{lab}_k"], out[f"w35{nm}_{lab}_w"] = r, k, w
            if nm == "x1":
                chk[f"w35_{lab}_r_eq"] = float(np.mean(np.isclose(r[valid], G[f"w35_{lab}_r"][valid], atol=1e-7)))
                chk[f"w35_{lab}_k_eq"] = float(np.mean(k[valid] == G[f"w35_{lab}_k"][valid]))
    for tf in ("15m", "30m", "1h"):
        kk = TF_MIN[tf]
        nb = n // kk
        jt = np.arange(nb, dtype=np.int64)
        et = (jt + 1) * kk
        vt = (jt * kk >= g["first"]) & (et < n)
        atr = G[f"atr14_{tf}"]
        atr = atr[:nb] if len(atr) >= nb else np.r_[atr, np.full(nb - len(atr), np.nan)]
        ok = vt & np.isfinite(atr)
        es = et[ok]
        atrd = np.ascontiguousarray(2.0 * atr[ok] / o[es])
        for nm, cost, cf in (("x1", COST, cumf), ("x2", 2 * COST, cumf), ("x0", 0.0, cumf)):
            for lab, s in (("L", 1), ("S", -1)):
                a = walk2(o, h, l, c, cf, es, s, 30.0, cost, FL, STEP, GAP, atrd, -1.0, n)
                r = np.full(nb, np.nan, np.float32); k = np.full(nb, -1, np.int32); w = np.full(nb, -1, np.int8)
                r[ok], k[ok], w[ok] = a[0], a[1], a[2]
                out[f"a2{nm}_{tf}_{lab}_r"], out[f"a2{nm}_{tf}_{lab}_k"], out[f"a2{nm}_{tf}_{lab}_w"] = r, k, w
                if nm == "x1":
                    ref = G[f"a2_{tf}_{lab}_r"]
                    m = min(len(ref), nb)
                    okm = ok[:m]
                    chk[f"a2_{tf}_{lab}_r_eq"] = float(np.mean(np.isclose(r[:m][okm], ref[:m][okm], atol=1e-7)))
                    chk[f"a2_{tf}_{lab}_k_eq"] = float(np.mean(k[:m][okm] == G[f"a2_{tf}_{lab}_k"][:m][okm]))
    # the 1x exit minutes of the grid (for one-position-at-a-time)
    for lab in ("L", "S"):
        out[f"g_w35_{lab}_k"] = G[f"w35_{lab}_k"]
    np.savez(os.path.join(VC, f"walk_{coin}.npz"), **out)
    drop(coin); RD._GR.pop(coin, None)
    log(coin, f"walks {time.time() - t0:.0f}s", chk)
    return coin, chk


if __name__ == "__main__":
    from multiprocessing import get_context
    os.makedirs(VC, exist_ok=True)
    coins = list(O.COINS)
    allchk = {}
    with get_context("fork").Pool(2) as pool:
        for c_, chk in pool.imap_unordered(O.build_coin, coins):
            allchk["build_" + c_] = chk
    with get_context("fork").Pool(2) as pool:
        for c_, chk in pool.imap_unordered(walks, coins):
            allchk["walk_" + c_] = chk
    json.dump(allchk, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "vwalk_checks.json"), "w"), indent=1, default=float)
    print(json.dumps(allchk, indent=1, default=float))
