"""Verifier (lens: look-ahead / time alignment / data errors) -- step 1: rebuild the B_sel_with20 bot with the study's
own loaders (cellsig.cell_rows -> goalpath.bot_rows -> goalpath.read), print SEL / CONF / LATE / FWD, and save the
signal rows + taken CONF trades for the independent checks (tz_b_hand.py, tz_b_cut.py).
    python3 tz_b_rebuild.py <outdir>"""
import os
import sys
import time
VHERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(VHERE))
from goalpath import *          # noqa: E402,F401  (cellsig, fy_common, rolesdata)

OUTD = sys.argv[1]
t0 = time.time()
sel = pd.read_csv(os.path.join(os.path.dirname(VHERE), "shortlist.csv"))
specs = [(r["name"], r.etf, r.htf, r.source.split(":")[0], r.source.split(":")[1], "W")
         for _, r in sel[sel.cond == "W"].iterrows()]
assert len(specs) == 20
S = bot_rows(specs)
print("rows", len(S), f"{time.time() - t0:.0f}s")
S.to_pickle(os.path.join(OUTD, "B_rows.pkl"))
for per in ("SEL", "CONF", "LATE", "FWD"):
    o, T = read(S, per)
    print(per, {k: (round(v, 5) if isinstance(v, float) else v) for k, v in o.items()})
    T.to_pickle(os.path.join(OUTD, f"B_taken_{per}.pkl"))
