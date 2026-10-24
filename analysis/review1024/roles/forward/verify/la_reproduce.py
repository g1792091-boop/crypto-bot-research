"""Look-ahead verifier, step 1: reproduce the headline principle numbers from the cached sig table."""
import sys
sys.path.insert(0, "/home/user/crypto-bot-research/analysis/review1024/roles/forward")
from fw_lib import *  # noqa

S = load("sig")
print("all signals", len(S), "cols", S.shape[1])
print("roles", S.role.value_counts().to_dict())
E = S[S.role != "trend"].reset_index(drop=True)
side = E.side.to_numpy()
a = np.zeros(len(E), np.int8)
for t_, h_ in AUTO.items():
    m = E.tf.to_numpy() == t_
    a[m] = (state(E, "Jdir", h_) * side)[m]
r = roe(E, "w35")
t = E.t.to_numpy()
print("entry signals", len(E), "open (NaN)", int(np.isnan(r).sum()))
for per, (pa, pb) in PERIOD.items():
    mp = (t >= pa) & (t < pb)
    for cl, c in (("with", 1), ("against", -1), ("neutral", 0)):
        m = mp & (a == c)
        print(per, cl, int(m.sum()), round(float(np.nanmean(r[m])) * 100, 2), "win", round(float(np.nanmean(r[m][np.isfinite(r[m])] > 0)) * 100, 1))
for sd in (1, -1):
    for cl, c in (("with", 1), ("against", -1)):
        m = (a == c) & (side == sd)
        print("side", sd, cl, int(m.sum()), round(float(np.nanmean(r[m])) * 100, 2))
for tf in TFS:
    for cl, c in (("with", 1), ("against", -1)):
        m = (a == c) & (E.tf.to_numpy() == tf)
        print("tf", tf, cl, int(m.sum()), round(float(np.nanmean(r[m])) * 100, 2))
print("t range KST", kst([t.min(), t.max()]))
print("DATA_END", kst([DATA_END]), "SPLIT", kst([SPLIT]))
