"""Verifier: one-position account + goal bootstrap of OBV20@4h>RSI@1h|a2 on CONF (study's own frame/one_position/
account/goal_bootstrap, rebuilt cache), plus P(x6) at margins up to 100 % and the largest single-trade ROE.
Run from this folder without -I: python3 vacct.py"""
import os, sys, json
import numpy as np
VHERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, "/home/user/crypto-bot-research/analysis/review1024/roles/obvstoch")
import oscore as O
O.CACHE = "/dev/shm/claude_verify_rsi1h"
from oscore import *
import accounts as AC
D = O.load_all()
CELL = "OBV20@4h>RSI@1h|a2"
a, b = O.P["CONF"]
b_eff = min(b, ext_end())
out = {}
for pb in (False, True):
    S = AC.frame(D, CELL, 1, "CONF", pb)
    Tk = S[RD.one_position(S, "X")]
    r = RD.account(Tk, "X", margin=0.4, start=a, end=b_eff)
    roe = np.maximum(Tk.X_roe.to_numpy(float), -1)
    rec = {"acct_m40": r, "max_trade_roe": float(roe.max()), "q99_trade_roe": float(np.quantile(roe, 0.99))}
    for mg in (0.4, 0.7, 1.0):
        gb = RD.goal_bootstrap(Tk, "X", margin=mg, days=(a, b_eff), n_boot=4000)
        rec[f"goal_m{int(mg*100)}"] = gb
    out["payback" if pb else "no_payback"] = rec
json.dump(out, open(os.path.join(VHERE, "vacct.json"), "w"), indent=1, default=float)
print(json.dumps(out, indent=1, default=float))
