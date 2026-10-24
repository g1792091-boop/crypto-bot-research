"""Verifier: how much do the 160 friend-family cells overlap? (a) agreement of the OBV trend states at the entry bars,
(b) share of with-trend signals shared between trend variants (same coin, tf, bar, timing, htf), (c) the per-cell
contrasts are 4 exits x the same signal sets."""
import os, sys, itertools, json
sys.path.insert(0, "/home/user/crypto-bot-research/analysis/review1024/roles/obvstoch")
import oscore as O
from oscore import *
VC = "/dev/shm/claude_verify_cost"
a, b = O.P["FIVE"]
agree = {}; share = {}
for (tf, htf) in O.MAPS:
    st_all = {T: [] for T in O.OBV_TRENDS}; sig_all = {Ot: [] for Ot in O.SRSI}
    for coin in COINS:
        Z = np.load(os.path.join(VC, f"{coin}.npz"))
        e = Z[f"{tf}_e"]; t = T0 + e * MIN; m = (t >= a) & (t < b)
        for T in O.OBV_TRENDS:
            st_all[T].append(Z[f"{tf}_st_{htf}_{T}"][m])
        for Ot in O.SRSI:
            sig_all[Ot].append(Z[f"{tf}_sig_{Ot}"][m])
    st = {T: np.concatenate(v) for T, v in st_all.items()}; sg = {k: np.concatenate(v) for k, v in sig_all.items()}
    for T1, T2 in itertools.combinations(O.OBV_TRENDS, 2):
        agree[f"{tf}>{htf} {T1}~{T2}"] = float((st[T1] == st[T2]).mean())
    for Ot in O.SRSI:
        sets = {T: (sg[Ot] != 0) & (st[T] == sg[Ot]) for T in O.OBV_TRENDS}
        for T1, T2 in itertools.combinations(O.OBV_TRENDS, 2):
            u = (sets[T1] | sets[T2]).sum()
            share[f"{tf}>{htf} {Ot} {T1}&{T2}"] = float((sets[T1] & sets[T2]).sum() / u) if u else np.nan
    kd, x = sg["SRSI_KD"] != 0, sg["SRSI_X"] != 0
    share[f"{tf}>{htf} SRSI_KD&SRSI_X same bar"] = float((kd & x).sum() / (kd | x).sum())
ag = pd.Series(agree); sh = pd.Series(share)
out = {"trend_state_agreement_mean": {p: float(ag[[k for k in ag.index if p in k]].mean()) for p in
                                      ("OBV20~OBV30", "OBV20~OBV50", "OBV30~OBV50", "OBV30~OBVSL10", "OBV20~OBVSL10", "OBV50~OBVSL10")},
       "with_signal_jaccard_mean": {p: float(sh[[k for k in sh.index if p in k]].mean()) for p in
                                    ("OBV20&OBV30", "OBV20&OBV50", "OBV30&OBV50", "OBV30&OBVSL10")},
       "SRSI_KD_SRSI_X_same_bar_jaccard": float(sh[[k for k in sh.index if "same bar" in k]].mean())}
print(json.dumps(out, indent=1))
json.dump(out, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "voverlap.json"), "w"), indent=1)
