"""Win rate and per trade against entries a month (price-model picks, weekday, one position, L10 ladder, stops ROE -35
/ -50 %, DeepCoin 0.14 %): where on this curve is the goal (s33: about 60 a month at 75-80 %)?"""
import os, sys, json
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
src = open(os.path.join(HERE, "s29_ladders.py")).read()
exec(src.split("\nSETS = {}\n")[0].replace('PART = sys.argv[1] if len(sys.argv) > 1 else "all"', 'PART = "x"'))
wk = lambda t: ((((t + KST) // DAY) + 3) % 7) < 5        # noqa: E731
z = np.load(os.path.join(OUTD, "ml21_price.npz"))
P, TT, CC = z["PRED"], z["T"], z["COIN"].astype(np.int64)
pl, ps = P[:, 0, 2], P[:, 1, 2]; best = np.fmax(pl, ps); side = np.where(pl >= ps, 1, -1)
out = {}
for thr in (-0.01, -0.005, 0.0, 0.005, 0.01, 0.015, 0.02, 0.03):
    mm = np.isfinite(best) & (best > thr) & wk(TT)
    t, coin, sd, pr = TT[mm], CC[mm], side[mm], best[mm]
    if len(t) > 400000:
        continue
    W, K = walk(t, coin, sd, 0.0014)
    for j, (s, ln) in enumerate(EXS):
        if not ln.startswith("L10 "):
            continue
        tt, ww = one_pos(t, W[:, j], K[:, j], pr)
        r = read(tt, ww)
        out[f"기준 {thr} / 손절 -{int(s*100)}%"] = r
        print(thr, s, "후보", len(t), {k: r[k] for k in ("달 평균 진입", "승률", "거래당", "한 달 중간값", "x5 이상 달", "-50% 닿은 달")}, flush=True)
json.dump(out, open(os.path.join(OUTD, "curve33b.json"), "w"), ensure_ascii=False, indent=1)
