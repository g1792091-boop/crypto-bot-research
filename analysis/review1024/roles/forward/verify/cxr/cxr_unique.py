"""Which de-duplication gives the report's '404 entries, +3.33 %, 392 shorts'? Read-only over the cached sig table.
    python3 cxr_unique.py"""
import os, sys
FW = "/home/user/crypto-bot-research/analysis/review1024/roles/forward"
sys.path.insert(0, FW)
from fw_lib import *  # noqa
S = load("sig"); S = S[S.role != "trend"].reset_index(drop=True)
P = pd.read_csv(os.path.join(FW, "search_picks.csv")); P = P[(P.exit == "a2") & (P.level == "F")].sort_values("rank")
side = S.side.to_numpy(); rows = []
for _, c in P.iterrows():
    role, tf = c.key.split("|")
    m = (S.role.to_numpy() == role) & (S.tf.to_numpy() == tf) & ((state(S, c.src, c.htf) * side) == 1)
    X = S[m].copy(); X["prio"] = int(c["rank"]); rows.append(X)
A = pd.concat(rows, ignore_index=True); A["roe"] = roe(A, "a2")
A = A[(A.t >= SPLIT) & (A.a2_why != 3) & np.isfinite(A.roe)]
for key in (["coin","e","side"], ["coin","e","side","tf"], ["coin","e","side","prio"], ["coin","e","side","role"],
            ["coin","t","side","tf"], ["coin","e","tf"], ["coin","e","side","name"]):
    U = A.sort_values("prio").drop_duplicates(key)
    print(key, len(U), round(100*U.roe.mean(), 2), "S", int((U.side<0).sum()), round(100*U.roe[U.side<0].mean(),2),
          "L", int((U.side>0).sum()), round(100*U.roe[U.side>0].mean(),2) if (U.side>0).any() else None,
          day_boot_ci(U.roe.to_numpy(float), U.day.to_numpy(), 2000, 7))
