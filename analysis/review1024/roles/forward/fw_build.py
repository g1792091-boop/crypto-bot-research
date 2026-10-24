"""Forward study of the friend's role principle: feature tables (built once, cached in the scratchpad).

SIG  = every recomputed signal of all 121 coded strategies on 15m / 30m / 1h / 4h with bar close in the forward window
       (2026-10-05 15:00 .. 10-24 15:00 UTC = 10-06 .. 10-24 KST; the recomputed signals match the rule bot's log 100 %,
       ../data/selfcheck_report.json), with
         outcomes  w35 / w30 / w35s20 / a2 (+ the opposite side = coin-flip twin on the same entry),
         blk       entry-block code (0 none, 1 KST weekend, 2 macro, 3 US open),
         states    c<h>_<src> condition state and l<h>_<src> latch of the 52 trend sources on the last CLOSED 1h / 4h / 1d
                   bar, J<h>_<V39 S6 OBV N12 raw3 dir adx adx_prev> the live trend bot's judge on that bar,
         tj_why_1022 / tj_why_1021  the live trend bot's full entry checks on its own mapping (auto).
BASE = every bar close of each coin on 15m / 30m / 1h / 4h in the same window, side +1 (long; *_opp = short), with the
       same outcomes and states: the "follow the trend at any bar" baseline (trend luck without an entry strategy).

Run from this folder without -I:  python3 fw_build.py
Output: <scratchpad>/review1024_roles/forward/{sig,base}.pkl.gz"""
import os
import sys
import time

sys.path.insert(0, "/home/user/crypto-bot-research/analysis/review1024/roles/data")
import rolesdata as RD  # noqa: E402
from common import *     # noqa: E402,F401

FOUT = os.path.join(SCR, "forward")
os.makedirs(FOUT, exist_ok=True)
SOURCES = RD.roles()["roles"]["trend_incl_dual"]          # 52 trend sources (condition + latch states)
JK = ("V39", "S6", "OBV", "N12", "raw3", "dir", "adx", "adx_prev")
VARS = ("w35", "a2", "w30", "w35s20")


def features(S):
    S = RD.add_outcomes(S, VARS, opp=True)
    S = RD.add_blocks(S)
    for h in HTFS:
        S = RD.add_states(S, h, SOURCES, kind="c")
        S = RD.add_states(S, h, SOURCES, kind="l")
        J = RD.add_judge(S[["t", "e", "coin", "tf", "side"]], htf=h, check=False)
        for k in JK:
            S[f"J{h}_{k}"] = J[f"tj_{k}"].to_numpy(np.float32)
    # compact dtypes
    for c in S.columns:
        if S[c].dtype == np.float64 and not c.endswith("_r"):
            S[c] = S[c].astype(np.float32)
    return S


def build_sig():
    t0 = time.time()
    S = RD.signals(period="fwd", min_nb=300)
    log("signals", len(S), round(time.time() - t0, 1))
    S = features(S)
    J = RD.add_judge(S[["t", "e", "coin", "tf", "side", "name"]], htf="auto", check=True)
    S["tj_why_1022"] = J["tj_why_1022"].fillna("").astype(str).to_numpy()
    S["tj_why_1021"] = J["tj_why_1021"].fillna("").astype(str).to_numpy()
    S["tj_dir_auto"] = J["tj_dir"].to_numpy(np.float32)
    log("sig features", S.shape, round(time.time() - t0, 1))
    return S


def build_base():
    rows = []
    a, b = RD.PERIODS["fwd"]
    for ci, coin in enumerate(COINS):
        z = RD._sigfile(coin)
        for tf in TFS:
            n = int(z[f"{tf}_n"])
            e0 = int(z[f"{tf}_e0"])
            tfm = TF_MIN[tf]
            nb = np.arange(n)
            e = e0 + nb.astype(np.int64) * tfm
            t = T0 + e * MIN
            m = (t >= a) & (t < b)
            rows.append(pd.DataFrame({"tf": tf, "coin": np.int8(ci), "side": np.int8(1), "t": t[m], "e": e[m],
                                      "nb": nb[m].astype(np.int32)}))
    B = pd.concat(rows, ignore_index=True)
    B["name"] = "ALLBARS"
    B = B.sort_values(["t", "coin", "tf"]).reset_index(drop=True)
    B = features(B)
    log("base", B.shape)
    return B


if __name__ == "__main__":
    S = build_sig()
    S.to_pickle(os.path.join(FOUT, "sig.pkl.gz"), compression="gzip")
    B = build_base()
    B.to_pickle(os.path.join(FOUT, "base.pkl.gz"), compression="gzip")
    for f in ("sig.pkl.gz", "base.pkl.gz"):
        log(f, round(os.path.getsize(os.path.join(FOUT, f)) / 1e6, 1), "MB")
