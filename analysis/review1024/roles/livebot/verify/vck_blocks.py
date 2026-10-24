"""Verifier: B0 / B2 / B3 own-minus-opposite gap by half-year, and the confirm+late p with day / week / month blocks.
Run: python3 vck_blocks.py <trades_dir>"""
import os, sys
import numpy as np, pandas as pd
TD = sys.argv[1]
DAY = 86_400_000
def ms(s): return int(pd.Timestamp(s, tz="UTC").value // 10**6)
A, B = ms("2024-01-01"), ms("2026-10-05 15:00")
def boot(g, x, n=5000, seed=1):
    ud, inv = np.unique(g, return_inverse=True)
    s = np.bincount(inv, weights=x); c = np.bincount(inv)
    pk = np.random.default_rng(seed).integers(0, len(ud), (n, len(ud)))
    return s[pk].sum(1) / np.maximum(c[pk].sum(1), 1)
for v in ("B0", "B1", "B2", "B3"):
    T = pd.read_csv(os.path.join(TD, f"trades_{v}.csv.gz"))
    T["gap"] = T.tb_roe - T.tb_opp_roe
    ts = pd.to_datetime(T.t, unit="ms")
    T["half"] = ts.dt.year.astype(str) + "H" + np.where(ts.dt.month <= 6, "1", "2")
    H = T[T.period != "fwd"].groupby("half").agg(n=("gap", "size"), own=("tb_roe", "mean"), opp=("tb_opp_roe", "mean"), gap=("gap", "mean"))
    print(f"\n{v} gap by half-year (pt):", " ".join(f"{i}:{100*r.gap:+.1f}({int(r.n)})" for i, r in H.iterrows()))
    P = T[(T.t >= A) & (T.t < B)]
    d = P.gap.to_numpy()
    for lab, g in (("day", P.t // DAY), ("week", P.t // (7 * DAY)), ("month", ts[(T.t >= A) & (T.t < B)].dt.to_period("M").astype(str))):
        bs = boot(np.asarray(g), d)
        print(f"  conf+late gap {100*d.mean():+.2f}pt  {lab:5s} blocks: p(opp>=own) one-sided {(bs >= 0).mean():.4f}  two-sided {2*min((bs >= 0).mean(), (bs <= 0).mean()):.4f}")
