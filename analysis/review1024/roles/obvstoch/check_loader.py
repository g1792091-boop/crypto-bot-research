"""Row-level parity of my cell rows (oscore.rows) with the shared loader path (RD.signals + add_outcomes + add_states)
for cells whose trend exists in the shared states: OBV30 (= c_OBV_S), OBV20 (= c_VO1_OBV_X_MA20), ST (= c_V39_ALL),
ICHI (= c_N12_ICHI_AO). Prints only counts and equality, no means (run before the selection)."""
import sys
import oscore as O
from oscore import *
D = O.load_all()
SRC = {"OBV30": "OBV_S", "OBV20": "VO1_OBV_X_MA20", "ST": "V39_ALL", "ICHI": "N12_ICHI_AO"}
res = []
for (tf, htf) in O.MAPS:
    for T, src in SRC.items():
        for Ot, lib in (("SRSI_KD", "O4_STOCHRSI_ZONE"), ("WR", "O6_WR14")):
            for X in ("w35", "w35s20", "a2"):
                R = O.rows(D, tf, htf, T, Ot, X, "SEL")
                S = RD.signals(names=[lib], tfs=[tf], period=O.P["SEL"])
                S = RD.add_outcomes(S, [X])
                S = RD.add_states(S, htf, [src], kind="c")
                col = f"c{htf}_{src}"
                A = S[(S[col] == S.side) & (S[f"{X}_why"] != 3) & (S[f"{X}_opp_why"] != 3) & S[f"{X}_roe"].notna()]
                A = A.sort_values(["coin", "e"])
                import numpy as np
                order = np.lexsort((R["e"], R["coin"]))
                same_n = len(A) == len(R["roe"])
                eq = same_n and np.allclose(A[f"{X}_roe"].to_numpy(), R["roe"][order], atol=1e-6) and \
                    (A.e.to_numpy() == R["e"][order]).all() and np.allclose(A[f"{X}_opp_roe"].to_numpy(), R["opp"][order], atol=1e-6)
                res.append((tf, htf, T, Ot, X, len(A), len(R["roe"]), bool(eq)))
import pandas as pd
df = pd.DataFrame(res, columns=["tf", "htf", "trend", "timing", "exit", "n_loader", "n_mine", "equal"])
df.to_csv("check_loader.csv", index=False)
print(df.equal.mean(), len(df)); print(df[~df.equal].head())
