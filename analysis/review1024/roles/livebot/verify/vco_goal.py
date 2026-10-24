"""vco step 4: independent 30-day day-block bootstrap (own code, other seed) of B3/B6 (and B0/B9), margin 0.4, with
payback, for 2024-26 (conf+late) and October (fwd) days; then the same under the re-walked cost / delay scenarios of
vco_rewalk (entries fixed). Run (no -I): python3 vco_goal.py"""
import os, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__))
DAY = 86_400_000
MS = lambda s: int(pd.Timestamp(s, tz="UTC").value // 10**6)
POOLS = {"2024-26": (MS("2024-01-01"), MS("2026-10-05 15:00")), "oct": (MS("2026-10-05 15:00"), MS("2026-10-24 15:00"))}
PAYBACK = 2 * 0.9 * 0.00042


def boot(t, roe, a, b, margin=0.4, n_boot=20000, seed=7, horizon=30, target=6.0, kst_days=False):
    off = 9 * 3_600_000 if kst_days else 0
    d = (t + off) // DAY
    lo, hi = (a + off) // DAY, (b - 1 + off) // DAY
    nd = int(hi - lo + 1)
    order = np.argsort(t, kind="stable")
    d, roe = d[order], np.maximum(roe[order], -1.0)
    by = [roe[d == lo + i] for i in range(nd)]
    rng = np.random.default_rng(seed)
    hit = l50 = l90 = 0
    fin = np.empty(n_boot)
    for k in range(n_boot):
        eq, half, done = 1.0, False, False
        for di in rng.integers(0, nd, horizon):
            for x in by[di]:
                eq *= 1.0 + margin * x
                if not done:
                    if eq >= target:
                        hit += 1; done = True
                    else:
                        if eq <= 0.5 and not half:
                            l50 += 1; half = True
                        if eq <= 0.1:
                            l90 += 1; done = True
        fin[k] = eq
    return dict(p6=hit / n_boot, l50=l50 / n_boot, l90=l90 / n_boot, med=float(np.median(fin)), nd=nd)


if __name__ == "__main__":
    rows = []
    for v in sys.argv[1:] or ["B3", "B6", "B0", "B9"]:
        R = pd.read_csv(os.path.join(HERE, f"vco_rewalk_{v}.csv.gz"))
        pb = R.lev.to_numpy() * PAYBACK
        for pn, (a, b) in POOLS.items():
            m = ((R.t >= a) & (R.t < b)).to_numpy()
            t = R.t.to_numpy(np.int64)[m]
            for sc in ["orig", "c2", "c1p6", "d1", "d2", "c0"]:
                for withpb in (True, False):
                    if sc == "c0" and withpb:
                        continue
                    x = R[sc].to_numpy()[m] + (pb[m] if withpb else 0)
                    nb = 20000 if pn == "oct" else 4000
                    g = boot(t, x, a, b, n_boot=nb)
                    rows.append({"v": v, "pool": pn, "scen": sc, "payback": withpb, "n": int(m.sum()), "mean": 100 * x.mean(), **g})
                    if sc == "orig" and withpb:
                        gk = boot(t, x, a, b, n_boot=nb, kst_days=True, seed=11)
                        rows.append({"v": v, "pool": pn, "scen": "orig_kstdays_seed11", "payback": withpb, "n": int(m.sum()),
                                     "mean": 100 * x.mean(), **gk})
            print(v, pn, "done", flush=True)
    O = pd.DataFrame(rows)
    O.to_csv(os.path.join(HERE, "vco_goal.csv"), index=False, float_format="%.4f")
    pd.set_option("display.width", 220)
    print(O.round(4).to_string(index=False))
