"""Verifier -- step 5: B_sel_with20 with-signals in LATE / FWD that the study dropped because a trade (any exit, either
side) was still open at the data end (cellsig.cell_rows drops them before the one-position path).
    python3 tz_b_fwdopen.py"""
import os
import sys
VH = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(VH))
import cellsig as CS            # noqa: E402
from cellsig import *           # noqa: E402,F401

sel = pd.read_csv(os.path.join(os.path.dirname(VH), "shortlist.csv"))
specs = [(r["name"], r.etf, r.htf, r.source.split(":")[0], r.source.split(":")[1], "W")
         for _, r in sel[sel.cond == "W"].iterrows()]
span = (int(EDGES[7]), int(EDGES[9]))
tot = kept = op35 = 0
rows = []
for name, etf, htf, kind, source, cond in specs:
    S = RD.signals(names=[name], tfs=[etf], period=span)
    if not len(S):
        continue
    S = RD.add_outcomes(S, ["w35", "w30", "w35s20", "a2"])
    idx = RD.htf_index(S, htf)
    st = np.zeros(len(S), int)
    for ci, coin in enumerate(COINS):
        m = (S.coin.to_numpy() == ci) & (idx >= 0)
        if not m.any():
            continue
        Z = RD._states(coin, htf)
        if kind == "j":
            v = sum(Z[f"j_{k}"].astype(int) for k in ("V39", "S6", "OBV", "N12"))
            v = np.where(np.abs(v) == 4, np.sign(v), 0)
            st[m] = v[idx[m]]
        else:
            st[m] = Z[f"{kind}_{source}"][idx[m]]
    w = st == S.side.to_numpy()
    anyopen = np.zeros(len(S), bool)
    for v in ("w35", "w30", "w35s20", "a2"):
        for sfx in ("", "_opp"):
            anyopen |= ~np.isfinite(S[f"{v}{sfx}_r"].to_numpy()) | (S[f"{v}{sfx}_why"].to_numpy() == 3)
    o35 = S.w35_why.to_numpy() == 3
    tot += int(w.sum())
    kept += int((w & ~anyopen).sum())
    op35 += int((w & o35).sum())
    for _, r in S[w & anyopen].iterrows():
        rows.append({"cell": f"{name}@{etf}", "t_utc": pd.to_datetime(r.t, unit="ms", utc=True), "side": r.side,
                     "w35_why": r.w35_why, "w35_roe_mark": r.w35_roe})
print("FWD with-signals", tot, "kept", kept, "dropped (any exit open at the end)", tot - kept, "w35 open", op35)
print(pd.DataFrame(rows).to_string())
