"""Month by month (KST calendar months, a fresh start each month): how often did the bot reach x5 before -50 %, and
did it ever do it two months in a row?"""
import os, sys, json
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
exec(open(os.path.join(HERE, "s4_combo.py")).read().split("res = {}")[0])
for lab, mems in (("A 하락장에서만", gate(A, (1,))), ("A 모든 장세", A), ("B 상승·횡보 + A 하락장", [m for m in B if m[4] != (1,)] + gate(A, (1,)))):
    T = trades(mems, None)
    d = pd.to_datetime(T.t + 9 * 3600 * 1000, unit="ms"); key = (d.dt.year * 100 + d.dt.month).to_numpy()
    rows = []
    for k in range(202003, 202611):
        if k % 100 == 0 or k % 100 > 12:
            continue
        w = T.w.to_numpy()[key == k]
        eq = np.cumprod(1 + w) if len(w) else np.array([1.0])
        res = "그대로"
        for v in eq:
            if v >= 5: res = "x5"; break
            if v <= 0.5: res = "-50%"; break
        rows.append((k, res, round(float(eq[-1]), 2), len(w)))
    R = pd.DataFrame(rows, columns=["month", "result", "month_x", "n"])
    hit = (R.result == "x5").to_numpy()
    streak = max((len(s) for s in "".join("1" if h else "0" for h in hit).split("0")), default=0)
    print(f"== {lab}: {len(R)} months, x5 first {hit.sum()} ({hit.mean():.0%}), -50% first {(R.result == '-50%').sum()}, "
          f"month ended above x1 {(R.month_x >= 1).sum()}, longest x5 streak {streak} months", flush=True)
    print("   x5 months:", R.month[hit].tolist(), flush=True)
