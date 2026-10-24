"""a2 'always short' on H2 per timeframe (every bar close, short side = the *_opp outcome of the base table).
    python3 cxr_short.py"""
import sys
sys.path.insert(0, "/home/user/crypto-bot-research/analysis/review1024/roles/forward")
from fw_lib import *  # noqa
B = load("base")
r = roe(B, "a2", True)
h2 = (B.t.to_numpy() >= SPLIT) & np.isfinite(r) & (B.a2_opp_why.to_numpy() != 3)
for tf in TFS + ("all",):
    m = h2 & ((B.tf.to_numpy() == tf) if tf != "all" else True)
    print(tf, int(m.sum()), round(100 * np.nanmean(r[m]), 2))
