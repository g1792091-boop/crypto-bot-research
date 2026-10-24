"""Verifier (costs lens): re-derive the friend-family (A) contrast numbers from the study's all_cells.csv.gz."""
import sys
import pandas as pd, numpy as np
A = pd.read_csv(sys.argv[1])
OBV = ("OBV20", "OBV30", "OBV50", "OBVSL10")
A["famA"] = A.trend.isin(OBV) & A.timing.isin(("SRSI_KD", "SRSI_X"))
A["diff"] = A.mean_roe - A.mean_against
for fam, q in (("A", A[A.famA]), ("all", A), ("nonOBV_SRSI", A[~A.trend.isin(OBV) & A.timing.isin(("SRSI_KD","SRSI_X"))]),
               ("OBV_other_timing", A[A.trend.isin(OBV) & ~A.timing.isin(("SRSI_KD","SRSI_X"))])):
    g = q.groupby("period").apply(lambda g: pd.Series({"cells": len(g), "mean_roe": g.mean_roe.mean(),
        "against": g.mean_against.mean(), "diff": g["diff"].mean(), "diff_pos_share": (g["diff"] > 0).mean(),
        "coin": g.mean_opp.mean(), "trend_only": g.trend_only.mean(), "sig_minus_trendonly": (g.mean_roe - g.trend_only).mean(),
        "n_med": g.n.median()}))
    print("==", fam); print(g.round(4).to_string())
for T in ("OBV20","OBV30","OBV50","OBVSL10","ST","EMA21_52","ICHI","J3","J3A"):
    q = A[(A.trend == T) & A.timing.isin(("SRSI_KD","SRSI_X"))]
    g = q.groupby("period").apply(lambda g: pd.Series({"diff": g["diff"].mean(), "pos": (g["diff"] > 0).mean()}))
    print(T, g.round(4).T.to_string().replace("\n", " | "))
