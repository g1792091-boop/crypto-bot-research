"""Actual 30-day windows fully inside 2024-01-01 .. 2026-10-05 15:00 (before the forward period), payback, margin 0.4:
windows that reached x6, grouped into distinct episodes; short share and always-short mean in those windows.
Run: python3 lm_rolling2.py <trades_dir>"""
import os, sys
import numpy as np, pandas as pd
TD = sys.argv[1]; DAY = 86_400_000; PAYBACK = 2 * 0.9 * 0.00042
A = int(pd.Timestamp("2024-01-01", tz="UTC").timestamp() * 1000) // DAY
B = int(pd.Timestamp("2026-10-05 15:00", tz="UTC").timestamp() * 1000) // DAY
for v in ["B3", "B4", "B6", "B9", "B0"]:
    T = pd.read_csv(os.path.join(TD, f"trades_{v}.csv.gz")).sort_values("t")
    T = T[(T.t // DAY >= A) & (T.t // DAY < B)]
    lev = np.where(T.coin == 0, 40.0, 30.0); d = T.t.to_numpy() // DAY
    r = np.maximum(T.tb_roe.to_numpy() + PAYBACK * lev, -1.0)
    sh = np.where(T.side.to_numpy() < 0, T.tb_roe.to_numpy(), T.tb_opp_roe.to_numpy())
    side = T.side.to_numpy()
    for m in (0.4,):
        hits, n, l50 = [], 0, 0
        for s in range(A, B - 30 + 1):
            sel = (d >= s) & (d < s + 30); eq = np.cumprod(1 + m * r[sel])
            if not len(eq): continue
            n += 1
            ok = (eq >= 6).any(); hl = (eq <= 0.5).any()
            if hl and (not ok or np.argmax(eq <= 0.5) < np.argmax(eq >= 6)): l50 += 1
            if ok: hits.append(s)
        eps = []
        for s in hits:
            if eps and s - eps[-1][-1] <= 1: eps[-1].append(s)
            else: eps.append([s])
        print(f"{v} m={m}: windows {n}, x6 {len(hits)} ({len(hits)/n:.1%}), lost50 first {l50/n:.1%}, episodes {len(eps)}")
        for e in eps:
            s0 = e[0]; sel = (d >= s0) & (d < s0 + 30)
            print("   episode start %s..%s (%d starts): trades %d, short share %.0f%%, own %.2f%%, always-short %.2f%%" %
                  (pd.Timestamp(e[0] * DAY, unit="ms").date(), pd.Timestamp(e[-1] * DAY, unit="ms").date(), len(e),
                   sel.sum(), 100 * (side[sel] < 0).mean(), 100 * T.tb_roe.to_numpy()[sel].mean(), 100 * sh[sel].mean()))
