"""PREREG9.md: the owners' manual style (PREREG8 M: 15m friend signal, 1h OR 4h ROC9, 35x, one position, the entry blocks, margin 40 %)
with only the resting take-profit / stop widths changed: screen ROE +10 / 15 / 20 / 30 / 40 / 50 % x -10 / 20 / 30 / 40 / 50 % (30
settings), stop first inside a 1m bar, the TetherMax payback 90 % added per trade. The best per-trade net ROE on 2020-03 .. 2024-12
(six coins, 600 trades or more) is read once on 2025-01 .. 2026-09 with the coin-flip twin.

    python3 -I frbracket.py       -> research/friendroc/results13.json"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # python3 -I leaves the script's folder out
from frcore import *
from frrun import take, rnd, coin_flip, MARGIN
from frloss import PER, COST
from frfamily import signals
from frmanual2 import walk_bracket, LEV, REFUND
from frdeep import per_stats
from frp30 import weekdays
import hashlib
from types import SimpleNamespace

TPS = (0.10, 0.15, 0.20, 0.30, 0.40, 0.50)
SLS = (-0.10, -0.20, -0.30, -0.40, -0.50)


def run(R, tp, sl, flip=False):
    r = np.zeros(len(R)); k = np.zeros(len(R), np.int64)
    for ci in range(6):
        g = grid(COINS[ci])
        cumf = np.cumsum(g["fund"])
        o, h, l, c = (np.ascontiguousarray(g[x], dtype=np.float64) for x in ("o", "h", "l", "c"))
        for side in (1, -1):
            m = ((R.coin == ci) & (R.side * (-1 if flip else 1) == side)).to_numpy()
            if m.any():
                r[m], k[m] = walk_bracket(o, h, l, c, cumf, R.e.to_numpy(np.int64)[m], side, LEV, COST, tp, sl, True, g["n"])
    return {"r": r, "k": k}


def detail(R, O, use, opp=None):
    t = R.t.to_numpy(np.int64)
    out = {}
    for pn, (a, z) in PER.items():
        m = use & (t >= a) & (t < z)
        idx = take(t, O["k"], m)
        roe0 = LEV * O["r"][idx]
        roe = roe0 + REFUND
        w, lo = roe[roe > 0], roe[roe <= 0]
        x = np.maximum(MARGIN * roe, -1.0)
        eq = np.cumprod(1 + x)
        d = {"n": int(len(idx)), "per_weekday": rnd(len(idx) / weekdays(a, z), 2), "win": rnd((roe > 0).mean(), 4),
             "avg_win_pct": rnd(w.mean() * 100, 1) if len(w) else None, "avg_loss_pct": rnd(lo.mean() * 100, 1) if len(lo) else None,
             "breakeven_win": rnd(-lo.mean() / (w.mean() - lo.mean()), 3) if len(w) and len(lo) else None,
             "roe_pct": rnd(roe.mean() * 100, 3), "roe_pct_no_payback": rnd(roe0.mean() * 100, 3),
             "mult40": rnd(eq[-1], 4), "maxdd40": rnd(float((eq / np.maximum.accumulate(np.r_[1.0, eq])[1:] - 1).min()), 3)}
        if opp is not None and pn in ("select", "confirm", "oct2026") and len(idx):
            growth = np.log1p(np.maximum(MARGIN * roe0, -1 + 1e-12)).sum()
            d["twin"] = coin_flip(SimpleNamespace(t=t), m, O, opp, LEV, roe0.mean(), growth)["pct_below"]
        out[pn] = d
    idx = take(t, O["k"], use & (t >= ms("2020-03-01")))
    roe = LEV * O["r"][idx] + REFUND
    tt = t[idx]
    mon = np.asarray(pd.to_datetime(tt + KST, unit="ms").strftime("%Y-%m"))
    x = np.maximum(MARGIN * roe, -1.0)
    v = np.array([np.prod(1 + x[mon == q]) for q in pd.period_range("2020-03", "2026-09", freq="M").strftime("%Y-%m")])
    out["months"] = {"median_all": rnd(np.median(v), 3), "up_all": int((v > 1).sum()), "n_all": len(v),
                     "median_2025": rnd(np.median(v[-21:]), 3), "up_2025": int((v[-21:] > 1).sum()), "x2_all": int((v >= 2).sum())}
    lg = np.log(np.maximum(1 + MARGIN * roe, 1e-9)); cs = np.r_[0, np.cumsum(lg)]
    hits = {51: 0, 10: 0, 4: 0}; ruin = n = 0
    for s in range(0, len(idx), 3):
        if tt[s] + 90 * DAY > ms("2026-10-23"):
            break
        e = np.searchsorted(tt, tt[s] + 90 * DAY)
        path = cs[s + 1:e + 1] - cs[s]
        if not len(path):
            continue
        n += 1
        for xx in hits:
            hits[xx] += int(path.max() >= np.log(xx))
        ruin += int(path.min() <= np.log(0.1))
    out["goal90"] = {f"x{xx}": rnd(vv / n, 4) for xx, vv in hits.items()} | {"to_10pct_or_less": rnd(ruin / n, 3)}
    return out


def main():
    want = open(os.path.join(RES_DIR, "PREREG9.md.sha256")).read().split()[0]
    sha = hashlib.sha256(open(os.path.join(RES_DIR, "PREREG9.md"), "rb").read()).hexdigest()
    assert sha == want, "PREREG9.md changed after it was frozen"
    A = signals("15m")
    R = A[A.block == ""].reset_index(drop=True)
    t = R.t.to_numpy(np.int64)
    doge = (R.coin == COINS.index("DOGEUSDT")).to_numpy()
    every = np.ones(len(R), bool)
    bnd = np.array([PER[pn] for pn in PER], np.int64)
    keys = list(PER)
    res = {"prereg9_sha256": sha, "grid": []}
    for tp in TPS:
        for sl in SLS:
            O = run(R, tp, sl)
            ext = t + (O["k"].astype(np.int64) + 1) * MIN
            row = {"tp": tp, "sl": sl}
            for nm, use in (("six", every), ("doge", doge)):
                S = per_stats(t, ext, LEV * O["r"] + REFUND, use, bnd)
                row[nm] = {pn: {"n": int(S[j, 0]), "win": rnd(S[j, 1] / S[j, 0], 4) if S[j, 0] else None,
                                "roe_pct": rnd(S[j, 2] / S[j, 0] * 100, 3) if S[j, 0] else None, "mult40": rnd(np.exp(S[j, 3]), 4)}
                           for j, pn in enumerate(keys)}
            res["grid"].append(row)
            s6 = row["six"]
            print(f"TP +{int(tp*100):2d} SL {int(sl*100):3d} | " + " | ".join(f"{p[:4]} n{s6[p]['n']} w{s6[p]['win']} roe{s6[p]['roe_pct']} x40 {s6[p]['mult40']}" for p in keys)
                  + f" || doge oct w{row['doge']['oct2026']['win']} x40 {row['doge']['oct2026']['mult40']} sel {row['doge']['select']['roe_pct']} conf {row['doge']['confirm']['roe_pct']}", flush=True)
    ok = [r for r in res["grid"] if r["six"]["select"]["n"] >= 600]
    pick = max(ok, key=lambda r: r["six"]["select"]["roe_pct"])
    res["both_positive"] = [(r["tp"], r["sl"]) for r in res["grid"] if r["six"]["select"]["roe_pct"] > 0 and r["six"]["confirm"]["roe_pct"] > 0]
    res["both_growing40"] = [(r["tp"], r["sl"]) for r in res["grid"] if r["six"]["select"]["mult40"] > 1 and r["six"]["confirm"]["mult40"] > 1]
    O = run(R, pick["tp"], pick["sl"]); Oo = run(R, pick["tp"], pick["sl"], flip=True)
    d = detail(R, O, every, Oo)
    d["doge"] = detail(R, O, doge)
    d["setting"] = {"tp": pick["tp"], "sl": pick["sl"]}
    d["verdict"] = {"select_positive": bool(d["select"]["roe_pct"] > 0), "confirm_positive": bool(d["confirm"]["roe_pct"] > 0),
                    "confirm_twin_975": bool(d["confirm"]["twin"] >= 0.975)}
    d["verdict"]["edge"] = all(d["verdict"].values())
    res["pick"] = d
    print("both positive", res["both_positive"], "| both growing at 40 %", res["both_growing40"], flush=True)
    print("PICK", d["setting"], flush=True)
    for p in PER:
        v = d[p]
        print(f"  {p:8s} n{v['n']} {v['per_weekday']}/d w{v['win']} be{v['breakeven_win']} aw{v['avg_win_pct']} al{v['avg_loss_pct']} roe{v['roe_pct']} (no pb {v['roe_pct_no_payback']}) "
              f"x40 {v['mult40']} dd{v['maxdd40']} twin {v.get('twin')}", flush=True)
    print("  months", d["months"], "goal90", d["goal90"], "verdict", d["verdict"], flush=True)
    print("  doge", {p: (d["doge"][p]["n"], d["doge"][p]["win"], d["doge"][p]["roe_pct"], d["doge"][p]["mult40"]) for p in PER}, flush=True)
    json.dump(res, open(os.path.join(RES_DIR, "results13.json"), "w"), ensure_ascii=False, indent=1, default=float)


if __name__ == "__main__":
    main()
