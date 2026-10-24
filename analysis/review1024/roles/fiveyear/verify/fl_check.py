"""Verifier (luck / multiple testing) -- step 2: re-derive the 'direction skill' numbers from the rebuilt cell table
(/dev/shm/claude_verify_fl/cells.pkl) and test them against drift and overlap.
    python3 fl_check.py <out_dir>"""
import os
import sys
FY = "/home/user/crypto-bot-research/analysis/review1024/roles/fiveyear"
sys.path.insert(0, FY)
import fy_common
fy_common.SHM = "/dev/shm/claude_verify_fl"
from fy_analyze import *          # noqa

OUT = sys.argv[1]
D = pd.read_pickle("/dev/shm/claude_verify_fl/cells.pkl")
PB = 35.0 * PAYBACK
Wf = D[(D.SEL_nW >= 60) & (D.SEL_MW >= 12)].copy()
print("with family", len(Wf))
Wf["pS"] = pval(Wf.SEL_tFlip.to_numpy(), Wf.SEL_MW.to_numpy())
Wf["bhS"] = bh(Wf.pS.to_numpy())
print("SEL BH pass (flip)", int(Wf.bhS.sum()), " t>3:", int((Wf.SEL_tFlip > 3).sum()))
G = Wf[Wf.bhS & (Wf.SEL_mW + PB > 0)]
print("G cells", len(G))
# compare to the study file
fp = pd.read_csv(os.path.join(FY, "flip_picked.csv"))
key = lambda z: set(zip(z["name"], z.etf, z.htf, z.kind, z.source))
print("flip_picked rows", len(fp), " same set as ours:", key(fp) == key(Wf[Wf.bhS]))
# CONF read of the 374 vs others
sel = Wf[Wf.bhS]
oth = Wf[~Wf.bhS]
for nm, z in (("374", sel), ("others", oth)):
    ok = z.CONF_nW > 0
    zz = z[ok]
    print(nm, "CONF cells", len(zz), "share mW>mWo", round(((zz.CONF_mW > zz.CONF_mWo)).mean(), 4),
          "cell avg mW", round(zz.CONF_mW.mean(), 5), "mWo", round(zz.CONF_mWo.mean(), 5),
          "trade-wtd mW", round((zz.CONF_mW * zz.CONF_nW).sum() / zz.CONF_nW.sum(), 5),
          "mWo", round((zz.CONF_mWo * zz.CONF_nW).sum() / zz.CONF_nW.sum(), 5))
    for th in (30, 60):
        zt = z[z.CONF_nW >= th]
        print("   n>=", th, len(zt), "share", round((zt.CONF_mW > zt.CONF_mWo).mean(), 4))
pC = pval(sel.CONF_tFlip.to_numpy(), sel.CONF_MW.to_numpy())
print("CONF BH among 374:", int(bh(pC).sum()), " CONF p<0.05:", int((pC < 0.05).sum()), " CONF tFlip>2:",
      int((sel.CONF_tFlip > 2).sum()))
# composition
print("\n374 by pair:\n", sel.groupby(["etf", "htf"]).size().to_string())
print("374 by kind:", sel.groupby("kind").size().to_dict())
print("374 distinct (pair,source):", sel.groupby(["etf", "htf", "kind", "source"]).ngroups,
      " distinct entries (name,etf):", sel.groupby(["name", "etf"]).ngroups)
print("374 by role:", sel.groupby("role").size().to_dict())
print("374 SEL long share: mean", round(sel.SEL_lsW.mean(), 3), "q10/50/90", sel.SEL_lsW.quantile([.1, .5, .9]).round(3).tolist(),
      " others mean", round(oth.SEL_lsW.mean(), 3))
print("374 CONF long share: mean", round(sel.CONF_lsW.mean(), 3), " others", round(oth.CONF_lsW.mean(), 3))
# drift-expected flip difference: a long with-trade's (w - o) under no timing info = barL - barS of its tf/period
for per in ("SEL", "CONF"):
    for nm, z in (("374", sel), ("others", oth)):
        z = z[z[f"{per}_nW"] > 0]
        drift = (2 * z[f"{per}_lsW"] - 1) * (z[f"{per}_barL"] - z[f"{per}_barS"])
        act = z[f"{per}_mW"] - z[f"{per}_mWo"]
        print(per, nm, "actual flip diff cell avg", round(act.mean(), 5), "drift-expected", round(drift.mean(), 5),
              " share act>drift", round((act > drift).mean(), 4), " share act>0", round((act > 0).mean(), 4))
    print(per, "bar long", D[f"{per}_barL"].groupby(D.etf).first().round(5).to_dict(), "bar short",
          D[f"{per}_barS"].groupby(D.etf).first().round(5).to_dict())
Wf.to_pickle(os.path.join(OUT, "Wf.pkl"))
