"""Check of s43 (close-based stops look much better): at every touch-stop of the price-model bot, how deep was the wick
beyond the stop, where did the minute close, was the minute's range abnormal (bad print?), and what happened next."""
import os, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
src = open(os.path.join(HERE, "s41_pm_autopsy.py")).read().split("DIMS = {")[0]
exec(src)
t, c, s, p = SETS["세 예측 동의 · 하루 1개"]
t = np.asarray(t, np.int64); c = np.asarray(c, np.int64); s = np.asarray(s, np.int64); p = np.asarray(p, float)
btc, own, vol, ses = attrs(t, c); keep = (c != 0) & (vol != 0)
t, c, s, p = t[keep], c[keep], s[keep], p[keep]
o_ = np.lexsort((-p, t)); t, c, s = t[o_], c[o_], s[o_]
cst = D.off[c] + ((t - GT0) // MIN); csend = D.off[c + 1]; lev = HB.LEVC[c].astype(float)
ti, w, k = FC.seq_sim(D.o, D.h, D.l, D.c, cst, s, t, csend, lev, 0.25, 0, 0.0, 0.12, 0.10, 0.05, 0.0014, HB.MARGIN)
L = lev[ti]; d = 0.25 / L - 0.0014
stopped = w < -0.4 * 0.25 + 0.001          # the stop exits (w = -10 % of the wallet)
rows = []
for i in np.flatnonzero(stopped):
    e0 = cst[ti[i]]; j = e0 + k[i] - 1; sd = s[ti[i]]; p0 = D.o[e0]
    if sd > 0:
        wick = D.l[j] / p0 - 1; cl = D.c[j] / p0 - 1
    else:
        wick = 1 - D.h[j] / p0; cl = 1 - D.c[j] / p0
    rng = (D.h[j] - D.l[j]) / D.c[j]
    med = np.median((D.h[j - 60:j] - D.l[j - 60:j]) / D.c[j - 60:j])
    # after the stop minute: did the next 3 closes stay above the stop? max adverse next 60 min
    nxt = (D.c[j + 1:j + 4] / p0 - 1) if sd > 0 else (1 - D.c[j + 1:j + 4] / p0)
    adv60 = np.min((D.l[j:j + 60] / p0 - 1) if sd > 0 else (1 - D.h[j:j + 60] / p0))
    rows.append({"coin": COINS[c[ti[i]]], "t": pd.Timestamp(t[ti[i]], unit="ms"), "stop": -d[i], "wick": wick, "close": cl,
                 "close_above_stop": cl > -d[i], "range/median60": rng / max(med, 1e-9), "next3_above": bool((nxt > -d[i]).all()),
                 "adv60_beyond_liq": adv60 <= -(1 / L[i] - 0.005)})
R = pd.DataFrame(rows)
print("touch stops:", len(R), "| close above the stop in the stop minute:", round(R.close_above_stop.mean(), 3),
      "| and the next 3 closes too:", round((R.close_above_stop & R.next3_above).mean(), 3))
print("stop-minute range / median range of the 60 minutes before: median", round(R["range/median60"].median(), 2),
      "| share > 10x:", round((R["range/median60"] > 10).mean(), 3), "| share > 30x:", round((R["range/median60"] > 30).mean(), 3))
print("wick beyond the stop (price %): median", round(float((R.stop - R.wick).median() * 100), 3), "| p90", round(float((R.stop - R.wick).quantile(0.9) * 100), 3))
print("would reach the liquidation distance within 60 min:", round(R.adv60_beyond_liq.mean(), 3))
print(R[R.close_above_stop].sort_values("range/median60", ascending=False).head(12).to_string())
