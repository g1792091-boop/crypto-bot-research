"""Verifier -- step 4: the B_sel_with20 CONFIRM account numbers re-derived with independent code: mean ROE (raw / with
the TetherMax payback), win rate, trades per day, a separate 30-day day-block bootstrap (own code, other seed, 20,000
paths) at margins 0.1 / 0.2 / 0.4 / 0.6, and the per-trade shift needed for a growth-optimal 30-day median of x6.
Also: how many FWD / LATE signals of the bot were dropped because the trade was still open at the data end.
    python3 tz_b_boot.py <workdir>"""
import os
import sys
DATA = "/home/user/crypto-bot-research/analysis/review1024/roles/data"
sys.path.insert(0, DATA)
from common import *            # noqa: E402,F401
import rolesdata as RD          # noqa: E402

WD = sys.argv[1]
T = pd.read_pickle(os.path.join(WD, "B_taken_CONF.pkl")).sort_values("t")
roe = np.maximum(T.w35_roe.to_numpy(float), -1.0)
PB = 35 * PAYBACK
a, b = ms("2024-01-01"), ms("2026-10-01")
days = (b - a) / DAY
print("CONF trades", len(T), "per day", round(len(T) / days, 4), "mean", roe.mean(), "pb", (roe + PB).mean(),
      "win", (roe > 0).mean(), "PB pts", PB)
d = T.t.to_numpy(np.int64) // DAY
d0, d1 = a // DAY, (b - 1) // DAY
nd = int(d1 - d0 + 1)
print("days in sample", nd)


def boot(x, margin, n=20000, seed=7, H=30):
    rng = np.random.default_rng(seed)
    by = [x[d == d0 + i] for i in range(nd)]
    lens = np.array([len(v) for v in by])
    hit = l50 = l90 = 0
    fin = np.empty(n)
    for k in range(n):
        pick = rng.integers(0, nd, H)
        seq = np.concatenate([by[i] for i in pick]) if lens[pick].sum() else np.zeros(0)
        eq = np.cumprod(1 + margin * seq) if len(seq) else np.ones(1)
        fin[k] = eq[-1]
        # first-passage: target x6, -50 %, -90 %
        it = np.flatnonzero(eq >= 6.0)
        i50 = np.flatnonzero(eq <= 0.5)
        i90 = np.flatnonzero(eq <= 0.1)
        ft = it[0] if len(it) else 10**9
        f50 = i50[0] if len(i50) else 10**9
        f90 = i90[0] if len(i90) else 10**9
        if ft < f90:
            hit += 1
        if f50 < ft:
            l50 += 1
        if f90 < ft:
            l90 += 1
    return hit / n, l50 / n, l90 / n, float(np.median(fin))


for m in (0.1, 0.2, 0.4, 0.6):
    for pb in (False, True):
        print(f"margin {m} payback {pb}:", [round(v, 4) for v in boot(roe + (PB if pb else 0), m)])


def growth(x, per_day):
    best = (0.0, 0.0)
    for m in np.linspace(0.005, 1.0, 200):
        g = np.mean(np.log(np.maximum(1 + m * x, 1e-12)))
        if g > best[1]:
            best = (m, g)
    return best[0], float(np.exp(30 * per_day * best[1]))


pdy = len(T) / days
for pb in (False, True):
    x0 = roe + (PB if pb else 0)
    for dd in np.arange(0, 0.3, 0.0025):
        m, xx = growth(x0 + dd, pdy)
        if xx >= 6:
            print("payback", pb, "need shift", round(dd * 100, 3), "pts, mean then", round((x0.mean() + dd) * 100, 3),
                  "margin", round(m, 3))
            break

# open-at-end drops in LATE / FWD for the bot's rows (cellsig drops why == 3 rows before the bot runs)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
