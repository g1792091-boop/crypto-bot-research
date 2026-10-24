"""Verifier (lens: costs / executability / overlap) for the 'direction skill' claim, part 1: overlap of the 374 BH cells.
Reads a copy of the rebuilt cell table (/dev/shm/claude_verify_xc/cells.pkl, built by the study's own build_acc +
fy_analyze code) and flip_picked.csv; writes nothing in the study folder.
    python3 xc_overlap.py"""
import os
import sys
FY = "/home/user/crypto-bot-research/analysis/review1024/roles/fiveyear"
sys.path.insert(0, FY)
import pandas as pd
import numpy as np
from fy_analyze import bh, pval, ENTRY_ROLES

PB = 35 * 2 * 0.9 * 0.00042
fam = pd.read_pickle("/dev/shm/claude_verify_xc/cells.pkl")
print(fam[["pair", "src", "name", "etf", "htf", "kind", "source", "role"]].head(3).to_string() if "name" in fam else fam.columns[-60:].tolist())
Wf = fam[(fam.SEL_nW >= 60) & (fam.SEL_MW >= 12)].copy()
Wf["bh"] = bh(pval(Wf.SEL_tFlip.to_numpy(), Wf.SEL_MW.to_numpy()))
print("with family", len(Wf), "BH pass", int(Wf.bh.sum()))
Wf["beat"] = Wf.CONF_mW > Wf.CONF_mWo
ok = Wf.CONF_nW > 0
print("CONF beat: BH", Wf[Wf.bh & ok].beat.mean().round(3), "others", Wf[~Wf.bh & ok].beat.mean().round(3))
print("CONF cell avg BH: W", Wf[Wf.bh].CONF_mW.mean().round(4), "opp", Wf[Wf.bh].CONF_mWo.mean().round(4))
B = Wf[Wf.bh]
Wf["ent"] = Wf.name + "@" + Wf.etf
B = Wf[Wf.bh]
g = B.groupby("ent").agg(n=("beat", "size"), beat=("beat", "mean"), mW=("CONF_mW", "mean"), mWo=("CONF_mWo", "mean"),
                         role=("role", "first"))
# the same entries' OTHER with-cells (non-BH) beat rate: is the carry-over the entry's or the trend source's?
o = Wf[~Wf.bh & ok & Wf.ent.isin(g.index)].groupby("ent").beat.agg(["size", "mean"]).rename(columns={"size": "n_other", "mean": "beat_other"})
g = g.join(o)
g = g.sort_values("n", ascending=False)
pd.set_option("display.width", 200)
print(g.round(3).to_string())
print("entries", len(g), "entry-weighted beat rate (BH cells):", g.beat.mean().round(3),
      "| entries with majority beat:", (g.beat > 0.5).sum(), "of", len(g))
print("same entries' other cells beat rate (cell-weighted):", Wf[~Wf.bh & ok & Wf.ent.isin(g.index)].beat.mean().round(3),
      "entry-weighted:", g.beat_other.mean().round(3))
print("all other cells (entries not in BH set):", Wf[~Wf.bh & ok & ~Wf.ent.isin(g.index)].beat.mean().round(3))
top = g.index[0]
print("without", top, ": BH beat", B[B.ent != top].beat.mean().round(3), "n", (B.ent != top).sum())
# role split
print(B.groupby("role").beat.agg(["size", "mean"]).round(3))
# G subset (SEL mean + payback > 0)
G = B[B.SEL_mW + PB > 0]
print("G cells", len(G), "entries", G.ent.nunique(), "CONF beat", G.beat.mean().round(3))
print(G.groupby("ent").size().sort_values(ascending=False).head(8).to_string())
