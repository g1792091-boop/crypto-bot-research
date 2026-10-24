"""Look-ahead verifier, step 6: effect of the trades still open at the data end (why == 3, dropped by fw_lib.roe) and
of the H2 trades whose exits run past the split; counts with / without them."""
import sys
sys.path.insert(0, "/home/user/crypto-bot-research/analysis/review1024/roles/forward")
from fw_lib import *  # noqa

S = load("sig")
E = S[S.role != "trend"].reset_index(drop=True)
side = E.side.to_numpy()
a = np.zeros(len(E), np.int8)
for t_, h_ in AUTO.items():
    m = E.tf.to_numpy() == t_
    a[m] = (state(E, "Jdir", h_) * side)[m]
r_drop = roe(E, "w35")
r_mark = np.maximum(35 * E.w35_r.to_numpy(float), -1)
why = E.w35_why.to_numpy()
t = E.t.to_numpy()
for per, (pa, pb) in PERIOD.items():
    mp = (t >= pa) & (t < pb)
    o = []
    for cl, c in (("with", 1), ("against", -1), ("neutral", 0)):
        m = mp & (a == c)
        o.append(f"{cl}: n={int(m.sum())} closed={int((m & (why != 3)).sum())} open={int((m & (why == 3)).sum())} "
                 f"drop={np.nanmean(r_drop[m]) * 100:.2f}% mark={np.mean(r_mark[m]) * 100:.2f}%")
    print(per, " | ".join(o))
# exits that end after the data end are impossible; exits of H1 signals that end in H2
k = E.w35_k.to_numpy()
cross = (t < SPLIT) & (t + (k + 1) * MIN > SPLIT)
print("H1 signals whose exit falls in H2:", int(cross.sum()))
# signals in the last hours: entry minute after the data end?
print("entry minute >= data end:", int(((t >= DATA_END)).sum()), "| NaN outcomes not open:", int((np.isnan(E.w35_r.to_numpy()) ).sum()))
