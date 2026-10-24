"""Verifier: re-derive the 19-day luck windows of luck.py from my own rebuilt cache (independent code), in UTC days (as
the study) and in KST days (as the report's 19-day table), and add:
  - share of past windows whose family best >= the KST +2.73 % (not only the UTC +2.42 %)
  - n-matched version (best among cells with n >= 90 in the window, the target had 95)
  - the single cell's own history: share of past windows where OBV30@4h>SRSI_X@1h|a2 itself was >= obs
  - pick-the-winner -> next 19 days (non-overlapping pairs), overall and conditional on the winner's pick mean >= obs
Writes vwin.json. Run from this folder: python3 vwin.py
"""
import json
import os
import sys

sys.path.insert(0, "/home/user/crypto-bot-research/analysis/review1024/roles/obvstoch")
import oscore as O  # noqa: E402
from oscore import *  # noqa: E402,F401,F403

O.CACHE = "/dev/shm/claude_verify_srsix"
HERE = os.path.dirname(os.path.abspath(__file__))
TARGET = "OBV30@4h>SRSI_X@1h|a2"
W = 19

if __name__ == "__main__":
    D = O.load_all()
    CELLS = O.cells()
    ids = [O.cell_id(*c) for c in CELLS]
    isA = np.array([c[2] in O.OBV_TRENDS and c[3] in O.SRSI for c in CELLS])
    a, b = ms("2020-03-01"), ext_end()
    out = {"ext_end": str(pd.to_datetime(b, unit="ms"))}
    for tz, off in (("utc", 0), ("kst", KST)):
        d0 = (a + off) // DAY
        nd = int((b - 1 + off) // DAY - d0 + 1)
        S = np.zeros((len(CELLS), nd))
        N = np.zeros((len(CELLS), nd))
        for i, c in enumerate(CELLS):
            R = O.rows(D, *c, (a, b))
            t = T0 + R["e"].astype(np.int64) * MIN
            di = ((t + off) // DAY - d0).astype(np.int64)
            S[i] = np.bincount(di, weights=R["roe"], minlength=nd)[:nd]
            N[i] = np.bincount(di, minlength=nd)[:nd]
        cS = np.c_[np.zeros(len(CELLS)), np.cumsum(S, 1)]
        cN = np.c_[np.zeros(len(CELLS)), np.cumsum(N, 1)]
        starts = np.arange(0, nd - W + 1)
        wS = cS[:, starts + W] - cS[:, starts]
        wN = cN[:, starts + W] - cN[:, starts]
        with np.errstate(invalid="ignore", divide="ignore"):
            wM = np.where(wN >= 30, wS / wN, np.nan)
            wM90 = np.where(wN >= 90, wS / wN, np.nan)
        fwd_start = int((ms("2026-10-06") + off) // DAY - d0) if tz == "utc" else int((ms("2026-10-05 15:00") + off) // DAY - d0)
        fi = int(np.flatnonzero(starts == fwd_start)[0])
        past = starts < fwd_start - W
        kT = ids.index(TARGET)
        bestA = np.nanmax(wM[isA], 0)
        bestAll = np.nanmax(wM, 0)
        bestA90 = np.nanmax(np.where(isA[:, None], wM90, np.nan), 0)
        o = {"windows_past": int(past.sum()), "fwd_window_days": [str(pd.to_datetime((d0 + fwd_start) * DAY, unit="ms").date()),
                                                                  str(pd.to_datetime((d0 + fwd_start + W - 1) * DAY, unit="ms").date())],
             "obs_bestA": float(bestA[fi]), "obs_bestA_cell": np.array(ids)[isA][int(np.nanargmax(wM[isA, fi]))],
             "obs_bestAll": float(bestAll[fi]), "obs_target": float(wM[kT, fi]), "obs_target_n": int(wN[kT, fi]),
             "share_bestA_ge_obs": float(np.mean(bestA[past] >= bestA[fi])),
             "share_bestA_ge_0.02725": float(np.mean(bestA[past] >= 0.0272504)),
             "share_bestAll_ge_obs": float(np.mean(bestAll[past] >= bestAll[fi])),
             "share_bestA_n90_ge_obs": float(np.nanmean(bestA90[past] >= wM90[kT, fi])) if np.isfinite(wM90[kT, fi]) else None,
             "share_target_ge_obs": float(np.nanmean(wM[kT][past] >= wM[kT, fi])),
             "target_windows_valid": int(np.isfinite(wM[kT][past]).sum()),
             "median_bestA": float(np.nanmedian(bestA[past]))}
        # pick the winner -> next window (non-overlapping consecutive windows, same rule as luck.py)
        rec = []
        for s0 in range(0, nd - 2 * W + 1, W):
            n1 = N[:, s0:s0 + W].sum(1)
            w1 = np.where(n1 >= 30, S[:, s0:s0 + W].sum(1) / np.maximum(n1, 1), np.nan)
            for lab, mask in (("all", np.ones(len(CELLS), bool)), ("A", isA)):
                w1m = np.where(mask, w1, np.nan)
                if np.all(np.isnan(w1m)):
                    continue
                k = int(np.nanargmax(w1m))
                n2 = N[k, s0 + W:s0 + 2 * W].sum()
                rec.append({"s0": s0, "fam": lab, "cell": ids[k], "pick": float(w1m[k]),
                            "next": float(S[k, s0 + W:s0 + 2 * W].sum() / n2) if n2 else np.nan, "n2": int(n2),
                            "next_contains_fwd": bool(s0 + 2 * W > fwd_start)})
        P = pd.DataFrame(rec)
        for lab in ("all", "A"):
            q = P[P.fam == lab]
            o[f"pick_{lab}_pairs"] = int(len(q))
            o[f"pick_{lab}_mean_next"] = float(q.next.mean())
            o[f"pick_{lab}_share_next_pos"] = float((q.next > 0).mean())
            o[f"pick_{lab}_pooled_next"] = float((q.next * q.n2).sum() / q.n2.sum())
            qq = q[~q.next_contains_fwd]
            o[f"pick_{lab}_mean_next_excl_fwd"] = float(qq.next.mean())
            hi = q[q.pick >= 0.024]
            o[f"pick_{lab}_pick_ge_2.4pct_pairs"] = int(len(hi))
            o[f"pick_{lab}_pick_ge_2.4pct_mean_next"] = float(hi.next.mean()) if len(hi) else None
            o[f"pick_{lab}_pick_ge_2.4pct_share_next_pos"] = float((hi.next > 0).mean()) if len(hi) else None
        out[tz] = o
    json.dump(out, open(os.path.join(HERE, "vwin.json"), "w"), indent=1, default=float)
    print(json.dumps(out, indent=1, default=float))
