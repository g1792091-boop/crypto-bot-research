"""Which strategies / sets make up the 574 pooled H2 rows (verifier helper)."""
import sys
sys.path.insert(0, "/home/user/crypto-bot-research/analysis/review1024/roles/forward")
from fw_lib import *  # noqa
import pandas as pd
C = pd.read_csv("ich_rewalk.csv")
C = C[~C.twin]
S = load("sig")
K = S[["coin", "tf", "e", "side", "name", "set", "role"]]
K = K.assign(coinname=np.asarray(COINS)[K.coin.to_numpy(int)])
M = C.merge(K, left_on=["coin", "tf", "e", "side"], right_on=["coinname", "tf", "e", "side"], how="left")
print(len(C), len(M))
print(M.groupby(["cell", "set", "name"]).size().to_string())
