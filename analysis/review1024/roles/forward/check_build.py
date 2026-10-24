import sys, os
sys.path.insert(0, "/home/user/crypto-bot-research/analysis/review1024/roles/data")
import rolesdata as RD
from common import *
FOUT = os.path.join(SCR, "forward")
S = pd.read_pickle(os.path.join(FOUT, "sig.pkl.gz"))
F = RD.forward("rule")
F = F[(F.coin >= 0) & F.tf.isin(TFS)]
key = ["t", "coin", "side", "tf"]
F2 = F.rename(columns={"strategy": "name"})
M = S.merge(F2[key + ["name", "j1h_dir", "j4h_dir", "j1d_dir", "tj_why_1022", "w35_r", "a2_r"]], on=key + ["name"], suffixes=("", "_f"))
print("matched", len(M), "of", len(F2))
for h in HTFS:
    print(h, "dir equal", np.mean(np.nan_to_num(M[f"J{h}_dir"].to_numpy()) == np.nan_to_num(M[f"j{h}_dir"].to_numpy())))
print("w35 r equal", np.nanmax(np.abs(M.w35_r - M.w35_r_f)), "a2", np.nanmax(np.abs(M.a2_r - M.a2_r_f)))
a = M.tj_why_1022.fillna("").astype(str); b = M.tj_why_1022_f.fillna("").astype(str)
print("why1022 equal", (a == b).mean()); print(pd.crosstab(a, b))
# market
SPLIT = ms("2026-10-15 03:00")
B = pd.read_pickle(os.path.join(FOUT, "base.pkl.gz"))
for ci, c in enumerate(COINS):
    g = grid(c)
    def px(t): return g["o"][(t - T0) // MIN]
    a0, s, e = ms("2026-10-05 15:00"), SPLIT, ms("2026-10-24 14:00")
    print(c, "H1 %+.1f%%" % (100 * (px(s) / px(a0) - 1)), "H2 %+.1f%%" % (100 * (px(e) / px(s) - 1)), "all %+.1f%%" % (100 * (px(e) / px(a0) - 1)))
    drop(c)
b15 = B[(B.tf == "15m") & (B.w35_why != 3)]
for lab, m in (("H1", b15.t < SPLIT), ("H2", b15.t >= SPLIT), ("all", b15.t > 0)):
    x = b15[m]
    print(lab, "always-long w35 ROE %.2f%% win %.2f | always-short %.2f%% win %.2f | a2 long %.2f short %.2f" % (
        100 * x.w35_r.mean() * 35, (x.w35_r > 0).mean(), 100 * x.w35_opp_r.mean() * 35, (x.w35_opp_r > 0).mean(),
        100 * x.a2_r.mean() * 30, 100 * x.a2_opp_r.mean() * 30))
