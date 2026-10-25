"""Every month of the best honest setting (price-model picks threshold 0.02, L10 ladder, stop ROE -50 %, weekdays, one
position) at DeepCoin 0.14 % and 0.08 %: the month list the owners can read (how many good months, which ones)."""
import os, sys, json
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
src = open(os.path.join(HERE, "s29_ladders.py")).read()
exec(src.split("\nres = {}\n")[0].replace('PART = sys.argv[1] if len(sys.argv) > 1 else "all"', 'PART = "price"'))
out = {}
for thr in (0.02, 0.03):
    t, coin, side, prio = SETS[f"가격모델 자리 (기준 {thr})"]
    for cost in (0.0014, 0.0008):
        W, K = walk(t, coin, side, cost)
        j = [i for i, (s, ln) in enumerate(EXS) if s == 0.50 and ln.startswith("L10 ")][0]
        tt, ww = one_pos(t, W[:, j], K[:, j], prio)
        d = pd.to_datetime(tt + KST, unit="ms"); ym = (d.year * 100 + d.month).to_numpy()
        rows = {}
        for y in range(2022, 2027):
            for m in range(1, 13):
                k = y * 100 + m
                if k > 202610:
                    break
                w = ww[ym == k]
                rows[str(k)] = [int(len(w)), round(float(np.prod(1 + w)), 2)]
        out[f"기준 {thr} / 왕복 {cost*100:.2f}%"] = rows
        v = np.array([r[1] for k, r in rows.items() if k < "202610"])
        print(thr, cost, "months", len(v), "no-trade", sum(r[0] == 0 for k, r in rows.items() if k < "202610"),
              "<x1", int((v < 1).sum()), "x1-1.5", int(((v >= 1) & (v < 1.5)).sum()), "x1.5-3", int(((v >= 1.5) & (v < 3)).sum()),
              ">=x3", int((v >= 3).sum()), "top", sorted(((r[1], k) for k, r in rows.items()), reverse=True)[:4],
              "Oct26", rows["202610"])
json.dump(out, open(os.path.join(OUTD, "months33c.json"), "w"), ensure_ascii=False, indent=1)
