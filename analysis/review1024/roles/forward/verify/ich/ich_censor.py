"""Trades of the five a2 family cells that were still OPEN at the data end (why == 3, dropped from the H2 read): how
many, and what they were worth marked at the last close (does dropping them flatter the +3.39 %?)."""
import sys
sys.path.insert(0, "/home/user/crypto-bot-research/analysis/review1024/roles/forward")
from fw_lib import *  # noqa
CELLS = [("other", "4h", "1d", "c_T5_ST10_3"), ("breakout", "4h", "1d", "Jlive"), ("range", "4h", "1d", "l_OBV_S"),
         ("timing", "1h", "4h", "c_N07_ICHI_CMO"), ("reversal", "1h", "4h", "c_N07_ICHI_CMO")]
S = load("sig")
S = S[S.role != "trend"]
tot_n = tot_s = 0
for role, tf, htf, src in CELLS:
    D = S[(S.role == role) & (S.tf == tf)]
    w = (state(D, src, htf).astype(int) * D.side.to_numpy(int)) == 1
    h2 = D.t.to_numpy() >= SPLIT
    op = D.a2_why.to_numpy() == 3
    x = np.maximum(30 * D.a2_r.to_numpy(float), -1)
    m = w & h2 & op
    ok = w & h2 & ~op & np.isfinite(x)
    print(role, tf, "open at end:", int(m.sum()), "marked mean ROE:", round(float(x[m].mean()), 4) if m.any() else None,
          "| closed:", int(ok.sum()), round(float(x[ok].mean()), 4))
    tot_n += int(m.sum()) + int(ok.sum())
    tot_s += float(x[m].sum()) + float(x[ok].sum())
print("pooled incl. open-at-end marked at the last close:", tot_n, round(tot_s / tot_n, 4))
