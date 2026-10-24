"""Entry-delay robustness (time alignment): re-walk every taken trade of 2024-01 .. 2026-10-05 entering 1 or 2 minutes
after the signal bar's close (the live bot reads the bars 8-20 s after the close), same forced minute, and compare
each variant with B0 on the same delay (joint day bootstrap as lb_variants). Run: python3 vla_delay.py <trades_dir>"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import lb_core as L  # noqa: E402
from lb_core import *  # noqa: E402,F401,F403
TD = sys.argv[1]
A, B = ms("2024-01-01"), ms("2026-10-05 15:00")
V = ["B0", "B3", "B4", "B5", "B6", "B9"]
res = {}
for d in (0, 1, 2):
    for v in V:
        T = pd.read_csv(os.path.join(TD, f"trades_{v}.csv.gz"))
        T = T[(T.t >= A) & (T.t < B)].reset_index(drop=True)
        T["e"] = T.e + d
        T["force"] = np.where(T.force >= 0, np.maximum(T.force, T.e + 1), -1)
        r, k, w = L.run_walk(T, "force")
        T["roe_d"] = L.lev_of(T.coin.to_numpy()) * r
        res[(d, v)] = T
for d in (0, 1, 2):
    B0 = res[(d, "B0")]
    line = f"delay {d} min: B0 {100 * B0.roe_d.mean():+.2f}%"
    for v in V[1:]:
        Tp = res[(d, v)]
        dV, d0 = Tp.t.to_numpy() // DAY, B0.t.to_numpy() // DAY
        ud = np.union1d(dV, d0)
        iV, i0 = np.searchsorted(ud, dV), np.searchsorted(ud, d0)
        sV, cV = np.bincount(iV, Tp.roe_d.to_numpy(), len(ud)), np.bincount(iV, minlength=len(ud))
        s0, c0 = np.bincount(i0, B0.roe_d.to_numpy(), len(ud)), np.bincount(i0, minlength=len(ud))
        pk = np.random.default_rng(3).integers(0, len(ud), (5000, len(ud)))
        diff = sV[pk].sum(1) / np.maximum(cV[pk].sum(1), 1) - s0[pk].sum(1) / np.maximum(c0[pk].sum(1), 1)
        line += f" | {v} {100 * Tp.roe_d.mean():+.2f}% (vs B0 {100 * (Tp.roe_d.mean() - B0.roe_d.mean()):+.2f}, p {(diff <= 0).mean():.3f})"
    print(line, flush=True)
chk = res[(0, "B6")]
print("delay 0 re-walk == file tb_roe (B6):", np.allclose(chk.roe_d, chk.tb_roe, atol=1e-6))
