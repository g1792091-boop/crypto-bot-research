"""Look-ahead verifier, step 9: per-mapping with-minus-against gaps (w35, Jdir, non-trend entries) within side and with
a UTC-day bootstrap CI (same day draw for both groups), to see how firm 'one step up is best' and 'the daily judge
hurt' are."""
import sys
sys.path.insert(0, "/home/user/crypto-bot-research/analysis/review1024/roles/forward")
from fw_lib import *  # noqa
from fw_extra import diff_ci

S = load("sig")
E = S[S.role != "trend"].reset_index(drop=True)
side = E.side.to_numpy()
r = roe(E, "w35")
day = E.day.to_numpy()
ok = np.isfinite(r)
for tf, h in MAPS:
    mt = (E.tf.to_numpy() == tf) & ok
    a = state(E, "Jdir", h) * side
    line = [f"{tf}->{h}"]
    for sd, lab in ((0, "both"), (1, "L"), (-1, "S")):
        ms_ = mt & ((side == sd) if sd else True)
        w, g = ms_ & (a == 1), ms_ & (a == -1)
        if w.sum() < 5 or g.sum() < 5:
            line.append(f"{lab}: n {int(w.sum())}/{int(g.sum())}")
            continue
        d, lo, hi, p = diff_ci(r[w], r[g], day[w], day[g])
        line.append(f"{lab}: {np.mean(r[w])*100:.2f} vs {np.mean(r[g])*100:.2f} gap {d*100:+.1f} [{lo*100:+.1f},{hi*100:+.1f}] n {int(w.sum())}/{int(g.sum())}")
    print(" | ".join(line))
