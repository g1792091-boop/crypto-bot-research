import site, sys
sys.dont_write_bytecode = True
us = site.getusersitepackages()
if us not in sys.path: sys.path.append(us)
import pandas as pd, numpy as np
R = pd.read_csv(sys.argv[1])
print(R.columns.tolist())
tr = R[R.status=='TRADED']
print(tr.groupby(['run','timeframe'])['hold_min'].describe(percentiles=[.5,.9,.95,.99]))
print(R.groupby(['run','kind','status']).size().unstack(2).fillna(0))
