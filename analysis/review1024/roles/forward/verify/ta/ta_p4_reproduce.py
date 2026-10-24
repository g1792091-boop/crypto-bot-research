"""Verifier (time alignment lens): reproduce P4 a2 / w35 from the cached sig table, list the taken trades."""
import sys, os, json
sys.path.insert(0, "/home/user/crypto-bot-research/analysis/review1024/roles/forward")
from fw_lib import *  # noqa
from fw_combo import add_roe

S = add_roe(load("sig"))
mem = json.load(open(os.path.join(REPO, "deploy", "combo.trend.json")))["members"]
mm = np.zeros(len(S), bool)
for it in mem:
    mm |= (S.name.to_numpy() == it["strategy"]) & (S.tf.to_numpy() == it["tf"])
print("member signals", mm.sum(), "pass 1022", (mm & (S.tj_why_1022.to_numpy() == "")).sum())
print(S[mm].tj_why_1022.value_counts().to_dict())
X = S[mm & (S.tj_why_1022.to_numpy() == "")].copy()
X["prio"] = X.coin.astype(int) * 10 + X.tf.map({t: i for i, t in enumerate(TFS)}).astype(int)
out = {}
for v in ("a2", "w35"):
    for per in ("all", "H1", "H2"):
        a, b = PERIOD[per]
        Y = X[(X.t >= a) & (X.t < b) & (X[f"{v}_why"] != 3)].reset_index(drop=True)
        T = Y[RD.one_position(Y, v, priority="prio")]
        A = RD.account(T, v, margin=0.4, start=a, end=b)
        print(v, per, len(Y), A["n"], round(A["mean_roe"], 5), round(A["win"], 4), round(A["final_x"], 4), round(A["max_dd"], 4))
        if per == "all":
            cols = ["t", "coin", "name", "tf", "side", "e", "nb", f"{v}_r", f"{v}_roe", f"{v}_k", f"{v}_why", f"{v}_opp_roe", "blk",
                    "tj_dir_auto"]
            T[cols].to_csv(f"ta_p4_{v}_trades.csv", index=False)
    # open-at-end signals of the members in the window
    Z = X[(X[f"{v}_why"] == 3)]
    print(v, "open at end (excluded) signals:", len(Z), Z[["t", "coin", "name", "tf", "side", f"{v}_roe", f"{v}_k"]].to_string() if len(Z) else "")
