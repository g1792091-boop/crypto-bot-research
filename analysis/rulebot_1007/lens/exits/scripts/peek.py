import site, sys
sys.dont_write_bytecode = True
us = site.getusersitepackages()
if us not in sys.path: sys.path.append(us)
import pandas as pd
X = pd.read_csv(sys.argv[1])
print(X.shape)
print(X.groupby(['run','kind']).size().unstack(0).fillna(0).astype(int))
print(X[X.kind=='base'].groupby(['run','kind_acct','timeframe']).size().unstack([1]).fillna(0))
b = X[X.kind=='base']
print(b.groupby(['run','v_lev']).size())
print(X.groupby(['run','kind','resolved']).size().unstack([2]).head(60))
