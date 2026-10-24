"""Verifier stage B: from /dev/shm/claude_verify_fy/hourly.npz (v_hourly.py)

1. Real numbers for every 1h source on 15m / 30m entries: pooled with - all (per year block, SEL, CONF), with - its
   coin-flip twin, split of with - all into a timing part ((with + twin)/2 - all) and a direction part ((with - twin)/2),
   month-clustered t (same formula as fy_analyze.cluster_t).
2. Null A (circular time shift, same shift for all coins / tfs / sources, >= 30 days from 0): the trend series keeps
   its persistence and cross-coin structure but loses its link to the trades. Gives p-values for V4OF4 / DIR and for
   the best source of the whole 1h search (max statistic over all sources).
3. Null B (direction only): keep the hours where the source has a side (|state|) but take the side from the shifted
   V39 supertrend sign: what the time selection alone gives.

    python3 v_perm.py [n_shift] [seed]   -> verify/v_real.csv, /dev/shm/claude_verify_fy/null_<seed>.pkl
"""
import os
import sys
import numpy as np
import pandas as pd

DATA = "/home/user/crypto-bot-research/analysis/review1024/roles/data"
sys.path.insert(0, DATA)
from common import HOUR, ms   # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
Z = np.load("/dev/shm/claude_verify_fy/hourly.npz")
ST, AG, SRCS = Z["ST"], Z["AG"], [str(s) for s in Z["srcs"]]
H0, NH = int(Z["H0"]), int(Z["NH"])
EDG = [ms(x) for x in ("2021-01-01", "2022-01-01", "2023-01-01", "2024-01-01", "2025-01-01", "2026-01-01",
                       "2026-10-01")]
hours_t = H0 + np.arange(NH, dtype=np.int64) * HOUR
BLK = np.searchsorted(np.array(EDG), hours_t, side="right") - 1          # 0..5
d = pd.to_datetime(hours_t, unit="ms", utc=True)
MON = np.array((d.year - 2021) * 12 + d.month - 1)
SEL_B, CONF_B = [0, 1, 2], [3, 4, 5]
NB, NM = 6, int(MON.max()) + 1
TFN = ("15m", "30m")

# all-signal sums per tf: per block and per month
ALLB = np.zeros((2, NB, 3))
ALLM = np.zeros((2, NM, 3))
for ti in range(2):
    a = AG[ti].sum(axis=(0, 2))                     # [hour, 3]
    for k in range(3):
        ALLB[ti, :, k] = np.bincount(BLK, weights=a[:, k], minlength=NB)
        ALLM[ti, :, k] = np.bincount(MON, weights=a[:, k], minlength=NM)


def with_sums(state, ti, group=BLK, ng=NB):
    """state [coin, hour] int8 -> with-sums per group [ng, 3] (n, w, opp)."""
    L = (state == 1)
    S = (state == -1)
    x = (AG[ti, :, :, 0, :] * L[..., None] + AG[ti, :, :, 1, :] * S[..., None]).sum(0)   # [hour, 3]
    return np.stack([np.bincount(group, weights=x[:, k], minlength=ng) for k in range(3)], -1)


def reads(state, ti):
    W = with_sums(state, ti)
    A = ALLB[ti]
    o = {}
    for nm, bl in (("SEL", SEL_B), ("CONF", CONF_B)):
        w, a = W[bl].sum(0), A[bl].sum(0)
        o[f"mW_{nm}"], o[f"mAll_{nm}"], o[f"mOpp_{nm}"] = w[1] / w[0], a[1] / a[0], w[2] / w[0]
        o[f"eff_{nm}"] = o[f"mW_{nm}"] - o[f"mAll_{nm}"]
        o[f"flip_{nm}"] = o[f"mW_{nm}"] - o[f"mOpp_{nm}"]
        o[f"timing_{nm}"] = (o[f"mW_{nm}"] + o[f"mOpp_{nm}"]) / 2 - o[f"mAll_{nm}"]
        o[f"dir_{nm}"] = o[f"flip_{nm}"] / 2
        o[f"n_{nm}"] = w[0]
    with np.errstate(invalid="ignore", divide="ignore"):
        effb = W[:, 1] / W[:, 0] - A[:, 1] / A[:, 0]
        flipb = (W[:, 1] - W[:, 2]) / W[:, 0]
    for b in range(NB):
        o[f"eff_y{b}"] = effb[b]
        o[f"flip_y{b}"] = flipb[b]
    o["years_pos"] = int(np.sum(effb > 0))
    o["years_flip_pos"] = int(np.sum(flipb > 0))
    return o


def cluster_t(state, ti):
    Wm = with_sums(state, ti, MON, NM)
    out = {}
    for nm, (ma, mb) in (("SEL", (0, 36)), ("CONF", (36, 69))):
        w, a = Wm[ma:mb], ALLM[ti, ma:mb]
        N1, N2 = w[:, 0].sum(), a[:, 0].sum()
        mu1, mu2 = w[:, 1].sum() / N1, a[:, 1].sum() / N2
        u = (w[:, 1] - mu1 * w[:, 0]) / N1 - (a[:, 1] - mu2 * a[:, 0]) / N2
        M = (w[:, 0] > 0).sum()
        out[f"t_eff_{nm}"] = (mu1 - mu2) / np.sqrt((u ** 2).sum() * M / max(M - 1, 1))
        dd = w[:, 1] - w[:, 2]
        muf = dd.sum() / N1
        uf = (dd - muf * w[:, 0]) / N1
        out[f"t_flip_{nm}"] = muf / np.sqrt((uf ** 2).sum() * M / max(M - 1, 1))
    return out


def main():
    nsh = int(sys.argv[1]) if len(sys.argv) > 1 else 500
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 20261024
    rows = []
    for si, s in enumerate(SRCS):
        if s == "j_V39":
            continue
        for ti in range(2):
            st = ST[:, si]
            if not np.any(st):
                continue
            r = {"src": s, "tf": TFN[ti], **reads(st, ti), **cluster_t(st, ti)}
            rows.append(r)
    R = pd.DataFrame(rows)
    R.to_csv(os.path.join(HERE, "v_real.csv"), index=False, float_format="%.6g")
    sidx = {s: i for i, s in enumerate(SRCS)}
    live = [i for i, s in enumerate(SRCS) if s != "j_V39" and np.any(ST[:, i])]
    rng = np.random.default_rng(seed)
    lo, hi = 24 * 30, NH - 24 * 30
    shifts = rng.integers(lo, hi, nsh)
    V39 = ST[:, sidx["j_V39"]]
    nul = []
    for k, L in enumerate(shifts):
        rolled = np.roll(ST, -L, axis=2)
        for ti in range(2):
            for si in live:
                st = rolled[:, si]
                r = reads(st, ti)
                rec = {"shift": int(L), "src": SRCS[si], "tf": TFN[ti], "kind": "A"}
                rec.update({c: r[c] for c in ("eff_SEL", "eff_CONF", "flip_SEL", "flip_CONF", "years_pos",
                                              "years_flip_pos", "timing_SEL", "timing_CONF")})
                nul.append(rec)
            # direction-only null for the two judges: keep |state| hours, side from the shifted V39
            for nm in ("j_V4OF4", "j_DIR"):
                st = (np.abs(ST[:, sidx[nm]]) * np.roll(V39, -L, axis=1)).astype(np.int8)
                r = reads(st, ti)
                rec = {"shift": int(L), "src": nm, "tf": TFN[ti], "kind": "B"}
                rec.update({c: r[c] for c in ("eff_SEL", "eff_CONF", "flip_SEL", "flip_CONF", "years_pos",
                                              "years_flip_pos", "timing_SEL", "timing_CONF")})
                nul.append(rec)
        if k % 50 == 0:
            print("shift", k, flush=True)
    Nn = pd.DataFrame(nul)
    Nn.to_pickle(f"/dev/shm/claude_verify_fy/null_{seed}.pkl")
    print("null rows", len(Nn))


if __name__ == "__main__":
    main()
