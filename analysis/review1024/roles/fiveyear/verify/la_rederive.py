"""Look-ahead / time-alignment verifier (lens: look-ahead, alignment, data errors) -- re-derive the headline claim of
the five-year study WITHOUT its accumulator (acc.npy is gone) straight from the data layer's per-signal files:

  * entry-role signals (range, pullback, breakout, reversal, timing, other) on 15m / 30m (and 1h / 4h for the rest of
    the friend's mapping), all coins, 2021-01-01 .. the forward end, own-bar warm-up nb >= 300 (RD.signals default)
  * w35 outcome (35x, -50 % net stop, ladder) from the grid; rows kept only when w35 / w30 / w35s20 / a2 and the
    opposite twins are finite and not open at the data end (as build_acc does)
  * the higher bar index computed TWO ways: RD.last_closed (searchsorted of bar close) and by plain arithmetic
    (bar open = floor(t / htf) * htf - htf); they must agree
  * V4OF4 / DIR from the stored judge columns of that bar; warm-up: higher bar nb >= 300
  * lag diagnostics: the same filter read on the PREVIOUS closed bar (lag -1, stale) and on the NEXT bar (lag +1 =
    the bar that is still open at the signal = deliberate look-ahead) -> shows what a timing leak would look like

Writes la_rederive_blocks.csv (per block: n / sum for all and with, per lag and source) and la_rederive_sid.csv (per
strategy per period).   Run from this folder without -I:  python3 la_rederive.py"""
import os
import sys
import time

DATA = "/home/user/crypto-bot-research/analysis/review1024/roles/data"
sys.path.insert(0, DATA)
import rolesdata as RD          # noqa: E402
from common import *            # noqa: E402,F401

HERE = os.path.dirname(os.path.abspath(__file__))
ENTRY = ["range", "pullback", "breakout", "reversal", "timing", "other"]
EDGES = np.array([ms("2021-01-01"), ms("2022-01-01"), ms("2023-01-01"), ms("2024-01-01"), ms("2025-01-01"),
                  ms("2026-01-01"), ms("2026-10-01"), RD.PERIODS["fwd"][0], GRID_END, RD.PERIODS["fwd"][1]], np.int64)
BLOCKS = ["Y21", "Y22", "Y23", "Y24", "Y25", "Y26a", "O26a", "F1", "F2"]
PAIRS = [("15m", "1h"), ("30m", "1h"), ("1h", "4h"), ("4h", "1d")]
HMS = {"1h": HOUR, "4h": 4 * HOUR, "1d": DAY}


def judge_states(Z, ii):
    v = (Z["j_V39"].astype(np.int16)[ii] + Z["j_S6"].astype(np.int16)[ii] + Z["j_OBV"].astype(np.int16)[ii]
         + Z["j_N12"].astype(np.int16)[ii])
    return {"V4OF4": np.where(np.abs(v) == 4, np.sign(v), 0).astype(np.int8), "DIR": Z["j_dir"][ii].astype(np.int8)}


def main():
    t0 = time.time()
    rows, srows = [], []
    mism_idx = 0
    checked_idx = 0
    for ci, coin in enumerate(COINS):
        for etf, htf in PAIRS:
            S = RD.signals(roles_=ENTRY, tfs=(etf,), period=(int(EDGES[0]), int(EDGES[-1])), coins=[coin])
            S = RD.add_outcomes(S, ["w35", "w30", "w35s20", "a2"])
            ok = np.ones(len(S), bool)
            for v in ("w35", "w30", "w35s20", "a2"):
                for sfx in ("", "_opp"):
                    ok &= np.isfinite(S[f"{v}{sfx}_r"].to_numpy()) & (S[f"{v}{sfx}_why"].to_numpy() != 3)
            S = S[ok].reset_index(drop=True)
            t = S.t.to_numpy(np.int64)
            side = S.side.to_numpy(np.int8)
            w = S.w35_roe.to_numpy(float)
            wo = S.w35_opp_roe.to_numpy(float)
            Z = RD._states(coin, htf)
            hc = Z["ts"] + TF_MIN[htf] * MIN
            idx = last_closed(hc, t)
            # arithmetic: the last higher bar closed at or before t opens at floor(t / H) * H - H (UTC grid from T0)
            H = HMS[htf]
            open_ar = (t - T0) // H * H + T0 - H
            idx2 = np.searchsorted(Z["ts"], open_ar)
            good = (idx2 < len(Z["ts"]))
            good[good] &= Z["ts"][idx2[good]] == open_ar[good]
            checked_idx += len(idx)
            mism_idx += int(((idx != idx2) & good).sum() + (~good & (idx >= 0)).sum())
            assert (hc[idx[idx >= 0]] <= t[idx >= 0]).all()
            nxt = np.clip(idx + 1, 0, len(hc) - 1)
            assert (hc[nxt[idx + 1 < len(hc)]] > t[idx + 1 < len(hc)]).all()
            blk = np.searchsorted(EDGES, t, side="right") - 1
            blk[(blk < 0) | (blk >= len(BLOCKS))] = -1
            sid = S.sid.to_numpy(int)
            for lag in (0, -1, 1):
                ii = idx + lag
                valid = (idx >= 1) & (ii >= 0) & (ii < len(hc))
                iic = np.clip(ii, 0, len(hc) - 1)
                warm = valid & (Z["nb"][np.clip(idx, 0, len(hc) - 1)] >= 300)
                J = judge_states(Z, iic)
                for src, st in J.items():
                    withm = warm & (st == side)
                    for b, bn in enumerate(BLOCKS):
                        qa = warm & (blk == b)
                        qw = withm & (blk == b)
                        rows.append({"coin": coin, "etf": etf, "htf": htf, "lag": lag, "src": src, "block": bn,
                                     "nALL": int(qa.sum()), "sALL": float(w[qa].sum()), "nW": int(qw.sum()),
                                     "sW": float(w[qw].sum()), "sWo": float(wo[qw].sum()),
                                     "nlongW": int((side[qw] > 0).sum())})
                    if lag == 0:
                        for b, bn in enumerate(BLOCKS):
                            qa = warm & (blk == b)
                            qw = withm & (blk == b)
                            ca = np.bincount(sid[qa], minlength=200)
                            sa = np.bincount(sid[qa], weights=w[qa], minlength=200)
                            cw = np.bincount(sid[qw], minlength=200)
                            sw = np.bincount(sid[qw], weights=w[qw], minlength=200)
                            for s_ in np.flatnonzero(ca):
                                srows.append({"coin": coin, "etf": etf, "htf": htf, "src": src, "block": bn, "sid": s_,
                                              "nALL": ca[s_], "sALL": sa[s_], "nW": cw[s_], "sW": sw[s_]})
            # stacked: 15m / 30m with 1h V4OF4 AND the 4h held judge on its last closed 4h bar
            if htf == "1h":
                Z4 = RD._states(coin, "4h")
                hc4 = Z4["ts"] + 240 * MIN
                i4 = last_closed(hc4, t)
                warm = (idx >= 1) & (Z["nb"][np.clip(idx, 0, len(hc) - 1)] >= 300)
                v4 = judge_states(Z, np.clip(idx, 0, len(hc) - 1))["V4OF4"]
                d4 = np.where(i4 >= 0, Z4["j_dir"][np.clip(i4, 0, len(hc4) - 1)], 0)
                st = (v4 == side) & (d4 == side)
                for b, bn in enumerate(BLOCKS):
                    qa = warm & (blk == b)
                    qw = qa & st
                    rows.append({"coin": coin, "etf": etf, "htf": htf, "lag": 0, "src": "V4OF4+4hDIR", "block": bn,
                                 "nALL": int(qa.sum()), "sALL": float(w[qa].sum()), "nW": int(qw.sum()),
                                 "sW": float(w[qw].sum()), "sWo": float(wo[qw].sum()), "nlongW": int((side[qw] > 0).sum())})
            log(coin, etf, htf, len(S), f"{time.time() - t0:.0f}s")
            del S
        RD._GR.pop(coin, None)
        RD._SIG.pop(coin, None)
        for h in HTFS:
            RD._STATES.pop((coin, h), None)
    pd.DataFrame(rows).to_csv(os.path.join(HERE, "la_rederive_blocks.csv"), index=False)
    pd.DataFrame(srows).to_csv(os.path.join(HERE, "la_rederive_sid.csv"), index=False)
    log("higher-bar index checked", checked_idx, "arithmetic mismatches", mism_idx)


if __name__ == "__main__":
    main()
