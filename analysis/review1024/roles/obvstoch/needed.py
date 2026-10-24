"""How much better per trade (ROE points, added to every taken trade) the listed cells would need to be for the MEDIAN
30-day path to reach x6 at margin 10 / 20 / 40 % (log-growth: trades_per_30d x mean log(1 + f (roe + delta)) = ln 6),
from the taken trades of the one-position account on CONF. Writes needed.csv."""
import oscore as O
from oscore import *
from accounts import frame, LIST
D = O.load_all()
rows = []
for cell, sgn, why in LIST:
    S = frame(D, cell, sgn, "CONF", False)
    Tk = S[RD.one_position(S, "X")]
    roe = Tk.X_roe.to_numpy(float)
    days = (GRID_END - O.P["CONF"][0]) / DAY
    n30 = len(Tk) / days * 30
    for f in (0.1, 0.2, 0.4):
        lo, hi = -0.5, 2.0
        for _ in range(60):
            mid = (lo + hi) / 2
            g = np.mean(np.log(np.maximum(1 + f * np.maximum(roe + mid, -1.0), 1e-12)))
            lo, hi = (lo, mid) if n30 * g >= np.log(6) else (mid, hi)
        rows.append({"cell": cell, "reverse": sgn < 0, "margin": f, "trades_per_30d": n30, "mean_roe_now": roe.mean(),
                     "sd_roe": roe.std(), "delta_needed": hi, "mean_roe_needed": roe.mean() + hi,
                     "payback_pts": PAYBACK * O.LEVX[O.parse(cell)[4]]})
R = pd.DataFrame(rows)
R.to_csv("needed.csv", index=False, float_format="%.5g")
print((R.set_index(["cell", "margin"])[["trades_per_30d", "mean_roe_now", "sd_roe", "delta_needed", "mean_roe_needed"]]).round(4).to_string())
