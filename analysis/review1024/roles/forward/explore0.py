import sys, time
sys.path.insert(0, "/home/user/crypto-bot-research/analysis/review1024/roles/data")
import rolesdata as RD
import numpy as np, pandas as pd
t0=time.time()
S = RD.signals(period="fwd", min_nb=300)
print(len(S), time.time()-t0)
print(S.groupby(["tf"]).size())
print(S.groupby("role").size())
F = RD.forward("rule")
print(F.shape); print(list(F.columns))
print(F.acct_status.value_counts(dropna=False)); print(F.group.value_counts(dropna=False))
print(F[['acct','group','strategy','tf']].drop_duplicates().shape)
print(F.acct.nunique())
print(F[F.taken==1].groupby('group').agg(n=('tr_roe','size'), roe=('tr_roe','mean'), pnl=('tr_pnl','sum')))
