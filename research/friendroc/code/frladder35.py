"""PREREG11.md: the owners' manual style (PREREG8 M: 15m friend signal, 1h OR 4h ROC9, 35x, the screen's -20 % stop before fees, one
position, the entry blocks, margin 40 %, the TetherMax payback 90 % per trade) with the fixed +10 % take-profit replaced by the bots'
ladder (best net ROE 12 % locks 10 %, then 5 % steps); A = M, B = M with PREREG10's four bigger-trend conditions. For reference: the
same ladder on the screen's ROE (before fees), and the screen's -30 % / -50 % stops.

    python3 -I frladder35.py      -> research/friendroc/results15.json"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # python3 -I leaves the script's folder out
from frcore import *
from frrun import rnd
from frloss import PER, COST, FL, STEP, GAP
from frfamily import signals
from frdeep import walk3
from frbracket import detail
from frmanual2 import LEV
from frtrend4 import trend_columns, conditions
import hashlib

FEE_ROE = LEV * COST                                       # 4.34 %: the round trip inside the screen's ROE


def outcomes(R, roe_stop, first_lock, flip=False):
    bt = grid("BTCUSDT")
    bc_, bo_ = (np.ascontiguousarray(bt[x], dtype=np.float64) for x in ("c", "o"))
    r = np.zeros(len(R)); k = np.zeros(len(R), np.int64); w = np.zeros(len(R), np.int8)
    for ci in range(6):
        g = grid(COINS[ci])
        cumf = np.cumsum(g["fund"])
        o, h, l, c = (np.ascontiguousarray(g[x], dtype=np.float64) for x in ("o", "h", "l", "c"))
        for side in (1, -1):
            m = ((R.coin == ci) & (R.side * (-1 if flip else 1) == side)).to_numpy()
            if m.any():
                r[m], k[m], w[m] = walk3(o, h, l, c, cumf, R.e.to_numpy(np.int64)[m], side, LEV, COST, first_lock, STEP, GAP, roe_stop,
                                         9.0, 0.0, 0, np.zeros(1, bool), False, bc_, bo_, 0.0, g["n"])
    return {"r": r, "k": k, "why": w}


def exits(R, O, use):
    """Per period, over the trades the one-position pass takes: exit reasons, the locked trades' mean net ROE, the median hold."""
    from frrun import take
    t = R.t.to_numpy(np.int64)
    out = {}
    for pn, (a, z) in PER.items():
        idx = take(t, O["k"], use & (t >= a) & (t < z))
        if not len(idx):
            out[pn] = None
            continue
        why = O["why"][idx]
        roe = LEV * O["r"][idx]
        out[pn] = {"stop": rnd(float((why == 0).mean()), 4), "lock": rnd(float((why == 1).mean()), 4), "open": int((why == 3).sum()),
                   "lock_mean_roe_pct": rnd(float(roe[why == 1].mean() * 100), 2) if (why == 1).any() else None,
                   "lock_ge_20_share": rnd(float((roe[why == 1] >= 0.20 - 1e-9).mean()), 4) if (why == 1).any() else None,
                   "hold_median_min": int(np.median(O["k"][idx]) + 1)}
    return out


def main():
    want = open(os.path.join(RES_DIR, "PREREG11.md.sha256")).read().split()[0]
    sha = hashlib.sha256(open(os.path.join(RES_DIR, "PREREG11.md"), "rb").read()).hexdigest()
    assert sha == want, "PREREG11.md changed after it was frozen"
    A = signals("15m")
    R = trend_columns(A[A.block == ""].reset_index(drop=True))
    every = np.ones(len(R), bool)
    t4 = np.logical_and.reduce(list(conditions(R).values()))
    doge = (R.coin == COINS.index("DOGEUSDT")).to_numpy()
    runs = {"계단 (순ROE) · 손절 −20": (-0.20, FL), "계단 (화면) · 손절 −20": (-0.20, FL - FEE_ROE),
            "계단 (순ROE) · 손절 −30": (-0.30, FL), "계단 (순ROE) · 손절 −50": (-0.50, FL)}
    res = {"prereg11_sha256": sha, "fee_roe_pct": rnd(FEE_ROE * 100, 3), "runs": {}}
    for rn, (sl, fl) in runs.items():
        main_run = rn.endswith("−20") and "순ROE" in rn
        O = outcomes(R, sl - FEE_ROE, fl)
        Oo = outcomes(R, sl - FEE_ROE, fl, flip=True) if main_run else None
        for an, use in (("A 손거래 방식", every), ("B + 네 조건", t4)):
            key = f"{an} · {rn}"
            d = detail(R, O, use, Oo)
            d["exits"] = exits(R, O, use)
            if main_run:
                d["doge"] = detail(R, O, use & doge)
                v = {"select_positive": bool(d["select"]["roe_pct"] > 0), "confirm_positive": bool(d["confirm"]["roe_pct"] > 0),
                     "confirm_twin_975": bool(d["confirm"].get("twin") is not None and d["confirm"]["twin"] >= 0.975)}
                v["earns"] = all(v.values())
                d["verdict"] = v | {"text": "과거 기록상 버는 구조" if v["earns"] else "아님"}
            res["runs"][key] = d
            print(f"== {key}", flush=True)
            for p in PER:
                x = d[p]
                print(f"  {p:8s} n{x['n']} {x['per_weekday']}/d w{x['win']} be{x['breakeven_win']} aw{x['avg_win_pct']} al{x['avg_loss_pct']} "
                      f"roe{x['roe_pct']} (no pb {x['roe_pct_no_payback']}) x40 {x['mult40']} dd{x['maxdd40']} twin {x.get('twin')} | {d['exits'][p]}",
                      flush=True)
            print("  months", d["months"], "goal90", d["goal90"], flush=True)
            if main_run:
                print("  doge", {p: (d["doge"][p]["n"], d["doge"][p]["win"], d["doge"][p]["roe_pct"], d["doge"][p]["mult40"]) for p in PER}, flush=True)
                print("  verdict", d["verdict"], flush=True)
    json.dump(res, open(os.path.join(RES_DIR, "results15.json"), "w"), ensure_ascii=False, indent=1, default=float)


if __name__ == "__main__":
    main()
