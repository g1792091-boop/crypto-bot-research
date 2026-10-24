import sys
sys.path.insert(0, "/home/user/crypto-bot-research/analysis/review1024/roles/forward")
from fw_lib import *
S = load("sig")
print(S.shape)
print([c for c in S.columns if not c.startswith(("c1h","c4h","c1d","l1h","l4h","l1d"))])
print(S.role.value_counts())
print(S.tf.value_counts())
