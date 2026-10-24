"""How many forward-period rows the study drops because the trade is still open at the data end (why == 3), all vs
V4OF4-with, 15m / 30m entry-role signals (the FWD numbers exclude them).   python3 la_fwdopen.py"""
import sys
sys.path.insert(0, "/home/user/crypto-bot-research/analysis/review1024/roles/data")
import rolesdata as RD
from common import *
tot = {}
for coin in COINS:
    for tf in ("15m", "30m"):
        S = RD.signals(roles_=["range", "pullback", "breakout", "reversal", "timing", "other"], tfs=(tf,), period="fwd", coins=[coin])
        S = RD.add_outcomes(S, ["w35"])
        Z = RD._states(coin, "1h")
        idx = last_closed(Z["ts"] + HOUR, S.t.to_numpy(np.int64))
        v = sum(Z[f"j_{k}"].astype(int)[idx] for k in ("V39", "S6", "OBV", "N12"))
        w = (np.abs(v) == 4) & (np.sign(v) == S.side.to_numpy())
        op = S.w35_why.to_numpy() == 3
        for k, m in (("all", np.ones(len(S), bool)), ("with", w)):
            a = tot.setdefault((tf, k), [0, 0, 0.0])
            a[0] += int(m.sum()); a[1] += int((m & op).sum()); a[2] += float(S.w35_roe.to_numpy()[m & op].sum())
for k, (n, no, s) in sorted(tot.items()):
    print(k, "rows", n, "open at end (dropped)", no, f"{100*no/n:.1f}%", "their mark-to-market mean ROE %", round(100 * s / max(no, 1), 2))
