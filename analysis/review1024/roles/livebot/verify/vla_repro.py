"""Look-ahead / alignment verifier, part A+B: re-derive the headline numbers from the trade files and check the
time structure of every taken trade (entry minute = signal bar close, one position at a time, forced exits after the
entry, exit minute consistent with the forced minute). Run: python3 vla_repro.py <trades_dir>"""
import os
import sys

import numpy as np
import pandas as pd

TD = sys.argv[1]
MIN, DAY = 60_000, 86_400_000
T0 = int(pd.Timestamp("2020-01-01", tz="UTC").value // 10**6)


def ms(s):
    return int(pd.Timestamp(s, tz="UTC").value // 10**6)


A, B = ms("2024-01-01"), ms("2026-10-05 15:00")
V = ["B0", "B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8", "B9", "B10", "W0", "W3"]
T = {v: pd.read_csv(os.path.join(TD, f"trades_{v}.csv.gz")) for v in V}
rows = []
for v in V:
    D = T[v].sort_values(["e"]).reset_index(drop=True)
    e = D.e.to_numpy(np.int64)
    t = D.t.to_numpy(np.int64)
    k = D.tb_k.to_numpy(np.int64)
    f = D.force.to_numpy(np.int64)
    wait = v.startswith("W")
    ent_ok = ((t - T0) // MIN == e) if not wait else (e >= (t - T0) // MIN)   # wait variants enter later than t
    overlap = (e[1:] <= e[:-1] + k[:-1]).sum()
    force_after = ((f < 0) | (f > e)).all()
    exit_before_force = ((f < 0) | (e + k <= f)).all()
    forced_at = ((D.tb_why == 2) == ((f >= 0) & (e + k == f))).mean()
    P = D[(D.t >= A) & (D.t < B)]
    rows.append(dict(variant=v, n_all=len(D), entry_eq_close=ent_ok.mean(), overlaps=int(overlap),
                     force_after_entry=force_after, exit_le_force=exit_before_force, why2_iff_force=forced_at,
                     n_cl=len(P), roe_cl=P.tb_roe.mean(), opp_cl=P.tb_opp_roe.mean(),
                     n_conf=int((P.period == "confirm").sum()), n_late=int((P.period == "late").sum())))
R = pd.DataFrame(rows)
b0 = R.set_index("variant").roe_cl["B0"]
R["vs_b0"] = R.roe_cl - b0
pd.set_option("display.width", 250)
print(R.to_string())
# joint day bootstrap vs B0 (as lb_variants, seed 3) to re-derive p
B0 = T["B0"][(T["B0"].t >= A) & (T["B0"].t < B)]
for v in V[1:]:
    Tp = T[v][(T[v].t >= A) & (T[v].t < B)]
    dV, d0 = Tp.t.to_numpy() // DAY, B0.t.to_numpy() // DAY
    ud = np.union1d(dV, d0)
    iV, i0 = np.searchsorted(ud, dV), np.searchsorted(ud, d0)
    sV, cV = np.bincount(iV, Tp.tb_roe.to_numpy(), len(ud)), np.bincount(iV, minlength=len(ud))
    s0, c0 = np.bincount(i0, B0.tb_roe.to_numpy(), len(ud)), np.bincount(i0, minlength=len(ud))
    rng = np.random.default_rng(3)
    pk = rng.integers(0, len(ud), (5000, len(ud)))
    diff = sV[pk].sum(1) / np.maximum(cV[pk].sum(1), 1) - s0[pk].sum(1) / np.maximum(c0[pk].sum(1), 1)
    print(v, "vs_b0", round(Tp.tb_roe.mean() - B0.tb_roe.mean(), 5), "p", (diff <= 0).mean())
