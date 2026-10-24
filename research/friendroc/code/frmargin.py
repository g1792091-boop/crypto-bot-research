"""After PREREG5 (not in it; a read for the owners' margin choice): the PREREG5 pick (by account growth) and the best per-trade
setting of PREREG5, with the TetherMax payback 90 %, at margins 5 .. 40 %. The margin with the largest 2020-03 .. 2024-12 growth is
read once on 2025-01 .. 2026-09. Margin does not change which trades are taken, only how much each one moves the account.

    python3 -I frmargin.py        -> research/friendroc/results8.json"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # python3 -I leaves the script's folder out
from frcore import *
from frrun import take, rnd
from frloss import PER, LEV
from frfamily import signals, outcomes, LADDERS
from frpay import mask, REFUND

MARGINS = (0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40)
SETTINGS = {"PREREG5 1등 (15분, 손절 -50%, 계단 10/5, ADX + 조용한 봉)": ("15m", -0.50, "L10", "F4+V"),
            "거래당 1등 (15분, 손절 -75%, 계단 20/10, ADX + 조용한 봉)": ("15m", -0.75, "L20", "F4+V")}


def main():
    res = {}
    R = signals("15m")
    R = R[R.block == ""].reset_index(drop=True)
    t = R.t.to_numpy(np.int64)
    for nm, (tf, st, ln, f) in SETTINGS.items():
        fl, step = LADDERS[ln]
        O = outcomes(R, st, fl, step)["own"]
        use = mask(R, f)
        rf = REFUND["p90"]
        out = {}
        for pn in ("select", "confirm", "oct2026", "last19"):
            a, z = PER[pn]
            idx = take(t, O["k"], use & (t >= a) & (t < z))
            roe = LEV * O["r"][idx] + rf
            months = (z - a) / DAY / 30.44
            mon = np.asarray(pd.to_datetime(t[idx] + KST, unit="ms").strftime("%Y-%m"))
            d = {"n": len(idx), "roe_pct": rnd(roe.mean() * 100, 3), "sd_pct": rnd(roe.std() * 100, 1)}
            for m in MARGINS:
                x = np.maximum(m * roe, -1.0)
                eq = np.cumprod(1 + x)
                mm = np.array([np.prod(1 + x[mon == q]) for q in np.unique(mon)])
                d[f"m{int(m * 100)}"] = {"mult": rnd(eq[-1], 4), "per_month_pct": rnd((eq[-1] ** (1 / months) - 1) * 100, 2),
                                         "maxdd": rnd(float((eq / np.maximum.accumulate(np.r_[1.0, eq])[1:] - 1).min()), 3),
                                         "month_median": rnd(np.median(mm), 3), "months_up": int((mm > 1).sum()), "months": int(len(mm))}
            out[pn] = d
        best = max(MARGINS, key=lambda m: out["select"][f"m{int(m * 100)}"]["mult"])
        out["best_margin_on_select"] = best
        res[nm] = out
        print(nm, "best margin on 2020-24:", best, flush=True)
        for pn in ("select", "confirm", "oct2026", "last19"):
            d = out[pn]
            print(f"  {pn:8s} n{d['n']} roe{d['roe_pct']} sd{d['sd_pct']} |",
                  " | ".join(f"{k}: x{v['mult']} {v['per_month_pct']}%/mo dd{v['maxdd']} med{v['month_median']} up{v['months_up']}/{v['months']}"
                             for k, v in d.items() if k.startswith("m")), flush=True)
    json.dump(res, open(os.path.join(RES_DIR, "results8.json"), "w"), ensure_ascii=False, indent=1, default=float)


if __name__ == "__main__":
    main()
