"""Actual (not bootstrapped) 30-day calendar windows, start every UTC day, 2024-01-01 .. 2026-10-24: share of windows that
reached x6 at any time, lost 50 % first, and the best window. Payback on/off, margins 0.4 / 1.0.
Run: python3 lm_rolling.py <trades_dir>"""
import os
import sys

import numpy as np
import pandas as pd

TD = sys.argv[1]
DAY = 86_400_000
PAYBACK = 2 * 0.9 * 0.00042
A = int(pd.Timestamp("2024-01-01", tz="UTC").timestamp() * 1000) // DAY
B = int(pd.Timestamp("2026-10-24 15:00", tz="UTC").timestamp() * 1000) // DAY
for v in ["B0", "B3", "B4", "B6", "B9", "W3"]:
    T = pd.read_csv(os.path.join(TD, f"trades_{v}.csv.gz")).sort_values("t")
    T = T[T.t // DAY >= A]
    lev = np.where(T.coin == 0, 40.0, 30.0)
    d = (T.t.to_numpy() // DAY)
    for pb in (False, True):
        r = np.maximum(T.tb_roe.to_numpy() + (PAYBACK * lev if pb else 0), -1.0)
        for m in (0.4, 1.0):
            hit = l50 = 0; best = 0; bestday = None; n = 0
            for s in range(A, B - 29):
                sel = (d >= s) & (d < s + 30)
                eq = np.cumprod(1 + m * r[sel])
                if len(eq) == 0:
                    continue
                n += 1
                reach = np.argmax(eq >= 6) if (eq >= 6).any() else None
                half = np.argmax(eq <= 0.5) if (eq <= 0.5).any() else None
                if reach is not None:
                    hit += 1
                if half is not None and (reach is None or half < reach):
                    l50 += 1
                if eq.max() > best:
                    best = eq.max(); bestday = pd.Timestamp(s * DAY, unit="ms").date()
            print(f"{v} payback={pb} margin={m}: windows {n}, reached x6 {hit} ({hit / n:.1%}), lost 50% first "
                  f"{l50 / n:.1%}, best peak x{best:.2f} (window from {bestday})")
