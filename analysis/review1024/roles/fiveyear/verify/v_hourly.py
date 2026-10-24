"""Verifier (independent of build_acc / fy_analyze): rebuild the 15m / 30m -> 1h alignment effect straight from the data
layer, then test it against nulls that keep the trend series' persistence.

Stage A (this file, main): per coin and entry tf, aggregate every entry-role signal (2021-01-01 .. 2026-10-01, own and
1h warm-up >= 300 bars, all four exits finite and closed, as build_acc) by the hour of its last CLOSED 1h bar and side:
n, sum w35 ROE, sum w35 ROE of the opposite side. Build per coin the hourly state arrays of every 1h source (52 c_, 52 l_,
judge variants RAW3 / DIR / DIR_ADX20 / V2OF4 / V4OF4 and raw V39 sign). Saved to /dev/shm/claude_verify_fy/hourly.npz.

    python3 v_hourly.py
"""
import os
import sys
import time
import numpy as np

DATA = "/home/user/crypto-bot-research/analysis/review1024/roles/data"
sys.path.insert(0, DATA)
import rolesdata as RD                   # noqa: E402
from common import COINS, HOUR, ms, last_closed, TF_MIN, MIN   # noqa: E402

OUTD = "/dev/shm/claude_verify_fy"
os.makedirs(OUTD, exist_ok=True)
ENTRY_ROLES = ["range", "pullback", "breakout", "reversal", "timing", "other"]
H0 = ms("2021-01-01")
H1 = ms("2026-10-01")
NH = (H1 - H0) // HOUR


def judge_hourly(Z, ii, ok):
    v = sum(Z[f"j_{k}"].astype(np.int16)[ii] for k in ("V39", "S6", "OBV", "N12"))
    d = Z["j_dir"][ii].astype(np.int8)
    adx = Z["j_adx"][ii]
    out = {"RAW3": Z["j_raw3"][ii].astype(np.int8), "DIR": d,
           "DIR_ADX20": np.where(adx >= 20.0, d, 0).astype(np.int8),
           "V2OF4": np.where(np.abs(v) >= 2, np.sign(v), 0).astype(np.int8),
           "V4OF4": np.where(np.abs(v) == 4, np.sign(v), 0).astype(np.int8),
           "V39": Z["j_V39"][ii].astype(np.int8)}
    return {k: np.where(ok, a, 0).astype(np.int8) for k, a in out.items()}


def main():
    t0 = time.time()
    R = RD.roles()
    tr = list(R["roles"]["trend_incl_dual"])
    srcs = [f"c_{s}" for s in tr] + [f"l_{s}" for s in tr] + ["j_RAW3", "j_DIR", "j_DIR_ADX20", "j_V2OF4", "j_V4OF4",
                                                              "j_V39"]
    ST = np.zeros((len(COINS), len(srcs), NH), np.int8)
    AG = np.zeros((2, len(COINS), NH, 2, 3))      # [tf, coin, hour, side(L,S), (n, w, opp)]
    hour_close = H0 + np.arange(NH, dtype=np.int64) * HOUR
    for ci, coin in enumerate(COINS):
        Z = RD._states(coin, "1h")
        hc = Z["ts"] + 60 * MIN
        idx = last_closed(hc, hour_close)
        ok = idx >= 1
        ii = np.clip(idx, 0, len(hc) - 1)
        ok &= Z["nb"][ii] >= 300
        J = judge_hourly(Z, ii, ok)
        for si, s in enumerate(srcs):
            if s.startswith("j_"):
                ST[ci, si] = J[s[2:]]
            else:
                a = Z.get(s)
                if a is not None:
                    ST[ci, si] = np.where(ok, a[ii], 0)
        for ti, tf in enumerate(("15m", "30m")):
            S = RD.signals(roles_=ENTRY_ROLES, tfs=[tf], coins=[coin], period=(int(H0), int(H1)))
            S = RD.add_outcomes(S, ["w35", "w30", "w35s20", "a2"])
            good = np.ones(len(S), bool)
            for v in ("w35", "w30", "w35s20", "a2"):
                for sfx in ("", "_opp"):
                    good &= np.isfinite(S[f"{v}{sfx}_r"].to_numpy()) & (S[f"{v}{sfx}_why"].to_numpy() != 3)
            S = S[good]
            t = S.t.to_numpy(np.int64)
            h = (t - H0) // HOUR                     # last closed 1h bar = the one closing at H0 + h hours
            # warm-up of the real 1h bar at the signal (study: idx >= 1 and nb >= 300)
            idx_s = last_closed(hc, t)
            w = (idx_s >= 1)
            w[w] &= Z["nb"][idx_s[w]] >= 300
            assert np.all(hc[np.clip(idx_s, 0, None)][w] == hour_close[h[w]]), "hour mapping differs from last_closed"
            sd = S.side.to_numpy()
            for k, lab in ((0, 1), (1, -1)):
                m = w & (sd == lab)
                AG[ti, ci, :, k, 0] += np.bincount(h[m], minlength=NH)
                AG[ti, ci, :, k, 1] += np.bincount(h[m], weights=S.w35_roe.to_numpy()[m], minlength=NH)
                AG[ti, ci, :, k, 2] += np.bincount(h[m], weights=S.w35_opp_roe.to_numpy()[m], minlength=NH)
            print(coin, tf, len(S), int(w.sum()), f"{time.time() - t0:.0f}s", flush=True)
        RD._GR.pop(coin, None)
        RD._SIG.pop(coin, None)
    np.savez(os.path.join(OUTD, "hourly.npz"), ST=ST, AG=AG, srcs=np.array(srcs), H0=H0, NH=NH)
    print("done", f"{time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
