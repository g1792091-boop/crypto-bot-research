"""Default parity of the parameterised DeepSeek copies vs research/deepseek200/lib_c.entries (every coin x tf).
Also checks the house exit against research/exitstyle/exitstyle.scan (lev 20, no liquidation) on a sample."""
import json
import os
import sys
from multiprocessing import Pool

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cvlib as C  # noqa: E402
import numpy as np  # noqa: E402

NAMES = [s for s, v in C.STRATS.items() if v[0] == "ds"]


def job(a):
    tf, coin = a
    L = C._lc()
    b, _z = C.load_npz(tf, coin)
    df = C.frame(b, tf)
    E = L.entries(df.copy(), tf, ctx=None, coin=coin)
    out = {}
    for nm in NAMES:
        mine = C.strategy_signal(nm, 0, df, tf)
        lg, sh = E[nm]
        ref = np.where(lg, 1, np.where(sh, -1, 0))
        out[f"{nm}|{tf}|{coin}"] = {"mismatch": int((mine != ref).sum()), "signals": int((ref != 0).sum())}
    return out


def exit_check():
    sys.path.insert(0, os.path.join(C.REPO, "research", "exitstyle"))
    sys.path.insert(0, os.path.join(C.REPO, "research", "levstop"))
    import exitstyle as XS
    res = {}
    for tf in C.TFS:
        b, z = C.load_npz(tf, "ETHUSD")
        sg = z["s__N23_HA_ST"]
        idx = np.flatnonzero(sg != 0)
        idx = idx[(idx > 5000) & (idx < len(sg) - 5000)][:3000]
        side = sg[idx].astype(np.int64)
        n = len(b["ts"])
        f_bar = C.FUNDING_8H * C.TF_MIN[tf] / 480.0
        lev = np.full(len(idx), 20.0)
        r = XS.scan(b, idx, side, lev, np.full(len(idx), 0.999), 4096, n, f_bar, 2.0, tp_r=None, ladder=True)
        dn, held, rn, rg, npct = C.outcomes(b, idx, side, tf, 2.0, "house")
        ok = r["done"] & dn
        res[tf] = {"n": int(ok.sum()), "max_abs_roe_diff": float(np.max(np.abs(r["roe"][ok] - 20 * npct[ok]))),
                   "held_equal": bool(np.array_equal(r["held"][ok], held[ok]))}
    return res


if __name__ == "__main__":
    C.check_prereg()
    jobs = [(tf, c) for tf in C.TFS for c in C.COINS]
    out = {}
    with Pool(4) as p:
        for r in p.imap_unordered(job, jobs):
            out.update(r)
    bad = {k: v for k, v in out.items() if v["mismatch"]}
    print("ds parity mismatches:", bad)
    out["_exit_check"] = exit_check()
    print(out["_exit_check"])
    os.makedirs(os.path.join(C.WORK, "work"), exist_ok=True)
    json.dump(out, open(os.path.join(C.WORK, "work", "ds_parity.json"), "w"), indent=1)
