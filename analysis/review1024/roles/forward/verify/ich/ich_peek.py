"""Peek: columns of the forward signal table and the a2 family top-5 cells (verifier, look-ahead lens)."""
import sys
sys.path.insert(0, "/home/user/crypto-bot-research/analysis/review1024/roles/forward")
from fw_lib import *  # noqa
S = load("sig")
print(S.shape)
cols = [c for c in S.columns if not (c.startswith("c1h") or c.startswith("c4h") or c.startswith("c1d") or c.startswith("l1h") or c.startswith("l4h") or c.startswith("l1d"))]
print(cols)
print(S.role.value_counts())
for role in ("timing", "reversal"):
    print(role, sorted(S[(S.role == role) & (S.tf == "1h")].name.unique()))
