"""Hand-built paths -> check exit codes, gross moves, costs, liquidation handling."""
import numpy as np
from lib import *
H = HMAX
def mk(bars):
    # bars: list of (o,h,l,c) as returns vs entry 100; remaining bars flat at last close
    O = np.full((1, H), 100.0); Hh = O.copy(); Lw = O.copy(); C = O.copy()
    last = 100.0
    for j in range(H):
        if j < len(bars):
            o, h, l, c = bars[j]
            O[0, j], Hh[0, j], Lw[0, j], C[0, j] = 100 * (1 + o), 100 * (1 + h), 100 * (1 + l), 100 * (1 + c)
            last = C[0, j]
        else:
            O[0, j] = Hh[0, j] = Lw[0, j] = C[0, j] = last
    return dict(O=O, H=Hh, L=Lw, C=C, E=O[:, 0].copy())
def run(bars, side, L, sd, td, order="adv", tfm=60):
    pp = mk(bars)
    k, cc, g, cost, y = exits(prep_moves(pp, side), L, np.array([sd]), np.array([td]), tfm, order)
    return int(k[0]), int(cc[0]), float(g[0]), float(cost[0]), float(y[0])
ok = True
def check(name, got, exp_k, exp_c, exp_g):
    global ok
    k, c, g, cost, y = got
    good = (k == exp_k and c == exp_c and abs(g - exp_g) < 1e-6)
    ok &= good
    print(f"{'OK ' if good else 'BAD'} {name}: k={k} code={c} g={g*100:.3f}% cost={cost*100:.4f}% y={y*100:.3f}%")
check("long TP bar1", run([(0, .006, -.002, .004)], 1, 20, .01, .005), 1, 1, .005)
check("long both touched adv", run([(0, .006, -.012, .0)], 1, 20, .01, .005), 1, 2, -.01)
check("long both touched fav", run([(0, .006, -.012, .0)], 1, 20, .01, .005, "fav"), 1, 1, .005)
check("long 50x stop beyond liq -> liq", run([(0, .001, -.016, -.01)], 1, 50, .02, .002), 1, 3, -(1/50 - MMR))
check("long gap stop bar2", run([(0, .001, -.002, -.001), (-.013, -.012, -.02, -.015)], 1, 20, .01, .005), 2, 2, -.013)
check("short TP bar3", run([(0, .002, -.001, .0), (0, .003, -.002, -.001), (-.001, .0, -.006, -.004)], -1, 20, .01, .005), 3, 1, .005)
check("short stop bar2", run([(0, .002, -.001, .0), (0, .011, -.002, .01)], -1, 20, .01, .005), 2, 2, -.01)
check("time exit", run([(0, .001, -.001, .003)], 1, 20, .01, .005), 64, 4, .003)
check("gap TP bar2 fills at open", run([(0, .001, -.001, .001), (.008, .009, .007, .008)], 1, 20, .01, .005), 2, 1, .008)
k, c, g, cost, y = run([(0, .001, -.016, -.01)], 1, 50, .02, .002)
exp_y = -1/50 - C_IN - FUND_8H * 60 / 480
print("liq y per notional", y, "expected", exp_y, "-> equity r at 40% margin:", 20 * y, "(= -0.40 - 20*(C_IN+fund))")
ok &= abs(y - exp_y) < 1e-7
k, c, g, cost, y = run([(0, .006, -.002, .004)], 1, 20, .01, .005)
ok &= abs(cost - (C_IN + C_OUT_TP + FUND_8H * 60 / 480)) < 1e-7
print("ALL OK" if ok else "FAILURES")
