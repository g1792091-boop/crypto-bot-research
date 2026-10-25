"""What the goal needs (owners 10/25 night): with the ladder they like (L10: 12->10, 22->20 ...) and stops ROE -35 /
-50 %, take the real sizes of the wins and of the losses (the price-model picks, threshold 0.02, DeepCoin 0.14 %), then for
a win rate p and N entries a month draw 20,000 months (wins and losses drawn from those real sizes) and read the median
month and the share of months >= x3 / x5 / x10 and touching -50 %. Shows which (win rate, entries a month) reach the goal."""
import os, sys, json
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
sys.argv = [sys.argv[0], "none"]
src = open(os.path.join(HERE, "s29_ladders.py")).read()
exec(src.split("\nres = {}\n")[0].replace('PART = sys.argv[1] if len(sys.argv) > 1 else "all"', 'PART = "price"'))
t, coin, side, prio = SETS["가격모델 자리 (기준 0.02)"]
out = {}
for s_ in (0.35, 0.50):
    W, K = walk(t, coin, side, 0.0014)
    j = [i for i, (s, ln) in enumerate(EXS) if s == s_ and ln.startswith("L10 ")][0]
    w = W[:, j]; w = w[np.isfinite(w)]
    win, loss = w[w > 0], w[w <= 0]
    g = np.random.default_rng(1)
    tab = {}
    for n in (10, 20, 40, 60, 100):
        for p in (0.6, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95):
            M = 20000
            iswin = g.random((M, n)) < p
            vals = np.where(iswin, g.choice(win, (M, n)), g.choice(loss, (M, n)))
            eq = np.cumprod(1 + vals, axis=1)
            end = eq[:, -1]
            tab[f"진입 {n}/달, 승률 {int(p*100)}%"] = {"중간값": round(float(np.median(end)), 2),
                "x3+": round(float((end >= 3).mean()), 2), "x5+": round(float((end >= 5).mean()), 2),
                "x10+": round(float((end >= 10).mean()), 2), "-50%닿음": round(float((eq <= 0.5).any(1).mean()), 2)}
    out[f"L10 / 손절 ROE -{int(s_*100)}%"] = {"이긴 거래 평균(지갑)": round(float(win.mean()), 4),
        "진 거래 평균(지갑)": round(float(loss.mean()), 4), "실제 승률": round(float((w > 0).mean()), 3),
        "이긴 거래 크기 분포": {k: round(float(np.mean((win >= a) & (win < b))), 3) for k, a, b in
                         (("+4~8%", 0, 0.08), ("+8~12%", 0.08, 0.12), ("+12~20%", 0.12, 0.2), ("+20%~", 0.2, 9))},
        "표": tab}
json.dump(out, open(os.path.join(OUTD, "need33.json"), "w"), ensure_ascii=False, indent=1)
for k, v in out.items():
    print(k, {kk: vv for kk, vv in v.items() if kk != "표"})
    for kk, vv in v["표"].items():
        print("   ", kk, vv)
