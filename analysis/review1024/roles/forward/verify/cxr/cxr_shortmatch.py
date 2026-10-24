"""tf-matched 'always short' baseline for the 574 pooled H2 rows of the a2 family TOP5 (each row compared with the
H2 mean of shorting every bar close of its own timeframe). Read-only.  python3 cxr_shortmatch.py"""
import os, sys
FW = "/home/user/crypto-bot-research/analysis/review1024/roles/forward"
sys.path.insert(0, FW)
from fw_lib import *  # noqa
B = load("base"); rs = roe(B, "a2", True)
ok = (B.t.to_numpy() >= SPLIT) & np.isfinite(rs) & (B.a2_opp_why.to_numpy() != 3)
base = {tf: float(np.mean(rs[ok & (B.tf.to_numpy() == tf)])) for tf in TFS}
S = load("sig"); S = S[S.role != "trend"].reset_index(drop=True)
P = pd.read_csv(os.path.join(FW, "search_picks.csv")); P = P[(P.exit == "a2") & (P.level == "F")]
rows = []
for _, c in P.iterrows():
    role, tf = c.key.split("|")
    m = (S.role.to_numpy() == role) & (S.tf.to_numpy() == tf) & ((state(S, c.src, c.htf) * S.side.to_numpy()) == 1)
    X = S[m].copy(); X["prio"] = int(c["rank"]); rows.append(X)
A = pd.concat(rows); A["roe"] = roe(A, "a2"); A = A[(A.t >= SPLIT) & (A.a2_why != 3) & np.isfinite(A.roe)]
A["bs"] = A.tf.map(base)
U = A.sort_values("prio").drop_duplicates(["coin", "e", "side"])
print("always-short H2 by tf", {k: round(100 * v, 2) for k, v in base.items()})
for lab, X in (("pooled", A), ("unique", U), ("named1h", A[A.prio.isin([4, 5])])):
    print(lab, len(X), "mean", round(100 * X.roe.mean(), 2), "tf-matched short baseline", round(100 * X.bs.mean(), 2),
          "excess", round(100 * (X.roe - X.bs).mean(), 2), "tf counts", X.tf.value_counts().to_dict())
