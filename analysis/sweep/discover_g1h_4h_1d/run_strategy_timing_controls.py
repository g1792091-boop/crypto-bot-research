"""DESCRIPTIVE extra control (not a PREREG rule; changes no decision).

Timing-preserving random-sign negative control on the REAL IS panel.
For every (strategy, H) cell with n >= 100, keep the strategy's actual signal TIMING and cluster
structure, but replace its direction by a random sign drawn per 'episode' (a maximal run of
same-direction signals whose consecutive signal bars are <= H bars apart, i.e. whose forward
windows overlap).  Direction then carries zero information by construction, so p (raw shift
null) and p_vn (A1) should be ~U(0,1) and z should have sd ~1 if the gate's null is calibrated
for THIS strategy's timing.  z sd > 1 on the raw test = the vol-timing anti-conservatism that
A1 is meant to fix.

Also: analytic per-cell MDE80 from the actual gate cell null_sd,
  mde80 = (z_{1-alpha/m} + z_{0.8}) * null_sd, reported relative to mu*_H (m = 666 by default,
the harness's upper bound for the family size).

usage: python3 run_strategy_timing_controls.py --tf 15m --reps 40 --out out
"""
import argparse
import os
import sys
import time

import numpy as np
import pandas as pd
from scipy.stats import norm

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sweep_lib as L  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--tf", required=True)
ap.add_argument("--reps", type=int, default=40)
ap.add_argument("--out", default=os.path.join(HERE, "out"))
ap.add_argument("--m_family", type=int, default=666)
ap.add_argument("--seed", type=int, default=7)
a = ap.parse_args()

t0 = time.time()
panel = L.load_panel(a.tf, "is")
sigs = L.load_signals(os.path.join(a.out, f"signals_is_{a.tf}.npz"))
gate = pd.read_csv(os.path.join(a.out, f"gate_is_{a.tf}.csv"))
zc = norm.isf(L.ALPHA / a.m_family) + norm.isf(0.2)
rng = np.random.default_rng([a.seed, L.tf_minutes(a.tf)])


def episodes(seg: np.ndarray, H: int) -> np.ndarray:
    """episode id per nonzero entry of seg (same sign, gap <= H)."""
    u = np.flatnonzero(seg)
    if len(u) == 0:
        return np.zeros(0, np.int64)
    s = seg[u]
    new = np.ones(len(u), bool)
    new[1:] = (np.diff(u) > H) | (s[1:] != s[:-1])
    return np.cumsum(new) - 1


rows = []
for H in L.HS:
    prep = L._prep_returns(panel, a.tf, "is", H)
    n_min = min(p["N"] for p in prep.values())
    shifts = L.gate_shifts(a.tf, H, n_min, L.B_GATE)
    for name in L.NAMES:
        g = gate[(gate.strategy == name) & (gate.H == H)]
        if g.empty:
            continue
        g = g.iloc[0]
        base = dict(strategy=name, tf=a.tf, H=H, n=int(g["n"]), mu_star=g["mu_star"], null_sd=g["null_sd"],
                    mde80_holm1=zc * g["null_sd"] if np.isfinite(g["null_sd"]) else np.nan)
        base["mde80_over_mu"] = base["mde80_holm1"] / g["mu_star"] if np.isfinite(base["mde80_holm1"]) else np.nan
        if g["n"] < L.MIN_N:
            rows.append(dict(base, reps=0))
            continue
        # episode structure per coin (inside the admissible segment)
        ep = {}
        for c, p in prep.items():
            if c not in sigs[name]:
                continue
            seg = sigs[name][c][p["lo"]:p["hi"]].astype(np.int8)
            ep[c] = (np.flatnonzero(seg), episodes(seg, H))
        n_ep = int(sum(len(np.unique(e)) for _, e in ep.values()))
        zs, zvs, ps, pvs = [], [], [], []
        for _ in range(a.reps):
            ds = {}
            for c, p in prep.items():
                d = np.zeros(len(panel[c]), np.int8)
                if c in ep and len(ep[c][0]):
                    u, e = ep[c]
                    sgn = rng.choice(np.array([-1, 1], np.int8), size=int(e.max()) + 1)
                    d[p["lo"] + u] = sgn[e]
                ds[c] = d
            st = L._cell_stats(ds, prep, shifts, None)
            zs.append(st["z"]); zvs.append(st["z_vn"]); ps.append(st["p"]); pvs.append(st["p_vn"])
        zs, zvs, ps, pvs = map(lambda x: np.asarray(x, float), (zs, zvs, ps, pvs))
        rows.append(dict(base, reps=a.reps, n_episodes=n_ep, sig_per_episode=g["n"] / max(n_ep, 1),
                         rs_z_mean=np.nanmean(zs), rs_z_sd=np.nanstd(zs, ddof=1), rs_rate_p05=np.nanmean(ps < 0.05),
                         rs_z_max=np.nanmax(zs), rs_zvn_mean=np.nanmean(zvs), rs_zvn_sd=np.nanstd(zvs, ddof=1),
                         rs_rate_pvn05=np.nanmean(pvs < 0.05), rs_zvn_max=np.nanmax(zvs),
                         rs_rate_both05=np.nanmean((ps < 0.05) & (pvs < 0.05))))
    print(f"{a.tf} H={H} done {time.time() - t0:.0f}s", flush=True)

res = pd.DataFrame(rows)
res["sec_total"] = time.time() - t0
fn = os.path.join(a.out, f"strategy_timing_controls_is_{a.tf}.csv")
res.to_csv(fn, index=False)
print(res.round(3).to_string(index=False))
print("saved", fn, f"{time.time() - t0:.0f}s")
