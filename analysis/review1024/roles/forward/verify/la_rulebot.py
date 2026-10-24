"""Look-ahead verifier, step 4: the rule bot's real trades split by the judge -- time alignment and data checks."""
import sys
sys.path.insert(0, "/home/user/crypto-bot-research/analysis/review1024/roles/forward")
from fw_lib import *  # noqa

F0 = RD.forward("rule")
print("rows", len(F0))
F = F0[(F0.taken == 1) & F0.tr_roe.notna() & F0.tf.isin(TFS) & (F0.coin >= 0)].copy()
print("taken w/ roe, 15m-4h, 6 coins:", len(F), "| tr_open among them:", int((F.tr_open == 1).sum()) if "tr_open" in F else "na")
print("tr_id unique:", F.tr_id.is_unique, "dups:", int(F.tr_id.duplicated().sum()))
print("groups:", F.group.value_counts().to_dict())
# time alignment
et = pd.to_datetime(F.tr_entry_time, utc=True, errors="coerce").astype("int64") // 10**6 if F.tr_entry_time.dtype == object else F.tr_entry_time
F["et"] = et
print("entry - signal close (s): min", (F.et - F.t).min() / 1e3, "median", (F.et - F.t).median() / 1e3, "max", (F.et - F.t).max() / 1e3)
for h in HTFS:
    m = F.tj_htf == h
    bcl = F.loc[m, f"j{h}_bar_close"]
    print(h, "rows", int(m.sum()), "judged bar close > signal close:", int((bcl > F.loc[m, "t"]).sum()),
          "| judged bar older than one htf bar:", int((F.loc[m, "t"] - bcl >= TF_MIN[h] * MIN).sum()))
# split
nf = ~F.group.isin(["flip"])
X = F[nf]
al = np.sign(np.nan_to_num(X.tj_dir.to_numpy())) * X.side.to_numpy()
tot = X.tr_pnl.sum()
print("non-flip trades", len(X), "pnl", round(tot), "roe", round(X.tr_roe.mean() * 100, 2))
for cl, c in (("with", 1), ("against", -1), ("neutral", 0)):
    m = al == c
    print(cl, int(m.sum()), "roe", round(X.tr_roe[m].mean() * 100, 2), "win", round((X.tr_roe[m] > 0).mean() * 100, 1),
          "pnl", round(X.tr_pnl[m].sum()), "share", round(X.tr_pnl[m].sum() / tot * 100, 1))
# closed-only (drop trades still open at export)
if "tr_open" in X:
    Y = X[X.tr_open != 1]
    al2 = np.sign(np.nan_to_num(Y.tj_dir.to_numpy())) * Y.side.to_numpy()
    print("closed only", len(Y), "pnl", round(Y.tr_pnl.sum()))
    for cl, c in (("with", 1), ("against", -1), ("neutral", 0)):
        m = al2 == c
        print("  ", cl, int(m.sum()), round(Y.tr_roe[m].mean() * 100, 2), round(Y.tr_pnl[m].sum()))
# within side
for sd in (1, -1):
    m0 = X.side.to_numpy() == sd
    print("side", sd, {cl: (int((m0 & (al == c)).sum()), round(X.tr_roe[m0 & (al == c)].mean() * 100, 2)) for cl, c in (("with", 1), ("against", -1), ("neutral", 0))})
# tj_dir stored vs states-based judge on the same signal time
J = RD.add_judge(X[["t", "e", "coin", "tf", "side"]].reset_index(drop=True), htf="auto", check=False)
print("tj_dir stored == recomputed:", float(np.mean(np.nan_to_num(J.tj_dir.to_numpy()) == np.nan_to_num(X.tj_dir.to_numpy()))))
# does a strategy's signal row ever map to an entry earlier than the signal close?
print("entries before signal close:", int((X.et < X.t).sum()))
